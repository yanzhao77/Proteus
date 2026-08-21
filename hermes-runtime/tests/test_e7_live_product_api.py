import unittest

from hermes_runtime.application.product_api import ProductApiFacade
from hermes_runtime.domain.models import Actor, ActorType
from hermes_runtime.domain.product_api import ProductApiRequest, ProductApiRejected


class ExistingReadModel:
    def project_status(self, project_id, actor_scope): return {"project_id": project_id}
    def decision_explain(self, decision_id, actor_scope): return {"decision_id": decision_id}
    def human_gate_request(self, gate_request_id, actor_scope): return {"gate_request_id": gate_request_id}
    def replay_reconcile_findings(self, project_id, actor_scope): return {"project_id": project_id, "findings": []}
    def docker_process_observations(self, process_id, actor_scope): return {"process_id": process_id, "observations": []}


class Gateway:
    def submit_human_gate_decision(self, payload): return {"status": "REJECTED"}


class LiveReadModel:
    def __init__(self): self.calls = []
    def snapshot(self, project_id, actor_scope):
        self.calls.append(("snapshot", project_id, actor_scope))
        return {"availability": "CURRENT", "item": {"production_id": project_id}, "snapshot_watermark": 7}
    def events(self, project_id, actor_scope, after, limit):
        self.calls.append(("events", project_id, actor_scope, after, limit))
        return {"availability": "CURRENT", "items": [], "after": after, "next_cursor": after, "snapshot_watermark": 7}


class E7LiveProductApiTests(unittest.TestCase):
    def setUp(self):
        self.live = LiveReadModel()
        self.facade = ProductApiFacade(ExistingReadModel(), Gateway(), live_production_read_model=self.live)
        self.actor = Actor(ActorType.USER, "alice")

    def request(self, path, body=None, verified="alice", method="GET"):
        return ProductApiRequest(method, path, {}, body or {}, self.actor, verified_identity_subject=verified)

    def test_live_snapshot_and_feed_use_verified_creator_scope(self):
        snapshot = self.facade.handle(self.request("/factory-home/productions/project-1/live"))
        self.assertEqual(200, snapshot.status_code)
        self.assertEqual("project-1", snapshot.body["item"]["production_id"])
        feed = self.facade.handle(self.request("/factory-home/productions/project-1/live-feed", {"after": 5, "limit": 20}))
        self.assertEqual(200, feed.status_code)
        self.assertEqual(("snapshot", "project-1"), self.live.calls[0][:2])
        self.assertEqual(("events", "project-1", 5, 20), (self.live.calls[1][0], self.live.calls[1][1], self.live.calls[1][3], self.live.calls[1][4]))
        self.assertTrue(self.live.calls[1][2]["identity_verified"])
        self.assertEqual("alice", self.live.calls[1][2]["identity_subject"])

    def test_live_routes_are_read_only_and_no_generic_event_endpoint_is_opened(self):
        with self.assertRaises(ProductApiRejected):
            self.facade.handle(self.request("/factory-home/productions/project-1/live", method="POST"))
        with self.assertRaises(ProductApiRejected):
            self.facade.handle(self.request("/factory-home/productions/project-1/events"))


if __name__ == "__main__":
    unittest.main()
