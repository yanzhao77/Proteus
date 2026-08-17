import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Optional, Tuple


REGISTRY_VERSION = "action-registry/1.0"
# P6 (ADR-0073): versioned registry extension. The 1.0 registry stays frozen
# (P1 contract); 1.1 adds the worker-executable 'implement' action so fresh
# implementation work can start through the real planner. P0-P5 could never
# start a first execution: the planner only emitted worker-executable
# candidates for verification_failed situations (P2/P3 tests seeded a candidate
# via raw SQL). P6 closes that entry-point gap without touching 1.0.
P6_REGISTRY_VERSION = "action-registry/1.1"
PLANNER_RULE_VERSION = "planner-rules/1.0"
RESOURCE_ESTIMATOR_VERSION = "resource-estimator/1.0"


class PlannerRejected(ValueError):
    pass


class ActionType(str, Enum):
    RETRY = "retry"
    DIAGNOSE = "diagnose"
    REPAIR = "repair"
    SWITCH_STRATEGY = "switch_strategy"
    SWITCH_AGENT = "switch_agent"
    EXPERT_REVIEW = "expert_review"
    RUN_DEEPER_TEST = "run_deeper_test"
    REPLAN = "replan"
    ROLLBACK = "rollback"
    SCHEDULE_READY_TASK = "schedule_ready_task"
    REQUEST_RESOURCE = "request_resource"
    PAUSE = "pause"
    HUMAN_GATE = "human_gate"
    # P6 registry extension (ADR-0073): worker-executable implementation action.
    # The P0-P5 planner only emitted worker-executable candidates for
    # verification_failed situations, so fresh implementation work could never
    # start through the real authority path (P2/P3 tests seeded a candidate via
    # raw SQL). This versioned extension lets the planner propose an
    # implementation execution for work_available tasks.
    IMPLEMENT = "implement"


class DiagnosisRequirement(str, Enum):
    REQUIRED = "REQUIRED"
    OPTIONAL = "OPTIONAL"
    FORBIDDEN = "FORBIDDEN"


RESOURCE_DIMENSIONS = (
    "llm_tokens", "llm_cost_minor", "agent_runs", "retry_count",
    "execution_time_ms", "cpu_time_ms", "gpu_time_ms",
    "docker_runtime_ms", "browser_runtime_ms", "external_api_calls",
    "storage_bytes", "human_attention_requests",
)


@dataclass(frozen=True)
class ResourceEstimate:
    amounts: Mapping[str, int]
    currency: Optional[str]
    estimator_version: str = RESOURCE_ESTIMATOR_VERSION


@dataclass(frozen=True)
class RegistryEntry:
    action_type: ActionType
    supported_situation_types: Tuple[str, ...]
    allowed_root_cause_statuses: Tuple[str, ...]
    diagnosis_requirement: DiagnosisRequirement
    required_capabilities: Tuple[str, ...]
    parameter_schema_version: str
    expected_outputs: Tuple[str, ...]
    preconditions: Tuple[str, ...]
    default_reversibility_basis_points: int
    resource_estimator_id: str
    evidence_gain_rule: str
    target_derivation_rule: str
    enabled: bool


@dataclass(frozen=True)
class HypothesisRef:
    description_code: str
    confidence_basis_points: int
    test_action_hint: str
    ordinal: int


@dataclass(frozen=True)
class EvidenceRequestRef:
    request_code: str
    evidence_kind: str
    target_ref: str
    reason_code: str
    priority: int


@dataclass(frozen=True)
class PlanningInput:
    project_id: str
    situation_id: str
    situation_version: int
    situation_type: str
    analysis_context_id: str
    analysis_context_hash: str
    task_id: Optional[str]
    task_state: Optional[str]
    graph_version_ref: Optional[str]
    budget_threshold_status: Optional[str]
    diagnosis_id: Optional[str]
    diagnosis_input_hash: Optional[str]
    root_cause_status: Optional[str]
    root_cause: Optional[str]
    hypotheses: Tuple[HypothesisRef, ...]
    evidence_requests: Tuple[EvidenceRequestRef, ...]
    registry_version: str = REGISTRY_VERSION
    planner_rule_version: str = PLANNER_RULE_VERSION
    resource_estimator_version: str = RESOURCE_ESTIMATOR_VERSION


