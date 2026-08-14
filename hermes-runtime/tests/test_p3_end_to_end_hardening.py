import os
import shutil
import subprocess
import unittest
from pathlib import Path

try:
    import psycopg
    from psycopg.types.json import Jsonb
except ImportError:
    psycopg = None
    Jsonb = None

from hermes_runtime.application.docker_execution import (
    ProductionExecutionAuthority,
    RecordDockerProcess,
    RecordExternalSideEffectReceipt,
)
from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.application.explain import (
    CaptureDecisionExplain,
    DecisionExplainAuthority,
    QueryDecisionExplain,
)
from hermes_runtime.application.quarantine import (
    QuarantineAuthority,
    RequestQuarantineAdoption,
    StartQuarantineReview,
)
from hermes_runtime.domain.docker_execution import (
    DockerProcessState,
    DockerResourceLimits,
    DockerSandboxProfile,
    ExecutionEnvelope,
    compile_docker_run_plan,
    deterministic_container_name,
)
from hermes_runtime.domain.explain import ExplainEdge, ExplainNode
from hermes_runtime.domain.models import Actor, ActorType
from hermes_runtime.infrastructure.docker_adapter import DockerExecutionAdapter
from hermes_runtime.infrastructure.postgres_production_execution import PostgresProductionExecutionStore
from hermes_runtime.infrastructure.postgres_quarantine import PostgresQuarantineStore


DATABASE_URL = os.environ.get("HERMES_TEST_DATABASE_URL")
DOCKER_ENABLED = os.environ.get("HERMES_TEST_DOCKER") == "1"


