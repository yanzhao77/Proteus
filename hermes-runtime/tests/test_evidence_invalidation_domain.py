import unittest

from hermes_runtime.domain.evidence_invalidation import (
    EvidenceInvalidationContext,
    EvidenceValidityState,
    assert_no_history_rewrite,
    canonical_payload_hash,
    invalidate_evidence_state,
    invalidated_evidence_blocks_use,
    propagation_action_for_scope,
    task_state_after_invalidation,
)


class EvidenceInvalidationDomainTests(unittest.TestCase):
    def test_invalidation_is_versioned_and_fails_closed_on_conflicts(self):
        current = EvidenceInvalidationContext("ev1", EvidenceValidityState.VALID, 0)
        invalidated = invalidate_evidence_state(current, expected_version=0)
        self.assertEqual(EvidenceValidityState.INVALIDATED, invalidated.state)
        self.assertEqual(1, invalidated.version)
        with self.assertRaisesRegex(ValueError, "EXPECTED_VERSION_CONFLICT"):
            invalidate_evidence_state(current, expected_version=1)
        with self.assertRaisesRegex(ValueError, "EVIDENCE_ALREADY_INVALIDATED"):
            invalidate_evidence_state(invalidated, expected_version=1)

    def test_invalidated_evidence_blocks_future_use(self):
        self.assertTrue(
            invalidated_evidence_blocks_use(
                ["ev1", "evidence:ev2"], ["evidence:ev2"]
            )
        )
        self.assertFalse(invalidated_evidence_blocks_use(["ev1"], ["ev2"]))

    def test_unknown_scope_requires_reverification_fail_closed(self):
        self.assertEqual(
            "REVERIFICATION_REQUIRED",
            propagation_action_for_scope("UNKNOWN", {}).value,
        )
        self.assertEqual(
            "GATE_EVIDENCE_INVALID",
            propagation_action_for_scope("gate", {"gate_decision_ids": ["d1"]}).value,
        )

    def test_evidence_and_verification_history_cannot_be_rewritten(self):
        for table_name in ("evidence", "verification_results"):
            with self.subTest(table_name=table_name):
                with self.assertRaisesRegex(ValueError, "EVIDENCE_HISTORY_IS_APPEND_ONLY"):
                    assert_no_history_rewrite(table_name, "UPDATE")
                with self.assertRaisesRegex(ValueError, "EVIDENCE_HISTORY_IS_APPEND_ONLY"):
                    assert_no_history_rewrite(table_name, "DELETE")

    def test_passed_task_is_not_flipped_to_failed_by_invalidation(self):
        self.assertEqual("REVERIFICATION_REQUIRED", task_state_after_invalidation("PASSED"))
        self.assertEqual("EVIDENCE_DEPENDENCY_STALE", task_state_after_invalidation("READY"))

    def test_payload_hash_is_canonical(self):
        self.assertEqual(
            canonical_payload_hash({"refs": ["b", "a"], "scope": "task"}),
            canonical_payload_hash({"scope": "task", "refs": ["b", "a"]}),
        )


if __name__ == "__main__":
    unittest.main()
