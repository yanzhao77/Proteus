from dataclasses import dataclass
from typing import Any, Mapping, Optional, Protocol

from hermes_runtime.domain.policy import POLICY_BUNDLE_VERSION


@dataclass(frozen=True)
class EvaluatePolicy:
    command_id: str
    idempotency_key: str
    project_id: str
    planning_run_id: str
    action_id: str
    expected_situation_version: int
    expected_action_content_hash: str
    actor_type: str = "policy_engine"
    actor_id: str = "policy-engine"
    reason: str = "evaluate policy"
    policy_bundle_version: str = POLICY_BUNDLE_VERSION
    target_environment: str = "unknown"
    runtime_emergency_freeze: bool = False


class PolicyStore(Protocol):
    def evaluate_policy(self, command: EvaluatePolicy) -> Mapping[str, Any]:
        ...


class PolicyEngine:
    def __init__(self, store: PolicyStore) -> None:
        self._store = store

    def evaluate(self, command: EvaluatePolicy) -> Mapping[str, Any]:
        return self._store.evaluate_policy(command)
