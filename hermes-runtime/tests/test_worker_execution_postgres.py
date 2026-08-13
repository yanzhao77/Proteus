import os
import threading
import unittest
from pathlib import Path

try:
    import psycopg
except ImportError:
    psycopg = None

from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.application.executions import ExecutionPreparation
from hermes_runtime.application.scheduling import (
    AcquireExecutionLease,
    ExecutionScheduler,
    RegisterScheduler,
)
from hermes_runtime.application.workers import (
    RecordArtifactCandidate,
    RecordEvidenceCandidate,
    RecordUsageSample,
    StartWorkerRun,
    SubmitExecutionResult,
    WorkerExecution,
)
from hermes_runtime.domain.worker_execution import (
    ArtifactCandidateSubmission,
    EvidenceCandidateSubmission,
    ExecutionOutcome,
    ExecutionResultSubmission,
    UsageSampleSubmission,
    WorkerFrozenContext,
    WorkerLeaseBinding,
)
from hermes_runtime.infrastructure.postgres_execution import PostgresExecutionStore
from hermes_runtime.infrastructure.postgres_scheduler import PostgresSchedulerStore
from hermes_runtime.infrastructure.postgres_worker_execution import (
    PostgresWorkerExecutionStore,
    WorkerExecutionFaultPoint,
)
try:
    from . import test_execution_postgres as execution_fixtures
except ImportError:
    import test_execution_postgres as execution_fixtures


DATABASE_URL = os.environ.get("HERMES_TEST_DATABASE_URL")


class _ExecutionFixture:
    seed_fixture = execution_fixtures.ExecutionPostgresTests.seed_fixture
    command = execution_fixtures.ExecutionPostgresTests.command


