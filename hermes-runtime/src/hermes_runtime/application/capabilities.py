from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Tuple

from hermes_runtime.domain.capability import (
    CONTEXT_BUILDER_VERSION,
    CONTEXT_SELECTOR_SCHEMA_VERSION,
    SANDBOX_COMPILER_TARGET,
    SANDBOX_COMPILER_VERSION,
    AuthorityRef,
    CapabilityRequirement,
    ContextSelector,
    SandboxCompileInput,
    WorkerTemplateRevision,
)


@dataclass(frozen=True)
class RegisterCapabilitySchema:
    command_id: str
    idempotency_key: str
    project_id: str
    capability_name: str
    schema_version: str
    description: str
    expected_version: int = 0
    actor_type: str = "capability_registry"
    actor_id: str = "capability-registry"
    reason: str = "register capability schema"


@dataclass(frozen=True)
class CreateWorkerTemplateRevision:
    command_id: str
    idempotency_key: str
    project_id: str
    template: WorkerTemplateRevision
    expected_version: int
    actor_type: str = "capability_registry"
    actor_id: str = "capability-registry"
    reason: str = "create worker template revision"


@dataclass(frozen=True)
class ChangeWorkerTemplateAvailability:
    command_id: str
    idempotency_key: str
    project_id: str
    template_id: str
    revision: int
    availability_status: str
    admission_status: str
    expected_version: int
    actor_type: str = "capability_registry"
    actor_id: str = "capability-registry"
    reason: str = "change worker template availability"


@dataclass(frozen=True)
class MatchCapabilityRequirements:
    command_id: str
    idempotency_key: str
    project_id: str
    requirement: CapabilityRequirement
    expected_version: int
    actor_type: str = "capability_registry"
    actor_id: str = "capability-registry"
    reason: str = "match capability requirements"


@dataclass(frozen=True)
class CreateContextBundle:
    command_id: str
    idempotency_key: str
    project_id: str
    task_id: str
    decision_id: str
    action_id: str
    template_id: str
    template_revision: int
    selectors: Tuple[ContextSelector, ...]
    resolved_refs: Tuple[AuthorityRef, ...]
    expected_version: int = 0
    selector_schema_version: str = CONTEXT_SELECTOR_SCHEMA_VERSION
    builder_version: str = CONTEXT_BUILDER_VERSION
    actor_type: str = "context_builder"
    actor_id: str = "context-builder"
    reason: str = "create immutable context bundle"


@dataclass(frozen=True)
class CompileSandboxProfile:
    command_id: str
    idempotency_key: str
    project_id: str
    compile_input: SandboxCompileInput
    expected_version: int = 0
    actor_type: str = "sandbox_compiler"
    actor_id: str = "sandbox-compiler"
    reason: str = "compile sandbox profile"
    compiler_version: str = SANDBOX_COMPILER_VERSION
    target: str = SANDBOX_COMPILER_TARGET


class CapabilityPreparationStore(Protocol):
    def register_capability_schema(self, command: RegisterCapabilitySchema) -> Mapping[str, Any]:
        ...

    def create_worker_template_revision(self, command: CreateWorkerTemplateRevision) -> Mapping[str, Any]:
        ...

    def change_worker_template_availability(self, command: ChangeWorkerTemplateAvailability) -> Mapping[str, Any]:
        ...

    def match_capability_requirements(self, command: MatchCapabilityRequirements) -> Mapping[str, Any]:
        ...

    def create_context_bundle(self, command: CreateContextBundle) -> Mapping[str, Any]:
        ...

    def compile_sandbox_profile(self, command: CompileSandboxProfile) -> Mapping[str, Any]:
        ...


class ExecutionPreparationAuthority:
    def __init__(self, store: CapabilityPreparationStore) -> None:
        self._store = store

    def register_capability_schema(self, command: RegisterCapabilitySchema) -> Mapping[str, Any]:
        return self._store.register_capability_schema(command)

    def create_worker_template_revision(self, command: CreateWorkerTemplateRevision) -> Mapping[str, Any]:
        return self._store.create_worker_template_revision(command)

    def change_worker_template_availability(self, command: ChangeWorkerTemplateAvailability) -> Mapping[str, Any]:
        return self._store.change_worker_template_availability(command)

    def match_capability_requirements(self, command: MatchCapabilityRequirements) -> Mapping[str, Any]:
        return self._store.match_capability_requirements(command)

    def create_context_bundle(self, command: CreateContextBundle) -> Mapping[str, Any]:
        return self._store.create_context_bundle(command)

    def compile_sandbox_profile(self, command: CompileSandboxProfile) -> Mapping[str, Any]:
        return self._store.compile_sandbox_profile(command)