@dataclass(frozen=True)
class CandidateAction:
    action_id: str
    action_type: ActionType
    reason_code: str
    target_refs: Tuple[str, ...]
    required_capabilities: Tuple[str, ...]
    parameters: Mapping[str, object]
    expected_outputs: Tuple[str, ...]
    preconditions: Tuple[str, ...]
    estimated_resources: ResourceEstimate
    planner_confidence_basis_points: int
    expected_progress_basis_points: int
    evidence_gain_basis_points: int
    reversibility_basis_points: int
    registry_version: str
    planner_rule_version: str
    ordinal: int
    content_hash: str


@dataclass(frozen=True)
class PlanningRunResult:
    planning_run_id: str
    input_hash: str
    candidate_actions: Tuple[CandidateAction, ...]
    single_candidate_reason_code: Optional[str]


P6_REGISTRY: Tuple[RegistryEntry, ...] = (
    RegistryEntry(ActionType.IMPLEMENT, ("work_available",), ("NONE",),
                  DiagnosisRequirement.FORBIDDEN, ("software_builder",),
                  "action-params/implement/1.0",
                  ("artifact_candidate", "verification_plan"),
                  ("task_state_ready", "verify_before_apply"), 4000,
                  "resource-estimator/implement/1.0", "progress_ready_work",
                  "ready_task", True),
)


REGISTRY: Tuple[RegistryEntry, ...] = (
    RegistryEntry(ActionType.RUN_DEEPER_TEST, ("verification_failed",),
                  ("UNKNOWN", "PROBABLE", "CONFIRMED"),
                  DiagnosisRequirement.REQUIRED, ("verification_runner",),
                  "action-params/run_deeper_test/1.0",
                  ("evidence", "diagnosis_update"),
                  ("current_diagnosis", "artifact_available"), 8000,
                  "resource-estimator/run_deeper_test/1.0", "high_evidence_gain",
                  "diagnosis_evidence_request", True),
    RegistryEntry(ActionType.DIAGNOSE, ("verification_failed",),
                  ("UNKNOWN", "PROBABLE"),
                  DiagnosisRequirement.REQUIRED, ("diagnosis_engine",),
                  "action-params/diagnose/1.0", ("diagnosis", "evidence_gap"),
                  ("current_diagnosis",), 9000,
                  "resource-estimator/diagnose/1.0", "reduce_root_cause_space",
                  "diagnosis_hypothesis", True),
    RegistryEntry(ActionType.REPAIR, ("verification_failed",),
                  ("PROBABLE", "CONFIRMED"),
                  DiagnosisRequirement.REQUIRED, ("code_modification",),
                  "action-params/repair/1.0", ("artifact_candidate", "verification_plan"),
                  ("current_diagnosis", "verify_before_apply"), 4500,
                  "resource-estimator/repair/1.0", "progress_root_cause",
                  "diagnosis_root_cause", True),
    RegistryEntry(ActionType.RETRY, ("verification_failed",), ("CONFIRMED",),
                  DiagnosisRequirement.REQUIRED, ("verification_runner",),
                  "action-params/retry/1.0", ("verification_result",),
                  ("current_diagnosis", "same_artifact_available"), 7000,
                  "resource-estimator/retry/1.0", "confirm_reproducibility",
                  "same_task_artifact", True),
    RegistryEntry(ActionType.SWITCH_STRATEGY, ("verification_failed", "budget_pressure"),
                  ("CONFIRMED", "PROBABLE", "UNKNOWN", "NONE"),
                  DiagnosisRequirement.OPTIONAL, ("planning",),
                  "action-params/switch_strategy/1.0", ("strategy_proposal",),
                  ("current_situation",), 6500,
                  "resource-estimator/switch_strategy/1.0", "progress_alternative",
                  "situation_scope", True),
    RegistryEntry(ActionType.SCHEDULE_READY_TASK, ("work_available",), ("NONE",),
                  DiagnosisRequirement.FORBIDDEN, ("scheduler_candidate",),
                  "action-params/schedule_ready_task/1.0",
                  ("execution_request_proposal",), ("task_state_ready",),
                  6000, "resource-estimator/schedule_ready_task/1.0",
                  "progress_ready_work", "ready_task", True),
    RegistryEntry(ActionType.REQUEST_RESOURCE, ("budget_pressure",), ("NONE",),
                  DiagnosisRequirement.OPTIONAL, ("budget_request",),
                  "action-params/request_resource/1.0", ("resource_request",),
                  ("budget_pressure_active",), 5000,
                  "resource-estimator/request_resource/1.0", "unblock_budget",
                  "resource_account", True),
    RegistryEntry(ActionType.PAUSE, ("budget_pressure",), ("NONE",),
                  DiagnosisRequirement.OPTIONAL, ("project_control_candidate",),
                  "action-params/pause/1.0", ("pause_proposal",),
                  ("budget_pressure_active",), 9000,
                  "resource-estimator/pause/1.0", "prevent_overspend",
                  "project", True),
    RegistryEntry(ActionType.HUMAN_GATE, ("policy_blocked",), ("NONE",),
                  DiagnosisRequirement.OPTIONAL, ("human_attention",),
                  "action-params/human_gate/1.0", ("human_decision_request",),
                  ("formal_policy_gap",), 5000,
                  "resource-estimator/human_gate/1.0", "external_decision",
                  "policy_gap", False),
)


