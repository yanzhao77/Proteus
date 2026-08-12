from typing import Protocol

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
from hermes_runtime.domain.models import CommandReceipt, EventEnvelope, PublishResult


class EventPublisher(Protocol):
    def publish(self, envelope: EventEnvelope) -> PublishResult:
        ...


class RuntimeStore(Protocol):
    def admit_agent_run(self, command: AdmitAgentRun) -> CommandReceipt:
        ...

    def invalidate_agent_run(
        self, command: InvalidateAgentRun
    ) -> CommandReceipt:
        ...

    def create_verification_plan(
        self, command: CreateVerificationPlan
    ) -> CommandReceipt:
        ...

    def revise_verification_plan(
        self, command: ReviseVerificationPlan
    ) -> CommandReceipt:
        ...

    def submit_completion_claim(
        self, command: SubmitCompletionClaim
    ) -> CommandReceipt:
        ...

    def record_verification_result(
        self, command: RecordVerificationResult
    ) -> CommandReceipt:
        ...

    def apply_verified_task_transition(
        self, command: ApplyVerifiedTaskTransition
    ) -> CommandReceipt:
        ...

    def record_security_rejection(
        self, command: object, code: str, detail: str
    ) -> None:
        ...

    def apply_work_graph_patch(
        self, command: ApplyWorkGraphPatch
    ) -> CommandReceipt:
        ...

    def recompute_task_readiness(
        self, command: RecomputeTaskReadiness
    ) -> CommandReceipt:
        ...

    def consume_feedback_created(
        self, command: ConsumeFeedbackCreated
    ) -> bool:
        ...

    def create_project(self, command: CreateProject) -> CommandReceipt:
        ...

    def request_project_transition(
        self, command: RequestProjectTransition
    ) -> CommandReceipt:
        ...

    def pause_project(self, command: PauseProject) -> CommandReceipt:
        ...

    def resume_project(self, command: ResumeProject) -> CommandReceipt:
        ...

    def cancel_project(self, command: CancelProject) -> CommandReceipt:
        ...
