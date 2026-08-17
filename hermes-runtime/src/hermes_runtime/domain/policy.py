import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Optional, Tuple


POLICY_BUNDLE_VERSION = "policy-bundle/1.0"
POLICY_RULE_VERSION = "policy-rules/1.0"


class PolicyRejected(ValueError):
    pass


class PolicyEffect(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_HUMAN = "REQUIRE_HUMAN"


RISK_LEVELS = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
CONSTRAINT_TYPES = {
    "network_access",
    "filesystem_write",
    "environment",
    "secret_access",
    "production_access",
    "max_risk_level",
    "required_mitigations",
    "allowed_tools",
    "forbidden_paths",
    "max_external_api_calls",
}


@dataclass(frozen=True)
class PolicyRule:
    rule_id: str
    scope_type: str
    scope_id: str
    priority: int
    effect: PolicyEffect
    action_types: Tuple[str, ...]
    target_environments: Tuple[str, ...]
    constraints: Mapping[str, object]
    reason_codes: Tuple[str, ...]
    non_overridable: bool = False
    enabled: bool = True


@dataclass(frozen=True)
class PolicyInput:
    project_id: str
    planning_run_id: str
    planner_input_hash: str
    action_id: str
    action_content_hash: str
    action_type: str
    target_refs: Tuple[str, ...]
    required_capabilities: Tuple[str, ...]
    parameters: Mapping[str, object]
    estimated_resources: Mapping[str, object]
    planner_confidence_basis_points: int
    expected_progress_basis_points: int
    evidence_gain_basis_points: int
    situation_id: str
    situation_version: int
    analysis_context_hash: str
    diagnosis_id: Optional[str]
    diagnosis_input_hash: Optional[str]
    candidate_registry_version: str
    target_environment: str = "unknown"
    runtime_emergency_freeze: bool = False
    policy_bundle_version: str = POLICY_BUNDLE_VERSION
    policy_rule_version: str = POLICY_RULE_VERSION


@dataclass(frozen=True)
class PolicyDecision:
    policy_decision_id: str
    result: PolicyEffect
    matched_rule_ids: Tuple[str, ...]
    reason_codes: Tuple[str, ...]
    constraints: Mapping[str, object]
    policy_bundle_version: str
    policy_rule_version: str
    policy_input_hash: str


POLICY_RULES: Tuple[PolicyRule, ...] = (
    PolicyRule(
        "policy.system.emergency_freeze.deny.v1", "runtime_emergency", "*", 1000,
        PolicyEffect.DENY, ("*",), ("*",), {},
        ("runtime_emergency_freeze",), True,
    ),
    PolicyRule(
        "policy.system.read_only_diagnosis.allow.v1", "system", "*", 100,
        PolicyEffect.ALLOW, ("diagnose", "run_deeper_test"), ("dev", "test", "unknown"),
        {
            "network_access": "disabled",
            "filesystem_write": "none",
            "production_access": "denied",
            "secret_access": "denied",
            "max_risk_level": "MEDIUM",
            "max_external_api_calls": 0,
        },
        ("read_only_diagnosis_allowed",),
    ),
    PolicyRule(
        "policy.system.retry.allow.v1", "system", "*", 100,
        PolicyEffect.ALLOW, ("retry",), ("dev", "test", "unknown"),
        {
            "network_access": "disabled",
            "filesystem_write": "none",
            "production_access": "denied",
            "secret_access": "denied",
            "max_risk_level": "MEDIUM",
        },
        ("same_artifact_retry_allowed",),
    ),
    PolicyRule(
        "policy.system.schedule_ready_task.allow.v1", "system", "*", 100,
        PolicyEffect.ALLOW, ("schedule_ready_task",), ("dev", "test", "unknown"),
        {"production_access": "denied", "max_risk_level": "HIGH"},
        ("schedule_ready_task_may_enter_later_checks",),
    ),
    PolicyRule(
        "policy.system.pause.allow.v1", "system", "*", 100,
        PolicyEffect.ALLOW, ("pause",), ("*",),
        {"production_access": "denied", "max_risk_level": "LOW"},
        ("pause_candidate_may_enter_later_checks",),
    ),
    PolicyRule(
        "policy.system.request_resource.human.v1", "system", "*", 100,
        PolicyEffect.REQUIRE_HUMAN, ("request_resource",), ("*",),
        {"required_mitigations": ("human_budget_authorization",)},
        ("external_budget_authorization_required",),
    ),
    PolicyRule(
        "policy.system.repair.dangerous.deny.v1", "system", "*", 900,
        PolicyEffect.DENY, ("repair",), ("*",), {},
        ("dangerous_repair_denied",), True,
    ),
    PolicyRule(
        "policy.system.repair.production.human.v1", "system", "*", 400,
        PolicyEffect.REQUIRE_HUMAN, ("repair",), ("production",),
        {
            "production_access": "requires_human",
            "required_mitigations": ("human_production_change_authorization",),
            "max_risk_level": "HIGH",
        },
        ("production_repair_requires_human",),
    ),
    PolicyRule(
        "policy.system.repair.safe_code.allow.v1", "system", "*", 100,
        PolicyEffect.ALLOW, ("repair",), ("dev", "test"),
        {
            "network_access": "disabled",
            "filesystem_write": "workspace_only",
            "production_access": "denied",
            "secret_access": "denied",
            "max_risk_level": "HIGH",
            "required_mitigations": ("verification_before_apply",),
        },
        ("bounded_code_repair_allowed",),
    ),
    PolicyRule(
        "policy.system.implement.safe_code.allow.v1", "system", "*", 100,
        PolicyEffect.ALLOW, ("implement",), ("dev", "test"),
        {
            "network_access": "disabled",
            "filesystem_write": "workspace_only",
            "production_access": "denied",
            "secret_access": "denied",
            "max_risk_level": "HIGH",
            "required_mitigations": ("verification_before_apply",),
        },
        ("bounded_implementation_allowed",),
    ),
)


def evaluate_policy(inputs: PolicyInput) -> PolicyDecision:
    if inputs.policy_bundle_version != POLICY_BUNDLE_VERSION:
        raise PolicyRejected("POLICY_BUNDLE_VERSION_UNSUPPORTED")
    normalized = _normalize_input(inputs)
    if _has_unknown_mandatory_security_property(normalized):
        return _decision(normalized, PolicyEffect.DENY, (), ("policy_input_incomplete",), {})
    applicable = tuple(rule for rule in POLICY_RULES if _matches(rule, normalized))
    if not applicable:
        return _decision(normalized, PolicyEffect.DENY, (), ("no_applicable_policy_rule",), {})

    effects = {rule.effect for rule in applicable}
    constraints: Mapping[str, object] = {}
    reason_codes = []
    for rule in sorted(applicable, key=lambda item: (-item.priority, item.rule_id)):
        reason_codes.extend(rule.reason_codes)
        constraints = intersect_constraints(constraints, rule.constraints)

    if PolicyEffect.DENY in effects:
        result = PolicyEffect.DENY
        constraints = {}
    elif PolicyEffect.REQUIRE_HUMAN in effects:
        result = PolicyEffect.REQUIRE_HUMAN
    elif effects == {PolicyEffect.ALLOW}:
        result = PolicyEffect.ALLOW
    else:
        raise PolicyRejected("POLICY_RULE_CONFLICT")
    return _decision(
        normalized, result, tuple(rule.rule_id for rule in applicable),
        tuple(sorted(set(reason_codes))), constraints,
    )


def intersect_constraints(left: Mapping[str, object], right: Mapping[str, object]):
    merged = dict(left)
    for key, value in right.items():
        if key not in CONSTRAINT_TYPES:
            raise PolicyRejected("POLICY_CONSTRAINT_UNSUPPORTED")
        if key not in merged:
            merged[key] = _canonical_value(value)
            continue
        merged[key] = _stricter_constraint(key, merged[key], value)
    return _canonical_value(merged)


def policy_input_hash(inputs: PolicyInput) -> str:
    return "sha256:" + _hash(_input_dict(inputs))


def _decision(inputs, effect, matched_rule_ids, reason_codes, constraints):
    input_hash = policy_input_hash(inputs)
    decision_id = "policy-" + _hash({
        "policy_input_hash": input_hash,
        "policy_bundle_version": inputs.policy_bundle_version,
        "policy_rule_version": inputs.policy_rule_version,
        "result": effect.value,
        "matched_rule_ids": list(matched_rule_ids),
        "reason_codes": list(reason_codes),
        "constraints": constraints,
    })[:32]
    return PolicyDecision(
        decision_id, effect, tuple(sorted(matched_rule_ids)),
        tuple(sorted(set(reason_codes))), _canonical_value(constraints),
        inputs.policy_bundle_version, inputs.policy_rule_version, input_hash,
    )


def _matches(rule: PolicyRule, inputs: PolicyInput) -> bool:
    if not rule.enabled:
        return False
    if rule.rule_id == "policy.system.emergency_freeze.deny.v1":
        return inputs.runtime_emergency_freeze
    if "*" not in rule.action_types and inputs.action_type not in rule.action_types:
        return False
    if "*" not in rule.target_environments and inputs.target_environment not in rule.target_environments:
        return False
    if inputs.action_type in {"diagnose", "run_deeper_test"}:
        return inputs.parameters.get("read_only") is True
    if inputs.action_type == "retry":
        return inputs.parameters.get("same_artifact") is True
    if inputs.action_type == "repair":
        dangerous = (
            inputs.parameters.get("delete_data")
            or inputs.parameters.get("secret_access")
            or inputs.parameters.get("privilege_escalation")
        )
        if rule.rule_id == "policy.system.repair.dangerous.deny.v1":
            return bool(dangerous)
        if dangerous:
            return False
        return inputs.parameters.get("requires_verification_before_apply") is True
    return True


def _has_unknown_mandatory_security_property(inputs: PolicyInput) -> bool:
    if inputs.action_type == "repair" and inputs.target_environment == "unknown":
        return True
    if inputs.action_type == "run_deeper_test" and inputs.parameters.get("read_only") is not True:
        return True
    return False


def _stricter_constraint(key: str, left, right):
    right = _canonical_value(right)
    if key == "max_risk_level":
        return left if RISK_LEVELS.index(str(left)) <= RISK_LEVELS.index(str(right)) else right
    if key == "max_external_api_calls":
        return min(int(left), int(right))
    if key in {"required_mitigations", "forbidden_paths"}:
        values = set(left if isinstance(left, (list, tuple, set)) else (left,))
        values.update(right if isinstance(right, (list, tuple, set)) else (right,))
        return tuple(sorted(values))
    if key == "allowed_tools":
        left_set = set(left if isinstance(left, (list, tuple, set)) else (left,))
        right_set = set(right if isinstance(right, (list, tuple, set)) else (right,))
        return tuple(sorted(left_set & right_set))
    order = {
        "network_access": ("disabled", "restricted", "enabled"),
        "filesystem_write": ("none", "workspace_only", "broad"),
        "secret_access": ("denied", "metadata_only", "allowed"),
        "production_access": ("denied", "requires_human", "allowed"),
        "environment": ("test", "dev", "unknown", "production"),
    }
    if key in order:
        ranking = order[key]
        return left if ranking.index(str(left)) <= ranking.index(str(right)) else right
    if left != right:
        raise PolicyRejected("POLICY_RULE_CONFLICT")
    return left


def _normalize_input(inputs: PolicyInput) -> PolicyInput:
    return PolicyInput(
        inputs.project_id, inputs.planning_run_id, inputs.planner_input_hash,
        inputs.action_id, inputs.action_content_hash, inputs.action_type,
        tuple(sorted(set(inputs.target_refs))),
        tuple(sorted(set(inputs.required_capabilities))),
        _canonical_value(inputs.parameters),
        _canonical_value(inputs.estimated_resources),
        int(inputs.planner_confidence_basis_points),
        int(inputs.expected_progress_basis_points),
        int(inputs.evidence_gain_basis_points),
        inputs.situation_id, int(inputs.situation_version),
        inputs.analysis_context_hash, inputs.diagnosis_id,
        inputs.diagnosis_input_hash, inputs.candidate_registry_version,
        str(inputs.target_environment or "unknown"),
        bool(inputs.runtime_emergency_freeze),
        inputs.policy_bundle_version, inputs.policy_rule_version,
    )


def _input_dict(inputs: PolicyInput):
    return {
        "version": "policy-input/1.0",
        "project_id": inputs.project_id,
        "planning_run_id": inputs.planning_run_id,
        "planner_input_hash": inputs.planner_input_hash,
        "action_id": inputs.action_id,
        "action_content_hash": inputs.action_content_hash,
        "action_type": inputs.action_type,
        "target_refs": list(inputs.target_refs),
        "required_capabilities": list(inputs.required_capabilities),
        "parameters": _canonical_value(inputs.parameters),
        "estimated_resources": _canonical_value(inputs.estimated_resources),
        "situation_id": inputs.situation_id,
        "situation_version": inputs.situation_version,
        "analysis_context_hash": inputs.analysis_context_hash,
        "diagnosis_id": inputs.diagnosis_id,
        "diagnosis_input_hash": inputs.diagnosis_input_hash,
        "candidate_registry_version": inputs.candidate_registry_version,
        "target_environment": inputs.target_environment,
        "runtime_emergency_freeze": inputs.runtime_emergency_freeze,
        "policy_bundle_version": inputs.policy_bundle_version,
        "policy_rule_version": inputs.policy_rule_version,
    }


def _canonical_value(value):
    return json.loads(json.dumps(value, sort_keys=True, separators=(",", ":")))


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=True).encode("utf-8")
    ).hexdigest()