REPAIR_ROOT_CAUSES = {
    "test_assertion_failure": "repair_test_assertion_failure",
    "artifact_hash_mismatch": "repair_artifact_hash_mismatch",
    "build_failure": "repair_build_failure",
}


def registry_entry(action_type: str, registry: Tuple[RegistryEntry, ...] = REGISTRY) -> RegistryEntry:
    try:
        parsed = ActionType(action_type)
    except ValueError:
        raise PlannerRejected("PLANNER_ACTION_TYPE_UNSUPPORTED")
    for entry in registry:
        if entry.action_type is parsed:
            if not entry.enabled:
                raise PlannerRejected("PLANNER_ACTION_TYPE_UNSUPPORTED")
            return entry
    raise PlannerRejected("PLANNER_ACTION_TYPE_UNSUPPORTED")


def diagnosis_requirement_for(situation_type: str) -> DiagnosisRequirement:
    if situation_type == "verification_failed":
        return DiagnosisRequirement.REQUIRED
    if situation_type == "work_available":
        return DiagnosisRequirement.FORBIDDEN
    if situation_type == "budget_pressure":
        return DiagnosisRequirement.OPTIONAL
    raise PlannerRejected("PLANNER_NO_VALID_CANDIDATE")


def generate_planning_run(inputs: PlanningInput) -> PlanningRunResult:
    if inputs.registry_version not in {REGISTRY_VERSION, P6_REGISTRY_VERSION}:
        raise PlannerRejected("PLANNER_REGISTRY_VERSION_UNSUPPORTED")
    requirement = diagnosis_requirement_for(inputs.situation_type)
    if requirement is DiagnosisRequirement.REQUIRED and not inputs.diagnosis_id:
        raise PlannerRejected("PLANNER_DIAGNOSIS_REQUIRED")
    if requirement is DiagnosisRequirement.FORBIDDEN and inputs.diagnosis_id:
        raise PlannerRejected("PLANNER_DIAGNOSIS_NOT_ALLOWED")

    normalized = _normalize_input(inputs)
    input_hash = compute_input_hash(normalized)
    planning_run_id = "planrun-" + _hash({"input_hash": input_hash})[:32]
    registry = P6_REGISTRY if normalized.registry_version == P6_REGISTRY_VERSION else REGISTRY
    candidates = _candidate_specs(normalized, registry)
    if not candidates:
        raise PlannerRejected("PLANNER_NO_VALID_CANDIDATE")

    material = {}
    for spec in candidates:
        if spec["expected_progress_basis_points"] == 0 and spec["evidence_gain_basis_points"] == 0:
            raise PlannerRejected("PLANNER_NO_PROGRESS_OR_EVIDENCE_GAIN")
        content_hash = candidate_content_hash(normalized, spec)
        material[content_hash] = (content_hash, spec)
    ordered_specs = tuple(
        item for _, item in sorted(material.values(), key=lambda pair: (
            _action_priority(pair[1]["type"]),
            -pair[1]["evidence_gain_basis_points"],
            -pair[1]["expected_progress_basis_points"],
            pair[0],
        ))
    )[:5]
    actions = tuple(
        _candidate(planning_run_id, normalized, spec, ordinal)
        for ordinal, spec in enumerate(ordered_specs)
    )
    single_reason = None
    if len(actions) == 1:
        single_reason = "ONLY_ONE_REGISTRY_CANDIDATE_VALID"
    return PlanningRunResult(planning_run_id, input_hash, actions, single_reason)


