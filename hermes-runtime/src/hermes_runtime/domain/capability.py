import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping, Optional, Tuple


CAPABILITY_SCHEMA_VERSION = "capability-schema/1.0"
WORKER_TEMPLATE_SCHEMA_VERSION = "worker-template-schema/1.0"
CAPABILITY_MATCHER_VERSION = "capability-matcher/1.0"
CONTEXT_SELECTOR_SCHEMA_VERSION = "context-selector/1.0"
CONTEXT_BUILDER_VERSION = "context-builder/1.0"
SANDBOX_COMPILER_VERSION = "sandbox-compiler/1.0"
SANDBOX_PROFILE_SCHEMA_VERSION = "sandbox-profile/1.0"
SANDBOX_COMPILER_TARGET = "contract-only/1.0"

MAX_CONTEXT_SELECTORS = 32
MAX_CONTEXT_ITEMS = 64
MAX_CONTEXT_ITEM_JSON_BYTES = 4096
MAX_CONTEXT_MANIFEST_JSON_BYTES = 65536

RESOURCE_DIMENSIONS = (
    "llm_tokens", "llm_cost_minor", "agent_runs", "retry_count",
    "execution_time_ms", "cpu_time_ms", "gpu_time_ms",
    "docker_runtime_ms", "browser_runtime_ms", "external_api_calls",
    "storage_bytes", "human_attention_requests",
)

SUPPORTED_CONTEXT_SELECTOR_TYPES = (
    "project", "task", "selected_action", "decision_record", "artifact",
    "verification_plan", "policy_decision", "risk_assessment",
    "resource_reservation", "evidence",
)

SUPPORTED_SANDBOX_CONSTRAINTS = (
    "network_access", "filesystem_write", "environment", "secret_access",
    "production_access", "allowed_tools", "forbidden_paths",
    "max_external_api_calls", "required_mitigations", "lock_scopes",
    "execution_time_ms", "cpu_time_ms", "storage_bytes", "process_count",
    "output_bytes",
)

SECRET_FIELD_PATTERN = re.compile(r"(secret|token|password|credential|private[_-]?key)", re.I)


class CapabilityRejected(ValueError):
    pass


class TrustLevel(str, Enum):
    UNTRUSTED = "UNTRUSTED"
    STANDARD = "STANDARD"
    ELEVATED = "ELEVATED"
    PRIVILEGED = "PRIVILEGED"


TRUST_RANK = {
    TrustLevel.UNTRUSTED.value: 0,
    TrustLevel.STANDARD.value: 100,
    TrustLevel.ELEVATED.value: 200,
    TrustLevel.PRIVILEGED.value: 300,
}


class AvailabilityStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DRAINING = "DRAINING"
    DISABLED = "DISABLED"


class AdmissionStatus(str, Enum):
    ADMISSIBLE = "ADMISSIBLE"
    NOT_ADMISSIBLE = "NOT_ADMISSIBLE"


@dataclass(frozen=True)
class WorkerTemplateRevision:
    template_id: str
    revision: int
    project_id: Optional[str]
    runtime_kind: str
    capabilities: Tuple[str, ...]
    trust_level: str
    allowed_tools: Tuple[str, ...]
    supported_sandbox_features: Tuple[str, ...]
    resource_envelope: Mapping[str, int]
    constraint_ranges: Mapping[str, Any]
    concurrency_capacity: int
    content_hash: Optional[str] = None


@dataclass(frozen=True)
class AvailableWorkerTemplate:
    template: WorkerTemplateRevision
    availability_status: str = AvailabilityStatus.AVAILABLE.value
    admission_status: str = AdmissionStatus.ADMISSIBLE.value
    availability_version: int = 1


@dataclass(frozen=True)
class CapabilityRequirement:
    project_id: str
    task_id: str
    decision_id: str
    action_id: str
    action_type: str
    action_content_hash: str
    required_capabilities: Tuple[str, ...]
    required_tools: Tuple[str, ...]
    minimum_trust: str
    sandbox_requirements: Mapping[str, Any]
    resource_envelope: Mapping[str, int]
    lock_scopes: Tuple[str, ...] = ()
    mandatory_constraints: Tuple[str, ...] = ()


@dataclass(frozen=True)
class CapabilityMatchResult:
    match_id: str
    status: str
    reason_code: str
    requirements_hash: str
    matcher_version: str
    template_id: Optional[str] = None
    template_revision: Optional[int] = None
    availability_version: Optional[int] = None
    template_content_hash: Optional[str] = None


@dataclass(frozen=True)
class ContextSelector:
    selector_type: str
    ref_id: str
    required: bool = True


