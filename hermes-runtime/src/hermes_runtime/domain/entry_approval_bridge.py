from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
import json
import uuid
from typing import Any, Mapping, Sequence


E4_COMPILER_VERSION = "e4-approval-bridge-v1"
E4_POLICY_VERSION = "e4-verification-policy-v1"
E4_NAMESPACE = uuid.UUID("81234cea-5e4a-4bb4-bcac-f87b0161c970")


class EntryE4Rejected(ValueError):
    pass


class BridgeStatus(str, Enum):
    PROCESSING = "PROCESSING"
    PROJECT_CREATED = "PROJECT_CREATED"
    GRAPH_APPLIED = "GRAPH_APPLIED"
    VERIFICATION_APPLYING = "VERIFICATION_APPLYING"
    MATERIALIZED = "MATERIALIZED"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    FAILED_TERMINAL = "FAILED_TERMINAL"


@dataclass(frozen=True)
class ApprovalSource:
    creator_subject: str
    draft_id: str
    draft_version: int
    draft_revision_id: str
    understanding_revision_id: str
    proposal_revision_id: str
    proposal_content_hash: str
    plan_id: str
    plan_version: int
    plan_revision_id: str
    plan_content_hash: str
    plan_content: Mapping[str, Any]


@dataclass(frozen=True)
class ApproveEntryPlan:
    verified_subject: str
    reason: str
    idempotency_key: str
    expected_draft_version: int
    master_plan_id: str
    expected_plan_version: int
    plan_revision_id: str
    approved_plan_content_hash: str
    proposal_revision_id: str
    proposal_content_hash: str
    compiled_blueprint_hash: str
    acknowledgements: tuple[str, ...]
    correlation_id: str


@dataclass(frozen=True)
class ApprovalPreview:
    bridge_id: str
    blueprint: Mapping[str, Any]
    compiled_blueprint_hash: str
    required_acknowledgements: tuple[str, ...]
    compiler_version: str = E4_COMPILER_VERSION
    policy_version: str = E4_POLICY_VERSION


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def content_hash(value: Any) -> str:
    return sha256(canonical_json(value)).hexdigest()


def stable_id(kind: str, *parts: str) -> str:
    return f"{kind}-{uuid.uuid5(E4_NAMESPACE, '|'.join((kind, *parts))).hex}"


def required_acknowledgements(plan: Mapping[str, Any]) -> tuple[str, ...]:
    required: set[str] = set()
    for item in plan.get("assumptions", []):
        if isinstance(item, Mapping) and item.get("status") == "UNCONFIRMED_SOURCE_ASSUMPTION":
            key = item.get("key") or item.get("assumption_id") or content_hash(item)[:16]
            required.add(f"assumption:{key}")
    for field in ("architecture", "verification_intent", "delivery_intent"):
        value = plan.get(field)
        if isinstance(value, Mapping) and value.get("status") == "REVIEW_REQUIRED":
            required.add(f"review:{field}")
    return tuple(sorted(required))


