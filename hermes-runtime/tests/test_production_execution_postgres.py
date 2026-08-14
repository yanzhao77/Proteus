import os
import unittest
from pathlib import Path

try:
    import psycopg
except ImportError:
    psycopg = None

from hermes_runtime.application.docker_execution import (
    ProductionExecutionAuthority,
    RecordDockerProcess,
    RecordExternalSideEffectReceipt,
)
from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.domain.docker_execution import DockerProcessState
from hermes_runtime.domain.models import Actor, ActorType
from hermes_runtime.infrastructure.postgres_production_execution import PostgresProductionExecutionStore


DATABASE_URL = os.environ.get("HERMES_TEST_DATABASE_URL")


@unittest.skipUnless(DATABASE_URL and psycopg, "requires real PostgreSQL 14+")
class ProductionExecutionPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = PostgresProductionExecutionStore(DATABASE_URL)
        cls.store.check_server_version(140000)
        for migration in sorted((Path(__file__).parents[1] / "migrations").glob("*.sql")):
            cls.store.apply_migration(migration)

    def setUp(self):
        self.store.reset_for_test()
        self.authority = ProductionExecutionAuthority(PostgresProductionExecutionStore(DATABASE_URL))
        self.operator = Actor(ActorType.SYSTEM_OPERATOR, "operator-1")

    def _process(self, suffix="1", **overrides):
        values = dict(
            command_id="cmd-docker-" + suffix,
            idempotency_key="idem-docker-" + suffix,
            project_id="project-1",
            execution_request_id="exec-1",
            run_id="run-1",
            lease_id="lease-1",
            lease_version=1,
            fencing_token=9,
            container_name="hermes-test-container",
            container_id="container-1",
            plan_hash="sha256:plan",
            state=DockerProcessState.RUNNING,
            actor=self.operator,
            reason="observe process",
            trace_id="trace-1",
            correlation_id="corr-1",
            causation_id="cmd-exec",
        )
        values.update(overrides)
        return self.authority.record_process(RecordDockerProcess(**values))

    def _receipt(self, suffix="1", **overrides):
        values = dict(
            command_id="cmd-side-" + suffix,
            idempotency_key="idem-side-" + suffix,
            project_id="project-1",
            execution_request_id="exec-1",
            run_id="run-1",
            lease_id="lease-1",
            lease_version=1,
            fencing_token=9,
            side_effect_key="side-key-1",
            action_class="local_fake",
            target_class="controlled_test_target",
            reversible=True,
            human_gate_authorization_ref="",
            request_payload_hash="sha256:req",
            external_receipt_ref="fake://receipt/1",
            external_receipt_hash="sha256:receipt",
            observed_outcome="SUCCEEDED",
            actor=self.operator,
            trace_id="trace-1",
            correlation_id="corr-1",
            causation_id="cmd-docker-1",
        )
        values.update(overrides)
        return self.authority.record_side_effect_receipt(RecordExternalSideEffectReceipt(**values))

    def test_process_lifecycle_is_recorded_with_event_outbox_receipt(self):
        running = self._process()
        self.assertEqual("DOCKER_PROCESS_RECORDED", running["result_code"])
        terminal = self._process(
            suffix="terminal",
            state=DockerProcessState.SUCCEEDED,
            command_id="cmd-docker-terminal",
            idempotency_key="idem-docker-terminal",
        )
        self.assertEqual("SUCCEEDED", terminal["lifecycle_state"])
        with psycopg.connect(DATABASE_URL) as connection:
            self.assertEqual(
                ("SUCCEEDED", 2),
                connection.execute(
                    "SELECT lifecycle_state,version FROM docker_process_runs WHERE run_id='run-1'"
                ).fetchone(),
            )
            self.assertEqual(2, connection.execute("SELECT count(*) FROM docker_process_observations").fetchone()[0])
            self.assertEqual(2, connection.execute("SELECT count(*) FROM event_log WHERE event_type='docker.process_observed'").fetchone()[0])

    def test_stale_fencing_and_idempotency_conflicts_fail_closed(self):
        self._process()
        retry = self._process()
        self.assertEqual("DOCKER_PROCESS_RECORDED", retry["result_code"])
        with self.assertRaisesRegex(CommandRejected, "DOCKER_STALE_FENCING_TOKEN"):
            self._process(suffix="stale", fencing_token=8, command_id="cmd-docker-stale", idempotency_key="idem-docker-stale")
        with self.assertRaisesRegex(CommandRejected, "IDEMPOTENCY_PAYLOAD_CONFLICT"):
            self._process(suffix="conflict", idempotency_key="idem-docker-1", plan_hash="sha256:changed")

    def test_side_effect_receipt_requires_current_fencing_and_gate_for_irreversible(self):
        self._process()
        receipt = self._receipt()
        self.assertEqual("SIDE_EFFECT_RECEIPT_RECORDED", receipt["result_code"])
        retry = self._receipt()
        self.assertEqual(receipt["receipt_id"], retry["receipt_id"])
        with self.assertRaisesRegex(CommandRejected, "SIDE_EFFECT_IDEMPOTENCY_CONFLICT"):
            self._receipt(suffix="conflict", side_effect_key="side-key-1", external_receipt_hash="sha256:changed")
        with self.assertRaisesRegex(CommandRejected, "SIDE_EFFECT_IRREVERSIBLE_REQUIRES_GATE"):
            self._receipt(suffix="irrev", side_effect_key="side-key-irrev", reversible=False)
        with self.assertRaisesRegex(CommandRejected, "DOCKER_STALE_FENCING_TOKEN"):
            self._receipt(suffix="stale", side_effect_key="side-key-stale", fencing_token=8)

    def test_effect_before_receipt_creates_reconcile_finding_and_rolls_back_receipt(self):
        self._process()
        with self.assertRaisesRegex(CommandRejected, "SIDE_EFFECT_RECEIPT_UNKNOWN_RECONCILE_REQUIRED"):
            self._receipt(suffix="unknown", side_effect_key="side-key-unknown", fault_point="after_effect_before_receipt")
        with psycopg.connect(DATABASE_URL) as connection:
            self.assertEqual(0, connection.execute("SELECT count(*) FROM external_side_effect_receipts WHERE side_effect_key='side-key-unknown'").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
