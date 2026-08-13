import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Optional, Tuple


WEIGHT_PROFILE_VERSION = "selection-weight-profile/1.0"
NORMALIZER_VERSION = "selection-normalizer/1.0"
CONFLICT_RULE_VERSION = "selection-conflict-rules/1.0"

MAX_PARALLEL_SELECTED_ACTIONS = 2
DEFAULT_HISTORICAL_SUCCESS_BASIS_POINTS = 3500

RESOURCE_DIMENSIONS = (
    "llm_tokens", "llm_cost_minor", "agent_runs", "retry_count",
    "execution_time_ms", "cpu_time_ms", "gpu_time_ms",
    "docker_runtime_ms", "browser_runtime_ms", "external_api_calls",
    "storage_bytes", "human_attention_requests",
)

RISK_LEVEL_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
SUPPORTED_CONSTRAINTS = {
    "network_access", "filesystem_write", "environment", "secret_access",
    "production_access", "max_risk_level", "required_mitigations",
    "allowed_tools", "forbidden_paths", "max_external_api_calls",
}

WEIGHTS = {
    "expected_progress": 1800,
    "confidence": 1200,
    "evidence_gain": 1600,
    "reversibility": 900,
    "risk": -1600,
    "cost": -900,
    "time": -600,
    "historical_success": 400,
}


class SelectionRejected(ValueError):
    pass


class Disposition(str, Enum):
    FILTERED = "FILTERED"
    ELIGIBLE_NOT_SELECTED = "ELIGIBLE_NOT_SELECTED"
    SELECTED = "SELECTED"


@dataclass(frozen=True)
class AccountSnapshot:
    account_id: str
    project_id: str
    scope_type: str
    scope_id: str
    currency: Optional[str]
    version: int
    threshold_status: str
    balances: Mapping[str, Tuple[int, int, int]]


@dataclass(frozen=True)
class CandidateInput:
    action_id: str
    planning_run_id: str
    project_id: str
    situation_id: str
    situation_version: int
    analysis_context_hash: str
    diagnosis_id: Optional[str]
    diagnosis_input_hash: Optional[str]
    action_type: str
    target_refs: Tuple[str, ...]
    required_capabilities: Tuple[str, ...]
    parameters: Mapping[str, object]
    estimated_resources: Mapping[str, object]
    planner_confidence_basis_points: int
    expected_progress_basis_points: int
    evidence_gain_basis_points: int
    reversibility_basis_points: int
    registry_version: str
    planner_rule_version: str
    ordinal: int
    content_hash: str
    policy_decision_id: Optional[str]
    policy_result: Optional[str]
    policy_constraints: Mapping[str, object]
    policy_input_hash: Optional[str]
    policy_bundle_version: Optional[str]
    policy_rule_version: Optional[str]
    risk_assessment_id: Optional[str]
    risk_level: Optional[str]
    residual_risk_basis_points: Optional[int]
    risk_required_mitigations: Tuple[str, ...]
    risk_available_mitigations: Tuple[str, ...]
    risk_input_hash: Optional[str]
    risk_model_version: Optional[str]
    risk_rule_version: Optional[str]
    account_id: Optional[str]
    account: Optional[AccountSnapshot]
    expected_account_version: Optional[int]


@dataclass(frozen=True)
class ScoreResult:
    score_id: str
    final_score_basis_points: int
    dimensions: Mapping[str, int]
    raw_dimensions: Mapping[str, int]
    contributions: Mapping[str, int]
    default_sources: Mapping[str, str]
    reason_codes: Tuple[str, ...]
    score_input_hash: str
    weight_profile_id: str = WEIGHT_PROFILE_VERSION
    normalizer_version: str = NORMALIZER_VERSION


@dataclass(frozen=True)
class CandidateDecision:
    action_id: str
    disposition: Disposition
    reason_codes: Tuple[str, ...]
    score: Optional[ScoreResult]
    account_id: Optional[str]
    reservation_required: bool
    reservation_id: Optional[str]
    resource_amounts: Mapping[str, int]
    normalized_cost_basis_points: Optional[int]
    derived_read_write: Mapping[str, object]
    rank_tuple: Tuple[object, ...]


