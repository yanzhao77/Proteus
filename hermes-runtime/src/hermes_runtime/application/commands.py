from dataclasses import dataclass

from hermes_runtime.domain.models import (
    AgentRun,
    Actor,
    CommandEnvelope,
    CompletionClaim,
    ProjectState,
    VerificationResult,
    VerificationPlan,
)
from hermes_runtime.domain.graph import GraphPatch


@dataclass(frozen=True)
class SubmitCompletionClaim:
    envelope: CommandEnvelope
    claim: CompletionClaim


@dataclass(frozen=True)
class AdmitAgentRun:
    envelope: CommandEnvelope
    run: AgentRun


@dataclass(frozen=True)
class InvalidateAgentRun:
    envelope: CommandEnvelope
    run_id: str


@dataclass(frozen=True)
class CreateVerificationPlan:
    envelope: CommandEnvelope
    plan: VerificationPlan


@dataclass(frozen=True)
class ReviseVerificationPlan:
    envelope: CommandEnvelope
    plan: VerificationPlan


@dataclass(frozen=True)
class RecordVerificationResult:
    envelope: CommandEnvelope
    result: VerificationResult


@dataclass(frozen=True)
class ApplyVerifiedTaskTransition:
    envelope: CommandEnvelope
    task_id: str
    verification_id: str


@dataclass(frozen=True)
class ApplyWorkGraphPatch:
    envelope: CommandEnvelope
    patch: GraphPatch


@dataclass(frozen=True)
class RecomputeTaskReadiness:
    envelope: CommandEnvelope
    task_ids: tuple


@dataclass(frozen=True)
class ConsumeFeedbackCreated:
    envelope: CommandEnvelope
    consumer_id: str
    event_id: str


@dataclass(frozen=True)
class CreateProject:
    envelope: CommandEnvelope
    title: str
    requested_by: Actor


@dataclass(frozen=True)
class RequestProjectTransition:
    envelope: CommandEnvelope
    target_state: ProjectState
    requested_by: Actor
    supporting_refs: tuple = ()


@dataclass(frozen=True)
class PauseProject:
    envelope: CommandEnvelope
    requested_by: Actor
    authorization_ref: str = ""


@dataclass(frozen=True)
class ResumeProject:
    envelope: CommandEnvelope
    requested_by: Actor
    authorization_ref: str = ""


@dataclass(frozen=True)
class CancelProject:
    envelope: CommandEnvelope
    requested_by: Actor
    authorization_ref: str


@dataclass(frozen=True)
class CreateResourceAccount:
    envelope: CommandEnvelope
    account_id: str
    scope_type: str
    scope_id: str
    limits: dict
    currency: str = ""
    thresholds_basis_points: tuple = (7500, 9500, 10000)


@dataclass(frozen=True)
class ReserveResources:
    envelope: CommandEnvelope
    account_id: str
    reservation_id: str
    owner_type: str
    owner_id: str
    amounts: dict
    currency: str = ""
    preparation_id: str = ""


@dataclass(frozen=True)
class ReleaseReservation:
    envelope: CommandEnvelope
    reservation_id: str
    terminal_status: str = "RELEASED"


@dataclass(frozen=True)
class RecordResourceUsage:
    envelope: CommandEnvelope
    usage_id: str
    sample_id: str
    reservation_id: str
    owner_type: str
    owner_id: str
    amounts: dict
    currency: str = ""


@dataclass(frozen=True)
class SettleReservation:
    envelope: CommandEnvelope
    settlement_id: str
    reservation_id: str


@dataclass(frozen=True)
class ReconcileReservation:
    envelope: CommandEnvelope
    reconcile_id: str
    reservation_id: str


@dataclass(frozen=True)
class IssueProjectBudgetFact:
    envelope: CommandEnvelope
    budget_fact_id: str
    account_id: str
    project_version: int
    from_state: str
    to_state: str