@dataclass(frozen=True)
class AuthorityRef:
    ref_type: str
    ref_id: str
    project_id: str
    task_id: Optional[str]
    version: Optional[int]
    content_hash: str
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class ContextBundle:
    bundle_id: str
    project_id: str
    task_id: str
    decision_id: str
    action_id: str
    template_id: str
    template_revision: int
    selector_schema_version: str
    builder_version: str
    selectors: Tuple[ContextSelector, ...]
    items: Tuple[AuthorityRef, ...]
    manifest: Mapping[str, Any]
    manifest_hash: str


@dataclass(frozen=True)
class SandboxCompileInput:
    project_id: str
    task_id: str
    action_id: str
    action_content_hash: str
    policy_constraints: Mapping[str, Any]
    risk_required_mitigations: Tuple[str, ...]
    risk_available_mitigations: Tuple[str, ...]
    action_constraints: Mapping[str, Any]
    template: WorkerTemplateRevision
    context_bundle_hash: str
    lock_scopes: Tuple[str, ...]
    compiler_version: str = SANDBOX_COMPILER_VERSION
    target: str = SANDBOX_COMPILER_TARGET


@dataclass(frozen=True)
class SandboxProfile:
    profile_id: str
    project_id: str
    task_id: str
    action_id: str
    template_id: str
    template_revision: int
    context_bundle_hash: str
    compiler_version: str
    target: str
    profile: Mapping[str, Any]
    profile_hash: str
    constraints_hash: str


def normalize_capability_name(value: str) -> str:
    text = str(value or "").strip().lower().replace("_", "-")
    if not text or "*" in text or text in {"all", "any", "database", "repo"}:
        raise CapabilityRejected("CAPABILITY_NAME_INVALID")
    if not re.match(r"^[a-z0-9][a-z0-9.-]{0,126}[a-z0-9]$", text):
        raise CapabilityRejected("CAPABILITY_NAME_INVALID")
    return text


def normalize_trust_level(value: str) -> str:
    text = str(value or "").strip().upper()
    if text not in TRUST_RANK:
        raise CapabilityRejected("CAPABILITY_TRUST_UNKNOWN")
    return text


def trust_rank(value: str) -> int:
    return TRUST_RANK[normalize_trust_level(value)]


def normalize_worker_template(template: WorkerTemplateRevision) -> Mapping[str, Any]:
    if template.revision < 1:
        raise CapabilityRejected("WORKER_TEMPLATE_REVISION_INVALID")
    if template.concurrency_capacity < 0:
        raise CapabilityRejected("WORKER_TEMPLATE_CAPACITY_INVALID")
    capabilities = tuple(sorted({normalize_capability_name(item) for item in template.capabilities}))
    if not capabilities:
        raise CapabilityRejected("WORKER_TEMPLATE_CAPABILITY_REQUIRED")
    envelope = _normalize_resource_envelope(template.resource_envelope, allow_empty=True)
    supported = tuple(sorted({_norm_key(item) for item in template.supported_sandbox_features}))
    unknown_features = set(supported) - set(SUPPORTED_SANDBOX_CONSTRAINTS)
    if unknown_features:
        raise CapabilityRejected("WORKER_TEMPLATE_SANDBOX_FEATURE_UNKNOWN")
    payload = {
        "schema_version": WORKER_TEMPLATE_SCHEMA_VERSION,
        "template_id": _require_id(template.template_id, "WORKER_TEMPLATE_ID_INVALID"),
        "revision": int(template.revision),
        "project_id": template.project_id,
        "runtime_kind": _require_id(template.runtime_kind, "WORKER_TEMPLATE_KIND_INVALID"),
        "capabilities": capabilities,
        "trust_level": normalize_trust_level(template.trust_level),
        "allowed_tools": tuple(sorted({_norm_atom(item) for item in template.allowed_tools})),
        "supported_sandbox_features": supported,
        "resource_envelope": envelope,
        "constraint_ranges": _canonical(template.constraint_ranges),
        "concurrency_capacity": int(template.concurrency_capacity),
    }
    return payload


def worker_template_content_hash(template: WorkerTemplateRevision) -> str:
    return hash_json(normalize_worker_template(template))