@dataclass(frozen=True)
class SelectionResult:
    decision_id: str
    selection_version: int
    input_snapshot_hash: str
    candidate_decisions: Tuple[CandidateDecision, ...]
    selected_action_ids: Tuple[str, ...]
    eligible_action_ids: Tuple[str, ...]
    decision_reason_codes: Tuple[str, ...]
    weight_profile_id: str = WEIGHT_PROFILE_VERSION
    normalizer_version: str = NORMALIZER_VERSION
    conflict_rule_version: str = CONFLICT_RULE_VERSION
    max_parallel: int = MAX_PARALLEL_SELECTED_ACTIONS


def select_actions(
    *,
    project_id: str,
    situation_id: str,
    situation_version: int,
    planning_run_id: str,
    planner_input_hash: str,
    selection_version: int,
    expected_selection_version: int,
    candidates: Tuple[CandidateInput, ...],
    weight_profile_id: str = WEIGHT_PROFILE_VERSION,
) -> SelectionResult:
    if weight_profile_id != WEIGHT_PROFILE_VERSION:
        raise SelectionRejected("SELECTION_WEIGHT_PROFILE_UNSUPPORTED")
    if selection_version != expected_selection_version + 1:
        raise SelectionRejected("SELECTION_VERSION_INVALID")
    snapshot_hash = input_snapshot_hash(
        project_id=project_id,
        situation_id=situation_id,
        situation_version=situation_version,
        planning_run_id=planning_run_id,
        planner_input_hash=planner_input_hash,
        expected_selection_version=expected_selection_version,
        candidates=candidates,
        weight_profile_id=weight_profile_id,
    )
    decisions = []
    eligible = []
    for candidate in sorted(candidates, key=lambda item: item.action_id):
        reasons = list(_policy_risk_filter(candidate))
        resource_amounts = _resource_amounts(candidate)
        account_id = candidate.account_id
        normalized_cost = None
        reservation_required = any(amount > 0 for amount in resource_amounts.values())
        if not reasons:
            budget_reasons, normalized_cost = _budget_filter(candidate, resource_amounts)
            reasons.extend(budget_reasons)
        if reasons:
            decisions.append(CandidateDecision(
                candidate.action_id, Disposition.FILTERED,
                tuple(sorted(set(reasons))), None, account_id, reservation_required,
                None, resource_amounts, normalized_cost,
                derive_read_write_sets(candidate), (),
            ))
            continue
        if not reservation_required:
            reasons.append("ZERO_RESOURCE_NO_RESERVATION_REQUIRED")
        score = score_candidate(candidate, normalized_cost or 0, weight_profile_id)
        derived = derive_read_write_sets(candidate)
        rank_tuple = _rank_tuple(candidate, score, normalized_cost or 0)
        decision = CandidateDecision(
            candidate.action_id, Disposition.ELIGIBLE_NOT_SELECTED,
            tuple(sorted(set(reasons))) or ("ELIGIBLE",), score, account_id,
            reservation_required, _reservation_id(snapshot_hash, candidate)
            if reservation_required else None, resource_amounts,
            normalized_cost or 0, derived, rank_tuple,
        )
        eligible.append(decision)
        decisions.append(decision)

    selected = []
    not_selected_reasons = {}
    for decision in sorted(eligible, key=lambda item: item.rank_tuple):
        if len(selected) >= MAX_PARALLEL_SELECTED_ACTIONS:
            not_selected_reasons[decision.action_id] = "CONCURRENCY_LIMIT"
            continue
        conflict = _conflicts_any(decision, selected)
        if conflict:
            not_selected_reasons[decision.action_id] = "ACTION_CONFLICT"
            continue
        selected.append(decision)
    if eligible and not selected:
        for decision in eligible:
            not_selected_reasons.setdefault(decision.action_id, "LOWER_RANKED")
    selected_ids = {item.action_id for item in selected}
    final_decisions = []
    for decision in decisions:
        if decision.action_id in selected_ids:
            final_decisions.append(CandidateDecision(
                decision.action_id, Disposition.SELECTED, ("SELECTED",),
                decision.score, decision.account_id, decision.reservation_required,
                decision.reservation_id, decision.resource_amounts,
                decision.normalized_cost_basis_points, decision.derived_read_write,
                decision.rank_tuple,
            ))
        elif decision.disposition is Disposition.ELIGIBLE_NOT_SELECTED:
            code = not_selected_reasons.get(decision.action_id, "LOWER_RANKED")
            final_decisions.append(CandidateDecision(
                decision.action_id, Disposition.ELIGIBLE_NOT_SELECTED, (code,),
                decision.score, decision.account_id, decision.reservation_required,
                decision.reservation_id, decision.resource_amounts,
                decision.normalized_cost_basis_points, decision.derived_read_write,
                decision.rank_tuple,
            ))
        else:
            final_decisions.append(decision)
    decision_reasons = tuple(sorted(set(
        ["ACTIONS_SELECTED"] if selected else ["NO_ELIGIBLE_ACTION"]
    )))
    decision_id = "decision-" + _hash({
        "input_snapshot_hash": snapshot_hash,
        "selection_version": selection_version,
        "selected_action_ids": sorted(selected_ids),
        "dispositions": [
            {
                "action_id": item.action_id,
                "disposition": item.disposition.value,
                "reason_codes": list(item.reason_codes),
                "reservation_id": item.reservation_id,
            }
            for item in sorted(final_decisions, key=lambda value: value.action_id)
        ],
    })[:32]
    return SelectionResult(
        decision_id, selection_version, snapshot_hash,
        tuple(sorted(final_decisions, key=lambda item: item.action_id)),
        tuple(sorted(selected_ids)),
        tuple(item.action_id for item in sorted(eligible, key=lambda item: item.action_id)),
        decision_reasons,
    )


