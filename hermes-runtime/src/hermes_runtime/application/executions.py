from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Tuple

from hermes_runtime.domain.execution import ArtifactInputRef, LockIntent


@dataclass(frozen=True)
class PrepareExecutionRequest:
    command_id: str
    idempotency_key: str
    project_id: str
    task_id: str
    expected_project_version: int
    expected_task_version: int
    decision_id: str
    decision_version: int
    decision_hash: str
    action_id: str
    action_version: int
    action_content_hash: str
    action_type: str
    action_requirements_hash: str
    policy_decision_id: str
    policy_version: int
    policy_hash: str
    risk_assessment_id: str
    risk_version: int
    risk_hash: str
    mandatory_mitigations_hash: str
    reservation_id: str
    reservation_version: int
    reservation_hash: str
    capability_match_id: str
    capability_match_version: int
    capability_requirements_hash: str
    worker_template_id: str
    worker_template_revision: int
    worker_template_content_hash: str
    worker_template_availability_version: int
    context_bundle_id: str
    context_manifest_hash: str
    sandbox_profile_id: str
    sandbox_profile_hash: str
    sandbox_compiler_version: str
    sandbox_compiler_target: str
    verification_plan_id: str
    verification_plan_version: int
    verification_plan_hash: str
    input_artifacts: Tuple[ArtifactInputRef, ...] = ()
    lock_intents: Tuple[LockIntent, ...] = ()
    priority: int = 0
    actor_type: str = "execution_preparer"
    actor_id: str = "execution-preparer"
    reason: str = "prepare execution request"


class ExecutionPreparationStore(Protocol):
    def prepare_execution_request(self, command: PrepareExecutionRequest) -> Mapping[str, Any]:
        ...

    def list_pending_queue(self, project_id: str, limit: int = 50) -> Tuple[Mapping[str, Any], ...]:
        ...


class ExecutionPreparation:
    def __init__(self, store: ExecutionPreparationStore) -> None:
        self._store = store

    def prepare(self, command: PrepareExecutionRequest) -> Mapping[str, Any]:
        return self._store.prepare_execution_request(command)

    def pending(self, project_id: str, limit: int = 50) -> Tuple[Mapping[str, Any], ...]:
        return self._store.list_pending_queue(project_id, limit)