def _docker_available():
    return DOCKER_ENABLED and shutil.which("docker") and subprocess.run(
        ["docker", "version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    ).returncode == 0


@unittest.skipUnless(DATABASE_URL and psycopg and _docker_available(), "requires PostgreSQL and real Docker")
class P3EndToEndHardeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = PostgresProductionExecutionStore(DATABASE_URL)
        cls.store.check_server_version(140000)
        for migration in sorted((Path(__file__).parents[1] / "migrations").glob("*.sql")):
            cls.store.apply_migration(migration)

    def setUp(self):
        self.store.reset_for_test()
        self.operator = Actor(ActorType.SYSTEM_OPERATOR, "operator-1")
        self.production = ProductionExecutionAuthority(PostgresProductionExecutionStore(DATABASE_URL))
        self.explain = DecisionExplainAuthority(PostgresProductionExecutionStore(DATABASE_URL))

    def _admin_connection(self):
        return psycopg.connect(DATABASE_URL)

    def _record_process(self, suffix, state, container_id="container-1"):
        return self.production.record_process(
            RecordDockerProcess(
                "cmd-p3-proc-" + suffix,
                "idem-p3-proc-" + suffix,
                "project-1",
                "exec-1",
                "run-1",
                "lease-1",
                1,
                101,
                "hermes-p3-e2e",
                container_id,
                "sha256:plan",
                state,
                self.operator,
                "p3 e2e process observation",
                "trace-p3",
                "corr-p3",
                "cmd-admission",
            )
        )

    def test_e2e_human_authorized_docker_execution_to_explain_without_task_self_pass(self):
        envelope = ExecutionEnvelope("project-1", "exec-1", 1, "run-1", "lease-1", 1, 101, "worker-1", "trace-p3", "corr-p3")
        profile = DockerSandboxProfile(
            image="postgres:16",
            allow_unpinned_image=True,
            command=("sh", "-c", "mkdir -p export && echo artifact > export/result.txt && echo p3-pass-candidate"),
            limits=DockerResourceLimits(timeout_seconds=10, stdout_bytes=128),
        )
        plan = compile_docker_run_plan(profile, envelope, run_label="p3-4-6-production-hardening")
        docker_result = DockerExecutionAdapter().execute(plan, envelope)
        self.assertEqual("SUCCEEDED", docker_result.outcome)
        running = self._record_process("running", DockerProcessState.RUNNING, docker_result.container_id)
        done = self._record_process("done", DockerProcessState.SUCCEEDED, docker_result.container_id)
        receipt = self.production.record_side_effect_receipt(
            RecordExternalSideEffectReceipt(
                "cmd-p3-side-1",
                "idem-p3-side-1",
                "project-1",
                "exec-1",
                "run-1",
                "lease-1",
                1,
                101,
                "local-fake-effect-1",
                "local_fake",
                "controlled_test_target",
                False,
                "gate:approved-production-test",
                "sha256:req",
                "fake://receipt/1",
                "sha256:receipt",
                "SUCCEEDED",
                self.operator,
                "trace-p3",
                "corr-p3",
                running["event_id"],
            )
        )
        captured = self.explain.capture(
            CaptureDecisionExplain(
                "cmd-p3-explain-1",
                "idem-p3-explain-1",
                "project-1",
                "execution_request",
                "exec-1",
                1,
                1,
                "sha256:exec",
                "decision-explain/1.0",
                "p3-e2e/1.0",
                {"why": "human gate authorized Docker execution; independent verification still required"},
                (
                    ExplainNode("gate-1", "HumanGateDecision", "gate-approved", 1, "sha256:gate", safe_summary={"decision": "APPROVED"}),
                    ExplainNode("docker-1", "DockerProcess", done["process_id"], 2, "sha256:plan", safe_summary={"state": "SUCCEEDED"}),
                    ExplainNode("side-1", "SideEffectReceipt", receipt["receipt_id"], 1, "sha256:receipt", safe_summary={"state": "MATCHED"}),
                ),
                (
                    ExplainEdge("gate-1", "docker-1", "authorized"),
                    ExplainEdge("docker-1", "side-1", "receipted"),
                ),
                "INTERNAL",
                "p3-standard-90d",
                "2099-01-01T00:00:00+00:00",
                {"tenant_id": "tenant-1", "project_id": "project-1"},
                self.operator,
                "authz:p3-e2e",
                "capture p3 execution trace",
                trace_id="trace-p3",
                correlation_id="corr-p3",
            )
        )
        queried = self.explain.query(
            QueryDecisionExplain("project-1", captured["snapshot_id"], self.operator, {"tenant_id": "tenant-1", "project_id": "project-1"})
        )
        self.assertEqual("trace-p3", queried["snapshot"]["trace_id"])
        with self._admin_connection() as connection:
            self.assertEqual(0, connection.execute("SELECT count(*) FROM tasks WHERE state='PASSED'").fetchone()[0])

    def test_e2e_stale_quarantine_adoption_fails_closed_and_is_explainable(self):
        qstore = PostgresQuarantineStore(DATABASE_URL)
        quarantine = QuarantineAuthority(qstore)
        with self._admin_connection() as connection:
            connection.execute(
                """
                INSERT INTO public.command_receipts(command_id,project_id,command_type,idempotency_key,request_hash,status,result,completed_at)
                VALUES ('cmd-p3-q-source','project-1','worker.result','idem-p3-q-source','sha256:source','APPLIED','{}',clock_timestamp())
                """
            )
            connection.execute(
                """
                INSERT INTO public.execution_quarantine_records(
                    quarantine_id,payload_kind,project_id,task_id,execution_request_id,
                    execution_attempt,run_id,submitted_lease_id,submitted_fencing_token,
                    observed_current_lease_id,observed_current_fencing_token,
                    worker_agent_identity,context_identity,reason_code,payload_hash,
                    safe_payload_envelope,source_command_id,idempotency_key,processing_state
                ) VALUES ('q-p3-e2e','EXECUTION_RESULT','project-1','task-1','exec-1',
                          1,'run-old','lease-old',1,'lease-new',2,'worker-1','ctx',
                          'FENCING_TOKEN_STALE','sha256:payload',
                          %s,'cmd-p3-q-source','idem-p3-q-source','P2_MINIMAL')
                """,
                (Jsonb({"result": "late"}),),
            )
        quarantine.start_review(
            StartQuarantineReview(
                "cmd-p3-q-review",
                "idem-p3-q-review",
                "project-1",
                "q-p3-e2e",
                0,
                self.operator,
                "authz:q",
                "review stale result",
                "2099-01-01T00:00:00+00:00",
            )
        )
        with self.assertRaisesRegex(CommandRejected, "QUARANTINE_ADOPTION_GUARD_FAILED"):
            quarantine.request_adoption(
                RequestQuarantineAdoption(
                    "cmd-p3-q-adopt",
                    "idem-p3-q-adopt",
                    "project-1",
                    "q-p3-e2e",
                    1,
                    self.operator,
                    "authz:q",
                    "try stale adoption",
                    "cmd-guarded",
                    "idem-guarded",
                    "execution.result.adopt",
                    {},
                    "2099-01-01T00:00:00+00:00",
                )
            )

    def test_e2e_effect_before_receipt_remains_reconcile_not_authority(self):
        self._record_process("running", DockerProcessState.RUNNING)
        with self.assertRaisesRegex(CommandRejected, "SIDE_EFFECT_RECEIPT_UNKNOWN_RECONCILE_REQUIRED"):
            self.production.record_side_effect_receipt(
                RecordExternalSideEffectReceipt(
                    "cmd-p3-side-unknown",
                    "idem-p3-side-unknown",
                    "project-1",
                    "exec-1",
                    "run-1",
                    "lease-1",
                    1,
                    101,
                    "local-fake-unknown",
                    "local_fake",
                    "controlled_test_target",
                    True,
                    "",
                    "sha256:req-unknown",
                    "fake://receipt/unknown",
                    "sha256:receipt-unknown",
                    "UNKNOWN",
                    self.operator,
                    "trace-p3",
                    "corr-p3",
                    "cmd-p3-proc-running",
                    fault_point="after_effect_before_receipt",
                )
            )
        with self._admin_connection() as connection:
            self.assertEqual(0, connection.execute("SELECT count(*) FROM external_side_effect_receipts WHERE side_effect_key='local-fake-unknown'").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
