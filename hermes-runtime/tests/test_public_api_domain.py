import unittest

from hermes_runtime.domain.models import Actor, ActorType
from hermes_runtime.domain.product_api import (
    ProductApiRejected,
    ProductApiRequest,
    canonical_payload_hash,
    ensure_safe_response,
    reject_forbidden_authority_shape,
    require_authority_command_metadata,
)


class PublicApiDomainTests(unittest.TestCase):
    def test_canonical_payload_hash_is_stable(self):
        self.assertEqual(
            canonical_payload_hash({"b": 2, "a": 1}),
            canonical_payload_hash({"a": 1, "b": 2}),
        )
        self.assertNotEqual(canonical_payload_hash({"a": 1}), canonical_payload_hash({"a": 2}))

    def test_authority_command_metadata_is_required(self):
        require_authority_command_metadata(
            {
                "command_id": "cmd-1",
                "idempotency_key": "idem-1",
                "expected_version": 3,
                "actor": {"type": "user", "id": "user-1"},
                "reason": "approve gate",
            }
        )
        with self.assertRaisesRegex(ProductApiRejected, "API_IDEMPOTENCY_KEY_MISSING"):
            require_authority_command_metadata(
                {
                    "command_id": "cmd-1",
                    "expected_version": 3,
                    "actor": {"type": "user", "id": "user-1"},
                    "reason": "approve gate",
                }
            )
        with self.assertRaisesRegex(ProductApiRejected, "API_EXPECTED_VERSION_INVALID"):
            require_authority_command_metadata(
                {
                    "command_id": "cmd-1",
                    "idempotency_key": "idem-1",
                    "expected_version": "3",
                    "actor": {"type": "user", "id": "user-1"},
                    "reason": "approve gate",
                }
            )

    def test_generic_patch_sql_event_and_status_mutations_fail_closed(self):
        actor = Actor(ActorType.USER, "user-1")
        cases = (
            ProductApiRequest("PATCH", "/projects/p1", {}, {}, actor),
            ProductApiRequest("POST", "/sql", {}, {"query": "select 1"}, actor),
            ProductApiRequest("POST", "/events", {}, {"event_type": "task.passed"}, actor),
            ProductApiRequest("POST", "/tasks/t1/status", {}, {"status": "PASSED"}, actor),
            ProductApiRequest("POST", "/projects/p1/transition", {}, {"project_state": "ACCEPTED"}, actor),
        )
        for request in cases:
            with self.subTest(request=request):
                with self.assertRaises(ProductApiRejected):
                    reject_forbidden_authority_shape(request)

    def test_unsafe_response_fields_and_secret_values_are_rejected(self):
        with self.assertRaisesRegex(ProductApiRejected, "API_UNSAFE_RESPONSE_FIELD"):
            ensure_safe_response({"task": {"mark_passed": True}})
        with self.assertRaisesRegex(ProductApiRejected, "API_SECRET_VALUE_FORBIDDEN"):
            ensure_safe_response({"secret_value": "plain-text"})


if __name__ == "__main__":
    unittest.main()
