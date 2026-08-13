import unittest

from hermes_runtime.domain.policy import (
    POLICY_BUNDLE_VERSION,
    PolicyEffect,
    PolicyInput,
    PolicyRejected,
    evaluate_policy,
    intersect_constraints,
)


def policy_input(action_type="run_deeper_test", params=None, environment="dev", **overrides):
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
        "planner_confidence_basis_points": 10000,
        "expected_progress_basis_points": 10000,
        "evidence_gain_basis_points": 10000,
        "situation_id": "situation-1",
        "situation_version": 1,
        "analysis_context_hash": "sha256:context",
        "diagnosis_id": "diagnosis-1",
        "diagnosis_input_hash": "sha256:diagnosis",
        "candidate_registry_version": "action-registry/1.0",
        "target_environment": environment,
    }
    data.update(overrides)
    return PolicyInput(**data)


class PolicyDomainTests(unittest.TestCase):
    def test_read_only_diagnosis_allow_has_restrictive_constraints(self):
        decision = evaluate_policy(policy_input())
        self.assertEqual(PolicyEffect.ALLOW, decision.result)
        self.assertEqual("policy-bundle/1.0", POLICY_BUNDLE_VERSION)
        self.assertEqual("disabled", decision.constraints["network_access"])
        self.assertEqual("none", decision.constraints["filesystem_write"])
        self.assertEqual("denied", decision.constraints["production_access"])

    def test_dangerous_repair_denied_despite_max_planner_quality(self):
        decision = evaluate_policy(policy_input(
            "repair",
            {"root_cause": "build_failure", "requires_verification_before_apply": True,
             "delete_data": True},
            "dev",
        ))
        self.assertEqual(PolicyEffect.DENY, decision.result)
        self.assertIn("dangerous_repair_denied", decision.reason_codes)
        self.assertEqual({}, decision.constraints)

    def test_repair_unknown_environment_fails_closed(self):
        decision = evaluate_policy(policy_input(
            "repair",
            {"root_cause": "build_failure", "requires_verification_before_apply": True},
            "unknown",
        ))
        self.assertEqual(PolicyEffect.DENY, decision.result)
        self.assertIn("policy_input_incomplete", decision.reason_codes)

    def test_production_repair_requires_human_not_gate(self):
        decision = evaluate_policy(policy_input(
            "repair",
            {"root_cause": "build_failure", "requires_verification_before_apply": True},
            "production",
        ))
        self.assertEqual(PolicyEffect.REQUIRE_HUMAN, decision.result)
        self.assertIn("human_production_change_authorization",
                      decision.constraints["required_mitigations"])

    def test_request_resource_requires_human(self):
        decision = evaluate_policy(policy_input(
            "request_resource", {"approval_not_granted": True}, "unknown",
            diagnosis_id=None, diagnosis_input_hash=None,
        ))
        self.assertEqual(PolicyEffect.REQUIRE_HUMAN, decision.result)
        self.assertIn("external_budget_authorization_required", decision.reason_codes)

    def test_emergency_deny_cannot_be_overridden_by_allow(self):
        decision = evaluate_policy(policy_input(runtime_emergency_freeze=True))
        self.assertEqual(PolicyEffect.DENY, decision.result)
        self.assertIn("runtime_emergency_freeze", decision.reason_codes)

    def test_no_rule_fails_closed(self):
        decision = evaluate_policy(policy_input("switch_agent", {}, "dev"))
        self.assertEqual(PolicyEffect.DENY, decision.result)
        self.assertIn("no_applicable_policy_rule", decision.reason_codes)

    def test_constraints_intersection_only_tightens(self):
        merged = intersect_constraints(
            {"max_risk_level": "HIGH", "max_external_api_calls": 5,
             "required_mitigations": ("a",), "filesystem_write": "workspace_only"},
            {"max_risk_level": "MEDIUM", "max_external_api_calls": 0,
             "required_mitigations": ("b",), "filesystem_write": "none"},
        )
        self.assertEqual("MEDIUM", merged["max_risk_level"])
        self.assertEqual(0, merged["max_external_api_calls"])
        self.assertEqual(["a", "b"], merged["required_mitigations"])
        self.assertEqual("none", merged["filesystem_write"])

    def test_unknown_constraint_fails_closed(self):
        with self.assertRaisesRegex(PolicyRejected, "POLICY_CONSTRAINT_UNSUPPORTED"):
            intersect_constraints({}, {"magic": True})

    def test_deterministic_independent_of_quality_fields_for_deny(self):
        first = evaluate_policy(policy_input(
            "repair", {"root_cause": "build_failure", "requires_verification_before_apply": True,
                       "delete_data": True}, "dev",
            planner_confidence_basis_points=1,
            expected_progress_basis_points=1,
            evidence_gain_basis_points=1,
        ))
        second = evaluate_policy(policy_input(
            "repair", {"root_cause": "build_failure", "requires_verification_before_apply": True,
                       "delete_data": True}, "dev",
            planner_confidence_basis_points=10000,
            expected_progress_basis_points=10000,
            evidence_gain_basis_points=10000,
        ))
        self.assertEqual(first.policy_decision_id, second.policy_decision_id)
        self.assertEqual(PolicyEffect.DENY, second.result)


if __name__ == "__main__":
    unittest.main()
