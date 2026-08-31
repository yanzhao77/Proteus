from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence


PROPOSAL_COMPILER = "proposal-compiler-v1"
MASTER_PLAN_COMPILER = "master-plan-compiler-v1"
SCHEMA_VERSION = "e3-v1"


class EntryE3Rejected(ValueError):
    """A stable E3 rejection whose message is a public error code."""


def _reject(code: str) -> None:
    raise EntryE3Rejected(code)


def _normalise(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _normalise(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, tuple):
        return [_normalise(item) for item in value]
    if isinstance(value, list):
        return [_normalise(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    _reject("ENTRY_PROPOSAL_SCHEMA_INVALID")


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        _normalise(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def canonical_content_hash(value: Any) -> str:
    return sha256(canonical_json(value)).hexdigest()


def _strings(value: Sequence[object] | object, code: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        _reject(code)
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            _reject(code)
        result.append(item.strip())
    return tuple(sorted(set(result)))


@dataclass(frozen=True)
class SourceClarification:
    clarification_id: str
    question: str
    rationale: str
    state: str
    answer: str | None


@dataclass(frozen=True)
class SourceAssumption:
    assumption_id: str
    statement: str
    basis: str


@dataclass(frozen=True)
class ProposalSource:
    creator_subject: str
    draft_id: str
    draft_state: str
    draft_revision_id: str
    draft_revision_number: int
    understanding_id: str
    understanding_state: str
    understanding_revision_id: str
    understanding_revision_number: int
    interpreted_intent: str
    objective: str
    user_constraints: tuple[str, ...]
    explicit_requirements: tuple[str, ...]
    ambiguities: tuple[str, ...]
    open_questions: tuple[str, ...]
    clarifications: tuple[SourceClarification, ...]
    assumptions: tuple[SourceAssumption, ...]


@dataclass(frozen=True)
class ProposalCandidate:
    content: Mapping[str, Any]
    content_hash: str


@dataclass(frozen=True)
class MasterPlanCandidate:
    content: Mapping[str, Any]
    content_hash: str


def _require_nonempty_text(value: object, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _reject(code)
    return value.strip()


def validate_proposal_source(source: ProposalSource) -> None:
    if not source.creator_subject or not source.draft_id or not source.understanding_id:
        _reject("ENTRY_PROPOSAL_SOURCE_NOT_READY")
    if source.draft_state != "SUBMITTED" or source.understanding_state != "READY":
        _reject("ENTRY_PROPOSAL_SOURCE_NOT_READY")
    if source.draft_revision_number < 1 or source.understanding_revision_number < 1:
        _reject("ENTRY_PROPOSAL_SOURCE_STALE")
    _require_nonempty_text(source.interpreted_intent, "ENTRY_PROPOSAL_SCHEMA_INVALID")
    _require_nonempty_text(source.objective, "ENTRY_PROPOSAL_SCHEMA_INVALID")
    if not source.explicit_requirements:
        _reject("ENTRY_PROPOSAL_SOURCE_NOT_READY")
    if any(item.state == "OPEN" for item in source.clarifications):
        _reject("ENTRY_PROPOSAL_SOURCE_NOT_READY")


def compile_proposal(source: ProposalSource) -> ProposalCandidate:
    validate_proposal_source(source)
    requirements = [
        {"key": f"requirement-{index:03d}", "statement": statement, "source": "entry_understanding"}
        for index, statement in enumerate(sorted(set(source.explicit_requirements)), start=1)
    ]
    clarification_records = [
        {
            "clarification_id": item.clarification_id,
            "question": item.question,
            "rationale": item.rationale,
            "state": item.state,
            "answer": item.answer,
            "source": "entry_clarifications",
        }
        for item in sorted(source.clarifications, key=lambda item: item.clarification_id)
    ]
    assumptions = [
        {
            "assumption_id": item.assumption_id,
            "statement": item.statement,
            "basis": item.basis,
            "status": "UNCONFIRMED_SOURCE_ASSUMPTION",
            "source": "entry_understanding_assumptions",
        }
        for item in sorted(source.assumptions, key=lambda item: item.assumption_id)
    ]
    unresolved = sorted(set(source.ambiguities) | set(source.open_questions))
    complexity = "LOW" if len(requirements) <= 2 else "MEDIUM" if len(requirements) <= 5 else "HIGH"
    content: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "compiler": PROPOSAL_COMPILER,
        "source": {
            "draft_id": source.draft_id,
            "draft_revision_id": source.draft_revision_id,
            "draft_revision_number": source.draft_revision_number,
            "understanding_id": source.understanding_id,
            "understanding_revision_id": source.understanding_revision_id,
            "understanding_revision_number": source.understanding_revision_number,
            "clarification_ids": [item["clarification_id"] for item in clarification_records],
            "assumption_ids": [item["assumption_id"] for item in assumptions],
        },
        "product_statement": source.interpreted_intent,
        "target_outcome": source.objective,
        "scope_in": sorted(set(source.explicit_requirements)),
        "scope_out": [],
        "requirements": requirements,
        "assumptions": assumptions,
        "clarifications": clarification_records,
        "candidate_architecture": {
            "status": "REVIEW_REQUIRED",
            "reason": "E3 deterministic compiler does not invent architecture beyond authoritative sources",
        },
        "proposed_phases": ["review", "delivery-planning"],
        "workforce_intent": {"status": "ADVISORY_ONLY", "allocated_workers": []},
        "verification_strategy": {"status": "REVIEW_REQUIRED", "requirement_keys": [item["key"] for item in requirements]},
        "delivery_strategy": {"status": "REVIEW_REQUIRED", "method": "not-authorized-for-production"},
        "complexity_band": complexity,
        "known_risks": unresolved,
        "unresolved_items": unresolved,
        "constraints": sorted(set(source.user_constraints)),
    }
    return ProposalCandidate(content=_normalise(content), content_hash=canonical_content_hash(content))


def _require_mapping(value: object, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _reject(code)
    return value


def validate_master_plan_content(content: Mapping[str, Any]) -> None:
    goal = _require_nonempty_text(content.get("goal"), "ENTRY_PLAN_SCHEMA_INVALID")
    if not goal:
        _reject("ENTRY_PLAN_SCHEMA_INVALID")
    requirements = content.get("requirements")
    nodes = content.get("nodes")
    dependencies = content.get("dependencies")
    verification = content.get("verification_intent")
    if not isinstance(requirements, list) or not isinstance(nodes, list) or not isinstance(dependencies, list):
        _reject("ENTRY_PLAN_SCHEMA_INVALID")
    keys: set[str] = set()
    covered: set[str] = set()
    for node in nodes:
        item = _require_mapping(node, "ENTRY_PLAN_SCHEMA_INVALID")
        key = _require_nonempty_text(item.get("node_key"), "ENTRY_PLAN_SCHEMA_INVALID")
        if key in keys:
            _reject("ENTRY_PLAN_DAG_INVALID")
        keys.add(key)
        refs = _strings(item.get("requirement_refs", []), "ENTRY_PLAN_SCHEMA_INVALID")
        covered.update(refs)
    graph: dict[str, set[str]] = {key: set() for key in keys}
    for edge in dependencies:
        item = _require_mapping(edge, "ENTRY_PLAN_SCHEMA_INVALID")
        source = _require_nonempty_text(item.get("source"), "ENTRY_PLAN_SCHEMA_INVALID")
        target = _require_nonempty_text(item.get("target"), "ENTRY_PLAN_SCHEMA_INVALID")
        if source not in keys or target not in keys or source == target:
            _reject("ENTRY_PLAN_DAG_INVALID")
        graph[source].add(target)
    visiting: set[str] = set()
    visited: set[str] = set()
    def visit(key: str) -> None:
        if key in visiting:
            _reject("ENTRY_PLAN_DAG_INVALID")
        if key in visited:
            return
        visiting.add(key)
        for target in sorted(graph[key]):
            visit(target)
        visiting.remove(key)
        visited.add(key)
    for key in sorted(graph):
        visit(key)
    requirement_keys = {_require_nonempty_text(_require_mapping(item, "ENTRY_PLAN_SCHEMA_INVALID").get("key"), "ENTRY_PLAN_SCHEMA_INVALID") for item in requirements}
    if not requirement_keys or not requirement_keys.issubset(covered):
        _reject("ENTRY_PLAN_REQUIREMENT_COVERAGE_INVALID")
    verification_mapping = _require_mapping(verification, "ENTRY_PLAN_SCHEMA_INVALID")
    refs = _strings(verification_mapping.get("requirement_keys", []), "ENTRY_PLAN_SCHEMA_INVALID")
    if not requirement_keys.issubset(set(refs)):
        _reject("ENTRY_PLAN_REQUIREMENT_COVERAGE_INVALID")
    serialised = canonical_json(content).decode("utf-8")
    if any(forbidden in serialised for forbidden in ("project_id", "task_id", "execution_id", "planning_run", "candidate_action")):
        _reject("ENTRY_PLAN_DOMAIN_INVALID")


def compile_master_plan(proposal_content: Mapping[str, Any], proposal_hash: str, proposal_revision_id: str | None = None) -> MasterPlanCandidate:
    proposal = _require_mapping(proposal_content, "ENTRY_PLAN_SCHEMA_INVALID")
    if proposal.get("schema_version") != SCHEMA_VERSION or proposal.get("compiler") != PROPOSAL_COMPILER:
        _reject("ENTRY_PLAN_SOURCE_NOT_READY")
    unresolved = proposal.get("unresolved_items")
    if not isinstance(unresolved, list):
        _reject("ENTRY_PLAN_SCHEMA_INVALID")
    if unresolved:
        _reject("ENTRY_PLAN_SOURCE_NOT_READY")
    requirements = proposal.get("requirements")
    if not isinstance(requirements, list) or not requirements:
        _reject("ENTRY_PLAN_SOURCE_NOT_READY")
    source = _require_mapping(proposal.get("source"), "ENTRY_PLAN_SCHEMA_INVALID")
    plan_requirements = []
    nodes = []
    for index, requirement in enumerate(sorted(requirements, key=lambda item: str(_require_mapping(item, "ENTRY_PLAN_SCHEMA_INVALID").get("key", ""))), start=1):
        item = _require_mapping(requirement, "ENTRY_PLAN_SCHEMA_INVALID")
        key = _require_nonempty_text(item.get("key"), "ENTRY_PLAN_SCHEMA_INVALID")
        statement = _require_nonempty_text(item.get("statement"), "ENTRY_PLAN_SCHEMA_INVALID")
        plan_requirements.append({"key": key, "statement": statement, "source": item.get("source", "entry_understanding")})
        nodes.append({
            "node_key": f"plan-node-{index:03d}",
            "phase": "delivery-planning",
            "title": statement,
            "requirement_refs": [key],
            "verification_refs": [f"verify-{key}"],
        })
    content: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "compiler": MASTER_PLAN_COMPILER,
        "proposal": {"proposal_revision_id": proposal_revision_id, "proposal_content_hash": proposal_hash},
        "source": {
            "draft_id": source.get("draft_id"),
            "draft_revision_id": source.get("draft_revision_id"),
            "understanding_id": source.get("understanding_id"),
            "understanding_revision_id": source.get("understanding_revision_id"),
        },
        "goal": _require_nonempty_text(proposal.get("target_outcome"), "ENTRY_PLAN_SCHEMA_INVALID"),
        "requirements": plan_requirements,
        "constraints": proposal.get("constraints", []),
        "architecture": proposal.get("candidate_architecture"),
        "phases": ["delivery-planning"],
        "nodes": nodes,
        "dependencies": [],
        "risks": proposal.get("known_risks", []),
        "verification_intent": {"status": "REVIEW_REQUIRED", "requirement_keys": [item["key"] for item in plan_requirements]},
        "delivery_intent": proposal.get("delivery_strategy"),
        "workforce_intent": proposal.get("workforce_intent"),
        "pre_approval_only": True,
    }
    validate_master_plan_content(content)
    return MasterPlanCandidate(content=_normalise(content), content_hash=canonical_content_hash(content))


PROPOSAL_EDITABLE_KEYS = (
    "product_statement", "target_outcome", "scope_in", "scope_out",
    "requirements", "assumptions", "unresolved_items", "complexity_band", "candidate_architecture",
)
PROPOSAL_COMPILER_EDITOR = "proposal-editor-v1"
MASTER_PLAN_COMPILER_EDITOR = "master-plan-editor-v1"
VALID_COMPLEXITY_BANDS = ("LOW", "MEDIUM", "HIGH", "REVIEW_REQUIRED")


def _as_str_list(value: object, code: str) -> list[str]:
    if not isinstance(value, list):
        _reject(code)
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            _reject(code)
        result.append(item.strip())
    return result


def _as_str(value: object, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _reject(code)
    return value.strip()


def validate_editable_proposal_fields(raw: object) -> Mapping[str, Any]:
    """Strict schema for a user-edited Proposal revision; rejects unknown keys and invalid shapes."""
    if not isinstance(raw, Mapping):
        _reject("ENTRY_PROPOSAL_EDIT_SCHEMA_INVALID")
    unknown = set(raw) - set(PROPOSAL_EDITABLE_KEYS)
    if unknown:
        _reject("ENTRY_PROPOSAL_EDIT_SCHEMA_INVALID")
    fields: dict[str, Any] = {}
    fields["product_statement"] = _as_str(raw.get("product_statement"), "ENTRY_PROPOSAL_EDIT_SCHEMA_INVALID")
    fields["target_outcome"] = _as_str(raw.get("target_outcome"), "ENTRY_PROPOSAL_EDIT_SCHEMA_INVALID")
    fields["scope_in"] = _as_str_list(raw.get("scope_in", []), "ENTRY_PROPOSAL_EDIT_SCHEMA_INVALID")
    fields["scope_out"] = _as_str_list(raw.get("scope_out", []), "ENTRY_PROPOSAL_EDIT_SCHEMA_INVALID")
    requirements = raw.get("requirements")
    if not isinstance(requirements, list) or not requirements:
        _reject("ENTRY_PROPOSAL_EDIT_SCHEMA_INVALID")
    req_keys: set[str] = set()
    reqs: list[Mapping[str, Any]] = []
    for item in requirements:
        if not isinstance(item, Mapping):
            _reject("ENTRY_PROPOSAL_EDIT_SCHEMA_INVALID")
        key = _as_str(item.get("key"), "ENTRY_PROPOSAL_EDIT_SCHEMA_INVALID")
        statement = _as_str(item.get("statement"), "ENTRY_PROPOSAL_EDIT_SCHEMA_INVALID")
        if key in req_keys:
            _reject("ENTRY_PROPOSAL_EDIT_SCHEMA_INVALID")
        req_keys.add(key)
        reqs.append({"key": key, "statement": statement, "source": _as_str(item.get("source", "entry_understanding"), "ENTRY_PROPOSAL_EDIT_SCHEMA_INVALID")})
    fields["requirements"] = reqs
    assumptions = raw.get("assumptions", [])
    if not isinstance(assumptions, list):
        _reject("ENTRY_PROPOSAL_EDIT_SCHEMA_INVALID")
    fields["assumptions"] = [
        {
            "assumption_id": _as_str(item.get("assumption_id"), "ENTRY_PROPOSAL_EDIT_SCHEMA_INVALID"),
            "statement": _as_str(item.get("statement"), "ENTRY_PROPOSAL_EDIT_SCHEMA_INVALID"),
            "basis": item.get("basis") if isinstance(item.get("basis"), str) else "",
            "status": _as_str(item.get("status", "UNCONFIRMED_SOURCE_ASSUMPTION"), "ENTRY_PROPOSAL_EDIT_SCHEMA_INVALID"),
        }
        for item in assumptions if isinstance(item, Mapping)
    ]
    fields["unresolved_items"] = _as_str_list(raw.get("unresolved_items", []), "ENTRY_PROPOSAL_EDIT_SCHEMA_INVALID")
    band = raw.get("complexity_band")
    if band not in VALID_COMPLEXITY_BANDS:
        _reject("ENTRY_PROPOSAL_EDIT_SCHEMA_INVALID")
    fields["complexity_band"] = band
    arch = raw.get("candidate_architecture")
    if not isinstance(arch, Mapping) or not isinstance(arch.get("status"), str) or not isinstance(arch.get("reason"), str):
        _reject("ENTRY_PROPOSAL_EDIT_SCHEMA_INVALID")
    fields["candidate_architecture"] = {"status": str(arch["status"]), "reason": str(arch["reason"])}
    return fields


def build_edited_proposal_content(base_content: Mapping[str, Any], fields: Mapping[str, Any]) -> ProposalCandidate:
    """Overlay edited fields onto the source lineage preserved from the latest revision."""
    source = _require_mapping(base_content.get("source"), "ENTRY_PROPOSAL_EDIT_SCHEMA_INVALID")
    content: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "compiler": PROPOSAL_COMPILER_EDITOR,
        "source": {
            "draft_id": source.get("draft_id"),
            "draft_revision_id": source.get("draft_revision_id"),
            "understanding_id": source.get("understanding_id"),
            "understanding_revision_id": source.get("understanding_revision_id"),
            "clarification_ids": list(source.get("clarification_ids", []) or []),
            "assumption_ids": list(source.get("assumption_ids", []) or []),
        },
        "product_statement": fields["product_statement"],
        "target_outcome": fields["target_outcome"],
        "scope_in": sorted(set(fields["scope_in"])),
        "scope_out": sorted(set(fields["scope_out"])),
        "requirements": fields["requirements"],
        "assumptions": fields["assumptions"],
        "clarifications": list(base_content.get("clarifications", []) or []),
        "candidate_architecture": fields["candidate_architecture"],
        "proposed_phases": list(base_content.get("proposed_phases", ["review", "delivery-planning"]) or ["review", "delivery-planning"]),
        "workforce_intent": dict(base_content.get("workforce_intent", {"status": "ADVISORY_ONLY", "allocated_workers": []})),
        "verification_strategy": dict(base_content.get("verification_strategy", {"status": "REVIEW_REQUIRED", "requirement_keys": [item["key"] for item in fields["requirements"]]})),
        "delivery_strategy": dict(base_content.get("delivery_strategy", {"status": "REVIEW_REQUIRED", "method": "not-authorized-for-production"})),
        "complexity_band": fields["complexity_band"],
        "known_risks": list(fields["unresolved_items"]),
        "unresolved_items": list(fields["unresolved_items"]),
        "constraints": sorted(set(base_content.get("constraints", []) or [])),
    }
    return ProposalCandidate(content=_normalise(content), content_hash=canonical_content_hash(content))


MASTER_PLAN_EDITABLE_KEYS = (
    "goal", "requirements", "constraints", "phases", "nodes", "dependencies", "verification_intent", "risks",
)


def validate_editable_master_plan_fields(raw: object) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        _reject("ENTRY_PLAN_EDIT_SCHEMA_INVALID")
    if set(raw) - set(MASTER_PLAN_EDITABLE_KEYS):
        _reject("ENTRY_PLAN_EDIT_SCHEMA_INVALID")
    fields: dict[str, Any] = {}
    fields["goal"] = _as_str(raw.get("goal"), "ENTRY_PLAN_EDIT_SCHEMA_INVALID")
    requirements = raw.get("requirements")
    if not isinstance(requirements, list) or not requirements:
        _reject("ENTRY_PLAN_EDIT_SCHEMA_INVALID")
    req_keys: set[str] = set()
    reqs: list[Mapping[str, Any]] = []
    for item in requirements:
        if not isinstance(item, Mapping):
            _reject("ENTRY_PLAN_EDIT_SCHEMA_INVALID")
        key = _as_str(item.get("key"), "ENTRY_PLAN_EDIT_SCHEMA_INVALID")
        statement = _as_str(item.get("statement"), "ENTRY_PLAN_EDIT_SCHEMA_INVALID")
        if key in req_keys:
            _reject("ENTRY_PLAN_EDIT_SCHEMA_INVALID")
        req_keys.add(key)
        reqs.append({"key": key, "statement": statement, "source": _as_str(item.get("source", "entry_understanding"), "ENTRY_PLAN_EDIT_SCHEMA_INVALID")})
    fields["requirements"] = reqs
    fields["constraints"] = _as_str_list(raw.get("constraints", []), "ENTRY_PLAN_EDIT_SCHEMA_INVALID")
    phases = raw.get("phases", [])
    fields["phases"] = _as_str_list(phases, "ENTRY_PLAN_EDIT_SCHEMA_INVALID")
    nodes = raw.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        _reject("ENTRY_PLAN_EDIT_SCHEMA_INVALID")
    node_keys: set[str] = set()
    node_list: list[Mapping[str, Any]] = []
    for item in nodes:
        if not isinstance(item, Mapping):
            _reject("ENTRY_PLAN_EDIT_SCHEMA_INVALID")
        node_key = _as_str(item.get("node_key"), "ENTRY_PLAN_EDIT_SCHEMA_INVALID")
        if node_key in node_keys:
            _reject("ENTRY_PLAN_DAG_INVALID")
        node_keys.add(node_key)
        node_list.append({
            "node_key": node_key,
            "phase": _as_str(item.get("phase"), "ENTRY_PLAN_EDIT_SCHEMA_INVALID"),
            "title": _as_str(item.get("title"), "ENTRY_PLAN_EDIT_SCHEMA_INVALID"),
            "requirement_refs": _as_str_list(item.get("requirement_refs", []), "ENTRY_PLAN_EDIT_SCHEMA_INVALID"),
            "verification_refs": _as_str_list(item.get("verification_refs", []), "ENTRY_PLAN_EDIT_SCHEMA_INVALID"),
        })
    fields["nodes"] = node_list
    dependencies = raw.get("dependencies", [])
    if not isinstance(dependencies, list):
        _reject("ENTRY_PLAN_EDIT_SCHEMA_INVALID")
    dep_list: list[Mapping[str, Any]] = []
    for item in dependencies:
        if not isinstance(item, Mapping):
            _reject("ENTRY_PLAN_EDIT_SCHEMA_INVALID")
        dep_list.append({
            "source": _as_str(item.get("source"), "ENTRY_PLAN_EDIT_SCHEMA_INVALID"),
            "target": _as_str(item.get("target"), "ENTRY_PLAN_EDIT_SCHEMA_INVALID"),
        })
    fields["dependencies"] = dep_list
    verification = raw.get("verification_intent")
    if not isinstance(verification, Mapping) or not isinstance(verification.get("requirement_keys"), list):
        _reject("ENTRY_PLAN_EDIT_SCHEMA_INVALID")
    fields["verification_intent"] = {
        "status": _as_str(verification.get("status", "REVIEW_REQUIRED"), "ENTRY_PLAN_EDIT_SCHEMA_INVALID"),
        "requirement_keys": _as_str_list(verification.get("requirement_keys"), "ENTRY_PLAN_EDIT_SCHEMA_INVALID"),
    }
    fields["risks"] = _as_str_list(raw.get("risks", []), "ENTRY_PLAN_EDIT_SCHEMA_INVALID")
    return fields


def build_edited_master_plan_content(
    base_content: Mapping[str, Any],
    fields: Mapping[str, Any],
    proposal_revision_id: str,
    proposal_content_hash: str,
    source: Mapping[str, Any],
) -> MasterPlanCandidate:
    content: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "compiler": MASTER_PLAN_COMPILER_EDITOR,
        "proposal": {"proposal_revision_id": proposal_revision_id, "proposal_content_hash": proposal_content_hash},
        "source": {
            "draft_id": source.get("draft_id"),
            "draft_revision_id": source.get("draft_revision_id"),
            "understanding_id": source.get("understanding_id"),
            "understanding_revision_id": source.get("understanding_revision_id"),
        },
        "goal": fields["goal"],
        "requirements": fields["requirements"],
        "constraints": fields["constraints"],
        "architecture": dict(base_content.get("architecture", {"status": "REVIEW_REQUIRED", "reason": "not-authored-by-editor"})),
        "phases": fields["phases"],
        "nodes": fields["nodes"],
        "dependencies": fields["dependencies"],
        "risks": fields["risks"],
        "verification_intent": fields["verification_intent"],
        "delivery_intent": dict(base_content.get("delivery_intent", {"status": "REVIEW_REQUIRED", "method": "not-authorized-for-production"})),
        "workforce_intent": dict(base_content.get("workforce_intent", {"status": "ADVISORY_ONLY", "allocated_workers": []})),
        "pre_approval_only": True,
    }
    validate_master_plan_content(content)
    return MasterPlanCandidate(content=_normalise(content), content_hash=canonical_content_hash(content))


def request_fingerprint(command_type: str, expected_version: int, reason: str, source_ids: Mapping[str, Any]) -> str:
    return canonical_content_hash({
        "command_type": command_type,
        "expected_version": expected_version,
        "reason": reason,
        "source": _normalise(source_ids),
    })