def compute_input_hash(inputs: PlanningInput) -> str:
    return "sha256:" + _hash({
        "version": "planner-input/1.0",
        "project_id": inputs.project_id,
        "situation_id": inputs.situation_id,
        "situation_version": inputs.situation_version,
        "situation_type": inputs.situation_type,
        "analysis_context_hash": inputs.analysis_context_hash,
        "task_id": inputs.task_id,
        "task_state": inputs.task_state,
        "graph_version_ref": inputs.graph_version_ref,
        "budget_threshold_status": inputs.budget_threshold_status,
        "diagnosis_id": inputs.diagnosis_id,
        "diagnosis_input_hash": inputs.diagnosis_input_hash,
        "root_cause_status": inputs.root_cause_status,
        "root_cause": inputs.root_cause,
        "hypotheses": [_hypothesis_dict(item) for item in inputs.hypotheses],
        "evidence_requests": [_request_dict(item) for item in inputs.evidence_requests],
        "registry_version": inputs.registry_version,
        "planner_rule_version": inputs.planner_rule_version,
        "resource_estimator_version": inputs.resource_estimator_version,
    })


def candidate_content_hash(inputs: PlanningInput, spec: Mapping[str, object]) -> str:
    return "sha256:" + _hash({
        "version": "candidate-content/1.0",
        "situation_id": inputs.situation_id,
        "situation_version": inputs.situation_version,
        "analysis_context_hash": inputs.analysis_context_hash,
        "diagnosis_id": inputs.diagnosis_id,
        "type": spec["type"],
        "reason_code": spec["reason_code"],
        "target_refs": sorted(set(spec["target_refs"])),
        "required_capabilities": sorted(set(spec["required_capabilities"])),
        "parameters": _canonical_value(spec["parameters"]),
        "expected_outputs": sorted(set(spec["expected_outputs"])),
        "preconditions": sorted(set(spec["preconditions"])),
        "estimated_resources": _resource_dict(spec["estimated_resources"]),
        "planner_confidence_basis_points": spec["planner_confidence_basis_points"],
        "expected_progress_basis_points": spec["expected_progress_basis_points"],
        "evidence_gain_basis_points": spec["evidence_gain_basis_points"],
        "reversibility_basis_points": spec["reversibility_basis_points"],
        "registry_version": inputs.registry_version,
        "planner_rule_version": inputs.planner_rule_version,
    })


def _candidate(planning_run_id: str, inputs: PlanningInput, spec, ordinal: int) -> CandidateAction:
    content_hash = candidate_content_hash(inputs, spec)
    action_id = "act-" + _hash({
        "planning_run_id": planning_run_id,
        "content_hash": content_hash,
    })[:32]
    return CandidateAction(
        action_id,
        ActionType(spec["type"]),
        spec["reason_code"],
        tuple(sorted(set(spec["target_refs"]))),
        tuple(sorted(set(spec["required_capabilities"]))),
        _canonical_value(spec["parameters"]),
        tuple(sorted(set(spec["expected_outputs"]))),
        tuple(sorted(set(spec["preconditions"]))),
        spec["estimated_resources"],
        spec["planner_confidence_basis_points"],
        spec["expected_progress_basis_points"],
        spec["evidence_gain_basis_points"],
        spec["reversibility_basis_points"],
        inputs.registry_version,
        inputs.planner_rule_version,
        ordinal,
        content_hash,
    )


