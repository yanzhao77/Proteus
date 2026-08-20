import unittest

from hermes_runtime.application.product_api import ProductApiFacade
from hermes_runtime.domain.models import Actor, ActorType
from hermes_runtime.domain.product_api import ProductApiRejected, ProductApiRequest


class ReadModel:
    def project_status(self, *_): return {}
    def decision_explain(self, *_): return {}
    def human_gate_request(self, *_): return {}
    def replay_reconcile_findings(self, *_): return {}
    def docker_process_observations(self, *_): return {}


class Gateway:
    def submit_human_gate_decision(self, payload): return payload


class E3Api:
    def __init__(self): self.calls = []
    def generate_proposal(self, *args): self.calls.append(("proposal", args)); return {"proposal_id": "ep-1", "version": 1, "pre_approval_only": True}
    def get_proposal(self, *args): return {"availability": "NOT_AVAILABLE", "item": None}
    def list_proposal_revisions(self, *args): return {"availability": "NOT_AVAILABLE", "items": []}
    def generate_master_plan(self, *args): self.calls.append(("plan", args)); return {"master_plan_id": "emp-1", "version": 1, "pre_approval_only": True}
    def get_master_plan(self, *args): return {"availability": "NOT_AVAILABLE", "item": None}
    def list_master_plan_revisions(self, *args): return {"availability": "NOT_AVAILABLE", "items": []}


def request(path, body, *, actor="creator-1"):
    return ProductApiRequest(
        method="POST", path=path, headers={}, body=body,
        actor=Actor(ActorType.USER, actor), verified_identity_subject="creator-1",
    )


def facade(e3):
    return ProductApiFacade(ReadModel(), Gateway(), entry_proposal_master_plan_api=e3)


class E3ProductApiTests(unittest.TestCase):
    def test_generate_proposal_uses_verified_subject_and_exact_metadata(self):
        e3 = E3Api()
        response = facade(e3).handle(request("/production-drafts/ed-1/proposal", {"reason": "review", "idempotency_key": "key-1", "expected_version": 0}))
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.body["item"]["pre_approval_only"])
        self.assertEqual(e3.calls, [("proposal", ("creator-1", "ed-1", 0, "key-1", "review"))])

    def test_generate_master_plan_has_exact_allowlist_and_no_approve_route(self):
        e3 = E3Api()
        response = facade(e3).handle(request("/production-drafts/ed-1/proposal/master-plan", {"reason": "review", "idempotency_key": "key-2", "expected_version": 0}))
        self.assertEqual(response.status_code, 201)
        self.assertEqual(e3.calls[0][0], "plan")
        with self.assertRaisesRegex(ProductApiRejected, "ENTRY_PLAN_SCHEMA_INVALID"):
            facade(e3).handle(request("/production-drafts/ed-1/proposal/master-plan", {"reason": "review", "idempotency_key": "key-2", "expected_version": 0, "approve": True}))
        with self.assertRaisesRegex(ProductApiRejected, "UNSUPPORTED_ROUTE"):
            facade(e3).handle(request("/production-drafts/ed-1/proposal/approve", {"reason": "review", "idempotency_key": "key-3", "expected_version": 0}))

    def test_browser_actor_cannot_override_verified_subject(self):
        e3 = E3Api()
        with self.assertRaisesRegex(ProductApiRejected, "ENTRY_DRAFT_IDENTITY_REQUIRED"):
            facade(e3).handle(request("/production-drafts/ed-1/proposal", {"reason": "review", "idempotency_key": "key-1", "expected_version": 0}, actor="foreign"))
