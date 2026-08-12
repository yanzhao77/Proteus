from hermes_runtime.application.commands import (
    AdmitAgentRun,
    ApplyVerifiedTaskTransition,
    ApplyWorkGraphPatch,
    CancelProject,
    ConsumeFeedbackCreated,
    CreateProject,
    CreateVerificationPlan,
    InvalidateAgentRun,
    PauseProject,
    RecordVerificationResult,
    RecomputeTaskReadiness,
    RequestProjectTransition,
    ResumeProject,
    ReviseVerificationPlan,
    SubmitCompletionClaim,
)
from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.application.ports import RuntimeStore
from hermes_runtime.domain.models import ActorType, CommandReceipt


class ControlPlane:
    def __init__(self, store: RuntimeStore) -> None:
        self._store = store

    def submit_completion_claim(
        self, command: SubmitCompletionClaim
    ) -> CommandReceipt:
        if command.envelope.actor.actor_type is not ActorType.WORKER:
            self._reject(
                command,
                "WORKER_IDENTITY_REQUIRED",
                "only a Worker may submit CompletionClaim",
            )
        if command.claim.worker_identity != command.envelope.actor:
            self._reject(
                command,
                "WORKER_IDENTITY_MISMATCH",
                "claim identity does not match command actor",
            )
        return self._store.submit_completion_claim(command)

    def admit_agent_run(self, command: AdmitAgentRun) -> CommandReceipt:
        self._require_command_type(command, "agent_run.admit")
        self._require_control_plane_authority(command)
        if command.run.created_by != command.envelope.actor:
            self._reject(command, "AGENT_RUN_CREATOR_MISMATCH", "run creator must match actor")
        return self._store.admit_agent_run(command)

    def invalidate_agent_run(self, command: InvalidateAgentRun) -> CommandReceipt:
        self._require_command_type(command, "agent_run.invalidate")
        self._require_control_plane_authority(command)
        return self._store.invalidate_agent_run(command)

    def create_verification_plan(
        self, command: CreateVerificationPlan
    ) -> CommandReceipt:
        self._require_command_type(command, "verification_plan.create")
        self._require_control_plane_authority(command)
        if command.plan.created_by != command.envelope.actor:
            self._reject(command, "VERIFICATION_PLAN_CREATOR_MISMATCH", "plan creator must match actor")
        return self._store.create_verification_plan(command)

    def revise_verification_plan(
        self, command: ReviseVerificationPlan
    ) -> CommandReceipt:
        self._require_command_type(command, "verification_plan.revise")
        self._require_control_plane_authority(command)
        if command.plan.created_by != command.envelope.actor:
            self._reject(command, "VERIFICATION_PLAN_CREATOR_MISMATCH", "plan creator must match actor")
        return self._store.revise_verification_plan(command)

    def record_verification_result(
        self, command: RecordVerificationResult
    ) -> CommandReceipt:
        if command.envelope.actor.actor_type is not ActorType.VERIFIER:
            self._reject(
                command,
                "VERIFIER_IDENTITY_REQUIRED",
                "Worker cannot produce formal PASS/FAIL",
            )
        if command.result.verifier_identity != command.envelope.actor:
            self._reject(
                command,
                "VERIFIER_IDENTITY_MISMATCH",
                "result identity does not match command actor",
            )
        return self._store.record_verification_result(command)

    def apply_verified_task_transition(
        self, command: ApplyVerifiedTaskTransition
    ) -> CommandReceipt:
        if command.envelope.actor.actor_type is not ActorType.CONTROL_PLANE:
            self._reject(
                command,
                "CONTROL_PLANE_AUTHORITY_REQUIRED",
                "only Control Plane may commit Task state",
            )
        return self._store.apply_verified_task_transition(command)

    def apply_work_graph_patch(
        self, command: ApplyWorkGraphPatch
    ) -> CommandReceipt:
        self._require_control_plane(command)
        return self._store.apply_work_graph_patch(command)

    def recompute_task_readiness(
        self, command: RecomputeTaskReadiness
    ) -> CommandReceipt:
        self._require_control_plane(command)
        return self._store.recompute_task_readiness(command)

    def consume_feedback_created(
        self, command: ConsumeFeedbackCreated
    ) -> bool:
        self._require_control_plane(command)
        return self._store.consume_feedback_created(command)

    def create_project(self, command: CreateProject) -> CommandReceipt:
        self._require_command_type(command, "project.create")
        self._require_project_submitter(command)
        self._require_requester(
            command,
            {ActorType.USER, ActorType.MAIN_HERMES, ActorType.CONTROL_PLANE},
        )
        return self._store.create_project(command)

    def request_project_transition(
        self, command: RequestProjectTransition
    ) -> CommandReceipt:
        self._require_command_type(command, "project.request_transition")
        self._require_project_submitter(command)
        self._require_requester(
            command,
            {
                ActorType.USER,
                ActorType.MAIN_HERMES,
                ActorType.CONTROL_PLANE,
                ActorType.RECOVERY_CONTROLLER,
            },
        )
        return self._store.request_project_transition(command)

    def pause_project(self, command: PauseProject) -> CommandReceipt:
        self._require_command_type(command, "project.pause")
        self._require_project_submitter(command)
        self._require_requester(
            command,
            {
                ActorType.USER,
                ActorType.MAIN_HERMES,
                ActorType.CONTROL_PLANE,
                ActorType.RECOVERY_CONTROLLER,
                ActorType.SYSTEM_OPERATOR,
            },
        )
        return self._store.pause_project(command)

    def resume_project(self, command: ResumeProject) -> CommandReceipt:
        self._require_command_type(command, "project.resume")
        self._require_project_submitter(command)
        self._require_requester(
            command,
            {
                ActorType.USER,
                ActorType.MAIN_HERMES,
                ActorType.CONTROL_PLANE,
                ActorType.RECOVERY_CONTROLLER,
                ActorType.SYSTEM_OPERATOR,
            },
        )
        return self._store.resume_project(command)

    def cancel_project(self, command: CancelProject) -> CommandReceipt:
        self._require_command_type(command, "project.cancel")
        self._require_project_submitter(command)
        self._require_requester(
            command, {ActorType.USER, ActorType.SYSTEM_OPERATOR}
        )
        if not command.authorization_ref:
            self._reject(
                command,
                "CANCELLATION_AUTHORIZATION_REQUIRED",
                "cancel requires a verified user or operator authorization reference",
            )
        return self._store.cancel_project(command)

    def _require_project_submitter(self, command) -> None:
        actor = command.envelope.actor
        if actor is None or actor.actor_type is not ActorType.CONTROL_PLANE:
            self._reject(
                command,
                "CONTROL_PLANE_AUTHORITY_REQUIRED",
                "only Control Plane may commit Project state",
            )
        if not command.envelope.reason.strip():
            self._reject(
                command,
                "COMMAND_REASON_REQUIRED",
                "Project authority commands require a non-empty reason",
            )

    def _require_command_type(self, command, expected: str) -> None:
        if command.envelope.command_type != expected:
            self._reject(
                command,
                "PROJECT_COMMAND_SEMANTICS_MISMATCH",
                "{} requires command_type {}".format(
                    type(command).__name__, expected
                ),
            )

    def _require_requester(self, command, allowed) -> None:
        requester = command.requested_by
        if requester is None or requester.actor_type not in allowed:
            self._reject(
                command,
                "PROJECT_REQUESTER_NOT_AUTHORIZED",
                "requester is not authorized for this Project command",
            )

    def _require_control_plane(self, command) -> None:
        if command.envelope.actor.actor_type is not ActorType.CONTROL_PLANE:
            self._reject(
                command,
                "CONTROL_PLANE_AUTHORITY_REQUIRED",
                "only Control Plane may mutate the authoritative Work Graph",
            )

    def _require_control_plane_authority(self, command) -> None:
        if command.envelope.actor.actor_type is not ActorType.CONTROL_PLANE:
            self._reject(command, "CONTROL_PLANE_AUTHORITY_REQUIRED", "only Control Plane may create authority records")
        if not command.envelope.reason.strip():
            self._reject(command, "COMMAND_REASON_REQUIRED", "authority commands require a reason")

    def _reject(self, command, code: str, detail: str) -> None:
        self._store.record_security_rejection(command, code, detail)
        raise CommandRejected(code, detail)
