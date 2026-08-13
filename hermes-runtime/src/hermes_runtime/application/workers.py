from dataclasses import dataclass
from typing import Any, Mapping, Optional, Protocol

from hermes_runtime.domain.worker_execution import (
    ArtifactCandidateSubmission,
    EvidenceCandidateSubmission,
    ExecutionResultSubmission,
    UsageSampleSubmission,
    WorkerFrozenContext,
    WorkerLeaseBinding,
)


@dataclass(frozen=True)
class StartWorkerRun:
    command_id: str
    idempotency_key: str
    binding: WorkerLeaseBinding
    frozen_context: WorkerFrozenContext
    actor_type: str = "worker"
    actor_id: str = ""
    reason: str = "start fenced worker run"


@dataclass(frozen=True)
class RecordArtifactCandidate:
    command_id: str
    idempotency_key: str
    binding: WorkerLeaseBinding
    candidate: ArtifactCandidateSubmission
    actor_type: str = "worker"
    actor_id: str = ""


@dataclass(frozen=True)
class RecordEvidenceCandidate:
    command_id: str
    idempotency_key: str
    binding: WorkerLeaseBinding
    candidate: EvidenceCandidateSubmission
    actor_type: str = "worker"
    actor_id: str = ""


@dataclass(frozen=True)
class RecordUsageSample:
    command_id: str
    idempotency_key: str
    binding: WorkerLeaseBinding
    sample: UsageSampleSubmission
    actor_type: str = "worker"
    actor_id: str = ""


@dataclass(frozen=True)
class SubmitExecutionResult:
    command_id: str
    idempotency_key: str
    binding: WorkerLeaseBinding
    result: ExecutionResultSubmission
    expected_account_version: int
    actor_type: str = "worker"
    actor_id: str = ""


class WorkerExecutionStore(Protocol):
    def start_run(self, command: StartWorkerRun) -> Mapping[str, Any]:
        ...

    def record_artifact_candidate(self, command: RecordArtifactCandidate) -> Mapping[str, Any]:
        ...

    def record_evidence_candidate(self, command: RecordEvidenceCandidate) -> Mapping[str, Any]:
        ...

    def record_usage_sample(self, command: RecordUsageSample) -> Mapping[str, Any]:
        ...

    def submit_result(self, command: SubmitExecutionResult) -> Mapping[str, Any]:
        ...

    def fail_worker_once(self, point: str) -> None:
        ...


class WorkerExecution:
    def __init__(self, store: WorkerExecutionStore) -> None:
        self._store = store

    def start_run(self, command: StartWorkerRun) -> Mapping[str, Any]:
        return self._store.start_run(_with_default_actor(command))

    def record_artifact_candidate(self, command: RecordArtifactCandidate) -> Mapping[str, Any]:
        return self._store.record_artifact_candidate(_with_default_actor(command))

    def record_evidence_candidate(self, command: RecordEvidenceCandidate) -> Mapping[str, Any]:
        return self._store.record_evidence_candidate(_with_default_actor(command))

    def record_usage_sample(self, command: RecordUsageSample) -> Mapping[str, Any]:
        return self._store.record_usage_sample(_with_default_actor(command))

    def submit_result(self, command: SubmitExecutionResult) -> Mapping[str, Any]:
        return self._store.submit_result(_with_default_actor(command))


def _with_default_actor(command):
    if command.actor_id:
        return command
    return command.__class__(
        **dict(command.__dict__, actor_id=command.binding.worker_agent_identity)
    )