def _candidate_specs(inputs: PlanningInput, registry: Tuple[RegistryEntry, ...] = REGISTRY):
    if inputs.situation_type == "verification_failed":
        return _verification_failed_specs(inputs, registry)
    if inputs.situation_type == "work_available":
        return _work_available_specs(inputs, registry)
    if inputs.situation_type == "budget_pressure":
        return _budget_pressure_specs(inputs, registry)
    raise PlannerRejected("PLANNER_NO_VALID_CANDIDATE")


def _verification_failed_specs(inputs: PlanningInput, registry: Tuple[RegistryEntry, ...] = REGISTRY):
    status = inputs.root_cause_status
    if status not in {"UNKNOWN", "PROBABLE", "CONFIRMED"}:
        raise PlannerRejected("PLANNER_DIAGNOSIS_INPUT_MISMATCH")
    specs = []
    if status in {"UNKNOWN", "PROBABLE", "CONFIRMED"}:
        for request in inputs.evidence_requests[:2] or (
            EvidenceRequestRef("collect_reproduction_trace", "verification_trace",
                               inputs.situation_id, "diagnosis_needs_more_evidence", 0),
        ):
            specs.append(_spec(
                ActionType.RUN_DEEPER_TEST,
                "collect_evidence_for_" + request.request_code,
                (request.target_ref,),
                {"evidence_kind": request.evidence_kind,
                 "request_code": request.request_code,
                 "read_only": True},
                7000 if status == "UNKNOWN" else 5500,
                2000,
                8500 if status == "UNKNOWN" else 6500,
            ))
    if status in {"UNKNOWN", "PROBABLE"}:
        for hypothesis in inputs.hypotheses[:2] or (
            HypothesisRef("hypothesis.unknown_verification_failure", 2500,
                          "run_deeper_test", 0),
        ):
            specs.append(_spec(
                ActionType.DIAGNOSE,
                "narrow_root_cause_" + hypothesis.description_code,
                (inputs.situation_id,),
                {"hypothesis_code": hypothesis.description_code,
                 "diagnosis_input_hash": inputs.diagnosis_input_hash,
                 "read_only": True},
                7500,
                2500,
                7500,
            ))
    if status == "PROBABLE" and inputs.root_cause in REPAIR_ROOT_CAUSES:
        specs.append(_spec(
            ActionType.REPAIR,
            "probable_" + REPAIR_ROOT_CAUSES[inputs.root_cause],
            (inputs.task_id or inputs.situation_id,),
            {"root_cause": inputs.root_cause, "basis": "PROBABLE",
             "requires_verification_before_apply": True},
            6000, 6500, 2500,
        ))
    if status == "CONFIRMED":
        if inputs.root_cause in REPAIR_ROOT_CAUSES:
            specs.append(_spec(
                ActionType.REPAIR,
                "confirmed_" + REPAIR_ROOT_CAUSES[inputs.root_cause],
                (inputs.task_id or inputs.situation_id,),
                {"root_cause": inputs.root_cause, "basis": "CONFIRMED",
                 "requires_verification_before_apply": True},
                8500, 8000, 1500,
            ))
        specs.append(_spec(
            ActionType.RETRY,
            "retry_to_confirm_reproducibility",
            (inputs.task_id or inputs.situation_id,),
            {"same_artifact": True, "read_only": True},
            7000, 4500, 3500,
        ))
        specs.append(_spec(
            ActionType.SWITCH_STRATEGY,
            "switch_strategy_after_confirmed_failure",
            (inputs.task_id or inputs.situation_id,),
            {"strategy": "lower_risk_alternative"},
            6500, 5500, 2000,
        ))
    return specs


def _work_available_specs(inputs: PlanningInput, registry: Tuple[RegistryEntry, ...] = REGISTRY):
    if inputs.task_state != "READY":
        raise PlannerRejected("PLANNER_TARGET_STALE")
    if inputs.registry_version == P6_REGISTRY_VERSION:
        return [_spec(
            ActionType.IMPLEMENT,
            "implement_authoritative_ready_task",
            (inputs.task_id or inputs.situation_id,),
            {"task_id": inputs.task_id, "graph_version_ref": inputs.graph_version_ref,
             "creates_execution_request": True,
             "requires_verification_before_apply": True},
            8500, 8000, 1000, registry,
        )]
    return [_spec(
        ActionType.SCHEDULE_READY_TASK,
        "schedule_authoritative_ready_task",
        (inputs.task_id or inputs.situation_id,),
        {"task_id": inputs.task_id, "graph_version_ref": inputs.graph_version_ref,
         "creates_execution_request": False},
        9000, 8000, 0,
    )]


