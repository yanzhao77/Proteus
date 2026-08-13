import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Optional, Tuple


RULE_SET_VERSION = "diagnosis-rules/1.0"
HISTORY_BOUND = 10


class RootCauseStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    PROBABLE = "PROBABLE"
    UNKNOWN = "UNKNOWN"


class EvidenceRelation(str, Enum):
    SUPPORTING = "SUPPORTING"
    CONTRADICTING = "CONTRADICTING"


@dataclass(frozen=True)
class CanonicalFinding:
    finding_code: str
    finding_type: str
    severity: str
    task_id: Optional[str]
    artifact_id: Optional[str]
    artifact_hash: Optional[str]
    component: Optional[str]
    source_verification_id: Optional[str]
    source_check_id: Optional[str]
    evidence_refs: Tuple[str, ...] = ()
    trace_id: Optional[str] = None


@dataclass(frozen=True)
class EvidenceSummary:
    evidence_id: str
    artifact_id: str
    artifact_hash: str
    producer_identity: str
    valid: bool
    relation: EvidenceRelation = EvidenceRelation.SUPPORTING
    reason_code: str = "DIRECT_VERIFICATION_EVIDENCE"


@dataclass(frozen=True)
class DiagnosisInput:
    project_id: str
    situation_id: str
    situation_version: int
    analysis_context_id: str
    analysis_context_hash: str
    observed_at_sequence: int
    failure_type: Optional[str]
    affected_components: Tuple[str, ...]
    findings: Tuple[CanonicalFinding, ...]
    evidence: Tuple[EvidenceSummary, ...]
    history_refs: Tuple[str, ...] = ()
    rule_set_version: str = RULE_SET_VERSION


@dataclass(frozen=True)
class Hypothesis:
    description_code: str
    confidence_basis_points: int
    test_action_hint: str
    ordinal: int


@dataclass(frozen=True)
class EvidenceRequest:
    request_code: str
    evidence_kind: str
    target_ref: str
    reason_code: str
    priority: int


@dataclass(frozen=True)
class DiagnosisResult:
    root_cause_status: RootCauseStatus
    root_cause: Optional[str]
    confidence_basis_points: int
    diagnostic_method: str
    input_hash: str
    matched_rule_ids: Tuple[str, ...]
    findings: Tuple[CanonicalFinding, ...]
    evidence: Tuple[EvidenceSummary, ...]
    hypotheses: Tuple[Hypothesis, ...]
    evidence_requests: Tuple[EvidenceRequest, ...]


@dataclass(frozen=True)
class DiagnosisRule:
    rule_id: str
    finding_codes: Tuple[str, ...]
    root_cause: str
    base_confidence: int
    probable_without_evidence: bool
    evidence_request_code: str
    hypothesis_code: str
    evidence_kind: str = "verification_evidence"


RULES: Tuple[DiagnosisRule, ...] = (
    DiagnosisRule(
        "rule.artifact_hash_mismatch.v1",
        ("ARTIFACT_HASH_MISMATCH",),
        "artifact_hash_mismatch",
        9500,
        False,
        "collect_artifact_hash_evidence",
        "hypothesis.artifact_hash_mismatch",
    ),
    DiagnosisRule(
        "rule.test_assertion_failure.v1",
        ("TEST_ASSERTION_FAILURE",),
        "test_assertion_failure",
        9000,
        True,
        "collect_test_failure_trace",
        "hypothesis.test_assertion_failure",
    ),
    DiagnosisRule(
        "rule.build_failure.v1",
        ("BUILD_FAILURE", "COMPILE_ERROR"),
        "build_failure",
        8800,
        True,
        "collect_build_log_excerpt",
        "hypothesis.build_failure",
    ),
    DiagnosisRule(
        "rule.dependency_unavailable.v1",
        ("DEPENDENCY_UNAVAILABLE",),
        "dependency_unavailable",
        8200,
        True,
        "collect_dependency_health",
        "hypothesis.dependency_unavailable",
    ),
)


