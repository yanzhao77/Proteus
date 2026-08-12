import unittest

from hermes_runtime.domain.models import (
    Actor,
    ActorType,
    Evidence,
    Task,
    TaskState,
    VerificationResult,
    VerificationCheckResult,
    Verdict,
)
from hermes_runtime.domain.state_machine import (
    GuardRejected,
    evaluate_completion_claim,
    evaluate_verified_transition,
)


class CompletionClaimGuardTests(unittest.TestCase):
    def test_worker_claim_can_only_reach_completion_claimed(self):
        task = Task("task-1", TaskState.RUNNING, 4, None, None, None)

        decision = evaluate_completion_claim(task, "artifact-1", "sha256:aaa")

        self.assertEqual(TaskState.COMPLETION_CLAIMED, decision.target_state)
        self.assertNotIn(decision.target_state, {TaskState.PASSED, TaskState.FAILED})

    def test_completion_claim_rejects_non_running_task(self):
        task = Task("task-1", TaskState.PASSED, 5, "artifact-1", "sha256:aaa", None)

        with self.assertRaisesRegex(GuardRejected, "TASK_NOT_RUNNING"):
            evaluate_completion_claim(task, "artifact-2", "sha256:bbb")


class VerificationGuardTests(unittest.TestCase):
    def setUp(self):
        self.task = Task(
            "task-1",
            TaskState.COMPLETION_CLAIMED,
            5,
            "artifact-1",
            "sha256:aaa",
            "worker-1",
            "project-1",
            "plan-1",
            1,
            "worker-run-1",
            "worker-context",
        )
        self.verifier = Actor(ActorType.VERIFIER, "verifier-1")
        self.evidence = Evidence(
            "evidence-1", "artifact-1", "sha256:aaa", "verifier-1", True
        )

    def result(self, verdict=Verdict.PASS, artifact_hash="sha256:aaa", evidence=None):
        return VerificationResult(
            verification_id="verification-1",
            plan_id="plan-1",
            plan_version=1,
            task_id="task-1",
            project_id="project-1",
            artifact_id="artifact-1",
            artifact_hash=artifact_hash,
            verifier_identity=self.verifier,
            verifier_run_id="verifier-run-1",
            verdict=verdict,
            check_results=(VerificationCheckResult(
                "required-check", verdict, (), ("evidence-1",),
                "2026-08-12T00:00:00Z", "2026-08-12T00:01:00Z",
            ),),
            evidence=(self.evidence,) if evidence is None else tuple(evidence),
            started_at="2026-08-12T00:00:00Z",
            completed_at="2026-08-12T00:01:00Z",
            correlation_id="corr-1",
        )

    def test_pass_requires_exact_hash_and_valid_evidence(self):
        decision = evaluate_verified_transition(self.task, self.result())
        self.assertEqual(TaskState.PASSED, decision.target_state)

    def test_fail_is_a_formal_failed_transition(self):
        decision = evaluate_verified_transition(self.task, self.result(Verdict.FAIL))
        self.assertEqual(TaskState.FAILED, decision.target_state)

    def test_hash_mismatch_is_rejected(self):
        with self.assertRaisesRegex(GuardRejected, "ARTIFACT_HASH_MISMATCH"):
            evaluate_verified_transition(
                self.task, self.result(artifact_hash="sha256:other")
            )

    def test_missing_evidence_cannot_pass(self):
        with self.assertRaisesRegex(GuardRejected, "VALID_EVIDENCE_REQUIRED"):
            evaluate_verified_transition(self.task, self.result(evidence=()))

    def test_invalid_evidence_cannot_pass(self):
        invalid = Evidence(
            "evidence-1", "artifact-1", "sha256:aaa", "verifier-1", False
        )
        with self.assertRaisesRegex(GuardRejected, "VALID_EVIDENCE_REQUIRED"):
            evaluate_verified_transition(self.task, self.result(evidence=(invalid,)))

    def test_worker_identity_cannot_produce_verdict(self):
        forged = VerificationResult(
            verification_id="verification-1",
            plan_id="plan-1",
            plan_version=1,
            task_id="task-1",
            project_id="project-1",
            artifact_id="artifact-1",
            artifact_hash="sha256:aaa",
            verifier_identity=Actor(ActorType.WORKER, "worker-1"),
            verifier_run_id="worker-run-1",
            verdict=Verdict.PASS,
            check_results=(VerificationCheckResult(
                "required-check", Verdict.PASS, (), ("evidence-1",),
                "2026-08-12T00:00:00Z", "2026-08-12T00:01:00Z",
            ),),
            evidence=(self.evidence,),
            started_at="2026-08-12T00:00:00Z",
            completed_at="2026-08-12T00:01:00Z",
            correlation_id="corr-1",
        )
        with self.assertRaisesRegex(GuardRejected, "VERIFIER_IDENTITY_REQUIRED"):
            evaluate_verified_transition(self.task, forged)


if __name__ == "__main__":
    unittest.main()
