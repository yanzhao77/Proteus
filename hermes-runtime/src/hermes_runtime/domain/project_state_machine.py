from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple

from hermes_runtime.domain.models import Project, ProjectState


class ProjectGuardRejected(ValueError):
    pass


class ProjectAction(str, Enum):
    ADVANCE = "ADVANCE"
    PAUSE = "PAUSE"
    RESUME = "RESUME"
    CANCEL = "CANCEL"


@dataclass(frozen=True)
class ProjectTransitionDecision:
    target_state: ProjectState
    resume_state: Optional[ProjectState]
    reason_code: str


@dataclass(frozen=True)
class ProjectGuardFactSummary:
    fact_id: str
    project_id: str
    project_version: int
    valid: bool
    current: bool
    authority: str
    result: str
    refs: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ProjectGuardContext:
    project_id: str
    project_version: int
    evidence: Optional[ProjectGuardFactSummary] = None
    policy: Optional[ProjectGuardFactSummary] = None
    budget: Optional[ProjectGuardFactSummary] = None
    gate: Optional[ProjectGuardFactSummary] = None
    requires_human_gate: bool = False
    required_tasks_passed: bool = True
    fact_refs: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ProjectTransitionRequirements:
    evidence: bool
    policy: bool
    budget: bool
    gate_if_required: bool
    tasks_passed: bool


MAINLINE = (
    ProjectState.CREATED,
    ProjectState.INTAKE,
    ProjectState.DISCOVERY,
    ProjectState.PLANNING,
    ProjectState.DESIGNING,
    ProjectState.IMPLEMENTING,
    ProjectState.VERIFYING,
    ProjectState.HARDENING,
    ProjectState.PACKAGING,
    ProjectState.DELIVERING,
    ProjectState.ACCEPTED,
)
LEGAL_ADVANCES = frozenset(zip(MAINLINE, MAINLINE[1:]))
TERMINAL_STATES = frozenset(
    {ProjectState.ACCEPTED, ProjectState.FAILED, ProjectState.CANCELLED}
)
PAUSABLE_STATES = frozenset(MAINLINE[:-1])

AUTHORITY_EVIDENCE = "verification_engine"
AUTHORITY_POLICY = "policy_engine"
AUTHORITY_BUDGET = "budget_engine"
AUTHORITY_GATE = "human_gate"

ADVANCE_REQUIREMENTS = ProjectTransitionRequirements(
    evidence=True,
    policy=True,
    budget=True,
    gate_if_required=True,
    tasks_passed=False,
)
VERIFYING_TO_HARDENING_REQUIREMENTS = ProjectTransitionRequirements(
    evidence=True,
    policy=True,
    budget=True,
    gate_if_required=True,
    tasks_passed=True,
)
PAUSE_REQUIREMENTS = ProjectTransitionRequirements(
    evidence=True,
    policy=True,
    budget=True,
    gate_if_required=True,
    tasks_passed=False,
)
RESUME_REQUIREMENTS = ProjectTransitionRequirements(
    evidence=True,
    policy=True,
    budget=True,
    gate_if_required=True,
    tasks_passed=False,
)
CANCEL_REQUIREMENTS = ProjectTransitionRequirements(
    evidence=False,
    policy=False,
    budget=False,
    gate_if_required=False,
    tasks_passed=False,
)


def project_transition_requirements(
    source: ProjectState,
    action: ProjectAction,
    target_state: Optional[ProjectState],
) -> ProjectTransitionRequirements:
    if action is ProjectAction.CANCEL:
        return CANCEL_REQUIREMENTS
    if action is ProjectAction.PAUSE:
        return PAUSE_REQUIREMENTS
    if action is ProjectAction.RESUME:
        return RESUME_REQUIREMENTS
    if (
        action is ProjectAction.ADVANCE
        and source is ProjectState.VERIFYING
        and target_state is ProjectState.HARDENING
    ):
        return VERIFYING_TO_HARDENING_REQUIREMENTS
    if action is ProjectAction.ADVANCE:
        return ADVANCE_REQUIREMENTS
    return ProjectTransitionRequirements(True, True, True, True, True)


