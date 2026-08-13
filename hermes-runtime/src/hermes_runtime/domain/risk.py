import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Optional, Tuple


RISK_MODEL_VERSION = "risk-model/1.0"
RISK_RULE_VERSION = "risk-rules/1.0"


class RiskRejected(ValueError):
    pass


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class RiskInput:
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
    reversibility_basis_points: int
    situation_id: str
    situation_version: int
    analysis_context_hash: str
    diagnosis_id: Optional[str]
    diagnosis_input_hash: Optional[str]
    candidate_registry_version: str
    target_environment: str = "unknown"
    verified_mitigations: Tuple[str, ...] = ()
    risk_model_version: str = RISK_MODEL_VERSION
    risk_rule_version: str = RISK_RULE_VERSION


@dataclass(frozen=True)
class RiskAssessment:
    risk_assessment_id: str
    risk_score_basis_points: int
    risk_level: RiskLevel
    factors: Mapping[str, int]
    reason_codes: Tuple[str, ...]
    required_mitigations: Tuple[str, ...]
    available_mitigations: Tuple[str, ...]
    residual_risk_basis_points: int
    risk_model_version: str
    risk_rule_version: str
    risk_input_hash: str


FACTOR_WEIGHTS = {
    "environment": 1600,
    "data_impact": 1200,
    "irreversibility": 1200,
    "privilege": 1000,
    "blast_radius": 1000,
    "network_exposure": 900,
    "secret_exposure": 1100,
    "supply_chain": 800,
    "rollback_confidence": 700,
    "worker_or_tool_trust": 500,
}


def assess_risk(inputs: RiskInput) -> RiskAssessment:
    if inputs.risk_model_version != RISK_MODEL_VERSION:
        raise RiskRejected("RISK_MODEL_VERSION_UNSUPPORTED")
    normalized = _normalize_input(inputs)
    factors, reasons, required = _derive_factors(normalized)
    score = sum(factors[name] * weight for name, weight in FACTOR_WEIGHTS.items()) // 10000
    level = risk_level_for(score)
    residual = _residual(score, normalized, required)
    input_hash = risk_input_hash(normalized)
    assessment_id = "risk-" + _hash({
        "risk_input_hash": input_hash,
        "risk_model_version": normalized.risk_model_version,
        "risk_rule_version": normalized.risk_rule_version,
        "score": score,
        "level": level.value,
        "factors": factors,
        "required_mitigations": list(required),
        "available_mitigations": list(normalized.verified_mitigations),
        "residual": residual,
    })[:32]
    return RiskAssessment(
        assessment_id, score, level, _canonical_value(factors),
        tuple(sorted(set(reasons))), tuple(sorted(set(required))),
        normalized.verified_mitigations, residual,
        normalized.risk_model_version, normalized.risk_rule_version, input_hash,
    )


def risk_level_for(score: int) -> RiskLevel:
    if score < 0 or score > 10000:
        raise RiskRejected("RISK_FACTOR_INVALID")
    if score < 2500:
        return RiskLevel.LOW
    if score < 5500:
        return RiskLevel.MEDIUM
    if score < 8000:
        return RiskLevel.HIGH
    return RiskLevel.CRITICAL


def risk_input_hash(inputs: RiskInput) -> str:
    return "sha256:" + _hash({
        "version": "risk-input/1.0",
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
        "reversibility_basis_points": inputs.reversibility_basis_points,
        "situation_id": inputs.situation_id,
        "situation_version": inputs.situation_version,
        "analysis_context_hash": inputs.analysis_context_hash,
        "diagnosis_id": inputs.diagnosis_id,
        "diagnosis_input_hash": inputs.diagnosis_input_hash,
        "candidate_registry_version": inputs.candidate_registry_version,
        "target_environment": inputs.target_environment,
        "verified_mitigations": list(inputs.verified_mitigations),
        "risk_model_version": inputs.risk_model_version,
        "risk_rule_version": inputs.risk_rule_version,
    })


