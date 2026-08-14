import unittest

from hermes_runtime.domain.replay_reconcile import (
    CheckpointSnapshot,
    ReplaySessionState,
    checkpoint_hash,
    classify_sequence,
    reconcile_plan_hash,
    transition_replay_state,
    validate_repair_actions,
    validate_schema_version,
)


class ReplayReconcileDomainTests(unittest.TestCase):
    def test_checkpoint_hash_is_canonical_and_detects_corruption(self):
        snapshot = CheckpointSnapshot(
            consumer_id="consumer",
            stream_name="hermes.runtime.events",
            partition_key="project-1",
            generation_id="generation-production",
            last_sequence=3,
            consumer_version="consumer/1",
            schema_version="1.0",
            projection_digest="sha256:projection",
        )
        self.assertEqual(checkpoint_hash(snapshot), checkpoint_hash(snapshot))
        changed = CheckpointSnapshot(
            **{**snapshot.__dict__, "last_sequence": 4}
        )
        self.assertNotEqual(checkpoint_hash(snapshot), checkpoint_hash(changed))

    def test_contiguous_gap_and_duplicate_classification(self):
        self.assertEqual("CONTIGUOUS", classify_sequence(7, 8))
        self.assertEqual("DUPLICATE_OR_LATE", classify_sequence(7, 7))
        self.assertEqual("EVENT_GAP_DETECTED", classify_sequence(7, 9))

    def test_schema_compatibility_fails_closed_for_unknown_major(self):
        self.assertEqual("SUPPORTED", validate_schema_version("1.9"))
        self.assertEqual("EVENT_SCHEMA_UNSUPPORTED", validate_schema_version("2.0"))

    def test_replay_state_machine_rejects_invalid_transition(self):
        self.assertEqual(
            ReplaySessionState.VALIDATED,
            transition_replay_state(ReplaySessionState.REQUESTED, ReplaySessionState.VALIDATED),
        )
        with self.assertRaises(ValueError):
            transition_replay_state(ReplaySessionState.REQUESTED, ReplaySessionState.ACTIVATED)

    def test_repair_whitelist_rejects_generic_sql_patch(self):
        self.assertEqual(
            ("ADVANCE_CHECKPOINT_IF_EFFECT_CONTIGUOUS",),
            tuple(action.value for action in validate_repair_actions(("ADVANCE_CHECKPOINT_IF_EFFECT_CONTIGUOUS",))),
        )
        with self.assertRaises(ValueError):
            validate_repair_actions(("UPDATE tasks SET status='PASSED'",))

    def test_plan_hash_binds_findings_versions_actions_and_dry_run(self):
        first = reconcile_plan_hash(
            ("finding-b", "finding-a"),
            {"finding-a": 1, "finding-b": 2},
            ("ADVANCE_CHECKPOINT_IF_EFFECT_CONTIGUOUS",),
            True,
        )
        second = reconcile_plan_hash(
            ("finding-a", "finding-b"),
            {"finding-b": 2, "finding-a": 1},
            ("ADVANCE_CHECKPOINT_IF_EFFECT_CONTIGUOUS",),
            True,
        )
        changed = reconcile_plan_hash(
            ("finding-a", "finding-b"),
            {"finding-b": 2, "finding-a": 1},
            ("MARK_UNSUPPORTED_SCHEMA_BLOCKED",),
            True,
        )
        self.assertEqual(first, second)
        self.assertNotEqual(first, changed)


if __name__ == "__main__":
    unittest.main()
