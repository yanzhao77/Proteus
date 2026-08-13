import unittest

from hermes_runtime.domain.diagnosis import (
    CanonicalFinding,
    DiagnosisInput,
    EvidenceRelation,
    EvidenceSummary,
    RootCauseStatus,
    diagnose,
)


def finding(code, refs=("ev-1",)):
    return CanonicalFinding(
        code, "verification_check", "HIGH", "task-1", "artifact-1",
        "sha256:artifact", "component:test", "verification-1",
        "check-1", tuple(refs), "trace-1",
    )


def evidence(evidence_id="ev-1", relation=EvidenceRelation.SUPPORTING, valid=True):
    return EvidenceSummary(
        evidence_id, "artifact-1", "sha256:artifact", "verifier-1",
        valid, relation,
        "DIRECT_VERIFICATION_EVIDENCE"
        if relation is EvidenceRelation.SUPPORTING else "CONTRADICTS_FINDING",
    )


def inputs(findings, evidence_items=()):
    return DiagnosisInput(
        "project-1", "situation-1", 1, "ctx-1",
        "sha256:context", 7, "test_failure", ("component:test",),
        tuple(findings), tuple(evidence_items),
    )


class DiagnosisDomainTests(unittest.TestCase):
    def test_direct_known_evidence_confirms_root_cause(self):
        result = diagnose(inputs(
            (finding("TEST_ASSERTION_FAILURE"),), (evidence(),)
        ))
        self.assertEqual(RootCauseStatus.CONFIRMED, result.root_cause_status)
        self.assertEqual("test_assertion_failure", result.root_cause)
        self.assertGreaterEqual(result.confidence_basis_points, 9000)
        self.assertEqual(("rule.test_assertion_failure.v1",), result.matched_rule_ids)

    def test_known_indirect_finding_without_direct_evidence_is_probable(self):
        result = diagnose(inputs((finding("TEST_ASSERTION_FAILURE"),), ()))
        self.assertEqual(RootCauseStatus.PROBABLE, result.root_cause_status)
        self.assertEqual("test_assertion_failure", result.root_cause)
        self.assertEqual(1, len(result.hypotheses))
        self.assertEqual(1, len(result.evidence_requests))

    def test_evidence_insufficient_for_hash_mismatch_returns_unknown_null_root(self):
        result = diagnose(inputs((finding("ARTIFACT_HASH_MISMATCH"),), ()))
        self.assertEqual(RootCauseStatus.UNKNOWN, result.root_cause_status)
        self.assertIsNone(result.root_cause)
        self.assertEqual(0, result.confidence_basis_points)

    def test_unknown_finding_is_preserved_as_unknown(self):
        result = diagnose(inputs((finding("FREE_TEXT_LOG_SAYS_WEIRD"),), ()))
        self.assertEqual(RootCauseStatus.UNKNOWN, result.root_cause_status)
        self.assertIsNone(result.root_cause)
        self.assertEqual("FREE_TEXT_LOG_SAYS_WEIRD", result.findings[0].finding_code)

    def test_conflicting_rules_return_unknown(self):
        result = diagnose(inputs((
            finding("TEST_ASSERTION_FAILURE"),
            finding("DEPENDENCY_UNAVAILABLE"),
        ), (evidence(),)))
        self.assertEqual(RootCauseStatus.UNKNOWN, result.root_cause_status)
        self.assertIsNone(result.root_cause)
        self.assertEqual(2, len(result.matched_rule_ids))

    def test_contradicting_evidence_downgrades_to_unknown(self):
        result = diagnose(inputs((
            finding("TEST_ASSERTION_FAILURE", ("ev-1", "ev-2-contradict")),
        ), (
            evidence("ev-1"),
            evidence("ev-2-contradict", EvidenceRelation.CONTRADICTING),
        )))
        self.assertEqual(RootCauseStatus.UNKNOWN, result.root_cause_status)
        self.assertIsNone(result.root_cause)

    def test_invalid_evidence_does_not_raise_confidence(self):
        result = diagnose(inputs(
            (finding("ARTIFACT_HASH_MISMATCH"),), (evidence(valid=False),)
        ))
        self.assertEqual(RootCauseStatus.UNKNOWN, result.root_cause_status)
        self.assertEqual(0, result.confidence_basis_points)

    def test_same_input_has_same_hash_and_output_independent_of_order(self):
        first = diagnose(inputs((
            finding("TEST_ASSERTION_FAILURE", ("ev-b", "ev-a")),
        ), (
            evidence("ev-b"), evidence("ev-a"),
        )))
        second = diagnose(inputs((
            finding("TEST_ASSERTION_FAILURE", ("ev-a", "ev-b")),
        ), (
            evidence("ev-a"), evidence("ev-b"),
        )))
        self.assertEqual(first.input_hash, second.input_hash)
        self.assertEqual(first.root_cause_status, second.root_cause_status)
        self.assertEqual(first.root_cause, second.root_cause)

    def test_rule_hypothesis_and_evidence_request_order_is_stable(self):
        result = diagnose(inputs((
            finding("DEPENDENCY_UNAVAILABLE"),
            finding("BUILD_FAILURE"),
        ), ()))
        self.assertEqual(RootCauseStatus.UNKNOWN, result.root_cause_status)
        self.assertEqual(
            sorted(item.ordinal for item in result.hypotheses),
            [item.ordinal for item in result.hypotheses],
        )
        self.assertEqual(
            sorted(item.priority for item in result.evidence_requests),
            [item.priority for item in result.evidence_requests],
        )

    def test_diagnosis_outputs_no_action_decision_or_execution_request(self):
        result = diagnose(inputs((finding("TEST_ASSERTION_FAILURE"),), ()))
        text = repr(result)
        self.assertNotIn("CandidateAction", text)
        self.assertNotIn("ExecutionRequest", text)
        self.assertNotIn("DecisionRecord", text)


if __name__ == "__main__":
    unittest.main()
