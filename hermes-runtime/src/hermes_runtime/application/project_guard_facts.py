from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from hermes_runtime.application.commands import (
    RecordProjectEvidenceFact,
    RecordProjectPolicyFact,
)


@dataclass(frozen=True)
class ProjectGuardFactRecord:
    fact_id: str
    project_id: str
    project_version: int
    from_state: str
    to_state: str
    result: str
    authority: str
    valid: bool


class ProjectGuardFactStore(Protocol):
    def record_evidence_fact(self, command: RecordProjectEvidenceFact) -> Mapping[str, Any]:
        ...

    def record_policy_fact(self, command: RecordProjectPolicyFact) -> Mapping[str, Any]:
        ...


class ProjectGuardFactAuthority:
    """Guarded runtime producers for project evidence/policy guard facts.

    P0-P5 created the guard tables and the fail-closed transition guard, but no
    runtime authority function produced project_evidence_facts or
    project_policy_decision_facts (only tests inserted them via raw SQL). P6
    closes that gap with guarded commands mirroring IssueProjectBudgetFact.
    The Control Plane submits these facts on behalf of the verification and
    policy authorities; Worker/Verifier/Scheduler roles cannot.
    """

    def __init__(self, store: ProjectGuardFactStore) -> None:
        self._store = store

    def record_evidence_fact(self, command: RecordProjectEvidenceFact) -> Mapping[str, Any]:
        return self._store.record_evidence_fact(command)

    def record_policy_fact(self, command: RecordProjectPolicyFact) -> Mapping[str, Any]:
        return self._store.record_policy_fact(command)
