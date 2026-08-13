import unittest

from hermes_runtime.domain.selection import (
    WEIGHT_PROFILE_VERSION,
    AccountSnapshot,
    CandidateInput,
    Disposition,
    input_snapshot_hash,
    score_candidate,
    select_actions,
)


def account(version=0, limit=100, reserved=0, scope_type="project", scope_id="project-1"):
    return AccountSnapshot(
        "account-1", "project-1", scope_type, scope_id, None, version, "NORMAL",
        {
            "agent_runs": (limit, 0, reserved),
            "execution_time_ms": (3_600_000, 0, 0),
        },
    )


def candidate(
    action_id="action-1",
    action_type="run_deeper_test",
    params=None,
    policy="ALLOW",
    risk_level="LOW",
    residual=1000,
    resources=None,
    acct=None,
    target_refs=("task-1",),
    progress=7000,
    confidence=7000,
    evidence_gain=7000,
    reversibility=8000,
    mitigations=(),
    available=(),
):
    return CandidateInput(
        action_id, "plan-1", "project-1", "situation-1", 1,
        "sha256:context", "diagnosis-1", "sha256:diagnosis",
        action_type, tuple(target_refs), ("verification_runner",),
        params if params is not None else {"read_only": True},
        resources if resources is not None else {
            "amounts": {"agent_runs": 1, "execution_time_ms": 1000},
            "currency": None,
            "estimator_version": "resource-estimator/1.0",
        },
        confidence, progress, evidence_gain, reversibility,
        "action-registry/1.0", "planner-rules/1.0", 0,
        "sha256:" + action_id,
        "policy-" + action_id if policy else None, policy,
        {"max_risk_level": "MEDIUM", "network_access": "disabled"},
        "sha256:policy", "policy-bundle/1.0", "policy-rules/1.0",
        "risk-" + action_id if risk_level else None, risk_level, residual,
        tuple(mitigations), tuple(available), "sha256:risk",
        "risk-model/1.0", "risk-rules/1.0", "account-1" if acct else None,
        acct, acct.version if acct else None,
    )


