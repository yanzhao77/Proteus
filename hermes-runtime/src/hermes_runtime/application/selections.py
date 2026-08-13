from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Tuple

from hermes_runtime.domain.selection import WEIGHT_PROFILE_VERSION


@dataclass(frozen=True)
class CandidateAccountBinding:
    action_id: str
    account_id: str
    expected_account_version: int


@dataclass(frozen=True)
class SelectActions:
    command_id: str
    idempotency_key: str
    project_id: str
    planning_run_id: str
    expected_situation_version: int
    expected_selection_version: int
    candidate_account_bindings: Tuple[CandidateAccountBinding, ...]
    weight_profile_id: str = WEIGHT_PROFILE_VERSION
    actor_type: str = "action_selection"
    actor_id: str = "action-selection"
    reason: str = "select action intent"


class SelectionStore(Protocol):
    def select_actions(self, command: SelectActions) -> Mapping[str, Any]:
        ...


class ActionSelection:
    def __init__(self, store: SelectionStore) -> None:
        self._store = store

    def select(self, command: SelectActions) -> Mapping[str, Any]:
        return self._store.select_actions(command)
