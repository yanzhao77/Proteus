from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from hermes_runtime.domain.diagnosis import RULE_SET_VERSION


@dataclass(frozen=True)
class RunDiagnosis:
    command_id: str
    idempotency_key: str
    project_id: str
    situation_id: str
    situation_version: int
    analysis_context_id: str
    analysis_context_hash: str
    actor_type: str = "diagnosis_engine"
    actor_id: str = "diagnosis-engine"
    rule_set_version: str = RULE_SET_VERSION


class DiagnosisStore(Protocol):
    def run_diagnosis(self, command: RunDiagnosis) -> Mapping[str, Any]:
        ...


class DiagnosisEngine:
    """Application entry point for deterministic Diagnosis facts."""

    def __init__(self, store: DiagnosisStore) -> None:
        self._store = store

    def run(self, command: RunDiagnosis) -> Mapping[str, Any]:
        return self._store.run_diagnosis(command)