def _budget_pressure_specs(inputs: PlanningInput, registry: Tuple[RegistryEntry, ...] = REGISTRY):
    status = inputs.budget_threshold_status
    if status not in {"WARN", "GATE", "HARD_STOP"}:
        raise PlannerRejected("PLANNER_NO_VALID_CANDIDATE")
    specs = []
    if status == "WARN":
        specs.append(_spec(
            ActionType.SWITCH_STRATEGY, "switch_to_lower_cost_strategy",
            (inputs.situation_id,), {"strategy": "lower_cost", "budget_status": status},
            7500, 5500, 1000,
        ))
        specs.append(_spec(
            ActionType.PAUSE, "pause_as_budget_pressure_option",
            (inputs.project_id,), {"scope": "project", "budget_status": status},
            5000, 3000, 0,
        ))
    else:
        specs.append(_spec(
            ActionType.REQUEST_RESOURCE, "request_budget_extension",
            (inputs.situation_id,), {"budget_status": status, "approval_not_granted": True},
            8000, 5000, 0,
        ))
        specs.append(_spec(
            ActionType.PAUSE, "pause_to_prevent_budget_overrun",
            (inputs.project_id,), {"scope": "project", "budget_status": status},
            9000, 6500, 0,
        ))
    return specs


def _spec(action_type: ActionType, reason_code: str, target_refs, parameters,
          confidence: int, progress: int, evidence_gain: int,
          registry: Tuple[RegistryEntry, ...] = REGISTRY):
    entry = registry_entry(action_type.value, registry)
    _validate_parameters(entry, parameters)
    return {
        "type": action_type.value,
        "reason_code": reason_code,
        "target_refs": tuple(target_refs),
        "required_capabilities": entry.required_capabilities,
        "parameters": parameters,
        "expected_outputs": entry.expected_outputs,
        "preconditions": entry.preconditions,
        "estimated_resources": _estimate(action_type),
        "planner_confidence_basis_points": confidence,
        "expected_progress_basis_points": progress,
        "evidence_gain_basis_points": evidence_gain,
        "reversibility_basis_points": entry.default_reversibility_basis_points,
    }


def _estimate(action_type: ActionType) -> ResourceEstimate:
    estimates = {
        ActionType.RUN_DEEPER_TEST: {"agent_runs": 1, "execution_time_ms": 600000,
                                     "cpu_time_ms": 120000, "docker_runtime_ms": 300000,
                                     "storage_bytes": 1048576},
        ActionType.DIAGNOSE: {"agent_runs": 1, "execution_time_ms": 300000,
                              "cpu_time_ms": 60000, "storage_bytes": 262144},
        ActionType.REPAIR: {"agent_runs": 1, "execution_time_ms": 900000,
                            "cpu_time_ms": 300000, "storage_bytes": 1048576},
        ActionType.RETRY: {"agent_runs": 1, "retry_count": 1,
                           "execution_time_ms": 300000, "cpu_time_ms": 120000},
        ActionType.SWITCH_STRATEGY: {"agent_runs": 1, "execution_time_ms": 180000,
                                     "cpu_time_ms": 30000},
        ActionType.SCHEDULE_READY_TASK: {"agent_runs": 1, "execution_time_ms": 0},
        ActionType.IMPLEMENT: {"agent_runs": 1, "execution_time_ms": 600000,
                               "cpu_time_ms": 300000, "docker_runtime_ms": 300000,
                               "storage_bytes": 1048576},
        ActionType.REQUEST_RESOURCE: {"human_attention_requests": 1},
        ActionType.PAUSE: {},
    }
    amounts = estimates.get(action_type)
    if amounts is None:
        raise PlannerRejected("PLANNER_ACTION_TYPE_UNSUPPORTED")
    _validate_resources(amounts)
    return ResourceEstimate(amounts, None)