def match_worker_template(
    requirement: CapabilityRequirement,
    templates: Tuple[AvailableWorkerTemplate, ...],
    *,
    known_capabilities: Tuple[str, ...] = (),
) -> CapabilityMatchResult:
    normalized = normalize_capability_requirement(requirement)
    requirements_hash = hash_json(normalized)
    known = {normalize_capability_name(item) for item in known_capabilities}
    if known and not set(normalized["required_capabilities"]).issubset(known):
        return _match_reject("UNKNOWN_REQUIREMENT", requirements_hash, requirement)
    rows = []
    for available in templates:
        template = normalize_worker_template(available.template)
        scope_ok = available.template.project_id in (None, requirement.project_id)
        if not scope_ok:
            continue
        rows.append((available, template))
    if not rows:
        return _match_reject("NO_MATCH", requirements_hash, requirement)

    compatible_caps = [
        item for item in rows
        if set(normalized["required_capabilities"]).issubset(item[1]["capabilities"])
    ]
    if not compatible_caps:
        return _match_reject("NO_MATCH", requirements_hash, requirement)

    available_rows = [
        item for item in compatible_caps
        if item[0].availability_status == AvailabilityStatus.AVAILABLE.value
        and item[0].admission_status == AdmissionStatus.ADMISSIBLE.value
    ]
    if not available_rows:
        return _match_reject("UNAVAILABLE", requirements_hash, requirement)

    trusted = [
        item for item in available_rows
        if trust_rank(item[1]["trust_level"]) >= trust_rank(normalized["minimum_trust"])
    ]
    if not trusted:
        return _match_reject("TRUST_INSUFFICIENT", requirements_hash, requirement)

    tools = [
        item for item in trusted
        if set(normalized["required_tools"]).issubset(item[1]["allowed_tools"])
    ]
    if not tools:
        return _match_reject("TOOL_UNSUPPORTED", requirements_hash, requirement)

    sandbox_keys = set(normalized["sandbox_requirements"]).union(normalized["mandatory_constraints"])
    sandbox = [
        item for item in tools
        if sandbox_keys.issubset(set(item[1]["supported_sandbox_features"]))
    ]
    if not sandbox:
        return _match_reject("SANDBOX_UNSUPPORTED", requirements_hash, requirement)

    resourced = [
        item for item in sandbox
        if _resource_envelope_fits(normalized["resource_envelope"], item[1]["resource_envelope"])
    ]
    if not resourced:
        return _match_reject("RESOURCE_ENVELOPE_UNSUPPORTED", requirements_hash, requirement)

    chosen_available, chosen = sorted(
        resourced,
        key=lambda item: (
            trust_rank(item[1]["trust_level"]),
            item[1]["template_id"],
            int(item[1]["revision"]),
        ),
    )[0]
    return CapabilityMatchResult(
        match_id="capmatch-" + raw_hash({
            "requirements_hash": requirements_hash,
            "template_id": chosen["template_id"],
            "revision": chosen["revision"],
            "availability_version": chosen_available.availability_version,
            "matcher_version": CAPABILITY_MATCHER_VERSION,
        })[:32],
        status="MATCHED",
        reason_code="MATCHED",
        requirements_hash=requirements_hash,
        matcher_version=CAPABILITY_MATCHER_VERSION,
        template_id=chosen["template_id"],
        template_revision=chosen["revision"],
        availability_version=chosen_available.availability_version,
        template_content_hash=worker_template_content_hash(chosen_available.template),
    )


def normalize_capability_requirement(requirement: CapabilityRequirement) -> Mapping[str, Any]:
    sandbox = _normalize_constraints(requirement.sandbox_requirements, allow_empty=True)
    mandatory = tuple(sorted({_norm_key(item) for item in requirement.mandatory_constraints}))
    unknown = set(sandbox).union(mandatory) - set(SUPPORTED_SANDBOX_CONSTRAINTS)
    if unknown:
        raise CapabilityRejected("CAPABILITY_REQUIREMENT_UNKNOWN_MANDATORY")
    return {
        "schema_version": CAPABILITY_SCHEMA_VERSION,
        "matcher_version": CAPABILITY_MATCHER_VERSION,
        "project_id": _require_id(requirement.project_id, "PROJECT_ID_INVALID"),
        "task_id": _require_id(requirement.task_id, "TASK_ID_INVALID"),
        "decision_id": _require_id(requirement.decision_id, "DECISION_ID_INVALID"),
        "action_id": _require_id(requirement.action_id, "ACTION_ID_INVALID"),
        "action_type": _norm_atom(requirement.action_type),
        "action_content_hash": _require_hash(requirement.action_content_hash),
        "required_capabilities": tuple(sorted({normalize_capability_name(item) for item in requirement.required_capabilities})),
        "required_tools": tuple(sorted({_norm_atom(item) for item in requirement.required_tools})),
        "minimum_trust": normalize_trust_level(requirement.minimum_trust),
        "sandbox_requirements": sandbox,
        "resource_envelope": _normalize_resource_envelope(requirement.resource_envelope, allow_empty=True),
        "lock_scopes": normalize_lock_scopes(requirement.lock_scopes),
        "mandatory_constraints": mandatory,
    }