def diagnose(inputs: DiagnosisInput) -> DiagnosisResult:
    findings = _canonical_findings(inputs.findings)
    evidence = _canonical_evidence(inputs.evidence)
    input_hash = compute_input_hash(inputs, findings, evidence)
    supporting = tuple(item for item in evidence if item.valid and item.relation is EvidenceRelation.SUPPORTING)
    contradicting = tuple(item for item in evidence if item.valid and item.relation is EvidenceRelation.CONTRADICTING)
    matched = _matched_rules(findings)

    if len({rule.root_cause for rule in matched}) > 1:
        return _unknown(
            input_hash,
            findings,
            evidence,
            "diagnosis.deterministic_rules.conflict",
            tuple(rule.rule_id for rule in matched),
            tuple(_hypothesis(rule, 4500, i) for i, rule in enumerate(matched)),
            tuple(_evidence_request(rule, inputs, i) for i, rule in enumerate(matched)),
        )
    if not matched:
        return _unknown(
            input_hash,
            findings,
            evidence,
            "diagnosis.deterministic_rules.no_match",
            (),
            (Hypothesis("hypothesis.unknown_verification_failure", 2500,
                        "run_deeper_test", 0),),
            (EvidenceRequest("collect_structured_finding", "verification_check_result",
                             inputs.situation_id, "finding_unsupported", 0),),
        )

    rule = matched[0]
    if contradicting:
        confidence = max(0, rule.base_confidence - 5000 - 1000 * len(contradicting))
        return _unknown(
            input_hash,
            findings,
            evidence,
            "diagnosis.deterministic_rules.contradicted",
            (rule.rule_id,),
            (_hypothesis(rule, max(confidence, 1000), 0),),
            (_evidence_request(rule, inputs, 0),),
        )
    if supporting:
        return DiagnosisResult(
            RootCauseStatus.CONFIRMED,
            rule.root_cause,
            rule.base_confidence,
            "deterministic_rule_registry",
            input_hash,
            (rule.rule_id,),
            findings,
            evidence,
            (),
            (),
        )
    if rule.probable_without_evidence:
        return DiagnosisResult(
            RootCauseStatus.PROBABLE,
            rule.root_cause,
            min(rule.base_confidence, 6500),
            "deterministic_rule_registry.missing_direct_evidence",
            input_hash,
            (rule.rule_id,),
            findings,
            evidence,
            (_hypothesis(rule, 6500, 0),),
            (_evidence_request(rule, inputs, 0),),
        )
    return _unknown(
        input_hash,
        findings,
        evidence,
        "diagnosis.deterministic_rules.insufficient_evidence",
        (rule.rule_id,),
        (_hypothesis(rule, 4000, 0),),
        (_evidence_request(rule, inputs, 0),),
    )


def diagnosis_id_for(inputs: DiagnosisInput, result: DiagnosisResult) -> str:
    digest = _hash({
        "project_id": inputs.project_id,
        "situation_id": inputs.situation_id,
        "situation_version": inputs.situation_version,
        "analysis_context_hash": inputs.analysis_context_hash,
        "rule_set_version": inputs.rule_set_version,
        "input_hash": result.input_hash,
    })
    return "diag-" + digest[:32]


def compute_input_hash(
    inputs: DiagnosisInput,
    findings: Optional[Tuple[CanonicalFinding, ...]] = None,
    evidence: Optional[Tuple[EvidenceSummary, ...]] = None,
) -> str:
    return "sha256:" + _hash({
        "version": "diagnosis-input/1.0",
        "project_id": inputs.project_id,
        "situation_id": inputs.situation_id,
        "situation_version": inputs.situation_version,
        "analysis_context_id": inputs.analysis_context_id,
        "analysis_context_hash": inputs.analysis_context_hash,
        "observed_at_sequence": inputs.observed_at_sequence,
        "failure_type": inputs.failure_type,
        "affected_components": sorted(set(inputs.affected_components)),
        "rule_set_version": inputs.rule_set_version,
        "findings": [_finding_dict(item) for item in (findings or _canonical_findings(inputs.findings))],
        "evidence": [_evidence_dict(item) for item in (evidence or _canonical_evidence(inputs.evidence))],
        "history_refs": sorted(set(inputs.history_refs))[:HISTORY_BOUND],
    })


def _matched_rules(findings: Tuple[CanonicalFinding, ...]) -> Tuple[DiagnosisRule, ...]:
    codes = {item.finding_code for item in findings}
    return tuple(rule for rule in RULES if codes.intersection(rule.finding_codes))


