import os
import threading
import unittest
import uuid
from pathlib import Path

try:
    import psycopg
except ImportError:  # The explicit integration command reports the missing dependency.
    psycopg = None

from hermes_runtime.application.commands import (
    ApplyVerifiedTaskTransition,
    RecordVerificationResult,
    SubmitCompletionClaim,
)
from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.application.handlers import ControlPlane
from hermes_runtime.domain.models import (
    Actor,
    ActorType,
    ArtifactCandidate,
    CommandEnvelope,
    CompletionClaim,
    Evidence,
    TaskState,
    VerificationResult,
    VerificationCheckResult,
    Verdict,
)
from hermes_runtime.infrastructure.postgres import FaultPoint, PostgresRuntimeStore


DATABASE_URL = os.environ.get("HERMES_TEST_DATABASE_URL")


def envelope(command_type, actor, expected_version, payload_key):
    return CommandEnvelope(
        command_id="cmd-" + str(uuid.uuid4()),
        command_type=command_type,
        idempotency_key=payload_key,
        expected_version=expected_version,
        actor=actor,
        reason="conformance test",
        project_id="project-1",
    )


@unittest.skipUnless(
    DATABASE_URL and psycopg,
    "requires psycopg and explicit HERMES_TEST_DATABASE_URL pointing to PostgreSQL 14+",
)
class PostgresVerticalSliceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = PostgresRuntimeStore(DATABASE_URL)
        cls.store.check_server_version(140000)
        migrations = Path(__file__).parents[1] / "migrations"
        for migration in sorted(migrations.glob("*.sql")):
            cls.store.apply_migration(migration)

    def setUp(self):
        self.store.reset_for_test()
        self.control_plane = ControlPlane(self.store)
        self.worker = Actor(ActorType.WORKER, "worker-1")
        self.verifier = Actor(ActorType.VERIFIER, "verifier-1")
        self.control = Actor(ActorType.CONTROL_PLANE, "control-plane-1")
        self.store.seed_verifier("verifier-1")
        self.store.seed_task("task-1", TaskState.RUNNING, version=1)
        self.store.seed_closure_authority("task-1")

    def claim_command(self, key="claim-key", expected_version=1, artifact_hash="sha256:aaa"):
        claim = CompletionClaim(
            claim_id="claim-1",
            task_id="task-1",
            run_id="run-task-1",
            worker_identity=self.worker,
            artifact=ArtifactCandidate(
                "artifact-1", "task-1", artifact_hash, "text/plain", "worker-1"
            ),
            summary="worker completed execution",
        )
        return SubmitCompletionClaim(
            envelope(
                "task.submit_completion_claim", self.worker, expected_version, key
            ),
            claim,
        )

    def verification_command(
        self,
        key="verify-key",
        expected_version=2,
        artifact_hash="sha256:aaa",
        verifier=None,
        valid_evidence=True,
        include_evidence=True,
        verdict=Verdict.PASS,
    ):
        identity = verifier or self.verifier
        result = VerificationResult(
            verification_id="verification-1",
            plan_id="plan-task-1",
            plan_version=1,
            task_id="task-1",
            project_id="project-1",
            artifact_id="artifact-1",
            artifact_hash=artifact_hash,
            verifier_identity=identity,
            verifier_run_id=("verifier-run-task-1" if identity == self.verifier else "missing-verifier-run"),
            verdict=verdict,
            check_results=(VerificationCheckResult(
                "required-check", verdict, (), ("evidence-1",) if include_evidence else (),
                "2026-08-12T00:00:00Z", "2026-08-12T00:01:00Z",
            ),),
            evidence=(
                Evidence(
                    "evidence-1",
                    "artifact-1",
                    artifact_hash,
                    identity.actor_id,
                    valid_evidence,
                ),
            ) if include_evidence else (),
            started_at="2026-08-12T00:00:00Z",
            completed_at="2026-08-12T00:01:00Z",
            correlation_id="corr-1",
        )
        return RecordVerificationResult(
            envelope("verification.record_result", identity, expected_version, key),
            result,
        )

    def transition_command(self, key="transition-key", expected_version=2):
        return ApplyVerifiedTaskTransition(
            envelope(
                "task.apply_verified_transition", self.control, expected_version, key
            ),
            task_id="task-1",
            verification_id="verification-1",
        )

    def submit_claim(self, **kwargs):
        return self.control_plane.submit_completion_claim(self.claim_command(**kwargs))

    def prepare_verification(self, **kwargs):
        self.submit_claim()
        return self.control_plane.record_verification_result(
            self.verification_command(**kwargs)
        )

    def test_completion_claim_and_outbox_commit_atomically(self):
        result = self.submit_claim()

        task = self.store.read_task("task-1")
        self.assertEqual("APPLIED", result.status)
        self.assertEqual(TaskState.COMPLETION_CLAIMED, task.state)
        self.assertEqual(2, task.version)
        self.assertEqual(1, self.store.count("completion_claims"))
        self.assertEqual(1, self.store.count("event_log"))
        self.assertEqual(1, self.store.count("outbox_messages"))
        self.assertEqual(
            self.store.scalar("SELECT event_id FROM event_log"),
            self.store.scalar("SELECT event_id FROM outbox_messages"),
        )

    def test_duplicate_completion_command_returns_original_without_second_effect(self):
        command = self.claim_command()
        first = self.control_plane.submit_completion_claim(command)
        second = self.control_plane.submit_completion_claim(command)

        self.assertEqual(first, second)
        self.assertEqual(1, self.store.count("completion_claims"))
        self.assertEqual(1, self.store.count("outbox_messages"))
        self.assertEqual(2, self.store.read_task("task-1").version)

    def test_duplicate_event_delivery_applies_consumer_effect_once(self):
        receipt = self.submit_claim()
        event_id = receipt.event_ids[0]

        first = self.store.consume_event("test-consumer", event_id)
        second = self.store.consume_event("test-consumer", event_id)

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(1, self.store.count("consumer_inbox"))
        self.assertEqual(1, self.store.count("consumer_effects"))

    def test_consumer_crash_before_checkpoint_is_duplicate_safe(self):
        receipt = self.submit_claim()
        event_id = receipt.event_ids[0]
        self.store.fail_once(FaultPoint.AFTER_CONSUMER_EFFECT_BEFORE_CHECKPOINT)

        with self.assertRaisesRegex(RuntimeError, "injected"):
            self.store.consume_event(
                "crashing-consumer", event_id, fail_before_checkpoint=True
            )

        applied = self.store.consume_event("crashing-consumer", event_id)
        self.assertTrue(applied)
        self.assertEqual(1, self.store.count("consumer_inbox"))
        self.assertEqual(1, self.store.count("consumer_effects"))
        self.assertEqual(1, self.store.count("consumer_checkpoints"))

    def test_same_idempotency_key_with_different_payload_conflicts(self):
        self.submit_claim()

        with self.assertRaisesRegex(CommandRejected, "IDEMPOTENCY_CONFLICT"):
            self.submit_claim(artifact_hash="sha256:different")

        self.assertEqual(1, self.store.count("completion_claims"))
        self.assertEqual(1, self.store.count("outbox_messages"))

    def test_completion_expected_version_conflict_has_no_side_effect(self):
        with self.assertRaisesRegex(CommandRejected, "VERSION_CONFLICT"):
            self.submit_claim(expected_version=0)

        self.assertEqual(TaskState.RUNNING, self.store.read_task("task-1").state)
        self.assertEqual(0, self.store.count("completion_claims"))
        self.assertEqual(0, self.store.count("outbox_messages"))

    def test_injected_failure_between_state_and_outbox_rolls_back_everything(self):
        self.store.fail_once(FaultPoint.AFTER_STATE_BEFORE_EVENT)

        with self.assertRaisesRegex(RuntimeError, "injected"):
            self.submit_claim()

        self.assertEqual(TaskState.RUNNING, self.store.read_task("task-1").state)
        self.assertEqual(1, self.store.read_task("task-1").version)
        self.assertEqual(0, self.store.count("completion_claims"))
        self.assertEqual(0, self.store.count("artifacts"))
        self.assertEqual(0, self.store.count("event_log"))
        self.assertEqual(0, self.store.count("outbox_messages"))
        self.assertEqual(
            0,
            self.store.scalar(
                "SELECT count(*) FROM command_receipts WHERE command_type NOT LIKE 'test.seed_%'"
            ),
        )

    def test_verification_result_is_recorded_without_changing_task(self):
        receipt = self.prepare_verification()

        task = self.store.read_task("task-1")
        self.assertEqual("APPLIED", receipt.status)
        self.assertEqual(TaskState.COMPLETION_CLAIMED, task.state)
        self.assertEqual(2, task.version)
        self.assertEqual(1, self.store.count("verification_results"))
        self.assertEqual(1, self.store.count("evidence"))

    def test_verification_fact_and_outbox_roll_back_together(self):
        self.submit_claim()
        self.store.fail_once(FaultPoint.AFTER_FACT_BEFORE_EVENT)

        with self.assertRaisesRegex(RuntimeError, "injected"):
            self.control_plane.record_verification_result(
                self.verification_command()
            )

        self.assertEqual(0, self.store.count("verification_results"))
        self.assertEqual(0, self.store.count("evidence"))
        self.assertEqual(1, self.store.count("event_log"))
        self.assertEqual(1, self.store.count("outbox_messages"))
        self.assertEqual(
            0,
            self.store.scalar(
                "SELECT count(*) FROM command_receipts WHERE command_type = 'verification.record_result'"
            ),
        )

    def test_hash_mismatch_is_rejected_audited_and_cannot_transition(self):
        self.submit_claim()

        with self.assertRaisesRegex(CommandRejected, "ARTIFACT_HASH_MISMATCH"):
            self.control_plane.record_verification_result(
                self.verification_command(artifact_hash="sha256:other")
            )

        self.assertEqual(0, self.store.count("verification_results"))
        self.assertEqual(1, self.store.count("audit_records"))
        self.assertEqual(TaskState.COMPLETION_CLAIMED, self.store.read_task("task-1").state)

    def test_invalid_verifier_identity_is_rejected_and_audited(self):
        self.submit_claim()
        intruder = Actor(ActorType.VERIFIER, "not-authorized")

        with self.assertRaisesRegex(CommandRejected, "VERIFIER_NOT_AUTHORIZED"):
            self.control_plane.record_verification_result(
                self.verification_command(verifier=intruder)
            )

        self.assertEqual(0, self.store.count("verification_results"))
        self.assertEqual(1, self.store.count("audit_records"))

    def test_worker_cannot_record_verdict_or_directly_transition(self):
        self.submit_claim()
        forged = Actor(ActorType.WORKER, "worker-1")

        with self.assertRaisesRegex(CommandRejected, "VERIFIER_IDENTITY_REQUIRED"):
            self.control_plane.record_verification_result(
                self.verification_command(verifier=forged)
            )
        with self.assertRaisesRegex(CommandRejected, "CONTROL_PLANE_AUTHORITY_REQUIRED"):
            command = self.transition_command()
            forged_envelope = CommandEnvelope(
                command.envelope.command_id,
                command.envelope.command_type,
                "worker-transition-key",
                command.envelope.expected_version,
                forged,
                command.envelope.reason,
                command.envelope.project_id,
            )
            self.control_plane.apply_verified_task_transition(
                ApplyVerifiedTaskTransition(
                    forged_envelope, command.task_id, command.verification_id
                )
            )

        self.assertEqual(TaskState.COMPLETION_CLAIMED, self.store.read_task("task-1").state)
        self.assertEqual(0, self.store.count("verification_results"))
        self.assertEqual(2, self.store.count("audit_records"))
        self.assertEqual(
            0,
            self.store.scalar(
                "SELECT count(*) FROM event_log WHERE event_type IN ('task.passed', 'task.failed', 'verification.recorded')"
            ),
        )

    def test_rejected_worker_forgery_still_enforces_payload_idempotency(self):
        self.submit_claim()
        forged = Actor(ActorType.WORKER, "worker-1")
        first = self.verification_command(
            key="forged-verdict-key", verifier=forged, verdict=Verdict.PASS
        )
        second = self.verification_command(
            key="forged-verdict-key", verifier=forged, verdict=Verdict.FAIL
        )

        with self.assertRaisesRegex(CommandRejected, "VERIFIER_IDENTITY_REQUIRED"):
            self.control_plane.record_verification_result(first)
        with self.assertRaisesRegex(CommandRejected, "IDEMPOTENCY_CONFLICT"):
            self.control_plane.record_verification_result(second)

        self.assertEqual(0, self.store.count("verification_results"))
        self.assertEqual(TaskState.COMPLETION_CLAIMED, self.store.read_task("task-1").state)
        self.assertEqual(
            1,
            self.store.scalar(
                "SELECT count(*) FROM audit_records WHERE reason_code = 'IDEMPOTENCY_CONFLICT'"
            ),
        )

    def test_concurrent_rejected_commands_enforce_payload_idempotency(self):
        self.submit_claim()
        barrier = threading.Barrier(2)
        outcomes = []
        forged = Actor(ActorType.WORKER, "worker-1")

        def run(command):
            plane = ControlPlane(PostgresRuntimeStore(DATABASE_URL))
            barrier.wait()
            try:
                plane.record_verification_result(command)
            except CommandRejected as exc:
                outcomes.append(exc.code)

        commands = (
            self.verification_command(
                key="concurrent-forgery-key", verifier=forged, verdict=Verdict.PASS
            ),
            self.verification_command(
                key="concurrent-forgery-key", verifier=forged, verdict=Verdict.FAIL
            ),
        )
        threads = [threading.Thread(target=run, args=(command,)) for command in commands]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertCountEqual(
            ["VERIFIER_IDENTITY_REQUIRED", "IDEMPOTENCY_CONFLICT"], outcomes
        )
        self.assertEqual(
            2,
            self.store.scalar(
                "SELECT count(*) FROM command_receipts WHERE command_type NOT LIKE 'test.seed_%'"
            ),
        )
        self.assertEqual(2, self.store.count("audit_records"))

    def test_append_only_and_immutable_facts_reject_update_and_delete(self):
        self.prepare_verification()

        statements = (
            "UPDATE artifacts SET media_type = 'application/json'",
            "DELETE FROM evidence",
            "UPDATE verification_results SET criteria = 'rewritten'",
            "DELETE FROM event_log",
        )
        for statement in statements:
            with self.subTest(statement=statement):
                with self.assertRaises(psycopg.errors.RaiseException):
                    with self.store._connect() as connection:
                        connection.execute(statement)

    def test_missing_or_invalid_evidence_cannot_pass(self):
        self.submit_claim()

        with self.assertRaisesRegex(
            CommandRejected, "CHECK_EVIDENCE_ARTIFACT_MISMATCH"
        ):
            self.control_plane.record_verification_result(
                self.verification_command(valid_evidence=False)
            )

        self.assertEqual(TaskState.COMPLETION_CLAIMED, self.store.read_task("task-1").state)
        self.assertEqual(0, self.store.count("verification_results"))

        with self.assertRaisesRegex(
            CommandRejected, "REQUIRED_CHECK_EVIDENCE_MISSING"
        ):
            self.control_plane.record_verification_result(
                self.verification_command(
                    key="verify-empty-evidence", include_evidence=False
                )
            )

        self.assertEqual(TaskState.COMPLETION_CLAIMED, self.store.read_task("task-1").state)
        self.assertEqual(0, self.store.count("verification_results"))

    def test_valid_pass_transitions_task_and_outbox_atomically(self):
        self.prepare_verification()
        result = self.control_plane.apply_verified_task_transition(
            self.transition_command()
        )

        task = self.store.read_task("task-1")
        self.assertEqual("APPLIED", result.status)
        self.assertEqual(TaskState.PASSED, task.state)
        self.assertEqual(3, task.version)
        self.assertEqual(
            1,
            self.store.scalar(
                "SELECT count(*) FROM event_log WHERE event_type = 'task.passed'"
            ),
        )
        self.assertEqual(3, self.store.count("outbox_messages"))

    def test_valid_fail_transitions_task_to_formal_failed(self):
        self.prepare_verification(verdict=Verdict.FAIL)
        self.control_plane.apply_verified_task_transition(self.transition_command())

        self.assertEqual(TaskState.FAILED, self.store.read_task("task-1").state)
        self.assertEqual(
            1,
            self.store.scalar(
                "SELECT count(*) FROM event_log WHERE event_type = 'task.failed'"
            ),
        )

    def test_duplicate_verification_delivery_does_not_transition_twice(self):
        self.prepare_verification()
        command = self.transition_command()
        first = self.control_plane.apply_verified_task_transition(command)
        second = self.control_plane.apply_verified_task_transition(command)

        self.assertEqual(first, second)
        self.assertEqual(3, self.store.read_task("task-1").version)
        self.assertEqual(
            1,
            self.store.scalar(
                "SELECT count(*) FROM event_log WHERE event_type = 'task.passed'"
            ),
        )

    def test_transition_expected_version_conflict_is_not_overwritten(self):
        self.prepare_verification()

        with self.assertRaisesRegex(CommandRejected, "VERSION_CONFLICT"):
            self.control_plane.apply_verified_task_transition(
                self.transition_command(expected_version=1)
            )

        self.assertEqual(TaskState.COMPLETION_CLAIMED, self.store.read_task("task-1").state)
        self.assertEqual(2, self.store.read_task("task-1").version)
        self.assertEqual(
            0,
            self.store.scalar(
                "SELECT count(*) FROM event_log WHERE event_type IN ('task.passed', 'task.failed')"
            ),
        )

    def test_transition_failure_before_outbox_rolls_back(self):
        self.prepare_verification()
        self.store.fail_once(FaultPoint.AFTER_STATE_BEFORE_EVENT)

        with self.assertRaisesRegex(RuntimeError, "injected"):
            self.control_plane.apply_verified_task_transition(
                self.transition_command()
            )

        self.assertEqual(TaskState.COMPLETION_CLAIMED, self.store.read_task("task-1").state)
        self.assertEqual(2, self.store.read_task("task-1").version)
        self.assertEqual(2, self.store.count("outbox_messages"))
        self.assertEqual(
            0,
            self.store.scalar(
                "SELECT count(*) FROM event_log WHERE event_type IN ('task.passed', 'task.failed')"
            ),
        )

    def test_independent_connections_cannot_apply_same_version_twice(self):
        self.prepare_verification()
        barrier = threading.Barrier(2)
        outcomes = []

        def run(command):
            plane = ControlPlane(PostgresRuntimeStore(DATABASE_URL))
            barrier.wait()
            try:
                outcomes.append(
                    ("ok", plane.apply_verified_task_transition(command).status)
                )
            except CommandRejected as exc:
                outcomes.append(("error", exc.code))

        first = self.transition_command(key="transition-race-1")
        second = self.transition_command(key="transition-race-2")
        threads = [
            threading.Thread(target=run, args=(first,)),
            threading.Thread(target=run, args=(second,)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(1, sum(kind == "ok" for kind, _ in outcomes))
        self.assertEqual(1, sum(value == "VERSION_CONFLICT" for _, value in outcomes))
        self.assertEqual(TaskState.PASSED, self.store.read_task("task-1").state)
        self.assertEqual(3, self.store.read_task("task-1").version)


if __name__ == "__main__":
    if not DATABASE_URL:
        raise SystemExit("HERMES_TEST_DATABASE_URL is required for integration tests")
    unittest.main()