def _require_text(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EntryE4Rejected(code)
    return value.strip()


def _derive_blueprint(source: ApprovalSource) -> Mapping[str, Any]:
    plan = source.plan_content
    if plan.get("pre_approval_only") is not True:
        raise EntryE4Rejected("ENTRY_APPROVAL_PLAN_NOT_PRE_APPROVAL")
    if plan.get("compiler") != "e3-master-plan-v1" or plan.get("schema_version") != "v1":
        raise EntryE4Rejected("ENTRY_APPROVAL_PLAN_NOT_CURRENT")
    nodes = plan.get("nodes")
    dependencies = plan.get("dependencies")
    if not isinstance(nodes, list) or not nodes or not isinstance(dependencies, list):
        raise EntryE4Rejected("ENTRY_APPROVAL_PLAN_INVALID")
    bridge_id = stable_id("e4bridge", source.draft_id, source.plan_revision_id, source.plan_content_hash)
    project_id = stable_id("project", bridge_id)
    lowered_nodes = []
    seen = set()
    for item in sorted(nodes, key=lambda row: str(row.get("node_key", ""))):
        if not isinstance(item, Mapping):
            raise EntryE4Rejected("ENTRY_APPROVAL_PLAN_INVALID")
        key = _require_text(item.get("node_key"), "ENTRY_APPROVAL_PLAN_INVALID")
        if key in seen:
            raise EntryE4Rejected("ENTRY_APPROVAL_PLAN_INVALID")
        seen.add(key)
        task_id = stable_id("task", bridge_id, key)
        lowered_nodes.append({
            "node_key": key,
            "task_id": task_id,
            "title": _require_text(item.get("title"), "ENTRY_APPROVAL_PLAN_INVALID"),
            "requirement_refs": tuple(sorted(str(ref) for ref in item.get("requirement_refs", []))),
            "verification_plan_id": stable_id("verification", bridge_id, key),
            "create_command_id": stable_id("create-verification", bridge_id, key),
            "verification_policy": E4_POLICY_VERSION,
        })
    tasks = {item["node_key"]: item for item in lowered_nodes}
    lowered_dependencies = []
    for edge in sorted(dependencies, key=lambda row: (str(row.get("source", "")), str(row.get("target", "")))):
        if not isinstance(edge, Mapping):
            raise EntryE4Rejected("ENTRY_APPROVAL_PLAN_INVALID")
        source_key = _require_text(edge.get("source"), "ENTRY_APPROVAL_PLAN_INVALID")
        target_key = _require_text(edge.get("target"), "ENTRY_APPROVAL_PLAN_INVALID")
        if source_key not in tasks or target_key not in tasks or source_key == target_key:
            raise EntryE4Rejected("ENTRY_APPROVAL_PLAN_INVALID")
        # E3 source -> target is lowered as target depends on source.
        lowered_dependencies.append({
            "task_id": tasks[target_key]["task_id"],
            "depends_on_task_id": tasks[source_key]["task_id"],
            "command_id": stable_id("dependency", bridge_id, source_key, target_key),
        })
    return {
        "schema_version": "e4-blueprint-v1",
        "compiler_version": E4_COMPILER_VERSION,
        "policy_version": E4_POLICY_VERSION,
        "bridge_id": bridge_id,
        "project_id": project_id,
        "project_command_id": stable_id("create-project", bridge_id),
        "graph_command_id": stable_id("apply-graph", bridge_id),
        "source": {
            "draft_id": source.draft_id,
            "draft_version": source.draft_version,
            "draft_revision_id": source.draft_revision_id,
            "understanding_revision_id": source.understanding_revision_id,
            "proposal_revision_id": source.proposal_revision_id,
            "proposal_content_hash": source.proposal_content_hash,
            "plan_id": source.plan_id,
            "plan_version": source.plan_version,
            "plan_revision_id": source.plan_revision_id,
            "plan_content_hash": source.plan_content_hash,
        },
        "tasks": lowered_nodes,
        "dependencies": lowered_dependencies,
        "required_acknowledgements": required_acknowledgements(plan),
        "pre_approval_only": True,
    }


def preview_approval(source: ApprovalSource) -> ApprovalPreview:
    if source.creator_subject == "":
        raise EntryE4Rejected("ENTRY_APPROVAL_SOURCE_NOT_CURRENT")
    blueprint = _derive_blueprint(source)
    return ApprovalPreview(
        bridge_id=str(blueprint["bridge_id"]),
        blueprint=blueprint,
        compiled_blueprint_hash=content_hash(blueprint),
        required_acknowledgements=tuple(blueprint["required_acknowledgements"]),
    )


def validate_approval(source: ApprovalSource, request: ApproveEntryPlan, preview: ApprovalPreview) -> None:
    if request.verified_subject != source.creator_subject:
        raise EntryE4Rejected("ENTRY_APPROVAL_UNAUTHORIZED")
    _require_text(request.reason, "ENTRY_APPROVAL_SCHEMA_INVALID")
    _require_text(request.idempotency_key, "ENTRY_APPROVAL_SCHEMA_INVALID")
    if request.expected_draft_version != source.draft_version or request.expected_plan_version != source.plan_version:
        raise EntryE4Rejected("ENTRY_APPROVAL_VERSION_CONFLICT")
    expected = (source.plan_id, source.plan_revision_id, source.plan_content_hash, source.proposal_revision_id, source.proposal_content_hash)
    actual = (request.master_plan_id, request.plan_revision_id, request.approved_plan_content_hash, request.proposal_revision_id, request.proposal_content_hash)
    if actual != expected:
        raise EntryE4Rejected("ENTRY_APPROVAL_SOURCE_STALE")
    if request.compiled_blueprint_hash != preview.compiled_blueprint_hash:
        raise EntryE4Rejected("ENTRY_APPROVAL_BLUEPRINT_MISMATCH")
    if tuple(sorted(set(request.acknowledgements))) != preview.required_acknowledgements:
        raise EntryE4Rejected("ENTRY_APPROVAL_ACKNOWLEDGEMENT_REQUIRED")
