from dataclasses import dataclass
from typing import Any, Mapping, Optional, Protocol


@dataclass(frozen=True)
class AnalyzeSituationEvent:
    raw_envelope: Mapping[str, Any]
    expected_situation_version: Optional[int] = None


@dataclass(frozen=True)
class ResolveSituation:
    situation_id: str
    project_id: str
    expected_version: int
    command_id: str
    idempotency_key: str
    actor_type: str
    actor_id: str
    reason: str


class SituationStore(Protocol):
    def analyze_event(
        self, command: AnalyzeSituationEvent
    ) -> Mapping[str, Any]:
        ...

    def resolve_situation(
        self, command: ResolveSituation
    ) -> Mapping[str, Any]:
        ...


class SituationAnalyzer:
    """Application entry point; classification remains pure domain logic."""

    def __init__(self, store: SituationStore) -> None:
        self._store = store

    def analyze(
        self, raw_envelope: Mapping[str, Any],
        expected_situation_version: Optional[int] = None,
    ) -> Mapping[str, Any]:
        return self._store.analyze_event(AnalyzeSituationEvent(
            raw_envelope, expected_situation_version
        ))

    def resolve(self, command: ResolveSituation) -> Mapping[str, Any]:
        return self._store.resolve_situation(command)