def _derive_factors(inputs: RiskInput):
    params = inputs.parameters
    reasons = []
    required = []
    env = {
        "test": 1200, "dev": 2000, "unknown": 6500, "production": 9000,
    }.get(inputs.target_environment, 6500)
    if inputs.target_environment == "unknown":
        reasons.append("missing_environment_conservative")
        required.append("target_environment_classification")
    if inputs.target_environment == "production":
        reasons.append("production_target")
        required.append("human_production_change_authorization")

    action_base = {
        "diagnose": 1800,
        "run_deeper_test": 2500,
        "retry": 2400,
        "schedule_ready_task": 4200,
        "pause": 1200,
        "request_resource": 3000,
        "switch_strategy": 4000,
        "repair": 7000,
    }.get(inputs.action_type, 6500)
    if inputs.action_type == "repair":
        required.append("verification_before_apply")

    data_impact = 8500 if params.get("delete_data") else (5500 if inputs.action_type == "repair" else 1500)
    privilege = 8500 if params.get("privilege_escalation") else (4500 if "code_modification" in inputs.required_capabilities else 1500)
    network = 6000 if params.get("network_access") == "enabled" else 1500
    secret = 9000 if params.get("secret_access") else 1000
    supply = 6500 if inputs.action_type in {"repair", "switch_strategy"} else 1800
    rollback = 8000
    if "rollback_plan_verified" in inputs.verified_mitigations:
        rollback = 2500
    elif params.get("requires_verification_before_apply") is True:
        rollback = 5500
    else:
        reasons.append("rollback_unverified")

    irreversibility = max(0, 10000 - int(inputs.reversibility_basis_points))
    if inputs.target_environment == "production" and inputs.action_type == "repair":
        data_impact = max(data_impact, 8000)
        privilege = max(privilege, 6500)
        network = max(network, 5000)
        supply = max(supply, 7500)
        rollback = max(rollback, 7500)
    blast = 8500 if inputs.target_environment == "production" else action_base
    trust = 4500 if inputs.action_type in {"repair", "schedule_ready_task"} else 2000
    factors = {
        "environment": env,
        "data_impact": data_impact,
        "irreversibility": irreversibility,
        "privilege": privilege,
        "blast_radius": blast,
        "network_exposure": network,
        "secret_exposure": secret,
        "supply_chain": supply,
        "rollback_confidence": rollback,
        "worker_or_tool_trust": trust,
    }
    return factors, tuple(reasons or ("deterministic_model_applied",)), tuple(required)


def _residual(score: int, inputs: RiskInput, required):
    reduction = 0
    verified = set(inputs.verified_mitigations)
    if "rollback_plan_verified" in verified:
        reduction += 1000
    if "verification_before_apply" in verified:
        reduction += 800
    # Required mitigations that are merely listed but not verified do not reduce residual risk.
    for item in required:
        if item in verified:
            reduction += 300
    return max(0, score - reduction)


def _normalize_input(inputs: RiskInput) -> RiskInput:
    return RiskInput(
        inputs.project_id, inputs.planning_run_id, inputs.planner_input_hash,
        inputs.action_id, inputs.action_content_hash, inputs.action_type,
        tuple(sorted(set(inputs.target_refs))),
        tuple(sorted(set(inputs.required_capabilities))),
        _canonical_value(inputs.parameters),
        _canonical_value(inputs.estimated_resources),
        int(inputs.reversibility_basis_points),
        inputs.situation_id, int(inputs.situation_version),
        inputs.analysis_context_hash, inputs.diagnosis_id,
        inputs.diagnosis_input_hash, inputs.candidate_registry_version,
        str(inputs.target_environment or "unknown"),
        tuple(sorted(set(inputs.verified_mitigations))),
        inputs.risk_model_version, inputs.risk_rule_version,
    )


def _canonical_value(value):
    return json.loads(json.dumps(value, sort_keys=True, separators=(",", ":")))


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=True).encode("utf-8")
    ).hexdigest()
