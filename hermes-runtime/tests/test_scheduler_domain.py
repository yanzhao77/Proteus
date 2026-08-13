import unittest

from hermes_runtime.domain.execution import LockIntent
from hermes_runtime.domain.scheduler import (
    LeaseProfile,
    SchedulerIdentity,
    SchedulerRejected,
    canonical_lock_scopes,
    hash_command_payload,
    next_fencing_token,
    stable_queue_sort_key,
    token_is_stale,
    validate_lease_profile,
    validate_scheduler_identity,
)


class SchedulerDomainTests(unittest.TestCase):
    def test_lease_profile_has_bounded_integer_milliseconds(self):
        profile = LeaseProfile(
            profile_id="p2-default",
            profile_version=1,
            initial_ttl_ms=30000,
            renew_interval_ms=10000,
            max_extension_ms=30000,
            max_lifetime_ms=300000,
            takeover_after_expiry_ms=0,
            requeue_backoff_ms=0,
        )
        normalized = validate_lease_profile(profile)
        self.assertEqual("lease-profile/1.0", normalized["schema_version"])
        self.assertEqual(30000, normalized["initial_ttl_ms"])
        with self.assertRaisesRegex(SchedulerRejected, "LEASE_PROFILE_INVALID"):
            validate_lease_profile(LeaseProfile("bad", 1, 0, 1, 1, 1, 0, 0))
        with self.assertRaisesRegex(SchedulerRejected, "LEASE_PROFILE_INVALID"):
            validate_lease_profile(LeaseProfile("bad", 1, 100, 200, 100, 100, 0, 0))
        with self.assertRaisesRegex(SchedulerRejected, "LEASE_PROFILE_INVALID"):
            validate_lease_profile(LeaseProfile("bad", 1, 100, 100, 100, 99, 0, 0))

    def test_scheduler_identity_is_not_unbounded_free_text(self):
        identity = validate_scheduler_identity(
            SchedulerIdentity("sched-1", "session-1", actor_id="sched-1")
        )
        self.assertEqual("scheduler", identity["actor_type"])
        with self.assertRaisesRegex(SchedulerRejected, "SCHEDULER_NOT_ADMITTED"):
            validate_scheduler_identity(
                SchedulerIdentity("sched-*", "session-1", actor_id="sched-1")
            )
        with self.assertRaisesRegex(SchedulerRejected, "SCHEDULER_NOT_ADMITTED"):
            validate_scheduler_identity(
                SchedulerIdentity("sched-1", "session-1", actor_type="worker", actor_id="w")
            )

    def test_queue_sort_is_priority_available_enqueued_stable_id(self):
        items = [
            {"queue_item_id": "q2", "priority": 5, "available_at": "2", "enqueued_at": "1"},
            {"queue_item_id": "q1", "priority": 10, "available_at": "2", "enqueued_at": "1"},
            {"queue_item_id": "q3", "priority": 10, "available_at": "1", "enqueued_at": "1"},
        ]
        ordered = sorted(items, key=stable_queue_sort_key)
        self.assertEqual(["q3", "q1", "q2"], [item["queue_item_id"] for item in ordered])

    def test_token_comparison_and_overflow_fail_closed(self):
        self.assertTrue(token_is_stale(1, 2))
        self.assertFalse(token_is_stale(2, 2))
        self.assertEqual(3, next_fencing_token(2))
        with self.assertRaisesRegex(SchedulerRejected, "FENCING_TOKEN_OVERFLOW"):
            next_fencing_token(9223372036854775807)

    def test_lock_scope_order_reuses_p2_vocabulary(self):
        scopes = canonical_lock_scopes((
            LockIntent("workspace:Project-1:Default"),
            LockIntent("repository:Repo-Main"),
            LockIntent("repository:Repo-Main"),
        ))
        self.assertEqual(("repository:repo-main", "workspace:project-1:default"), scopes)

    def test_scheduler_payload_hash_is_canonical(self):
        left = hash_command_payload({"b": 2, "a": 1})
        right = hash_command_payload({"a": 1, "b": 2})
        self.assertEqual(left, right)
        self.assertTrue(left.startswith("sha256:"))


if __name__ == "__main__":
    unittest.main()
