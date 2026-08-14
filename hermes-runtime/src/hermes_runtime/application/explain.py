from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

from hermes_runtime.domain.explain import ExplainEdge, ExplainNode
from hermes_runtime.domain.models import Actor


@dataclass(frozen=True)
class CaptureDecisionExplain:
    command_id: str
    idempotency_key: str
    project_id: str
    source_type: str
    source_id: str
    source_version: int
    expected_source_version: int
    source_hash: str
    schema_version: str
    producer_version: str
    summary: Mapping[str, Any]
    nodes: Sequence[ExplainNode]
    edges: Sequence[ExplainEdge]
    redaction_class: str
    retention_policy: str
    retention_until: str
    authorization_scope: Mapping[str, Any]
    actor: Actor
    authorization_ref: str
    reason: str
    causation_id: str = ""
    correlation_id: str = ""
    trace_id: str = ""
    fault_point: str = ""


@dataclass(frozen=True)
class QueryDecisionExplain:
    project_id: str
    snapshot_id: str
    actor: Actor
    authorization_scope: Mapping[str, Any]


class ExplainStore(Protocol):
    def capture(self, command: CaptureDecisionExplain) -> Mapping[str, Any]:
        ...

    def query(self, query: QueryDecisionExplain) -> Mapping[str, Any]:
        ...


class DecisionExplainAuthority:
    def __init__(self, store: ExplainStore) -> None:
        self._store = store

    def capture(self, command: CaptureDecisionExplain) -> Mapping[str, Any]:
        return self._store.capture(command)

    def query(self, query: QueryDecisionExplain) -> Mapping[str, Any]:
        return self._store.query(query)