def evaluate_project_transition(
    project: Project,
    action: ProjectAction,
    target_state: Optional[ProjectState] = None,
    guard: Optional[ProjectGuardContext] = None,
) -> ProjectTransitionDecision:
    if project.state in TERMINAL_STATES:
        raise ProjectGuardRejected("PROJECT_TERMINAL")

    if action is ProjectAction.ADVANCE:
        if target_state is None or (project.state, target_state) not in LEGAL_ADVANCES:
            raise ProjectGuardRejected("ILLEGAL_PROJECT_TRANSITION")
        _evaluate_guard_context(
            project,
            project_transition_requirements(project.state, action, target_state),
            guard,
        )
        return ProjectTransitionDecision(target_state, None, "PROJECT_ADVANCE_ALLOWED")

    if action is ProjectAction.PAUSE:
        if project.state is ProjectState.PAUSED:
            raise ProjectGuardRejected("PROJECT_ALREADY_PAUSED")
        if project.state not in PAUSABLE_STATES:
            raise ProjectGuardRejected("PROJECT_NOT_PAUSABLE")
        _evaluate_guard_context(
            project,
            project_transition_requirements(project.state, action, target_state),
            guard,
        )
        return ProjectTransitionDecision(
            ProjectState.PAUSED, project.state, "PROJECT_PAUSE_ALLOWED"
        )

    if action is ProjectAction.RESUME:
        if project.state is not ProjectState.PAUSED:
            raise ProjectGuardRejected("PROJECT_NOT_PAUSED")
        if project.resume_state not in PAUSABLE_STATES:
            raise ProjectGuardRejected("PROJECT_RESUME_CONTEXT_MISSING")
        _evaluate_guard_context(
            project,
            project_transition_requirements(project.state, action, project.resume_state),
            guard,
        )
        return ProjectTransitionDecision(
            project.resume_state, None, "PROJECT_RESUME_ALLOWED"
        )

    if action is ProjectAction.CANCEL:
        return ProjectTransitionDecision(
            ProjectState.CANCELLED, None, "PROJECT_CANCEL_ALLOWED"
        )

    raise ProjectGuardRejected("UNKNOWN_PROJECT_ACTION")


def _evaluate_guard_context(
    project: Project,
    requirements: ProjectTransitionRequirements,
    guard: Optional[ProjectGuardContext],
) -> None:
    if not any(
        (
            requirements.evidence,
            requirements.policy,
            requirements.budget,
            requirements.gate_if_required,
            requirements.tasks_passed,
        )
    ):
        return
    if guard is None:
        raise ProjectGuardRejected("PROJECT_GUARD_INPUT_INCOMPLETE")
    if guard.project_id != project.project_id or guard.project_version != project.version:
        raise ProjectGuardRejected("PROJECT_GUARD_INPUT_INCOMPLETE")
    if requirements.evidence:
        _require_fact(
            guard.evidence,
            project,
            AUTHORITY_EVIDENCE,
            "VALID",
            "PROJECT_EVIDENCE_REQUIRED",
            "PROJECT_EVIDENCE_INVALID",
        )
    if requirements.policy:
        policy = _require_fact(
            guard.policy,
            project,
            AUTHORITY_POLICY,
            ("ALLOW", "REQUIRE_HUMAN"),
            "PROJECT_POLICY_DECISION_REQUIRED",
            "PROJECT_POLICY_NOT_ALLOWED",
        )
        if policy.result == "REQUIRE_HUMAN":
            guard = ProjectGuardContext(
                guard.project_id,
                guard.project_version,
                guard.evidence,
                guard.policy,
                guard.budget,
                guard.gate,
                True,
                guard.required_tasks_passed,
                guard.fact_refs,
            )
    if requirements.budget:
        _require_fact(
            guard.budget,
            project,
            AUTHORITY_BUDGET,
            "OK",
            "PROJECT_BUDGET_FACT_REQUIRED",
            "PROJECT_BUDGET_HARD_STOP",
        )
    if requirements.gate_if_required and guard.requires_human_gate:
        _require_fact(
            guard.gate,
            project,
            AUTHORITY_GATE,
            "ANSWERED_APPLIED",
            "PROJECT_GATE_DECISION_REQUIRED",
            "PROJECT_GATE_NOT_APPLIED",
        )
    if requirements.tasks_passed and not guard.required_tasks_passed:
        raise ProjectGuardRejected("REQUIRED_TASKS_NOT_PASSED")


def _require_fact(
    fact: Optional[ProjectGuardFactSummary],
    project: Project,
    expected_authority: str,
    expected_result,
    missing_code: str,
    invalid_code: str,
) -> ProjectGuardFactSummary:
    if fact is None:
        raise ProjectGuardRejected(missing_code)
    if fact.project_id != project.project_id:
        raise ProjectGuardRejected("PROJECT_GUARD_FACT_PROJECT_MISMATCH")
    if fact.project_version != project.version or not fact.current:
        raise ProjectGuardRejected("PROJECT_GUARD_FACT_STALE")
    if fact.authority != expected_authority:
        raise ProjectGuardRejected(invalid_code)
    allowed_results = (
        expected_result if isinstance(expected_result, tuple) else (expected_result,)
    )
    if not fact.valid or fact.result not in allowed_results:
        raise ProjectGuardRejected(invalid_code)
    return fact