def score_candidate(
    candidate: CandidateInput,
    normalized_cost_basis_points: int,
    weight_profile_id: str = WEIGHT_PROFILE_VERSION,
) -> ScoreResult:
    if weight_profile_id != WEIGHT_PROFILE_VERSION:
        raise SelectionRejected("SELECTION_WEIGHT_PROFILE_UNSUPPORTED")
    risk_value = _clamp(int(candidate.residual_risk_basis_points or 10000))
    time_amount = int(_resource_amounts(candidate).get("execution_time_ms", 0))
    normalized_time = _clamp(time_amount * 10000 // 3_600_000)
    raw = {
        "expected_progress": candidate.expected_progress_basis_points,
        "confidence": candidate.planner_confidence_basis_points,
        "evidence_gain": candidate.evidence_gain_basis_points,
        "reversibility": candidate.reversibility_basis_points,
        "risk": risk_value,
        "cost": normalized_cost_basis_points,
        "time": normalized_time,
        "historical_success": DEFAULT_HISTORICAL_SUCCESS_BASIS_POINTS,
    }
    dimensions = {key: _clamp(int(value)) for key, value in raw.items()}
    contributions = {
        key: dimensions[key] * weight // 10000
        for key, weight in WEIGHTS.items()
    }
    final = _clamp(sum(contributions.values()))
    defaults = {"historical_success": "DEFAULT_NO_HISTORY"}
    score_input_hash = "sha256:" + _hash({
        "action_id": candidate.action_id,
        "action_content_hash": candidate.content_hash,
        "policy_decision_id": candidate.policy_decision_id,
        "risk_assessment_id": candidate.risk_assessment_id,
        "dimensions": dimensions,
        "weights": WEIGHTS,
        "weight_profile_id": weight_profile_id,
        "normalizer_version": NORMALIZER_VERSION,
    })
    return ScoreResult(
        "score-" + _hash({
            "score_input_hash": score_input_hash,
            "final": final,
        })[:32],
        final, dimensions, raw, contributions, defaults,
        ("DEFAULT_NO_HISTORY", "INTEGER_BASIS_POINTS"),
        score_input_hash, weight_profile_id, NORMALIZER_VERSION,
    )


def input_snapshot_hash(
    *,
    project_id: str,
    situation_id: str,
    situation_version: int,
    planning_run_id: str,
    planner_input_hash: str,
    expected_selection_version: int,
    candidates: Tuple[CandidateInput, ...],
    weight_profile_id: str = WEIGHT_PROFILE_VERSION,
) -> str:
    return "sha256:" + _hash({
        "version": "selection-input-snapshot/1.0",
        "project_id": project_id,
        "situation_id": situation_id,
        "situation_version": situation_version,
        "planning_run_id": planning_run_id,
        "planner_input_hash": planner_input_hash,
        "expected_selection_version": expected_selection_version,
        "weight_profile_id": weight_profile_id,
        "normalizer_version": NORMALIZER_VERSION,
        "conflict_rule_version": CONFLICT_RULE_VERSION,
        "candidates": [_candidate_snapshot(item) for item in sorted(candidates, key=lambda c: c.action_id)],
    })


def derive_read_write_sets(candidate: CandidateInput) -> Mapping[str, object]:
    params = dict(candidate.parameters)
    readonly = bool(params.get("read_only")) or candidate.action_type in {"diagnose", "run_deeper_test", "retry"}
    targets = tuple(sorted(set(candidate.target_refs)))
    if readonly:
        return {"read_only": True, "read_set": list(targets), "write_set": [], "project_global_mutation": False}
    if candidate.action_type in {"pause", "request_resource", "switch_strategy"}:
        return {"read_only": False, "read_set": list(targets), "write_set": ["project:" + candidate.project_id],
                "project_global_mutation": True}
    if not targets:
        return {"read_only": False, "read_set": [], "write_set": ["unknown:" + candidate.action_id],
                "project_global_mutation": True}
    return {"read_only": False, "read_set": list(targets),
            "write_set": [str(item) for item in targets], "project_global_mutation": False}


def _policy_risk_filter(candidate: CandidateInput) -> Tuple[str, ...]:
    reasons = []
    if not candidate.policy_decision_id:
        return ("POLICY_DECISION_MISSING",)
    if candidate.policy_result == "DENY":
        return ("POLICY_DENY",)
    if candidate.policy_result == "REQUIRE_HUMAN":
        return ("POLICY_REQUIRE_HUMAN",)
    if candidate.policy_result != "ALLOW":
        return ("POLICY_DECISION_STALE",)
    if not candidate.risk_assessment_id:
        return ("RISK_ASSESSMENT_MISSING",)
    if candidate.risk_level not in RISK_LEVEL_ORDER:
        return ("RISK_ASSESSMENT_STALE",)

    constraints = dict(candidate.policy_constraints or {})
    for key in constraints:
        if key not in SUPPORTED_CONSTRAINTS:
            reasons.append("POLICY_CONSTRAINT_UNSUPPORTED")
    max_risk = constraints.get("max_risk_level")
    if max_risk is not None:
        if str(max_risk) not in RISK_LEVEL_ORDER:
            reasons.append("POLICY_CONSTRAINT_UNSUPPORTED")
        elif RISK_LEVEL_ORDER[str(candidate.risk_level)] > RISK_LEVEL_ORDER[str(max_risk)]:
            reasons.append("POLICY_RISK_CONSTRAINT_UNSATISFIED")
    required = tuple(str(item) for item in constraints.get("required_mitigations", ()) or ())
    available = set(candidate.risk_available_mitigations)
    for mitigation in tuple(candidate.risk_required_mitigations) + required:
        if mitigation not in available:
            reasons.append("REQUIRED_MITIGATION_UNVERIFIED")
            break
    if constraints.get("production_access") == "denied" and candidate.parameters.get("target_environment") == "production":
        reasons.append("POLICY_ACTION_CONSTRAINT_UNSATISFIED")
    if constraints.get("network_access") == "disabled" and candidate.parameters.get("network_access") == "enabled":
        reasons.append("POLICY_ACTION_CONSTRAINT_UNSATISFIED")
    if constraints.get("secret_access") == "denied" and candidate.parameters.get("secret_access"):
        reasons.append("POLICY_ACTION_CONSTRAINT_UNSATISFIED")
    max_calls = constraints.get("max_external_api_calls")
    if max_calls is not None and int(candidate.parameters.get("external_api_calls", 0)) > int(max_calls):
        reasons.append("POLICY_ACTION_CONSTRAINT_UNSATISFIED")
    return tuple(reasons)


def _budget_filter(candidate: CandidateInput, amounts: Mapping[str, int]):
    if any(amount < 0 for amount in amounts.values()):
        return ("BUDGET_ESTIMATE_INVALID",), None
    if not amounts:
        return ("BUDGET_ESTIMATE_INVALID",), None
    if not any(amount > 0 for amount in amounts.values()):
        return (), 0
    if not candidate.account_id or not candidate.account:
        return ("BUDGET_ACCOUNT_BINDING_REQUIRED",), None
    account = candidate.account
    if account.project_id != candidate.project_id:
        return ("BUDGET_ACCOUNT_SCOPE_MISMATCH",), None
    if account.version != candidate.expected_account_version:
        return ("BUDGET_ACCOUNT_VERSION_CONFLICT",), None
    if account.threshold_status == "HARD_STOP":
        return ("BUDGET_HARD_STOP",), None
    estimate_currency = candidate.estimated_resources.get("currency")
    if (estimate_currency or None) != (account.currency or None):
        return ("BUDGET_CURRENCY_MISMATCH",), None
    if not _scope_matches(candidate, account):
        return ("BUDGET_ACCOUNT_SCOPE_MISMATCH",), None
    ratios = []
    for dimension, amount in amounts.items():
        if dimension not in RESOURCE_DIMENSIONS:
            return ("BUDGET_ESTIMATE_INVALID",), None
        balance = account.balances.get(dimension)
        if balance is None:
            return ("BUDGET_INFEASIBLE",), None
        limit, consumed, reserved = balance
        available = limit - consumed - reserved
        if amount > available:
            return ("BUDGET_INFEASIBLE",), None
        ratios.append(0 if limit <= 0 else amount * 10000 // limit)
    return (), _clamp(max(ratios or (0,)))


def _resource_amounts(candidate: CandidateInput) -> Mapping[str, int]:
    estimate = candidate.estimated_resources
    if "amounts" not in estimate or not isinstance(estimate["amounts"], Mapping):
        return {}
    return {str(key): int(value) for key, value in estimate["amounts"].items()}


def _scope_matches(candidate: CandidateInput, account: AccountSnapshot) -> bool:
    if account.scope_type == "project":
        return account.scope_id == candidate.project_id
    if account.scope_type == "action":
        return account.scope_id == candidate.action_id
    if account.scope_type == "task":
        return account.scope_id in set(candidate.target_refs)
    return False


def _rank_tuple(candidate: CandidateInput, score: ScoreResult, normalized_cost: int):
    return (
        -score.final_score_basis_points,
        int(candidate.residual_risk_basis_points or 10000),
        -int(candidate.reversibility_basis_points),
        int(normalized_cost),
        candidate.action_id,
    )


def _conflicts_any(candidate: CandidateDecision, selected: Tuple[CandidateDecision, ...]) -> bool:
    return any(_conflicts(candidate.derived_read_write, item.derived_read_write)
               for item in selected)


def _conflicts(left: Mapping[str, object], right: Mapping[str, object]) -> bool:
    if left.get("read_only") and right.get("read_only"):
        return False
    if left.get("project_global_mutation") or right.get("project_global_mutation"):
        return True
    left_writes = set(left.get("write_set") or ())
    right_writes = set(right.get("write_set") or ())
    if not left_writes or not right_writes:
        return True
    return bool(left_writes & right_writes)


def _candidate_snapshot(candidate: CandidateInput) -> Mapping[str, object]:
    return {
        "action_id": candidate.action_id,
        "content_hash": candidate.content_hash,
        "type": candidate.action_type,
        "target_refs": list(candidate.target_refs),
        "parameters": _canonical(candidate.parameters),
        "estimated_resources": _canonical(candidate.estimated_resources),
        "policy": {
            "id": candidate.policy_decision_id,
            "result": candidate.policy_result,
            "constraints": _canonical(candidate.policy_constraints),
            "input_hash": candidate.policy_input_hash,
            "bundle_version": candidate.policy_bundle_version,
            "rule_version": candidate.policy_rule_version,
        },
        "risk": {
            "id": candidate.risk_assessment_id,
            "level": candidate.risk_level,
            "residual": candidate.residual_risk_basis_points,
            "required_mitigations": list(candidate.risk_required_mitigations),
            "available_mitigations": list(candidate.risk_available_mitigations),
            "input_hash": candidate.risk_input_hash,
            "model_version": candidate.risk_model_version,
            "rule_version": candidate.risk_rule_version,
        },
        "account": None if candidate.account is None else {
            "id": candidate.account.account_id,
            "version": candidate.account.version,
            "currency": candidate.account.currency,
            "threshold_status": candidate.account.threshold_status,
            "balances": _canonical(candidate.account.balances),
        },
    }


def _reservation_id(snapshot_hash: str, candidate: CandidateInput) -> str:
    return "reservation-" + _hash({
        "snapshot_hash": snapshot_hash,
        "action_id": candidate.action_id,
        "account_id": candidate.account_id,
        "amounts": _resource_amounts(candidate),
    })[:32]


def _clamp(value: int) -> int:
    return max(0, min(10000, int(value)))


def _canonical(value: object) -> object:
    return json.loads(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True))


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