def _validate_resources(amounts: Mapping[str, int]) -> None:
    for dimension, amount in amounts.items():
        if dimension not in RESOURCE_DIMENSIONS:
            raise PlannerRejected("PLANNER_ACTION_PARAMETERS_INVALID")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
            raise PlannerRejected("PLANNER_ACTION_PARAMETERS_INVALID")


def _validate_parameters(entry: RegistryEntry, parameters: Mapping[str, object]) -> None:
    if not isinstance(parameters, Mapping):
        raise PlannerRejected("PLANNER_ACTION_PARAMETERS_INVALID")
    if entry.action_type is ActionType.SCHEDULE_READY_TASK:
        if not parameters.get("task_id"):
            raise PlannerRejected("PLANNER_ACTION_PARAMETERS_INVALID")
        if parameters.get("creates_execution_request") is not False:
            raise PlannerRejected("PLANNER_ACTION_PARAMETERS_INVALID")
    if entry.action_type in {ActionType.RUN_DEEPER_TEST, ActionType.DIAGNOSE}:
        if parameters.get("read_only") is not True:
            raise PlannerRejected("PLANNER_ACTION_PARAMETERS_INVALID")
    if entry.action_type is ActionType.REPAIR:
        if not parameters.get("root_cause"):
            raise PlannerRejected("PLANNER_ACTION_PARAMETERS_INVALID")
        if parameters.get("requires_verification_before_apply") is not True:
            raise PlannerRejected("PLANNER_ACTION_PARAMETERS_INVALID")
    if entry.action_type is ActionType.REQUEST_RESOURCE:
        if parameters.get("approval_not_granted") is not True:
            raise PlannerRejected("PLANNER_ACTION_PARAMETERS_INVALID")
    if entry.action_type is ActionType.IMPLEMENT:
        if not parameters.get("task_id"):
            raise PlannerRejected("PLANNER_ACTION_PARAMETERS_INVALID")
        if parameters.get("creates_execution_request") is not True:
            raise PlannerRejected("PLANNER_ACTION_PARAMETERS_INVALID")
        if parameters.get("requires_verification_before_apply") is not True:
            raise PlannerRejected("PLANNER_ACTION_PARAMETERS_INVALID")


def _normalize_input(inputs: PlanningInput) -> PlanningInput:
    return PlanningInput(
        inputs.project_id, inputs.situation_id, int(inputs.situation_version),
        inputs.situation_type, inputs.analysis_context_id,
        inputs.analysis_context_hash, inputs.task_id, inputs.task_state,
        inputs.graph_version_ref, inputs.budget_threshold_status,
        inputs.diagnosis_id, inputs.diagnosis_input_hash,
        inputs.root_cause_status, inputs.root_cause,
        tuple(sorted(set(inputs.hypotheses), key=lambda item: (
            item.ordinal, item.description_code, item.test_action_hint
        ))),
        tuple(sorted(set(inputs.evidence_requests), key=lambda item: (
            item.priority, item.request_code, item.target_ref
        ))),
        inputs.registry_version, inputs.planner_rule_version,
        inputs.resource_estimator_version,
    )


def _action_priority(action_type: str) -> int:
    order = [
        "run_deeper_test", "diagnose", "repair", "retry",
        "switch_strategy", "schedule_ready_task", "implement",
        "request_resource", "pause",
    ]
    return order.index(action_type) if action_type in order else 999


def _hypothesis_dict(item: HypothesisRef):
    return {
        "description_code": item.description_code,
        "confidence_basis_points": item.confidence_basis_points,
        "test_action_hint": item.test_action_hint,
        "ordinal": item.ordinal,
    }


def _request_dict(item: EvidenceRequestRef):
    return {
        "request_code": item.request_code,
        "evidence_kind": item.evidence_kind,
        "target_ref": item.target_ref,
        "reason_code": item.reason_code,
        "priority": item.priority,
    }


def _resource_dict(item: ResourceEstimate):
    return {
        "amounts": {key: item.amounts[key] for key in sorted(item.amounts)},
        "currency": item.currency,
        "estimator_version": item.estimator_version,
    }


def _canonical_value(value):
    return json.loads(json.dumps(value, sort_keys=True, separators=(",", ":")))


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=True).encode("utf-8")
    ).hexdigest()