def build_context_bundle(
    *,
    project_id: str,
    task_id: str,
    decision_id: str,
    action_id: str,
    template_id: str,
    template_revision: int,
    selectors: Tuple[ContextSelector, ...],
    resolved_refs: Tuple[AuthorityRef, ...],
    selector_schema_version: str = CONTEXT_SELECTOR_SCHEMA_VERSION,
    builder_version: str = CONTEXT_BUILDER_VERSION,
) -> ContextBundle:
    if selector_schema_version != CONTEXT_SELECTOR_SCHEMA_VERSION:
        raise CapabilityRejected("CONTEXT_SELECTOR_SCHEMA_UNSUPPORTED")
    if builder_version != CONTEXT_BUILDER_VERSION:
        raise CapabilityRejected("CONTEXT_BUILDER_UNSUPPORTED")
    if len(selectors) > MAX_CONTEXT_SELECTORS:
        raise CapabilityRejected("CONTEXT_SELECTOR_LIMIT_EXCEEDED")
    if len(resolved_refs) > MAX_CONTEXT_ITEMS:
        raise CapabilityRejected("CONTEXT_ITEM_LIMIT_EXCEEDED")
    normalized_selectors = tuple(sorted(
        (_normalize_selector(item) for item in selectors),
        key=lambda item: (item.selector_type, item.ref_id),
    ))
    normalized_items = tuple(sorted(
        (_normalize_authority_ref(project_id, task_id, item) for item in resolved_refs),
        key=lambda item: (item.ref_type, item.ref_id, item.version or 0, item.content_hash),
    ))
    item_payloads = []
    for item in normalized_items:
        payload = {
            "ref_type": item.ref_type,
            "ref_id": item.ref_id,
            "project_id": item.project_id,
            "task_id": item.task_id,
            "version": item.version,
            "content_hash": item.content_hash,
            "metadata": _canonical(item.metadata),
        }
        _reject_secret_values(payload)
        if len(_canonical_bytes(payload)) > MAX_CONTEXT_ITEM_JSON_BYTES:
            raise CapabilityRejected("CONTEXT_ITEM_SIZE_LIMIT_EXCEEDED")
        item_payloads.append(payload)
    manifest = {
        "schema_version": "context-bundle-manifest/1.0",
        "selector_schema_version": selector_schema_version,
        "builder_version": builder_version,
        "project_id": _require_id(project_id, "PROJECT_ID_INVALID"),
        "task_id": _require_id(task_id, "TASK_ID_INVALID"),
        "decision_id": _require_id(decision_id, "DECISION_ID_INVALID"),
        "action_id": _require_id(action_id, "ACTION_ID_INVALID"),
        "template_id": _require_id(template_id, "WORKER_TEMPLATE_ID_INVALID"),
        "template_revision": int(template_revision),
        "selectors": [
            {"selector_type": item.selector_type, "ref_id": item.ref_id, "required": item.required}
            for item in normalized_selectors
        ],
        "items": item_payloads,
        "limits": {
            "max_selectors": MAX_CONTEXT_SELECTORS,
            "max_items": MAX_CONTEXT_ITEMS,
            "max_item_json_bytes": MAX_CONTEXT_ITEM_JSON_BYTES,
            "max_manifest_json_bytes": MAX_CONTEXT_MANIFEST_JSON_BYTES,
        },
    }
    if len(_canonical_bytes(manifest)) > MAX_CONTEXT_MANIFEST_JSON_BYTES:
        raise CapabilityRejected("CONTEXT_MANIFEST_SIZE_LIMIT_EXCEEDED")
    manifest_hash = hash_json(manifest)
    return ContextBundle(
        bundle_id="ctx-" + raw_hash({"manifest_hash": manifest_hash})[:32],
        project_id=project_id,
        task_id=task_id,
        decision_id=decision_id,
        action_id=action_id,
        template_id=template_id,
        template_revision=template_revision,
        selector_schema_version=selector_schema_version,
        builder_version=builder_version,
        selectors=normalized_selectors,
        items=normalized_items,
        manifest=manifest,
        manifest_hash=manifest_hash,
    )


