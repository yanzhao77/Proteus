from dataclasses import dataclass
from typing import Any, Mapping, Optional, Protocol

from hermes_runtime.domain.planner import (
    PLANNER_RULE_VERSION,
    REGISTRY_VERSION,
)


@dataclass(frozen=True)
class PlanCandidates:
    command_id: str
    idempotency_key: str
    project_id: str
    situation_id: str
    expected_situation_version: int
    analysis_context_id: str
    analysis_context_hash: str
    actor_type: str = "action_planner"
    actor_id: str = "action-planner"
    reason: str = "plan candidate actions"
    expected_diagnosis_id: Optional[str] = None
    expected_diagnosis_input_hash: Optional[str] = None
    registry_version: str = REGISTRY_VERSION
    planner_rule_version: str = PLANNER_RULE_VERSION


class PlannerStore(Protocol):
    def plan_candidates(self, command: PlanCandidates) -> Mapping[str, Any]:
        ...


class ActionPlanner:
    """Application entry point for immutable CandidateAction generation."""

    def __init__(self, store: PlannerStore) -> None:
        self._store = store

    def plan(self, command: PlanCandidates) -> Mapping[str, Any]:
        return self._store.plan_candidates(command)
