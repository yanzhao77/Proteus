import unittest

from hermes_runtime.domain.human_gate import (
    AuthorizationAssertion,
    GateDecisionKind,
    HumanGateRejected,
    ResumeContext,
    aggregate_gate_decisions,
    hash_payload,
    validate_approver,
    validate_requester,
)
from hermes_runtime.domain.models import Actor, ActorType, ProjectState


class HumanGateDomainTests(unittest.TestCase):
    def test_resume_context_hash_is_canonical(self):
        requester = Actor(ActorType.MAIN_HERMES, "main")
        left = ResumeContext(
            context_id="ctx-1",
            project_id="project-1",
            before_state=ProjectState.IMPLEMENTING,
            project_version=7,
            original_command_type="execution.admit",
            requester=requester,
            gate_request_id="gate-1",
            policy_decision_id="policy-1",
            evidence_refs=("e2", "e1"),
            supporting_refs=("s2", "s1"),
            expected_task_versions={"task-b": 2, "task-a": 1},
        )
        right = ResumeContext(
            context_id="ctx-1",
            project_id="project-1",
            before_state=ProjectState.IMPLEMENTING,
            project_version=7,
            original_command_type="execution.admit",
            requester=requester,
            gate_request_id="gate-1",
            policy_decision_id="policy-1",
            evidence_refs=("e1", "e2"),
            supporting_refs=("s1", "s2"),
            expected_task_versions={"task-a": 1, "task-b": 2},
        )

        self.assertEqual(left.context_hash, right.context_hash)
        self.assertTrue(left.context_hash.startswith("sha256:"))

    def test_hash_payload_is_stable_and_sensitive_to_content(self):
        self.assertEqual(hash_payload({"a": 1, "b": 2}), hash_payload({"b": 2, "a": 1}))
        self.assertNotEqual(hash_payload({"a": 1}), hash_payload({"a": 2}))

    def test_requester_boundary_only_allows_main_control_or_recovery(self):
        for actor_type in (
            ActorType.MAIN_HERMES,
            ActorType.CONTROL_PLANE,
            ActorType.RECOVERY_CONTROLLER,
        ):
            validate_requester(Actor(actor_type, actor_type.value))
        for actor_type in (
            ActorType.WORKER,
            ActorType.SCHEDULER,
            ActorType.VERIFIER,
            ActorType.ACTION_PLANNER,
        ):
            with self.subTest(actor_type=actor_type):
                with self.assertRaisesRegex(HumanGateRejected, "GATE_REQUESTER_UNAUTHORIZED"):
                    validate_requester(Actor(actor_type, actor_type.value))

    def test_authorized_human_approver_is_scope_bound(self):
        requester = Actor(ActorType.MAIN_HERMES, "main")
        approver = Actor(ActorType.USER, "user-1")
        assertion = AuthorizationAssertion(
            assertion_id="assert-1",
            issuer="test-only",
            subject="user-1",
            role="approver",
            project_id="project-1",
            task_id=None,
            gate_request_id="gate-1",
            action_scope="project:resume",
            valid_from="2026-01-01T00:00:00Z",
            valid_until="2099-01-01T00:00:00Z",
            assertion_hash="sha256:assertion",
        )

        validate_approver(
            requester,
            approver,
            assertion,
            "project-1",
            None,
            "gate-1",
            "project:resume",
        )
        with self.assertRaisesRegex(HumanGateRejected, "GATE_SCOPE_MISMATCH"):
            validate_approver(
                requester,
                approver,
                assertion,
                "project-2",
                None,
                "gate-1",
                "project:resume",
            )

    def test_self_approval_and_non_human_approval_fail_closed(self):
        requester = Actor(ActorType.USER, "user-1")
        assertion = AuthorizationAssertion(
            assertion_id="assert-1",
            issuer="test-only",
            subject="user-1",
            role="approver",
            project_id="project-1",
            task_id=None,
            gate_request_id="gate-1",
            action_scope="project:resume",
            valid_from="2026-01-01T00:00:00Z",
            valid_until="2099-01-01T00:00:00Z",
            assertion_hash="sha256:assertion",
        )
        with self.assertRaisesRegex(HumanGateRejected, "GATE_SELF_APPROVAL_FORBIDDEN"):
            validate_approver(
                requester,
                requester,
                assertion,
                "project-1",
                None,
                "gate-1",
                "project:resume",
            )
        with self.assertRaisesRegex(HumanGateRejected, "GATE_APPROVER_UNAUTHORIZED"):
            validate_approver(
                Actor(ActorType.MAIN_HERMES, "main"),
                Actor(ActorType.WORKER, "worker-1"),
                assertion,
                "project-1",
                None,
                "gate-1",
                "project:resume",
            )

    def test_gate_aggregation_is_all_required_and_reject_wins(self):
        self.assertEqual(
            "APPROVED",
            aggregate_gate_decisions((GateDecisionKind.APPROVE,), required_count=1),
        )
        self.assertEqual(
            "INCOMPLETE",
            aggregate_gate_decisions((GateDecisionKind.APPROVE,), required_count=2),
        )
        self.assertEqual(
            "REJECTED",
            aggregate_gate_decisions(
                (GateDecisionKind.APPROVE, GateDecisionKind.REJECT),
                required_count=2,
            ),
        )
        with self.assertRaisesRegex(HumanGateRejected, "GATE_RESUME_GUARD_FAILED"):
            aggregate_gate_decisions((GateDecisionKind.APPROVE,), required_count=0)


if __name__ == "__main__":
    unittest.main()