def compile_sandbox_profile(inputs: SandboxCompileInput) -> SandboxProfile:
    if inputs.compiler_version != SANDBOX_COMPILER_VERSION:
        raise CapabilityRejected("SANDBOX_COMPILER_UNSUPPORTED")
    if inputs.target != SANDBOX_COMPILER_TARGET:
        raise CapabilityRejected("SANDBOX_TARGET_UNSUPPORTED")
    template = normalize_worker_template(inputs.template)
    supported = set(template["supported_sandbox_features"])
    sources = [
        ("policy", inputs.policy_constraints),
        ("action", inputs.action_constraints),
        ("template", inputs.template.constraint_ranges),
        ("risk", {"required_mitigations": list(inputs.risk_required_mitigations)}),
        ("locks", {"lock_scopes": list(inputs.lock_scopes)}),
    ]
    for source, constraints in sources:
        normalized = _normalize_constraints(constraints, allow_empty=True)
        unknown = set(normalized) - set(SUPPORTED_SANDBOX_CONSTRAINTS)
        if unknown:
            raise CapabilityRejected("SANDBOX_UNKNOWN_MANDATORY_CONSTRAINT")
        unsupported = set(normalized) - supported - {"required_mitigations", "lock_scopes"}
        if unsupported:
            raise CapabilityRejected("SANDBOX_TEMPLATE_UNSUPPORTED_CONSTRAINT")
        if source != "locks":
            _reject_secret_values(normalized)
    required_mitigations = set(_norm_atom(item) for item in inputs.risk_required_mitigations)
    available_mitigations = set(_norm_atom(item) for item in inputs.risk_available_mitigations)
    if not required_mitigations.issubset(available_mitigations):
        raise CapabilityRejected("SANDBOX_REQUIRED_MITIGATION_UNAVAILABLE")
    merged = _merge_constraints([constraints for _, constraints in sources])
    profile = {
        "schema_version": SANDBOX_PROFILE_SCHEMA_VERSION,
        "compiler_version": inputs.compiler_version,
        "target": inputs.target,
        "network": _network_profile(merged),
        "filesystem": _filesystem_profile(merged),
        "process": {
            "allowed_tools": list(merged.get("allowed_tools", ())),
            "process_count": merged.get("process_count", 1),
        },
        "environment": {
            "allowed": list(merged.get("environment", ())),
            "default_allow": False,
        },
        "secrets": _secret_profile(merged),
        "limits": {
            key: merged[key] for key in (
                "max_external_api_calls", "execution_time_ms", "cpu_time_ms",
                "storage_bytes", "process_count", "output_bytes"
            ) if key in merged
        },
        "external_side_effects": {
            "production_access": merged.get("production_access", "denied"),
        },
        "artifact_outputs": {
            "filesystem_write": merged.get("filesystem_write", "none"),
        },
        "audit": {
            "telemetry_required": True,
            "required_mitigations": list(merged.get("required_mitigations", ())),
        },
        "lock_scopes": list(merged.get("lock_scopes", ())),
        "bindings": {
            "project_id": inputs.project_id,
            "task_id": inputs.task_id,
            "action_id": inputs.action_id,
            "action_content_hash": inputs.action_content_hash,
            "template_id": template["template_id"],
            "template_revision": template["revision"],
            "context_bundle_hash": _require_hash(inputs.context_bundle_hash),
        },
    }
    constraints_hash = hash_json({
        "policy": _normalize_constraints(inputs.policy_constraints, allow_empty=True),
        "risk_required_mitigations": sorted(required_mitigations),
        "risk_available_mitigations": sorted(available_mitigations),
        "action": _normalize_constraints(inputs.action_constraints, allow_empty=True),
        "template": _normalize_constraints(inputs.template.constraint_ranges, allow_empty=True),
        "lock_scopes": normalize_lock_scopes(inputs.lock_scopes),
    })
    conforming, reasons = profile_conforms(profile, [
        inputs.policy_constraints, inputs.action_constraints,
        inputs.template.constraint_ranges, {"required_mitigations": list(required_mitigations)},
        {"lock_scopes": list(inputs.lock_scopes)},
    ])
    if not conforming:
        raise CapabilityRejected("SANDBOX_PROFILE_WEAKENS_CONSTRAINTS:" + ",".join(reasons))
    profile_hash = hash_json(profile)
    return SandboxProfile(
        profile_id="sbx-" + raw_hash({"profile_hash": profile_hash})[:32],
        project_id=inputs.project_id,
        task_id=inputs.task_id,
        action_id=inputs.action_id,
        template_id=template["template_id"],
        template_revision=template["revision"],
        context_bundle_hash=inputs.context_bundle_hash,
        compiler_version=inputs.compiler_version,
        target=inputs.target,
        profile=profile,
        profile_hash=profile_hash,
        constraints_hash=constraints_hash,
    )


