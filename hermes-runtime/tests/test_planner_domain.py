import unittest

from hermes_runtime.domain.planner import (
    PLANNER_RULE_VERSION,
    REGISTRY,
    REGISTRY_VERSION,
    ActionType,
    EvidenceRequestRef,
    HypothesisRef,
    PlannerRejected,
    PlanningInput,
    diagnosis_requirement_for,
    generate_planning_run,
    registry_entry,
)


def diagnosis_input(status="UNKNOWN", root=None, requests=None, hypotheses=None):
    return PlanningInput(
        "project-1", "situation-1", 1, "verification_failed",
        "ctx-1", "sha256:context", "task-1", "FAILED", None, None,
        "diagnosis-1", "sha256:diagnosis-input", status, root,
        tuple(hypotheses or (
            HypothesisRef("hypothesis.unknown_verification_failure", 2500,
                          "run_deeper_test", 0),
        )),
        tuple(requests or (
            EvidenceRequestRef("collect_structured_finding",
                               "verification_check_result", "ctx-1",
                               "finding_unsupported", 0),
        )),
    )


class PlannerDomainTests(unittest.TestCase):
    def test_registry_version_and_action_order_are_fixed(self):
        self.assertEqual("action-registry/1.0", REGISTRY_VERSION)
        self.assertEqual("planner-rules/1.0", PLANNER_RULE_VERSION)
        enabled = [entry.action_type.value for entry in REGISTRY if entry.enabled]
        self.assertEqual([
            "run_deeper_test", "diagnose", "repair", "retry",
            "switch_strategy", "schedule_ready_task",
            "request_resource", "pause",
        ], enabled)

    def test_unknown_and_disabled_action_fail_closed(self):
        with self.assertRaisesRegex(PlannerRejected, "PLANNER_ACTION_TYPE_UNSUPPORTED"):
            registry_entry("human_gate")
        with self.assertRaisesRegex(PlannerRejected, "PLANNER_ACTION_TYPE_UNSUPPORTED"):
            registry_entry("shell_command")

    def test_registry_contains_no_authorization_decision(self):
        serialized = repr(REGISTRY)
        for forbidden in ("ALLOW", "DENY", "REQUIRE_HUMAN", "SELECTED", "QUEUED"):
            self.assertNotIn(forbidden, serialized)

    def test_unknown_diagnosis_generates_evidence_candidates_no_repair(self):
        result = generate_planning_run(diagnosis_input("UNKNOWN", None))
        action_types = [item.action_type for item in result.candidate_actions]
        self.assertIn(ActionType.RUN_DEEPER_TEST, action_types)
        self.assertIn(ActionType.DIAGNOSE, action_types)
        self.assertNotIn(ActionType.REPAIR, action_types)
        self.assertTrue(1 <= len(action_types) <= 5)

    def test_probable_can_include_conservative_repair_and_evidence_alternative(self):
        result = generate_planning_run(diagnosis_input(
            "PROBABLE", "test_assertion_failure"
        ))
        action_types = [item.action_type for item in result.candidate_actions]
        self.assertIn(ActionType.REPAIR, action_types)
        self.assertIn(ActionType.RUN_DEEPER_TEST, action_types)

    def test_confirmed_uses_mapped_repair_retry_and_switch_strategy(self):
        result = generate_planning_run(diagnosis_input(
            "CONFIRMED", "test_assertion_failure"
        ))
        action_types = [item.action_type for item in result.candidate_actions]
        self.assertIn(ActionType.REPAIR, action_types)
        self.assertIn(ActionType.RETRY, action_types)
        self.assertIn(ActionType.SWITCH_STRATEGY, action_types)

    def test_ready_task_generates_single_schedule_candidate(self):
        result = generate_planning_run(PlanningInput(
            "project-1", "situation-1", 1, "work_available",
            "ctx-1", "sha256:context", "task-1", "READY",
            "work_graph:7", None, None, None, None, None, (), (),
        ))
        self.assertEqual(1, len(result.candidate_actions))
        self.assertEqual(ActionType.SCHEDULE_READY_TASK,
                         result.candidate_actions[0].action_type)
        self.assertEqual("ONLY_ONE_REGISTRY_CANDIDATE_VALID",
                         result.single_candidate_reason_code)

    def test_not_ready_target_is_stale(self):
        with self.assertRaisesRegex(PlannerRejected, "PLANNER_TARGET_STALE"):
            generate_planning_run(PlanningInput(
                "project-1", "situation-1", 1, "work_available",
                "ctx-1", "sha256:context", "task-1", "RUNNING",
                "work_graph:7", None, None, None, None, None, (), (),
            ))

    def test_budget_hard_stop_only_request_resource_and_pause(self):
        result = generate_planning_run(PlanningInput(
            "project-1", "situation-1", 1, "budget_pressure",
            "ctx-1", "sha256:context", None, None, None, "HARD_STOP",
            None, None, None, None, (), (),
        ))
        self.assertEqual(
            {ActionType.REQUEST_RESOURCE, ActionType.PAUSE},
            {item.action_type for item in result.candidate_actions},
        )
        self.assertNotIn(ActionType.REPAIR,
                         [item.action_type for item in result.candidate_actions])

    def test_semantic_order_independence_and_stable_ids(self):
        requests = (
            EvidenceRequestRef("b", "kind", "target", "reason", 1),
            EvidenceRequestRef("a", "kind", "target", "reason", 0),
        )
        first = generate_planning_run(diagnosis_input(requests=requests))
        second = generate_planning_run(diagnosis_input(requests=tuple(reversed(requests))))
        self.assertEqual(first.planning_run_id, second.planning_run_id)
        self.assertEqual(
            [item.action_id for item in first.candidate_actions],
            [item.action_id for item in second.candidate_actions],
        )
        self.assertEqual(
            [item.content_hash for item in first.candidate_actions],
            [item.content_hash for item in second.candidate_actions],
        )

    def test_every_candidate_has_quality_fields_and_integer_resources(self):
        result = generate_planning_run(diagnosis_input("CONFIRMED", "build_failure"))
        hashes = set()
        for candidate in result.candidate_actions:
            self.assertTrue(candidate.reason_code)
            self.assertTrue(candidate.target_refs)
            self.assertTrue(candidate.required_capabilities)
            self.assertTrue(candidate.preconditions)
            self.assertTrue(candidate.expected_outputs)
            self.assertGreater(
                candidate.expected_progress_basis_points
                + candidate.evidence_gain_basis_points, 0,
            )
            hashes.add(candidate.content_hash)
            for amount in candidate.estimated_resources.amounts.values():
                self.assertIsInstance(amount, int)
                self.assertGreaterEqual(amount, 0)
        self.assertEqual(len(result.candidate_actions), len(hashes))

    def test_diagnosis_requirement_by_situation(self):
        self.assertEqual("REQUIRED", diagnosis_requirement_for("verification_failed").value)
        self.assertEqual("FORBIDDEN", diagnosis_requirement_for("work_available").value)
        self.assertEqual("OPTIONAL", diagnosis_requirement_for("budget_pressure").value)


if __name__ == "__main__":
    unittest.main()
