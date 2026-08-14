import os
import threading
import unittest
from pathlib import Path

try:
    import psycopg
except ImportError:
    psycopg = None

from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.application.explain import (
    CaptureDecisionExplain,
    DecisionExplainAuthority,
    QueryDecisionExplain,
)
from hermes_runtime.domain.explain import ExplainEdge, ExplainNode
from hermes_runtime.domain.models import Actor, ActorType
from hermes_runtime.infrastructure.postgres_explain import PostgresExplainStore


DATABASE_URL = os.environ.get("HERMES_TEST_DATABASE_URL")


@unittest.skipUnless(DATABASE_URL and psycopg, "requires real PostgreSQL 14+")
class ExplainPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = PostgresExplainStore(DATABASE_URL)
        cls.store.check_server_version(140000)
        for migration in sorted((Path(__file__).parents[1] / "migrations").glob("*.sql")):
            cls.store.apply_migration(migration)

    def setUp(self):
        self.store.reset_for_test()
        self.authority = DecisionExplainAuthority(PostgresExplainStore(DATABASE_URL))
        self.operator = Actor(ActorType.SYSTEM_OPERATOR, "operator-1")

    def _admin_connection(self):
        return psycopg.connect(DATABASE_URL)

    def _capture(self, suffix="1", **overrides):
        values = dict(
            command_id="cmd-explain-" + suffix,
            idempotency_key="idem-explain-" + suffix,
            project_id="project-1",
            source_type="decision",
            source_id="decision-" + suffix,
            source_version=1,
            expected_source_version=1,
            source_hash="sha256:decision",
            schema_version="decision-explain/1.0",
            producer_version="explain-runtime/1.0",
            summary={"why": "policy allowed repair", "risk": "LOW"},
            nodes=(
                ExplainNode(
                    "situation-1",
                    "Situation",
                    "situation-1",
                    1,
                    "sha256:situation",
                    safe_summary={"trigger": "verification failed"},
                ),
                ExplainNode(
                    "decision-1",
                    "DecisionRecord",
                    "decision-1",
                    1,
                    "sha256:decision",
                    safe_summary={"selected": "repair"},
                ),
            ),
            edges=(ExplainEdge("situation-1", "decision-1", "caused"),),
            redaction_class="INTERNAL",
            retention_policy="p3-standard-90d",
            retention_until="2099-01-01T00:00:00+00:00",
            authorization_scope={"tenant_id": "tenant-1", "project_id": "project-1"},
            actor=self.operator,
            authorization_ref="authz:explain",
            reason="capture immutable explain",
            causation_id="cmd-decision-1",
            correlation_id="corr-1",
            trace_id="trace-1",
        )
        values.update(overrides)
        return self.authority.capture(CaptureDecisionExplain(**values))

    def test_capture_is_immutable_audited_and_queryable_by_trace(self):
        captured = self._capture()
        self.assertEqual("DECISION_EXPLAIN_CAPTURED", captured["result_code"])
        queried = self.authority.query(
            QueryDecisionExplain(
                "project-1",
                captured["snapshot_id"],
                self.operator,
                {"tenant_id": "tenant-1", "project_id": "project-1"},
            )
        )
        self.assertEqual(captured["snapshot_hash"], queried["snapshot"]["snapshot_hash"])
        self.assertEqual(2, len(queried["nodes"]))
        self.assertEqual("trace-1", queried["snapshot"]["trace_id"])
        with self._admin_connection() as connection:
            self.assertEqual(
                1,
                connection.execute(
                    "SELECT count(*) FROM event_log WHERE event_type='decision.explain_recorded'"
                ).fetchone()[0],
            )
            self.assertEqual(
                1,
                connection.execute(
                    "SELECT count(*) FROM outbox_messages o JOIN event_log e ON e.event_id=o.event_id WHERE e.event_type='decision.explain_recorded'"
                ).fetchone()[0],
            )
            self.assertEqual(
                "APPLIED",
                connection.execute(
                    "SELECT status FROM command_receipts WHERE command_id='cmd-explain-1'"
                ).fetchone()[0],
            )
            with self.assertRaises(psycopg.errors.RaiseException):
                connection.execute(
                    "UPDATE public.decision_explain_snapshots SET reason='patched'"
                )

    def test_late_fact_and_query_time_rule_change_do_not_mutate_old_snapshot(self):
        first = self._capture()
        changed = self._capture(
            suffix="late",
            source_version=2,
            expected_source_version=2,
            source_hash="sha256:decision2",
            summary={"why": "new policy would choose another action"},
        )
        self.assertNotEqual(first["snapshot_id"], changed["snapshot_id"])
        queried = self.authority.query(
            QueryDecisionExplain(
                "project-1",
                first["snapshot_id"],
                self.operator,
                {"tenant_id": "tenant-1", "project_id": "project-1"},
            )
        )
        self.assertEqual(first["snapshot_hash"], queried["snapshot"]["snapshot_hash"])
        self.assertEqual({"why": "policy allowed repair", "risk": "LOW"}, queried["snapshot"]["summary"])

    def test_missing_link_is_stored_as_missing_not_fabricated(self):
        captured = self._capture(
            suffix="missing",
            nodes=(
                ExplainNode(
                    "gate-missing",
                    "HumanGateDecision",
                    "gate-unknown",
                    0,
                    "",
                    "MISSING",
                    "gate decision was not available",
                ),
            ),
            edges=(),
        )
        queried = self.authority.query(
            QueryDecisionExplain(
                "project-1",
                captured["snapshot_id"],
                self.operator,
                {"tenant_id": "tenant-1", "project_id": "project-1"},
            )
        )
        self.assertEqual("MISSING", queried["nodes"][0]["status"])
        self.assertEqual(1, queried["snapshot"]["missing_links"].__len__())

    def test_idempotent_retry_conflict_concurrency_and_expected_version(self):
        first = self._capture()
        retry = self._capture()
        self.assertEqual(first["snapshot_id"], retry["snapshot_id"])
        with self.assertRaisesRegex(CommandRejected, "IDEMPOTENCY_PAYLOAD_CONFLICT"):
            self._capture(suffix="conflict", idempotency_key="idem-explain-1", summary={"why": "changed"})
        with self.assertRaisesRegex(CommandRejected, "EXPLAIN_SOURCE_VERSION_MISMATCH"):
            self._capture(suffix="stale", source_version=2, expected_source_version=1)

        results = []

        def compete(index):
            try:
                results.append(
                    self._capture(
                        suffix="race-" + str(index),
                        source_id="decision-race",
                        idempotency_key="idem-race",
                    )
                )
            except CommandRejected as exc:
                results.append(exc.code)

        threads = [threading.Thread(target=compete, args=(i,)) for i in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(2, sum(isinstance(result, dict) for result in results))
        self.assertEqual(results[0]["snapshot_id"], results[1]["snapshot_id"])

    def test_unauthorized_cross_scope_secret_and_faults_fail_closed(self):
        captured = self._capture(suffix="secure")
        with self.assertRaisesRegex(CommandRejected, "AUDIT_QUERY_UNAUTHORIZED"):
            self.authority.query(
                QueryDecisionExplain(
                    "project-1",
                    captured["snapshot_id"],
                    self.operator,
                    {"tenant_id": "other", "project_id": "project-1"},
                )
            )
        with self.assertRaisesRegex(CommandRejected, "RETENTION_REDACTION_VIOLATION"):
            self._capture(suffix="secret", summary={"stdout": "api_token=abc"})
        self.authority._store.fail_explain_once("after_event_before_audit")
        with self.assertRaisesRegex(CommandRejected, "INJECTED_P3_EXPLAIN_CRASH_AFTER_EVENT"):
            self._capture(suffix="fault")
        with self._admin_connection() as connection:
            self.assertEqual(
                0,
                connection.execute(
                    "SELECT count(*) FROM command_receipts WHERE command_id='cmd-explain-fault'"
                ).fetchone()[0],
            )
            self.assertEqual(
                0,
                connection.execute(
                    "SELECT count(*) FROM decision_explain_snapshots WHERE command_id='cmd-explain-fault'"
                ).fetchone()[0],
            )


if __name__ == "__main__":
    unittest.main()