def profile_conforms(
    profile: Mapping[str, Any],
    constraint_sources: Iterable[Mapping[str, Any]],
) -> Tuple[bool, Tuple[str, ...]]:
    try:
        expected = _merge_constraints(tuple(constraint_sources))
    except CapabilityRejected as exc:
        return False, (str(exc),)
    actual = _constraints_from_profile(profile)
    reasons = []
    if not _network_at_least_as_strict(actual.get("network_access"), expected.get("network_access")):
        reasons.append("NETWORK_WEAKENED")
    if not _ranked_at_least_as_strict(actual.get("filesystem_write"), expected.get("filesystem_write"),
                                      {"none": 0, "artifact-output-only": 1, "workspace-only": 2, "unrestricted": 3}):
        reasons.append("FILESYSTEM_WEAKENED")
    if not _ranked_at_least_as_strict(actual.get("production_access"), expected.get("production_access"),
                                      {"denied": 0, "requires-human": 1, "allowed": 2}):
        reasons.append("PRODUCTION_WEAKENED")
    if not _secret_at_least_as_strict(actual.get("secret_access"), expected.get("secret_access")):
        reasons.append("SECRET_WEAKENED")
    for key in ("allowed_tools", "environment", "lock_scopes"):
        expected_set = set(expected.get(key, ()))
        actual_set = set(actual.get(key, ()))
        if expected_set and not actual_set.issubset(expected_set):
            reasons.append(key.upper() + "_WEAKENED")
    for key in ("forbidden_paths", "required_mitigations"):
        if not set(expected.get(key, ())).issubset(set(actual.get(key, ()))):
            reasons.append(key.upper() + "_WEAKENED")
    for key in (
        "max_external_api_calls", "execution_time_ms", "cpu_time_ms",
        "storage_bytes", "process_count", "output_bytes",
    ):
        if key in expected and (key not in actual or int(actual[key]) > int(expected[key])):
            reasons.append(key.upper() + "_WEAKENED")
    return not reasons, tuple(sorted(set(reasons)))


def normalize_lock_scopes(values: Tuple[str, ...]) -> Tuple[str, ...]:
    result = []
    for value in values:
        text = str(value or "").strip().lower()
        if not text or "*" in text:
            raise CapabilityRejected("LOCK_SCOPE_INVALID")
        if not re.match(r"^[a-z0-9][a-z0-9:/._-]{0,191}$", text):
            raise CapabilityRejected("LOCK_SCOPE_INVALID")
        result.append(text)
    return tuple(sorted(set(result)))


def hash_json(value: Any) -> str:
    return "sha256:" + raw_hash(value)


def raw_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _match_reject(reason: str, requirements_hash: str, requirement: CapabilityRequirement) -> CapabilityMatchResult:
    return CapabilityMatchResult(
        match_id="capmatch-" + raw_hash({
            "requirements_hash": requirements_hash,
            "reason_code": reason,
            "matcher_version": CAPABILITY_MATCHER_VERSION,
        })[:32],
        status="NOT_ADMISSIBLE",
        reason_code=reason,
        requirements_hash=requirements_hash,
        matcher_version=CAPABILITY_MATCHER_VERSION,
    )


def _normalize_selector(selector: ContextSelector) -> ContextSelector:
    selector_type = _norm_key(selector.selector_type)
    if selector_type not in SUPPORTED_CONTEXT_SELECTOR_TYPES:
        raise CapabilityRejected("CONTEXT_SELECTOR_UNKNOWN")
    ref_id = _require_id(selector.ref_id, "CONTEXT_SELECTOR_REF_INVALID")
    if ref_id in {"*", "all"} or "*" in ref_id:
        raise CapabilityRejected("CONTEXT_SELECTOR_WILDCARD_FORBIDDEN")
    return ContextSelector(selector_type, ref_id, bool(selector.required))


def _normalize_authority_ref(project_id: str, task_id: str, item: AuthorityRef) -> AuthorityRef:
    ref_type = _norm_key(item.ref_type)
    if ref_type not in SUPPORTED_CONTEXT_SELECTOR_TYPES:
        raise CapabilityRejected("CONTEXT_REF_TYPE_UNKNOWN")
    if item.project_id != project_id:
        raise CapabilityRejected("CONTEXT_REF_PROJECT_MISMATCH")
    if item.task_id is not None and item.task_id != task_id:
        raise CapabilityRejected("CONTEXT_REF_TASK_MISMATCH")
    return AuthorityRef(
        ref_type=ref_type,
        ref_id=_require_id(item.ref_id, "CONTEXT_REF_ID_INVALID"),
        project_id=project_id,
        task_id=item.task_id,
        version=int(item.version) if item.version is not None else None,
        content_hash=_require_hash(item.content_hash),
        metadata=_canonical(item.metadata),
    )