class SelectionDomainTests(unittest.TestCase):
    def test_eight_dimension_integer_score_and_default_history(self):
        score = score_candidate(candidate(acct=account()), 100)
        self.assertEqual(WEIGHT_PROFILE_VERSION, score.weight_profile_id)
        self.assertEqual(
            {
                "expected_progress", "confidence", "evidence_gain", "reversibility",
                "risk", "cost", "time", "historical_success",
            },
            set(score.dimensions),
        )
        self.assertTrue(all(isinstance(v, int) for v in score.dimensions.values()))
        self.assertEqual("DEFAULT_NO_HISTORY", score.default_sources["historical_success"])

    def test_input_order_does_not_change_snapshot_or_selection(self):
        first = candidate("action-a", acct=account())
        second = candidate("action-b", acct=account())
        h1 = input_snapshot_hash(
            project_id="project-1", situation_id="situation-1", situation_version=1,
            planning_run_id="plan-1", planner_input_hash="sha256:planner",
            expected_selection_version=0, candidates=(first, second),
        )
        h2 = input_snapshot_hash(
            project_id="project-1", situation_id="situation-1", situation_version=1,
            planning_run_id="plan-1", planner_input_hash="sha256:planner",
            expected_selection_version=0, candidates=(second, first),
        )
        self.assertEqual(h1, h2)

    def test_policy_deny_filters_before_score_and_no_reservation(self):
        result = select_actions(
            project_id="project-1", situation_id="situation-1", situation_version=1,
            planning_run_id="plan-1", planner_input_hash="sha256:planner",
            selection_version=1, expected_selection_version=0,
            candidates=(candidate(policy="DENY", acct=account(), progress=10000),),
        )
        decision = result.candidate_decisions[0]
        self.assertEqual(Disposition.FILTERED, decision.disposition)
        self.assertIn("POLICY_DENY", decision.reason_codes)
        self.assertIsNone(decision.score)
        self.assertEqual((), result.selected_action_ids)

    def test_require_human_and_risk_constraints_fail_closed(self):
        require_human = select_actions(
            project_id="project-1", situation_id="situation-1", situation_version=1,
            planning_run_id="plan-1", planner_input_hash="sha256:planner",
            selection_version=1, expected_selection_version=0,
            candidates=(candidate(policy="REQUIRE_HUMAN", acct=account()),),
        ).candidate_decisions[0]
        self.assertIn("POLICY_REQUIRE_HUMAN", require_human.reason_codes)
        high_risk = select_actions(
            project_id="project-1", situation_id="situation-1", situation_version=1,
            planning_run_id="plan-1", planner_input_hash="sha256:planner",
            selection_version=1, expected_selection_version=0,
            candidates=(candidate(risk_level="HIGH", residual=7000, acct=account()),),
        ).candidate_decisions[0]
        self.assertIn("POLICY_RISK_CONSTRAINT_UNSATISFIED", high_risk.reason_codes)

    def test_unverified_mitigation_and_unknown_constraint_filter(self):
        unverified = candidate(
            acct=account(), mitigations=("verification_before_apply",), available=()
        )
        result = select_actions(
            project_id="project-1", situation_id="situation-1", situation_version=1,
            planning_run_id="plan-1", planner_input_hash="sha256:planner",
            selection_version=1, expected_selection_version=0,
            candidates=(unverified,),
        ).candidate_decisions[0]
        self.assertIn("REQUIRED_MITIGATION_UNVERIFIED", result.reason_codes)
        unknown = candidate(acct=account())
        object.__setattr__(unknown, "policy_constraints", {"magic": True})
        result = select_actions(
            project_id="project-1", situation_id="situation-1", situation_version=1,
            planning_run_id="plan-1", planner_input_hash="sha256:planner",
            selection_version=1, expected_selection_version=0,
            candidates=(unknown,),
        ).candidate_decisions[0]
        self.assertIn("POLICY_CONSTRAINT_UNSUPPORTED", result.reason_codes)

    def test_budget_and_zero_resource(self):
        infeasible = select_actions(
            project_id="project-1", situation_id="situation-1", situation_version=1,
            planning_run_id="plan-1", planner_input_hash="sha256:planner",
            selection_version=1, expected_selection_version=0,
            candidates=(candidate(acct=account(limit=1, reserved=1)),),
        ).candidate_decisions[0]
        self.assertIn("BUDGET_INFEASIBLE", infeasible.reason_codes)
        zero = select_actions(
            project_id="project-1", situation_id="situation-1", situation_version=1,
            planning_run_id="plan-1", planner_input_hash="sha256:planner",
            selection_version=1, expected_selection_version=0,
            candidates=(candidate(resources={"amounts": {"agent_runs": 0}, "currency": None}, acct=None),),
        ).candidate_decisions[0]
        self.assertEqual(Disposition.SELECTED, zero.disposition)
        self.assertIn("SELECTED", zero.reason_codes)
        self.assertFalse(zero.reservation_required)

    def test_conflict_rules_allow_readonly_and_filter_mutable_target(self):
        read_a = candidate("read-a", acct=account())
        read_b = candidate("read-b", acct=account())
        result = select_actions(
            project_id="project-1", situation_id="situation-1", situation_version=1,
            planning_run_id="plan-1", planner_input_hash="sha256:planner",
            selection_version=1, expected_selection_version=0,
            candidates=(read_a, read_b),
        )
        self.assertEqual(("read-a", "read-b"), result.selected_action_ids)
        mut_a = candidate("mut-a", action_type="repair", params={"requires_verification_before_apply": True},
                          acct=account(), target_refs=("task-1",))
        mut_b = candidate("mut-b", action_type="repair", params={"requires_verification_before_apply": True},
                          acct=account(), target_refs=("task-1",))
        result = select_actions(
            project_id="project-1", situation_id="situation-1", situation_version=1,
            planning_run_id="plan-1", planner_input_hash="sha256:planner",
            selection_version=1, expected_selection_version=0,
            candidates=(mut_a, mut_b),
        )
        self.assertEqual(1, len(result.selected_action_ids))
        reasons = {d.action_id: d.reason_codes for d in result.candidate_decisions}
        loser = ({"mut-a", "mut-b"} - set(result.selected_action_ids)).pop()
        self.assertIn("ACTION_CONFLICT", reasons[loser])

    def test_no_eligible_action_is_explained(self):
        result = select_actions(
            project_id="project-1", situation_id="situation-1", situation_version=1,
            planning_run_id="plan-1", planner_input_hash="sha256:planner",
            selection_version=1, expected_selection_version=0,
            candidates=(candidate(policy="DENY", acct=account()),),
        )
        self.assertIn("NO_ELIGIBLE_ACTION", result.decision_reason_codes)


if __name__ == "__main__":
    unittest.main()