@unittest.skipUnless(DATABASE_URL and psycopg, "requires real PostgreSQL 14+")
class WorkerExecutionPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = PostgresWorkerExecutionStore(DATABASE_URL)
        for migration in sorted((Path(__file__).parents[1] / "migrations").glob("*.sql")):
            cls.store.apply_migration(migration)

    def setUp(self):
        self.store.reset_for_test()
        self.execution = ExecutionPreparation(PostgresExecutionStore(DATABASE_URL))
        self.scheduler = ExecutionScheduler(PostgresSchedulerStore(DATABASE_URL))
        self.worker = WorkerExecution(PostgresWorkerExecutionStore(DATABASE_URL))
        self.fixture = _ExecutionFixture()
        self.fixture.store = self.store
        self.fixture.seed_fixture()

    def prepare_leased(self):
        prepared = self.execution.prepare(self.fixture.command("p2-4"))
        self.scheduler.register(RegisterScheduler(
            command_id="cmd-register-worker",
            idempotency_key="key-register-worker",
            project_id="project-1",
            scheduler_id="sched-1",
            scheduler_session_id="session-1",
            actor_id="sched-1",
        ))
        lease = self.scheduler.acquire(AcquireExecutionLease(
            command_id="cmd-acquire-worker",
            idempotency_key="key-acquire-worker",
            project_id="project-1",
            scheduler_id="sched-1",
            scheduler_session_id="session-1",
            actor_id="sched-1",
        ))
        return prepared, lease

    def binding(self, lease, **overrides):
        values = dict(
            project_id="project-1",
            execution_request_id=lease["execution_request_id"],
            execution_attempt=1,
            run_id="worker-run-1",
            lease_id=lease["lease_id"],
            lease_version=lease["lease_version"],
            fencing_token=lease["fencing_token"],
            scheduler_id="sched-1",
            scheduler_session_id="session-1",
            worker_agent_identity="worker-1",
            context_identity="worker-context-1",
            observed_request_version=lease["request_version"],
        )
        values.update(overrides)
        return WorkerLeaseBinding(**values)

    def frozen(self):
        return WorkerFrozenContext(
            worker_template_id="template-1",
            worker_template_revision=1,
            worker_template_content_hash="sha256:template",
            context_bundle_id="ctx-1",
            context_manifest_hash="sha256:context",
            sandbox_profile_id="sbx-1",
            sandbox_profile_hash="sha256:sandbox",
            reservation_id="reservation-1",
        )

    def start(self, lease, suffix="1", **overrides):
        binding = self.binding(lease, **overrides)
        return self.worker.start_run(StartWorkerRun(
            "cmd-start-" + suffix,
            "key-start-" + suffix,
            binding,
            self.frozen(),
            actor_id=binding.worker_agent_identity,
        ))

    def record_artifact(self, binding, suffix="1"):
        return self.worker.record_artifact_candidate(RecordArtifactCandidate(
            "cmd-art-cand-" + suffix,
            "key-art-cand-" + suffix,
            binding,
            ArtifactCandidateSubmission(
                "artifact-candidate-" + suffix,
                "patch",
                "sha256:artifact" + suffix,
                "object://artifact/" + suffix,
                10,
                "text/plain",
            ),
            actor_id=binding.worker_agent_identity,
        ))

    def record_evidence(self, binding, suffix="1"):
        return self.worker.record_evidence_candidate(RecordEvidenceCandidate(
            "cmd-ev-cand-" + suffix,
            "key-ev-cand-" + suffix,
            binding,
            EvidenceCandidateSubmission(
                "evidence-candidate-" + suffix,
                "adapter-log",
                "object://evidence/" + suffix,
                "sha256:evidence" + suffix,
                "2026-08-13T00:00:00Z",
            ),
            actor_id=binding.worker_agent_identity,
        ))

    def record_usage(self, binding, suffix="1", amount=100):
        return self.worker.record_usage_sample(RecordUsageSample(
            "cmd-usage-" + suffix,
            "key-usage-" + suffix,
            binding,
            UsageSampleSubmission(
                "usage-" + suffix,
                "sample-" + suffix,
                "reservation-1",
                {"execution_time_ms": amount},
                interval_start="2026-08-13T00:00:00Z",
                interval_end="2026-08-13T00:00:01Z",
            ),
            actor_id=binding.worker_agent_identity,
        ))

    def submit_success(self, binding, suffix="1", account_version=1):
        return self.worker.submit_result(SubmitExecutionResult(
            "cmd-result-" + suffix,
            "key-result-" + suffix,
            binding,
            ExecutionResultSubmission(
                "result-" + suffix,
                ExecutionOutcome.SUCCEEDED,
                "",
                ("artifact-candidate-" + suffix,),
                ("evidence-candidate-" + suffix,),
                ("sample-" + suffix,),
                "2026-08-13T00:00:00Z",
                "2026-08-13T00:00:01Z",
                "test-adapter",
                "1.0",
                primary_artifact_candidate_id="artifact-candidate-" + suffix,
                completion_claim_id="claim-" + suffix,
            ),
            account_version,
            actor_id=binding.worker_agent_identity,
        ))

    def test_worker_start_transitions_leased_to_running_with_p2_agentrun_binding(self):
        _, lease = self.prepare_leased()
        result = self.start(lease)
        self.assertEqual("EXECUTION_RUN_STARTED", result["result_code"])
        self.assertEqual("RUNNING", result["request_state"])
        with psycopg.connect(DATABASE_URL) as connection:
            self.assertEqual(("RUNNING", "worker-run-1"), connection.execute(
                """SELECT r.request_state,a.run_id
                   FROM execution_request_current_states r
                   JOIN agent_runs a ON a.execution_request_id=r.execution_request_id
                   WHERE r.execution_request_id=%s""",
                (lease["execution_request_id"],),
            ).fetchone())
            self.assertEqual(1, connection.execute(
                "SELECT count(*) FROM event_log WHERE event_type='execution.running'"
            ).fetchone()[0])

    def test_two_workers_compete_for_start_only_one_current_run(self):
        _, lease = self.prepare_leased()
        barrier = threading.Barrier(2)
        results = []

        def attempt(run_id, suffix):
            local = WorkerExecution(PostgresWorkerExecutionStore(DATABASE_URL))
            barrier.wait(timeout=5)
            try:
                results.append(local.start_run(StartWorkerRun(
                    "cmd-start-race-" + suffix,
                    "key-start-race-" + suffix,
                    self.binding(lease, run_id=run_id),
                    self.frozen(),
                    actor_id="worker-1",
                ))["result_code"])
            except CommandRejected as exc:
                results.append(exc.code)

        threads = [
            threading.Thread(target=attempt, args=("worker-run-a", "a")),
            threading.Thread(target=attempt, args=("worker-run-b", "b")),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
            self.assertFalse(thread.is_alive())
        self.assertEqual(1, results.count("EXECUTION_RUN_STARTED"), results)
        self.assertEqual(1, self.store.scalar(
            "SELECT count(*) FROM agent_runs WHERE status='RUNNING'"
        ))

    def test_current_token_candidates_usage_result_claim_and_settlement_are_atomic(self):
        _, lease = self.prepare_leased()
        self.start(lease)
        running_version = self.store.scalar(
            "SELECT request_version FROM execution_request_current_states WHERE execution_request_id='{}'".format(
                lease["execution_request_id"]
            )
        )
        binding = self.binding(lease, observed_request_version=running_version)
        self.record_artifact(binding)
        self.record_evidence(binding)
        self.record_usage(binding, amount=120)
        result = self.submit_success(binding)
        self.assertEqual("EXECUTION_RESULT_ADMITTED", result["result_code"])
        self.assertEqual("SUCCEEDED", result["request_state"])
        with psycopg.connect(DATABASE_URL) as connection:
            self.assertEqual(1, connection.execute("SELECT count(*) FROM execution_results").fetchone()[0])
            self.assertEqual(1, connection.execute("SELECT count(*) FROM completion_claims").fetchone()[0])
            self.assertEqual(1, connection.execute("SELECT count(*) FROM resource_settlements").fetchone()[0])
            self.assertEqual((120, 0), connection.execute(
                """SELECT consumed_amount,reserved_amount FROM resource_balances
                   WHERE account_id='account-1' AND dimension='execution_time_ms'"""
            ).fetchone())
            self.assertEqual("COMPLETION_CLAIMED", connection.execute(
                "SELECT state FROM tasks WHERE task_id='task-1'"
            ).fetchone()[0])
            self.assertEqual(0, connection.execute(
                "SELECT count(*) FROM verification_results"
            ).fetchone()[0])
            self.assertEqual(0, connection.execute(
                "SELECT count(*) FROM execution_lock_ownerships WHERE lock_state='ACTIVE'"
            ).fetchone()[0])

    def test_stale_token_result_is_quarantined_and_cannot_claim_or_settle(self):
        _, lease = self.prepare_leased()
        self.start(lease)
        running_version = self.store.scalar(
            "SELECT request_version FROM execution_request_current_states WHERE execution_request_id='{}'".format(
                lease["execution_request_id"]
            )
        )
        current = self.binding(lease, observed_request_version=running_version)
        self.record_artifact(current)
        self.record_evidence(current)
        self.record_usage(current, amount=80)
        stale = self.binding(lease, fencing_token=lease["fencing_token"] + 1,
                             observed_request_version=running_version)
        with self.assertRaisesRegex(CommandRejected, "FENCING_TOKEN_STALE"):
            self.submit_success(stale)
        with psycopg.connect(DATABASE_URL) as connection:
            self.assertEqual(1, connection.execute(
                "SELECT count(*) FROM execution_quarantine_records WHERE reason_code='FENCING_TOKEN_STALE'"
            ).fetchone()[0])
            self.assertEqual(0, connection.execute("SELECT count(*) FROM execution_results").fetchone()[0])
            self.assertEqual(0, connection.execute("SELECT count(*) FROM completion_claims").fetchone()[0])
            self.assertEqual(0, connection.execute("SELECT count(*) FROM resource_settlements").fetchone()[0])
            self.assertEqual((0, 500), connection.execute(
                """SELECT consumed_amount,reserved_amount FROM resource_balances
                   WHERE account_id='account-1' AND dimension='execution_time_ms'"""
            ).fetchone())

    def test_duplicate_usage_sample_is_not_double_counted_and_payload_conflict_rejects(self):
        _, lease = self.prepare_leased()
        self.start(lease)
        version = self.store.scalar(
            "SELECT request_version FROM execution_request_current_states WHERE execution_request_id='{}'".format(
                lease["execution_request_id"]
            )
        )
        binding = self.binding(lease, observed_request_version=version)
        first = self.record_usage(binding)
        second = self.record_usage(binding)
        self.assertEqual(first["sample_id"], second["sample_id"])
        with self.assertRaisesRegex(CommandRejected, "IDEMPOTENCY_PAYLOAD_CONFLICT"):
            self.record_usage(binding, amount=101)
        self.assertEqual(1, self.store.scalar(
            "SELECT count(*) FROM resource_usage_records WHERE sample_id='sample-1'"
        ))

    def test_two_current_results_concurrently_only_one_terminal_result_and_settlement(self):
        _, lease = self.prepare_leased()
        self.start(lease)
        version = self.store.scalar(
            "SELECT request_version FROM execution_request_current_states WHERE execution_request_id='{}'".format(
                lease["execution_request_id"]
            )
        )
        binding = self.binding(lease, observed_request_version=version)
        self.record_artifact(binding)
        self.record_evidence(binding)
        self.record_usage(binding)
        barrier = threading.Barrier(2)
        results = []

        def attempt(suffix):
            local = WorkerExecution(PostgresWorkerExecutionStore(DATABASE_URL))
            barrier.wait(timeout=5)
            try:
                results.append(local.submit_result(SubmitExecutionResult(
                    "cmd-result-race-" + suffix,
                    "key-result-race-" + suffix,
                    binding,
                    ExecutionResultSubmission(
                        "result-race-" + suffix,
                        ExecutionOutcome.SUCCEEDED,
                        "",
                        ("artifact-candidate-1",),
                        ("evidence-candidate-1",),
                        ("sample-1",),
                        "2026-08-13T00:00:00Z",
                        "2026-08-13T00:00:01Z",
                        "test-adapter",
                        "1.0",
                        primary_artifact_candidate_id="artifact-candidate-1",
                        completion_claim_id="claim-race-" + suffix,
                    ),
                    1,
                    actor_id="worker-1",
                ))["result_code"])
            except CommandRejected as exc:
                results.append(exc.code)

        threads = [threading.Thread(target=attempt, args=(suffix,)) for suffix in ("a", "b")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
            self.assertFalse(thread.is_alive())
        self.assertEqual(1, results.count("EXECUTION_RESULT_ADMITTED"), results)
        self.assertEqual(1, self.store.scalar("SELECT count(*) FROM execution_results"))
        self.assertEqual(1, self.store.scalar("SELECT count(*) FROM resource_settlements"))

    def test_takeover_invalidates_old_run_and_old_payload_quarantines(self):
        _, lease = self.prepare_leased()
        self.start(lease)
        old_version = self.store.scalar(
            "SELECT request_version FROM execution_request_current_states WHERE execution_request_id='{}'".format(
                lease["execution_request_id"]
            )
        )
        old_binding = self.binding(lease, observed_request_version=old_version)
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute(
                "UPDATE execution_leases SET expires_at=clock_timestamp() - interval '1 millisecond' WHERE lease_id=%s",
                (lease["lease_id"],),
            )
            connection.execute(
                "UPDATE execution_lock_ownerships SET expires_at=clock_timestamp() - interval '1 millisecond' WHERE lease_id=%s",
                (lease["lease_id"],),
            )
        self.scheduler.register(RegisterScheduler(
            command_id="cmd-register-new-worker",
            idempotency_key="key-register-new-worker",
            project_id="project-1",
            scheduler_id="sched-2",
            scheduler_session_id="session-2",
            actor_id="sched-2",
        ))
        new_lease = self.scheduler.acquire(AcquireExecutionLease(
            command_id="cmd-acquire-new-worker",
            idempotency_key="key-acquire-new-worker",
            project_id="project-1",
            scheduler_id="sched-2",
            scheduler_session_id="session-2",
            actor_id="sched-2",
        ))
        self.assertGreater(new_lease["fencing_token"], lease["fencing_token"])
        self.assertEqual("EXPIRED", self.store.scalar(
            "SELECT status FROM agent_runs WHERE run_id='worker-run-1'"
        ))
        with self.assertRaisesRegex(CommandRejected, "EXECUTION_REQUEST_NOT_RUNNING|AGENT_RUN_NOT_ACTIVE|FENCING_TOKEN_STALE"):
            self.record_artifact(old_binding)
        self.assertEqual(1, self.store.scalar("SELECT count(*) FROM execution_quarantine_records"))

    def test_fault_injection_precommit_points_roll_back_authority(self):
        points = (
            WorkerExecutionFaultPoint.AFTER_RECEIPT_PLACEHOLDER,
            WorkerExecutionFaultPoint.AFTER_RESULT_VALIDATED,
            WorkerExecutionFaultPoint.AFTER_RESULT_WRITE,
            WorkerExecutionFaultPoint.AFTER_COMPLETION_CLAIM,
            WorkerExecutionFaultPoint.AFTER_SETTLEMENT,
            WorkerExecutionFaultPoint.AFTER_RUN_TERMINAL,
            WorkerExecutionFaultPoint.AFTER_REQUEST_TERMINAL,
            WorkerExecutionFaultPoint.AFTER_LEASE_RELEASE,
            WorkerExecutionFaultPoint.AFTER_EVENT_BEFORE_OUTBOX,
            WorkerExecutionFaultPoint.AFTER_RECEIPT_BEFORE_COMMIT,
        )
        for point in points:
            with self.subTest(point=point.value):
                self.setUp()
                _, lease = self.prepare_leased()
                self.start(lease, point.value)
                version = self.store.scalar(
                    "SELECT request_version FROM execution_request_current_states WHERE execution_request_id='{}'".format(
                        lease["execution_request_id"]
                    )
                )
                binding = self.binding(lease, observed_request_version=version)
                self.record_artifact(binding, point.value)
                self.record_evidence(binding, point.value)
                self.record_usage(binding, point.value)
                faulted = PostgresWorkerExecutionStore(DATABASE_URL)
                faulted.fail_worker_once(point.value)
                with self.assertRaises(CommandRejected):
                    WorkerExecution(faulted).submit_result(SubmitExecutionResult(
                        "cmd-result-fault-" + point.value,
                        "key-result-fault-" + point.value,
                        binding,
                        ExecutionResultSubmission(
                            "result-fault-" + point.value,
                            ExecutionOutcome.SUCCEEDED,
                            "",
                            ("artifact-candidate-" + point.value,),
                            ("evidence-candidate-" + point.value,),
                            ("sample-" + point.value,),
                            "2026-08-13T00:00:00Z",
                            "2026-08-13T00:00:01Z",
                            "test-adapter",
                            "1.0",
                            primary_artifact_candidate_id="artifact-candidate-" + point.value,
                            completion_claim_id="claim-fault-" + point.value,
                        ),
                        1,
                        actor_id="worker-1",
                    ))
                self.assertEqual(0, self.store.scalar("SELECT count(*) FROM execution_results"))
                self.assertEqual(0, self.store.scalar("SELECT count(*) FROM resource_settlements"))


if __name__ == "__main__":
    unittest.main()