def _normalize_constraints(constraints: Mapping[str, Any], allow_empty: bool = False) -> Mapping[str, Any]:
    if not constraints and allow_empty:
        return {}
    normalized = {}
    for raw_key, value in dict(constraints or {}).items():
        key = _norm_key(raw_key)
        if key not in SUPPORTED_SANDBOX_CONSTRAINTS:
            raise CapabilityRejected("SANDBOX_UNKNOWN_MANDATORY_CONSTRAINT")
        if key in {"allowed_tools", "forbidden_paths", "required_mitigations", "environment", "lock_scopes"}:
            values = value if isinstance(value, (list, tuple, set)) else [value]
            normalized[key] = tuple(sorted({_norm_atom(item) for item in values if str(item).strip()}))
        elif key in {"max_external_api_calls", "execution_time_ms", "cpu_time_ms",
                     "storage_bytes", "process_count", "output_bytes"}:
            number = int(value)
            if number < 0:
                raise CapabilityRejected("SANDBOX_NUMERIC_CONSTRAINT_INVALID")
            normalized[key] = number
        elif key == "network_access":
            normalized[key] = _normalize_network(value)
        elif key == "secret_access":
            normalized[key] = _normalize_secret_access(value)
        else:
            normalized[key] = _norm_atom(value)
    return normalized


def _merge_constraints(sources: Iterable[Mapping[str, Any]]) -> Mapping[str, Any]:
    merged = {}
    for constraints in sources:
        normalized = _normalize_constraints(constraints, allow_empty=True)
        for key, value in normalized.items():
            if key in {"allowed_tools", "environment", "lock_scopes"}:
                previous = set(merged[key]) if key in merged else None
                current = set(value)
                merged[key] = tuple(sorted(current if previous is None else previous.intersection(current)))
            elif key in {"forbidden_paths", "required_mitigations"}:
                merged[key] = tuple(sorted(set(merged.get(key, ())).union(set(value))))
            elif key in {"max_external_api_calls", "execution_time_ms", "cpu_time_ms",
                         "storage_bytes", "process_count", "output_bytes"}:
                merged[key] = min(int(merged[key]), int(value)) if key in merged else int(value)
            elif key == "network_access":
                merged[key] = _merge_network(merged.get(key), value)
            elif key == "filesystem_write":
                merged[key] = _min_ranked(merged.get(key), value, {
                    "none": 0, "artifact-output-only": 1,
                    "workspace-only": 2, "unrestricted": 3,
                })
            elif key == "secret_access":
                merged[key] = _merge_secret(merged.get(key), value)
            elif key == "production_access":
                merged[key] = _min_ranked(merged.get(key), value, {
                    "denied": 0, "requires-human": 1, "allowed": 2,
                })
    return _canonical(merged)


def _constraints_from_profile(profile: Mapping[str, Any]) -> Mapping[str, Any]:
    limits = profile.get("limits") or {}
    result = {
        "network_access": profile.get("network", {}).get("mode", "disabled"),
        "filesystem_write": profile.get("filesystem", {}).get("write", "none"),
        "production_access": profile.get("external_side_effects", {}).get("production_access", "denied"),
        "allowed_tools": tuple(profile.get("process", {}).get("allowed_tools") or ()),
        "forbidden_paths": tuple(profile.get("filesystem", {}).get("forbidden_paths") or ()),
        "environment": tuple(profile.get("environment", {}).get("allowed") or ()),
        "lock_scopes": tuple(profile.get("lock_scopes") or ()),
        "required_mitigations": tuple(profile.get("audit", {}).get("required_mitigations") or ()),
    }
    secret = profile.get("secrets", {})
    if secret.get("mode") == "handles":
        result["secret_access"] = {"handles": tuple(secret.get("handles") or ())}
    else:
        result["secret_access"] = secret.get("mode", "denied")
    result.update(limits)
    return _normalize_constraints(result, allow_empty=True)


def _network_profile(merged):
    value = merged.get("network_access", "disabled")
    if isinstance(value, tuple):
        return {"mode": "allowlist", "egress_allowlist": list(value)}
    return {"mode": value, "egress_allowlist": []}


def _filesystem_profile(merged):
    return {
        "read": "context_bundle_and_artifact_refs",
        "write": merged.get("filesystem_write", "none"),
        "forbidden_paths": list(merged.get("forbidden_paths", ())),
    }


def _secret_profile(merged):
    value = merged.get("secret_access", "denied")
    if isinstance(value, tuple):
        return {"mode": "handles", "handles": list(value)}
    return {"mode": value, "handles": []}


def _normalize_network(value):
    if isinstance(value, Mapping):
        if "allowlist" not in value:
            raise CapabilityRejected("SANDBOX_NETWORK_CONSTRAINT_INVALID")
        return tuple(sorted({_norm_atom(item) for item in value["allowlist"]}))
    text = _norm_atom(value)
    if text not in {"disabled", "unrestricted"}:
        raise CapabilityRejected("SANDBOX_NETWORK_CONSTRAINT_INVALID")
    return text


