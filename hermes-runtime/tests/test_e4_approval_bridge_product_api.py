import unittest

from hermes_runtime.application.product_api import ProductApiFacade
from hermes_runtime.domain.models import Actor, ActorType
from hermes_runtime.domain.product_api import ProductApiRequest, ProductApiRejected


class _Read: pass
class _Gateway: pass
class _E4:
    def __init__(self): self.calls=[]
    def preview(self, subject, draft): self.calls.append(("preview",subject,draft)); return {"availability":"CURRENT","item":{"bridge_id":"b"}}
    def approve(self, subject, draft, payload): self.calls.append(("approve",subject,draft,payload)); return {"status":"PROCESSING","project_id":None}
    def get_approval(self, subject, draft): self.calls.append(("get",subject,draft)); return {"availability":"NOT_AVAILABLE","item":None}
    def reconcile(self, subject, draft, payload): self.calls.append(("reconcile",subject,draft,payload)); return {"status":"RECONCILIATION_REQUIRED"}


class E4ProductApiTests(unittest.TestCase):
    def request(self, method, path, body=None, subject="creator"):
        return ProductApiRequest(method, path, {}, body or {}, Actor(ActorType.USER, subject), subject)
    def facade(self):
        self.e4=_E4(); return ProductApiFacade(_Read(), _Gateway(), entry_approval_bridge_api=self.e4)
    def test_preview_uses_verified_creator_and_has_no_side_effect(self):
        result=self.facade().handle(self.request("GET","/production-drafts/draft/proposal/master-plan/approval-preview"))
        self.assertEqual(result.status_code,200); self.assertEqual(self.e4.calls,[("preview","creator","draft")])
    def test_approve_strict_payload_and_processing_only(self):
        body={"reason":"approve","idempotency_key":"k","expected_draft_version":1,"master_plan_id":"p","expected_plan_version":1,"plan_revision_id":"r","approved_plan_content_hash":"h","proposal_revision_id":"pr","proposal_content_hash":"ph","compiled_blueprint_hash":"bh","acknowledgements":[],"correlation_id":"c"}
        result=self.facade().handle(self.request("POST","/production-drafts/draft/proposal/master-plan/approve",body))
        self.assertEqual(result.status_code,202); self.assertIsNone(result.body["project_id"])
        with self.assertRaises(ProductApiRejected):
            self.facade().handle(self.request("POST","/production-drafts/draft/proposal/master-plan/approve",{**body,"project_id":"client"}))
    def test_actor_cannot_override_verified_subject(self):
        facade=self.facade()
        request=ProductApiRequest("GET","/production-drafts/draft/proposal/master-plan/approval-preview",{}, {}, Actor(ActorType.USER,"other"),"creator")
        with self.assertRaises(ProductApiRejected): facade.handle(request)
