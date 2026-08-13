import unittest

from hermes_runtime.domain.situation import (
    CANONICALIZATION_VERSION,
    RULE_SET_VERSION,
    Severity,
    SituationRejected,
    SituationType,
    TriggerFact,
    canonical_fingerprint,
    classify_trigger,
    context_hash,
)


class SituationDomainTests(unittest.TestCase):
    def fact(self, event_type, payload, task_id="task-1", project_id="project-1"):
        return TriggerFact(project_id, event_type, "1.0", task_id, payload)

    def test_verification_fail_is_classified_without_diagnosing_root_cause(self):
        result = classify_trigger(self.fact("verification.recorded", {
            "verdict": "FAIL", "finding_codes": ["TEST_FAILED"],
            "evidence_refs": ["evidence-1"],
        }))
        self.assertEqual(SituationType.VERIFICATION_FAILED, result.situation_type)
        self.assertEqual("unknown_verification_failure", result.failure_type)
        self.assertEqual(Severity.HIGH, result.severity)
        self.assertNotIn("root_cause", vars(result))

    def test_non_fail_verification_and_non_trigger_are_ignored(self):
        self.assertIsNone(classify_trigger(self.fact(
            "verification.recorded", {"verdict": "PASS"}
        )))
        self.assertIsNone(classify_trigger(self.fact(
            "metric.sample", {"value": 1}
        )))

    def test_ready_and_budget_threshold_rules_are_deterministic(self):
        ready = classify_trigger(self.fact("task.readiness_recomputed", {
            "ready_state_changes": [{"task_id": "task-1", "to_state": "READY"}]
        }))
        self.assertEqual(SituationType.WORK_AVAILABLE, ready.situation_type)
        for threshold, severity in (
            ("WARN", Severity.MEDIUM), ("GATE", Severity.HIGH),
            ("HARD_STOP", Severity.CRITICAL),
        ):
            with self.subTest(threshold=threshold):
                result = classify_trigger(self.fact("budget.reserved", {
                    "threshold_status": threshold, "account_id": "account-1",
                    "entity_version": 3,
                }))
                self.assertEqual(SituationType.BUDGET_PRESSURE, result.situation_type)
                self.assertEqual(severity, result.severity)
                self.assertEqual(10000, result.confidence_basis_points)

    def test_version_conflict_requires_structured_authority_reason(self):
        result = classify_trigger(self.fact("command.version_conflict", {
            "reason_code": "VERSION_CONFLICT", "entity_ref": "task:task-1",
            "expected_version": 2, "observed_version": 3,
        }))
        self.assertEqual(SituationType.STATE_CONFLICT, result.situation_type)
        with self.assertRaisesRegex(
            SituationRejected, "SITUATION_CLASSIFICATION_UNSUPPORTED"
        ):
            classify_trigger(self.fact("command.version_conflict", {
                "reason_code": "arbitrary"
            }))

    def test_unimplemented_policy_and_stall_rules_fail_closed(self):
        for event_type in ("policy.evaluated", "agent.stalled", "resource.missing"):
            with self.subTest(event_type=event_type):
                with self.assertRaisesRegex(
                    SituationRejected, "SITUATION_CLASSIFICATION_UNSUPPORTED"
                ):
                    classify_trigger(self.fact(event_type, {}))

    def test_unknown_major_schema_fails_closed(self):
        with self.assertRaisesRegex(
            SituationRejected, "SITUATION_TRIGGER_SCHEMA_INVALID"
        ):
            classify_trigger(TriggerFact(
                "project-1", "verification.recorded", "2.0", "task-1",
                {"verdict": "FAIL"},
            ))

    def test_fingerprint_is_semantic_order_independent_and_project_scoped(self):
        first = classify_trigger(self.fact("feedback.created", {
            "failure_type": "integration_failure",
            "affected_components": ["database", "api", "api"],
            "evidence_refs": ["evidence-2", "evidence-1"],
        }))
        second = classify_trigger(self.fact("feedback.created", {
            "failure_type": "integration_failure",
            "affected_components": ["api", "database"],
            "evidence_refs": ["evidence-1", "evidence-2"],
            "event_id": "ignored", "occurred_at": "ignored",
        }))
        self.assertEqual(
            canonical_fingerprint("project-1", first, "task-1"),
            canonical_fingerprint("project-1", second, "task-1"),
        )
        self.assertNotEqual(
            canonical_fingerprint("project-1", first, "task-1"),
            canonical_fingerprint("project-2", first, "task-1"),
        )
        self.assertNotEqual(
            canonical_fingerprint("project-1", first, "task-1"),
            canonical_fingerprint("project-1", first, "task-2"),
        )
        changed = classify_trigger(self.fact("feedback.created", {
            "failure_type": "compile_failure", "affected_components": ["api"]
        }))
        self.assertNotEqual(
            canonical_fingerprint("project-1", first, "task-1"),
            canonical_fingerprint("project-1", changed, "task-1"),
        )
        self.assertEqual("situation-fingerprint/1.0", CANONICALIZATION_VERSION)

    def test_context_hash_ignores_mapping_order_but_not_rule_version(self):
        first = {"project_id": "project-1", "refs": ["a", "b"],
                 "rule_set_version": RULE_SET_VERSION}
        second = {"rule_set_version": RULE_SET_VERSION, "refs": ["a", "b"],
                  "project_id": "project-1"}
        self.assertEqual(context_hash(first), context_hash(second))
        self.assertNotEqual(
            context_hash(first),
            context_hash(dict(first, rule_set_version="situation-rules/2.0")),
        )


if __name__ == "__main__":
    unittest.main()