def _unknown(
    input_hash: str,
    findings: Tuple[CanonicalFinding, ...],
    evidence: Tuple[EvidenceSummary, ...],
    method: str,
    matched_rule_ids: Tuple[str, ...],
    hypotheses: Tuple[Hypothesis, ...],
    evidence_requests: Tuple[EvidenceRequest, ...],
) -> DiagnosisResult:
    return DiagnosisResult(
        RootCauseStatus.UNKNOWN,
        None,
        0,
        method,
        input_hash,
        matched_rule_ids,
        findings,
        evidence,
        tuple(sorted(hypotheses, key=lambda item: (item.ordinal, item.description_code))),
        tuple(sorted(evidence_requests, key=lambda item: (item.priority, item.request_code))),
    )


def _hypothesis(rule: DiagnosisRule, confidence: int, ordinal: int) -> Hypothesis:
    return Hypothesis(rule.hypothesis_code, confidence, "run_deeper_test", ordinal)


def _evidence_request(rule: DiagnosisRule, inputs: DiagnosisInput, priority: int) -> EvidenceRequest:
    target = inputs.analysis_context_id
    return EvidenceRequest(
        rule.evidence_request_code,
        rule.evidence_kind,
        target,
        "direct_evidence_missing_or_contradicted",
        priority,
    )


def _canonical_findings(findings: Tuple[CanonicalFinding, ...]) -> Tuple[CanonicalFinding, ...]:
    normalized = {
        _finding_key(item): CanonicalFinding(
            _norm_code(item.finding_code),
            _text(item.finding_type) or "verification_check",
            _text(item.severity) or "MEDIUM",
            _optional(item.task_id),
            _optional(item.artifact_id),
            _optional(item.artifact_hash),
            _optional(item.component),
            _optional(item.source_verification_id),
            _optional(item.source_check_id),
            tuple(sorted({_text(ref) for ref in item.evidence_refs if _text(ref)})),
            _optional(item.trace_id),
        )
        for item in findings
    }
    return tuple(normalized[key] for key in sorted(normalized))


def _canonical_evidence(evidence: Tuple[EvidenceSummary, ...]) -> Tuple[EvidenceSummary, ...]:
    normalized = {}
    for item in evidence:
        key = (item.evidence_id, item.relation.value)
        if item.evidence_id in {existing[0] for existing in normalized} and key not in normalized:
            # Same Evidence cannot be both supporting and contradicting for one diagnosis.
            continue
        normalized[key] = EvidenceSummary(
            _text(item.evidence_id),
            _text(item.artifact_id),
            _text(item.artifact_hash),
            _text(item.producer_identity),
            bool(item.valid),
            item.relation,
            _norm_code(item.reason_code),
        )
    return tuple(normalized[key] for key in sorted(normalized))


def _finding_key(item: CanonicalFinding):
    normalized = (
        _norm_code(item.finding_code),
        _text(item.finding_type) or "verification_check",
        _text(item.severity) or "MEDIUM",
        _optional(item.task_id),
        _optional(item.artifact_id),
        _optional(item.artifact_hash),
        _optional(item.component),
        _optional(item.source_verification_id),
        _optional(item.source_check_id),
        tuple(sorted({_text(ref) for ref in item.evidence_refs if _text(ref)})),
        _optional(item.trace_id),
    )
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"))


def _finding_dict(item: CanonicalFinding) -> Mapping[str, object]:
    return {
        "finding_code": item.finding_code,
        "finding_type": item.finding_type,
        "severity": item.severity,
        "task_id": item.task_id,
        "artifact_id": item.artifact_id,
        "artifact_hash": item.artifact_hash,
        "component": item.component,
        "source_verification_id": item.source_verification_id,
        "source_check_id": item.source_check_id,
        "evidence_refs": list(item.evidence_refs),
        "trace_id": item.trace_id,
    }


def _evidence_dict(item: EvidenceSummary) -> Mapping[str, object]:
    return {
        "evidence_id": item.evidence_id,
        "artifact_id": item.artifact_id,
        "artifact_hash": item.artifact_hash,
        "producer_identity": item.producer_identity,
        "valid": item.valid,
        "relation": item.relation.value,
        "reason_code": item.reason_code,
    }


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def _norm_code(value: object) -> str:
    return _text(value).upper().replace("-", "_").replace(".", "_")


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _optional(value: object) -> Optional[str]:
    text = _text(value)
    return text or None
