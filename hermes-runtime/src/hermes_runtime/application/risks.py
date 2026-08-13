from dataclasses import dataclass
from typing import Any, Mapping, Tuple, Protocol

from hermes_runtime.domain.risk import RISK_MODEL_VERSION


@dataclass(frozen=True)
class AssessRisk:
    command_id: str
    idempotency_key: str
    project_id: str
    planning_run_id: str
    action_id: str
    expected_situation_version: int
    expected_action_content_hash: str
    actor_type: str = "risk_engine"
    actor_id: str = "risk-engine"
    reason: str = "assess risk"
    risk_model_version: str = RISK_MODEL_VERSION
    target_environment: str = "unknown"
    verified_mitigations: Tuple[str, ...] = ()


class RiskStore(Protocol):
    def assess_risk(self, command: AssessRisk) -> Mapping[str, Any]:
        ...


class RiskEngine:
    def __init__(self, store: RiskStore) -> None:
        self._store = store

    def assess(self, command: AssessRisk) -> Mapping[str, Any]:
        return self._store.assess_risk(command)
