from hermes_runtime.domain.models import (
    ActorType,
    Task,
    TaskState,
    TransitionDecision,
    VerificationResult,
    Verdict,
)


class GuardRejected(ValueError):
    pass


def evaluate_completion_claim(
    task: Task, artifact_id: str, artifact_hash: str
) -> TransitionDecision:
    if task.state is not TaskState.RUNNING:
        raise GuardRejected("TASK_NOT_RUNNING")
    if not artifact_id or not artifact_hash.startswith("sha256:"):
        raise GuardRejected("INVALID_ARTIFACT")
    return TransitionDecision(
        TaskState.COMPLETION_CLAIMED, "worker completion claim admitted"
    )


def validate_verification_result(task: Task, result: VerificationResult) -> None:
    if task.state not in {TaskState.COMPLETION_CLAIMED, TaskState.VERIFYING}:
        raise GuardRejected("TASK_NOT_AWAITING_VERIFICATION")
    if result.verifier_identity.actor_type is not ActorType.VERIFIER:
        raise GuardRejected("VERIFIER_IDENTITY_REQUIRED")
    if result.task_id != task.task_id:
        raise GuardRejected("VERIFICATION_TASK_MISMATCH")
    if task.project_id is not None and result.project_id != task.project_id:
        raise GuardRejected("VERIFICATION_PROJECT_MISMATCH")
    if not task.current_verification_plan_id:
        raise GuardRejected("CURRENT_VERIFICATION_PLAN_REQUIRED")
    if (
        result.plan_id != task.current_verification_plan_id
        or result.plan_version != task.current_verification_plan_version
    ):
        raise GuardRejected("VERIFICATION_PLAN_MISMATCH")
    if (
        result.artifact_id != task.current_artifact_id
        or result.artifact_hash != task.current_artifact_hash
    ):
        raise GuardRejected("ARTIFACT_HASH_MISMATCH")
    if result.verifier_identity.actor_id == task.completion_worker_identity:
        raise GuardRejected("WORKER_VERIFIER_IDENTITY_NOT_INDEPENDENT")
    if result.verifier_run_id == task.completion_worker_run_id:
        raise GuardRejected("WORKER_VERIFIER_RUN_NOT_INDEPENDENT")
    valid_evidence = [
        evidence
        for evidence in result.evidence
        if evidence.valid
        and evidence.artifact_id == result.artifact_id
        and evidence.artifact_hash == result.artifact_hash
        and evidence.producer_identity == result.verifier_identity.actor_id
    ]
    if not valid_evidence:
        raise GuardRejected("VALID_EVIDENCE_REQUIRED")


def evaluate_verified_transition(
    task: Task, result: VerificationResult
) -> TransitionDecision:
    validate_verification_result(task, result)
    if result.verdict is Verdict.PASS:
        return TransitionDecision(TaskState.PASSED, "formal verification passed")
    if result.verdict is Verdict.FAIL:
        return TransitionDecision(TaskState.FAILED, "formal verification failed")
    raise GuardRejected("FORMAL_PASS_OR_FAIL_REQUIRED")