def _normalize_secret_access(value):
    if isinstance(value, Mapping):
        if "handles" not in value:
            raise CapabilityRejected("SANDBOX_SECRET_CONSTRAINT_INVALID")
        handles = tuple(sorted({_norm_secret_handle(item) for item in value["handles"]}))
        return handles
    text = _norm_atom(value)
    if text not in {"denied", "unrestricted"}:
        raise CapabilityRejected("SANDBOX_SECRET_CONSTRAINT_INVALID")
    return text


def _merge_network(previous, current):
    if previous is None:
        return current
    if previous == "disabled" or current == "disabled":
        return "disabled"
    if previous == "unrestricted":
        return current
    if current == "unrestricted":
        return previous
    return tuple(sorted(set(previous).intersection(set(current))))


def _merge_secret(previous, current):
    if previous is None:
        return current
    if previous == "denied" or current == "denied":
        return "denied"
    if previous == "unrestricted":
        return current
    if current == "unrestricted":
        return previous
    return tuple(sorted(set(previous).intersection(set(current))))


def _network_at_least_as_strict(actual, expected) -> bool:
    if expected is None:
        return True
    if actual == expected:
        return True
    if actual == "disabled":
        return True
    if expected == "unrestricted":
        return True
    if isinstance(actual, tuple) and isinstance(expected, tuple):
        return set(actual).issubset(set(expected))
    return False


def _secret_at_least_as_strict(actual, expected) -> bool:
    if expected is None:
        return True
    if actual == expected or actual == "denied":
        return True
    if expected == "unrestricted":
        return True
    if isinstance(actual, tuple) and isinstance(expected, tuple):
        return set(actual).issubset(set(expected))
    return False


def _ranked_at_least_as_strict(actual, expected, ranks) -> bool:
    if expected is None:
        return True
    return ranks.get(actual, 999) <= ranks.get(expected, -1)


def _min_ranked(previous, current, ranks):
    text = _norm_atom(current)
    if text not in ranks:
        raise CapabilityRejected("SANDBOX_CONSTRAINT_VALUE_INVALID")
    if previous is None:
        return text
    return previous if ranks[previous] <= ranks[text] else text


def _normalize_resource_envelope(envelope: Mapping[str, Any], allow_empty: bool = False) -> Mapping[str, int]:
    if not envelope and allow_empty:
        return {}
    result = {}
    for raw_key, raw_value in dict(envelope or {}).items():
        key = _norm_key(raw_key)
        if key not in RESOURCE_DIMENSIONS:
            raise CapabilityRejected("RESOURCE_DIMENSION_UNKNOWN")
        value = int(raw_value)
        if value < 0:
            raise CapabilityRejected("RESOURCE_AMOUNT_INVALID")
        result[key] = value
    return _canonical(result)


def _resource_envelope_fits(required: Mapping[str, int], supported: Mapping[str, int]) -> bool:
    for dimension, amount in required.items():
        if int(supported.get(dimension, -1)) < int(amount):
            return False
    return True


def _reject_secret_values(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized_key = str(key).lower().replace("-", "_")
            if normalized_key not in {"secret_access", "secret_handles"} and SECRET_FIELD_PATTERN.search(str(key)) and "handle" not in normalized_key:
                raise CapabilityRejected("SECRET_VALUE_FORBIDDEN")
            _reject_secret_values(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_secret_values(item)
    elif isinstance(value, str):
        if re.search(r"(sk-[A-Za-z0-9]{12,}|BEGIN [A-Z ]*PRIVATE KEY|password=)", value):
            raise CapabilityRejected("SECRET_VALUE_FORBIDDEN")


def _norm_atom(value: Any) -> str:
    text = str(value or "").strip().lower().replace("_", "-")
    if not text or text in {"*", "all"}:
        raise CapabilityRejected("VALUE_INVALID")
    return text


def _norm_key(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text or text in {"*", "all"}:
        raise CapabilityRejected("VALUE_INVALID")
    return text


def _norm_secret_handle(value: Any) -> str:
    text = str(value or "").strip()
    if not text.startswith("secret://") or len(text) > 256:
        raise CapabilityRejected("SECRET_HANDLE_INVALID")
    return text


def _require_id(value: str, code: str) -> str:
    text = str(value or "").strip()
    if not text or "*" in text:
        raise CapabilityRejected(code)
    return text


def _require_hash(value: str) -> str:
    text = str(value or "").strip()
    if not text.startswith("sha256:"):
        raise CapabilityRejected("HASH_INVALID")
    return text


def _canonical(value: Any) -> Any:
    return json.loads(_canonical_bytes(value).decode("utf-8"))


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
