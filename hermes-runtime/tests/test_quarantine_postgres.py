import os
import threading
import unittest
import uuid
from pathlib import Path

try:
    import psycopg
    from psycopg.types.json import Jsonb
except ImportError:
    psycopg = None
    Jsonb = None

from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.application.quarantine import (
    DiscardQuarantine,
    ExpireQuarantine,
    MarkQuarantineAdopted,
    MarkQuarantineRedriven,
    QuarantineAuthority,
    RequestQuarantineAdoption,
    RequestQuarantineRedrive,
    StartQuarantineReview,
)
from hermes_runtime.domain.models import Actor, ActorType
from hermes_runtime.infrastructure.postgres_quarantine import PostgresQuarantineStore


DATABASE_URL = os.environ.get("HERMES_TEST_DATABASE_URL")


@unittest.skipUnless(DATABASE_URL and psycopg, "requires real PostgreSQL 14+")
class QuarantinePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = PostgresQuarantineStore(DATABASE_URL)
        cls.store.check_server_version(140000)
        for migration in sorted((Path(__file__).parents[1] / "migrations").glob("*.sql")):
            cls.store.apply_migration(migration)

    def setUp(self):
        self.store.reset_for_test()
        self.authority = QuarantineAuthority(self.store)
        self.operator = Actor(ActorType.SYSTEM_OPERATOR, "operator-1")

    def _admin_connection(self):
        return psycopg.connect(DATABASE_URL)

    def _seed_quarantine(self, quarantine_id="quarantine-1", stale=False):
        with self._admin_connection() as connection:
            connection.execute(
                """
                INSERT INTO public.command_receipts(
                    command_id,project_id,command_type,idempotency_key,
                    request_hash,status,result,completed_at
                ) VALUES ('cmd-source-q','project-1','worker.result','idem-source-q',
                          'sha256:source','APPLIED','{}',clock_timestamp())
                """
            )
            connection.execute(
                """
                INSERT INTO public.execution_quarantine_records(
                    quarantine_id,payload_kind,project_id,task_id,execution_request_id,
                    execution_attempt,run_id,submitted_lease_id,submitted_fencing_token,
                    observed_current_lease_id,observed_current_fencing_token,
                    worker_agent_identity,context_identity,reason_code,payload_hash,
                    safe_payload_envelope,source_command_id,idempotency_key,
                    processing_state
                ) VALUES (%s,'EXECUTION_RESULT','project-1','task-1','exec-1',
                          1,'run-1','lease-old',%s,'lease-current',2,
                          'worker-1','ctx-1','FENCING_TOKEN_STALE','sha256:payload',
                          %s,'cmd-source-q','idem-source-q','P2_MINIMAL')
                """,
                (
                    quarantine_id,
                    1 if stale else 2,
                    Jsonb({"result_id": "late-result", "verdict": "not-authority"}),
                ),
            )
        return quarantine_id

    def _start(self, quarantine_id="quarantine-1", suffix="1", expected=0):
        return self.authority.start_review(
            StartQuarantineReview(
                command_id="cmd-q-start-" + suffix,
                idempotency_key="idem-q-start-" + suffix,
                project_id="project-1",
                quarantine_id=quarantine_id,
                expected_version=expected,
                actor=self.operator,
                authorization_ref="authz:" + suffix,
                reason="review stale payload",
                retention_until="2099-01-01T00:00:00+00:00",
            )
        )

    def test_review_lifecycle_is_append_only_and_discard_is_audited(self):
        self._seed_quarantine()
        started = self._start()
        self.assertEqual("UNDER_REVIEW", started["lifecycle_state"])
        discarded = self.authority.discard(
            DiscardQuarantine(
                "cmd-q-discard-1",
                "idem-q-discard-1",
                "project-1",
                "quarantine-1",
                1,
                self.operator,
                "authz:discard",
                "duplicate stale payload",
                "2099-01-01T00:00:00+00:00",
            )
        )
        self.assertEqual("DISCARDED", discarded["lifecycle_state"])
        with self._admin_connection() as connection:
            state = connection.execute(
                "SELECT lifecycle_state,version FROM public.quarantine_current_states WHERE quarantine_id='quarantine-1'"
            ).fetchone()
            self.assertEqual(("DISCARDED", 2), state)
            self.assertEqual(
                2,
                connection.execute(
                    "SELECT count(*) FROM public.quarantine_operations WHERE quarantine_id='quarantine-1'"
                ).fetchone()[0],
            )
            self.assertEqual(
                2,
                connection.execute(
                    "SELECT count(*) FROM public.event_log WHERE event_type LIKE 'quarantine.%'"
                ).fetchone()[0],
            )
            with self.assertRaises(psycopg.errors.RaiseException):
                connection.execute(
                    "UPDATE public.quarantine_operations SET reason='patched'"
                )

    def test_concurrent_review_only_one_expected_version_wins(self):
        self._seed_quarantine()
        results = []

        def compete(suffix):
            try:
                results.append(self._start(suffix=suffix))
            except CommandRejected as exc:
                results.append(exc.code)

        threads = [threading.Thread(target=compete, args=(str(i),)) for i in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(1, sum(isinstance(result, dict) for result in results))
        self.assertIn("EXPECTED_VERSION_CONFLICT", results)

    def test_idempotent_retry_and_payload_conflict_are_enforced(self):
        self._seed_quarantine()
        first = self._start()
        retry = self._start()
        self.assertEqual(first["operation_id"], retry["operation_id"])
        with self.assertRaisesRegex(CommandRejected, "IDEMPOTENCY_PAYLOAD_CONFLICT"):
            self.authority.start_review(
                StartQuarantineReview(
                    "cmd-q-start-conflict",
                    "idem-q-start-1",
                    "project-1",
                    "quarantine-1",
                    0,
                    self.operator,
                    "authz:changed",
                    "changed payload",
                    "2099-01-01T00:00:00+00:00",
                )
            )

    def test_adoption_creates_guarded_command_shell_and_never_passes_task(self):
        self._seed_quarantine(stale=False)
        self._start()
        adopted = self.authority.request_adoption(
            RequestQuarantineAdoption(
                "cmd-q-adopt-1",
                "idem-q-adopt-1",
                "project-1",
                "quarantine-1",
                1,
                self.operator,
                "authz:adopt",
                "request guarded adoption",
                "cmd-guarded-adopt",
                "idem-guarded-adopt",
                "execution.result.adopt",
                {"policy_version": 1, "project_version": 0, "task_version": 0},
                "2099-01-01T00:00:00+00:00",
            )
        )
        self.assertEqual("ADOPTION_REQUESTED", adopted["lifecycle_state"])
        with self._admin_connection() as connection:
            self.assertEqual(
                1,
                connection.execute(
                    "SELECT count(*) FROM public.quarantine_adoption_requests WHERE guarded_command_id='cmd-guarded-adopt'"
                ).fetchone()[0],
            )
            self.assertEqual(
                0,
                connection.execute(
                    "SELECT count(*) FROM public.tasks WHERE task_id='task-1' AND state='PASSED'"
                ).fetchone()[0],
            )

    def test_stale_fencing_adoption_and_resolved_records_fail_closed(self):
        self._seed_quarantine(stale=True)
        self._start()
        with self.assertRaisesRegex(CommandRejected, "QUARANTINE_ADOPTION_GUARD_FAILED"):
            self.authority.request_adoption(
                RequestQuarantineAdoption(
                    "cmd-q-adopt-stale",
                    "idem-q-adopt-stale",
                    "project-1",
                    "quarantine-1",
                    1,
                    self.operator,
                    "authz:adopt",
                    "request guarded adoption",
                    "cmd-guarded-stale",
                    "idem-guarded-stale",
                    "execution.result.adopt",
                    {},
                    "2099-01-01T00:00:00+00:00",
                )
            )
        self.authority.discard(
            DiscardQuarantine(
                "cmd-q-discard-stale",
                "idem-q-discard-stale",
                "project-1",
                "quarantine-1",
                1,
                self.operator,
                "authz:discard",
                "discard after stale guard",
                "2099-01-01T00:00:00+00:00",
            )
        )
        with self.assertRaisesRegex(CommandRejected, "QUARANTINE_ALREADY_RESOLVED"):
            self.authority.expire(
                ExpireQuarantine(
                    "cmd-q-expire-resolved",
                    "idem-q-expire-resolved",
                    "project-1",
                    "quarantine-1",
                    2,
                    self.operator,
                    "expire resolved",
                )
            )

    def test_redrive_uses_new_identity_and_preserves_original_causation(self):
        self._seed_quarantine()
        self._start()
        with self.assertRaisesRegex(CommandRejected, "QUARANTINE_REDRIVE_CONFLICT"):
            self.authority.request_redrive(
                RequestQuarantineRedrive(
                    "cmd-q-redrive-conflict",
                    "idem-q-redrive-conflict",
                    "project-1",
                    "quarantine-1",
                    1,
                    self.operator,
                    "authz:redrive",
                    "redrive conflict",
                    "cmd-source-q",
                    "idem-new-redrive",
                    {"execution_request_id": "exec-1"},
                    "2099-01-01T00:00:00+00:00",
                )
            )
        redriven = self.authority.request_redrive(
            RequestQuarantineRedrive(
                "cmd-q-redrive-1",
                "idem-q-redrive-1",
                "project-1",
                "quarantine-1",
                1,
                self.operator,
                "authz:redrive",
                "redrive with new command",
                "cmd-redrive-new",
                "idem-redrive-new",
                {"execution_request_id": "exec-1"},
                "2099-01-01T00:00:00+00:00",
                causation_id="cmd-source-q",
            )
        )
        self.assertEqual("REDRIVE_REQUESTED", redriven["lifecycle_state"])
        with self._admin_connection() as connection:
            self.assertEqual(
                ("cmd-redrive-new", "cmd-source-q"),
                connection.execute(
                    """
                    SELECT redrive_command_id, original_causation_id
                    FROM public.quarantine_redrive_requests
                    WHERE quarantine_id='quarantine-1'
                    """
                ).fetchone(),
            )

    def test_retention_expiry_and_fault_injection_roll_back_atomically(self):
        self._seed_quarantine()
        with self.assertRaisesRegex(CommandRejected, "QUARANTINE_RETENTION_EXPIRED"):
            self.authority.start_review(
                StartQuarantineReview(
                    "cmd-q-expired",
                    "idem-q-expired",
                    "project-1",
                    "quarantine-1",
                    0,
                    self.operator,
                    "authz:expired",
                    "expired",
                    "2000-01-01T00:00:00+00:00",
                )
            )
        self.store.fail_quarantine_once("after_event_before_state")
        with self.assertRaisesRegex(CommandRejected, "INJECTED_P3_QUARANTINE_CRASH_AFTER_EVENT"):
            self._start(suffix="fault")
        with self._admin_connection() as connection:
            self.assertEqual(
                0,
                connection.execute(
                    "SELECT count(*) FROM public.quarantine_operations WHERE quarantine_id='quarantine-1'"
                ).fetchone()[0],
            )
            self.assertEqual(
                0,
                connection.execute(
                    "SELECT count(*) FROM public.command_receipts WHERE command_id='cmd-q-start-fault'"
                ).fetchone()[0],
            )


if __name__ == "__main__":
    unittest.main()
