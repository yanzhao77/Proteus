import unittest

from hermes_runtime.application.human_gate_product import HumanGateProductFacade, ProductGateDecisionRequest
from hermes_runtime.domain.human_gate import GateDecisionKind, HumanGateRejected
from hermes_runtime.domain.identity import IdentityAssertionInput
from hermes_runtime.domain.models import Actor, ActorType
from hermes_runtime.infrastructure.local_identity import LocalIdentityAssertionProvider


class FakePresentationStore:
    def get_gate_request(self, gate_request_id):
        return {"gate_request_id": gate_request_id, "safe_payload": {"question": "Approve deploy?"}}

    def list_gate_requests(self, project_id, actor):
        return ({"project_id": project_id, "gate_request_id": "gate-1", "safe_payload": {}},)


class FakeDecisionSink:
    def __init__(self):
        self.commands = []

    def submit_decision(self, command):
        self.commands.append(command)
        return {"status": "RECORDED", "gate_decision_id": command.gate_decision_id}


class FakeEvidenceQuery:
    def __init__(self, invalid=()):
        self.invalid = tuple(invalid)

    def invalid_evidence_refs(self, project_id, evidence_refs):
        return tuple(ref for ref in evidence_refs if ref in self.invalid)


class HumanGateProductBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.requester = Actor(ActorType.MAIN_HERMES, "main")
        self.approver = Actor(ActorType.USER, "user-1")
        self.provider = LocalIdentityAssertionProvider()
        self.assertion = self.provider.issue(
            "assert-1",
            IdentityAssertionInput(
                issuer="local-test",
                subject="user-1",
                role="approver",
                project_id="project-1",
                task_id=None,
                gate_request_id="gate-1",
                action_scope="project:resume",
                valid_from="2026-01-01T00:00:00Z",
                valid_until="2099-01-01T00:00:00Z",
            ),
        )
        self.sink = FakeDecisionSink()
        self.facade = HumanGateProductFacade(FakePresentationStore(), self.sink, FakeEvidenceQuery())

    def _request(self, **overrides):
        values = dict(
            command_id="cmd-1",
            idempotency_key="idem-1",
            project_id="project-1",
            gate_decision_id="decision-1",
            gate_request_id="gate-1",
            decision=GateDecisionKind.APPROVE,
            requester=self.requester,
            approver=self.approver,
            authorization_ref="authz-1",
            assertion=self.assertion,
            expected_gate_version=3,
            current_gate_version=3,
            action_scope="project:resume",
            reason="approve guarded resume",
            now="2026-08-14T00:00:00Z",
            evidence_refs=("evidence-1",),
        )
        values.update(overrides)
        return ProductGateDecisionRequest(**values)

    def test_present_and_submit_decision_without_resume_authority(self):
        self.assertEqual("gate-1", self.facade.present_request("gate-1")["gate_request_id"])
        result = self.facade.submit_decision(self._request())
        self.assertEqual("RECORDED", result["status"])
        self.assertEqual("decision-1", self.sink.commands[0].gate_decision_id)
        with self.assertRaisesRegex(HumanGateRejected, "GATE_PRODUCT_FACADE_CANNOT_RESUME_PROJECT"):
            self.facade.apply_resume()

    def test_unauthorized_self_and_expired_approvals_fail_closed(self):
        bad_actor = Actor(ActorType.WORKER, "worker-1")
        with self.assertRaisesRegex(HumanGateRejected, "GATE_APPROVER_UNAUTHORIZED"):
            self.facade.submit_decision(self._request(approver=bad_actor))

        self_actor_assertion = self.provider.issue(
            "assert-self",
            IdentityAssertionInput(
                issuer="local-test",
                subject="main",
                role="approver",
                project_id="project-1",
                task_id=None,
                gate_request_id="gate-1",
                action_scope="project:resume",
                valid_from="2026-01-01T00:00:00Z",
                valid_until="2099-01-01T00:00:00Z",
            ),
        )
        with self.assertRaisesRegex(HumanGateRejected, "GATE_SELF_APPROVAL_FORBIDDEN"):
            self.facade.submit_decision(
                self._request(
                    requester=Actor(ActorType.USER, "main"),
                    approver=Actor(ActorType.USER, "main"),
                    assertion=self_actor_assertion,
                )
            )

        with self.assertRaisesRegex(HumanGateRejected, "GATE_ASSERTION_EXPIRED"):
            self.facade.submit_decision(self._request(now="2100-01-01T00:00:00Z"))

    def test_stale_gate_version_and_invalid_evidence_fail_closed(self):
        with self.assertRaisesRegex(HumanGateRejected, "GATE_VERSION_CONFLICT"):
            self.facade.submit_decision(self._request(expected_gate_version=2))

        facade = HumanGateProductFacade(FakePresentationStore(), self.sink, FakeEvidenceQuery(invalid=("evidence-1",)))
        with self.assertRaisesRegex(HumanGateRejected, "GATE_EVIDENCE_INVALID"):
            facade.submit_decision(self._request())


if __name__ == "__main__":
    unittest.main()
