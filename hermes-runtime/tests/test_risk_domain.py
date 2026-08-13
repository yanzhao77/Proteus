import unittest

from hermes_runtime.domain.risk import RiskInput, RiskLevel, assess_risk, risk_level_for


def risk_input(action_type="run_deeper_test", params=None, environment="dev", mitigations=(), **overrides):
    data = {
        "project_id": "project-1",
        "planning_run_id": "planrun-1",
        "planner_input_hash": "sha256:planner",
        "action_id": "act-1",
        "action_content_hash": "sha256:action",
        "action_type": action_type,
        "target_refs": ("task-1",),
        "required_capabilities": ("verification_runner",),
        "parameters": params if params is not None else {"read_only": True},
        "estimated_resources": {"amounts": {"agent_runs": 1}, "currency": None},
        "reversibility_basis_points": 8000,
        "situation_id": "situation-1",
        "situation_version": 1,
        "analysis_context_hash": "sha256:context",
        "diagnosis_id": "diagnosis-1",
        "diagnosis_input_hash": "sha256:diagnosis",
        "candidate_registry_version": "action-registry/1.0",
        "target_environment": environment,
        "verified_mitigations": tuple(mitigations),
    }
    data.update(overrides)
    return RiskInput(**data)


class RiskDomainTests(unittest.TestCase):
    def test_level_boundaries_are_mechanical(self):
        self.assertEqual(RiskLevel.LOW, risk_level_for(2499))
        self.assertEqual(RiskLevel.MEDIUM, risk_level_for(2500))
        self.assertEqual(RiskLevel.MEDIUM, risk_level_for(5499))
        self.assertEqual(RiskLevel.HIGH, risk_level_for(5500))
        self.assertEqual(RiskLevel.HIGH, risk_level_for(7999))
        self.assertEqual(RiskLevel.CRITICAL, risk_level_for(8000))

    def test_read_only_diagnosis_is_low_or_medium(self):
        assessment = assess_risk(risk_input())
        self.assertIn(assessment.risk_level, {RiskLevel.LOW, RiskLevel.MEDIUM})
        self.assertNotIn("ALLOW", repr(assessment))
        self.assertNotIn("DENY", repr(assessment))

    def test_repair_has_higher_risk_and_requires_verification_mitigation(self):
        assessment = assess_risk(risk_input(
            "repair",
            {"root_cause": "build_failure", "requires_verification_before_apply": True},
            "dev",
            required_capabilities=("code_modification",),
            reversibility_basis_points=4500,
        ))
        self.assertGreaterEqual(assessment.risk_score_basis_points, 4000)
        self.assertIn("verification_before_apply", assessment.required_mitigations)

    def test_production_repair_is_high_or_critical(self):
        assessment = assess_risk(risk_input(
            "repair",
            {"root_cause": "build_failure", "requires_verification_before_apply": True},
            "production",
            required_capabilities=("code_modification",),
            reversibility_basis_points=3000,
        ))
        self.assertIn(assessment.risk_level, {RiskLevel.HIGH, RiskLevel.CRITICAL})
        self.assertIn("human_production_change_authorization",
                      assessment.required_mitigations)

    def test_secret_and_privilege_raise_risk(self):
        baseline = assess_risk(risk_input("repair", {
            "root_cause": "build_failure", "requires_verification_before_apply": True
        }, "dev", required_capabilities=("code_modification",)))
        elevated = assess_risk(risk_input("repair", {
            "root_cause": "build_failure", "requires_verification_before_apply": True,
            "secret_access": True, "privilege_escalation": True
        }, "dev", required_capabilities=("code_modification",)))
        self.assertGreater(elevated.risk_score_basis_points,
                           baseline.risk_score_basis_points)

    def test_missing_environment_is_conservative(self):
        assessment = assess_risk(risk_input("retry", {"same_artifact": True}, "unknown"))
        self.assertIn("missing_environment_conservative", assessment.reason_codes)
        self.assertGreaterEqual(assessment.factors["environment"], 6500)

    def test_unverified_mitigation_does_not_reduce_residual(self):
        required_only = assess_risk(risk_input(
            "repair",
            {"root_cause": "build_failure", "requires_verification_before_apply": True},
            "dev",
        ))
        self.assertEqual(required_only.risk_score_basis_points,
                         required_only.residual_risk_basis_points)
        verified = assess_risk(risk_input(
            "repair",
            {"root_cause": "build_failure", "requires_verification_before_apply": True},
            "dev",
            mitigations=("verification_before_apply", "rollback_plan_verified"),
        ))
        self.assertLess(verified.residual_risk_basis_points,
                        verified.risk_score_basis_points)

    def test_deterministic_same_input_same_id_and_score(self):
        first = assess_risk(risk_input())
        second = assess_risk(risk_input())
        self.assertEqual(first.risk_assessment_id, second.risk_assessment_id)
        self.assertEqual(first.risk_score_basis_points,
                         second.risk_score_basis_points)


if __name__ == "__main__":
    unittest.main()
