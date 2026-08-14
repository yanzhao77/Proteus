import unittest

from hermes_runtime.domain.quarantine import (
    QuarantineOperation,
    QuarantineReviewContext,
    QuarantineState,
    assert_reviewer_actor,
    canonical_payload_hash,
    immutable_origin_fields,
    transition_quarantine_state,
    validate_adoption_command,
    validate_redrive_identity,
)


class QuarantineDomainTests(unittest.TestCase):
    def test_review_discard_adoption_redrive_and_expiry_transitions_are_explicit(self):
        self.assertEqual(
            QuarantineState.UNDER_REVIEW,
            transition_quarantine_state(
                QuarantineReviewContext("q1", QuarantineState.QUARANTINED, 0),
                QuarantineOperation.START_REVIEW,
            ),
        )
        self.assertEqual(
            QuarantineState.DISCARDED,
            transition_quarantine_state(
                QuarantineReviewContext("q1", QuarantineState.UNDER_REVIEW, 1),
                QuarantineOperation.DISCARD,
            ),
        )
        self.assertEqual(
            QuarantineState.ADOPTION_REQUESTED,
            transition_quarantine_state(
                QuarantineReviewContext("q2", QuarantineState.UNDER_REVIEW, 1),
                QuarantineOperation.REQUEST_ADOPTION,
            ),
        )
        self.assertEqual(
            QuarantineState.ADOPTED,
            transition_quarantine_state(
                QuarantineReviewContext("q2", QuarantineState.ADOPTION_REQUESTED, 2),
                QuarantineOperation.MARK_ADOPTED,
            ),
        )
        self.assertEqual(
            QuarantineState.REDRIVE_REQUESTED,
            transition_quarantine_state(
                QuarantineReviewContext("q3", QuarantineState.UNDER_REVIEW, 1),
                QuarantineOperation.REQUEST_REDRIVE,
            ),
        )
        self.assertEqual(
            QuarantineState.REDRIVEN,
            transition_quarantine_state(
                QuarantineReviewContext("q3", QuarantineState.REDRIVE_REQUESTED, 2),
                QuarantineOperation.MARK_REDRIVEN,
            ),
        )

    def test_terminal_or_expired_records_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "QUARANTINE_ALREADY_RESOLVED"):
            transition_quarantine_state(
                QuarantineReviewContext("q1", QuarantineState.DISCARDED, 2),
                QuarantineOperation.START_REVIEW,
            )
        with self.assertRaisesRegex(ValueError, "QUARANTINE_RETENTION_EXPIRED"):
            transition_quarantine_state(
                QuarantineReviewContext(
                    "q1", QuarantineState.UNDER_REVIEW, 1, retention_expired=True
                ),
                QuarantineOperation.REQUEST_REDRIVE,
            )

    def test_forbidden_actors_cannot_run_quarantine_operations(self):
        for actor_type in ("worker", "scheduler", "action_planner", "verifier"):
            with self.subTest(actor_type=actor_type):
                with self.assertRaisesRegex(ValueError, "QUARANTINE_REVIEW_UNAUTHORIZED"):
                    assert_reviewer_actor(actor_type)
        assert_reviewer_actor("system_operator")
        assert_reviewer_actor("control_plane")
        assert_reviewer_actor("recovery_controller")

    def test_adoption_is_guarded_semantic_command_not_pass_or_fail_patch(self):
        validate_adoption_command(
            semantic_command_type="execution.result.adopt",
            guarded_command_id="cmd-new",
            guarded_idempotency_key="idem-new",
        )
        with self.assertRaisesRegex(ValueError, "QUARANTINE_ADOPTION_GUARD_FAILED"):
            validate_adoption_command(
                semantic_command_type="task.pass",
                guarded_command_id="cmd-pass",
                guarded_idempotency_key="idem-pass",
                task_directive="PASSED",
            )

    def test_redrive_requires_new_command_and_idempotency_identity(self):
        validate_redrive_identity(
            original_command_id="cmd-old",
            original_idempotency_key="idem-old",
            redrive_command_id="cmd-new",
            redrive_idempotency_key="idem-new",
        )
        with self.assertRaisesRegex(ValueError, "QUARANTINE_REDRIVE_CONFLICT"):
            validate_redrive_identity(
                original_command_id="cmd-old",
                original_idempotency_key="idem-old",
                redrive_command_id="cmd-old",
                redrive_idempotency_key="idem-new",
            )
        with self.assertRaisesRegex(ValueError, "QUARANTINE_REDRIVE_CONFLICT"):
            validate_redrive_identity(
                original_command_id="cmd-old",
                original_idempotency_key="idem-old",
                redrive_command_id="cmd-new",
                redrive_idempotency_key="idem-old",
            )

    def test_hash_is_canonical_and_origin_fields_are_immutable(self):
        self.assertEqual(
            canonical_payload_hash({"b": 2, "a": 1}),
            canonical_payload_hash({"a": 1, "b": 2}),
        )
        self.assertIn("safe_payload_envelope", immutable_origin_fields())
        self.assertIn("submitted_fencing_token", immutable_origin_fields())


if __name__ == "__main__":
    unittest.main()
