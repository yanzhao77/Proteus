"""E7 Live Production projection evidence against disposable PostgreSQL."""
from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

try:
    import psycopg
except ImportError:  # pragma: no cover
    psycopg = None

from hermes_runtime.infrastructure.postgres_factory_home_read_model import PostgresCreatorActorProjectScope
from hermes_runtime.application.product_api import ProductApiFacade
from hermes_runtime.domain.models import Actor, ActorType
from hermes_runtime.domain.product_api import ProductApiRequest
from hermes_runtime.infrastructure.postgres_live_production_read_model import PostgresLiveProductionReadModel

try:
    from tests.test_e4_approval_bridge_postgres import E4ApprovalBridgePostgresDurabilityTests
except ModuleNotFoundError:  # repository-root unittest discovery
    from test_e4_approval_bridge_postgres import E4ApprovalBridgePostgresDurabilityTests

DATABASE_URL = os.getenv("HERMES_TEST_DATABASE_URL", "")
FORBIDDEN = ("fencing_token", "lease_token", "password", "secret", "authorization", "postgresql://", "database_url", "raw_input")


@unittest.skipUnless(psycopg is not None and DATABASE_URL, "requires HERMES_TEST_DATABASE_URL")
class E7LiveProductionPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        E4ApprovalBridgePostgresDurabilityTests.setUpClass()

    def setUp(self):
        self.seed = E4ApprovalBridgePostgresDurabilityTests(
            "test_01_receipt_commits_before_any_child_side_effect"
        )
        self.seed.setUp()
        result = self.seed._fresh_orchestrator().approve(
            self.seed.alice,
            self.seed.draft_id,
            self.seed._payload("e7-live-projection-materialization"),
        )
        self.assertEqual("MATERIALIZED", result["status"])
        self.project_id = result["project_id"]
        self.alice = {"identity_verified": True, "identity_subject": self.seed.alice, "actor_id": self.seed.alice, "actor_type": "user"}
        self.bob = {"identity_verified": True, "identity_subject": "e7-bob", "actor_id": "e7-bob", "actor_type": "user"}
        self.reader = PostgresLiveProductionReadModel(DATABASE_URL, PostgresCreatorActorProjectScope(DATABASE_URL))

    def test_snapshot_joins_e4_materialization_with_real_task_dag_and_verification(self):
        snapshot = self.reader.snapshot(self.project_id, self.alice)
        self.assertEqual("CURRENT", snapshot["availability"])
        self.assertEqual("e7-live-production-projection/1", snapshot["projection_schema_version"])
        item = snapshot["item"]
        self.assertEqual(self.project_id, item["production_id"])
        self.assertEqual(self.project_id, item["project"]["project_id"])
        self.assertTrue(item["materialization"]["bridge_id"])
        self.assertTrue(item["materialization"]["map"])
        self.assertGreaterEqual(len(item["workflow"]["nodes"]), 1)
        self.assertGreaterEqual(len(item["verification"]["plans"]), 1)
        for node in item["workflow"]["nodes"]:
            self.assertEqual(node["task_id"], node["source_identity"])
            self.assertIsInstance(node["version"], int)
            self.assertFalse(node["completion_claim"]["verified"])

    def test_snapshot_is_creator_scoped_and_project_id_probing_fails_closed(self):
        denied = self.reader.snapshot(self.project_id, self.bob)
        self.assertEqual("NOT_AVAILABLE", denied["availability"])
        self.assertIsNone(denied["item"])
        malformed_actor = {"identity_verified": True, "identity_subject": self.seed.alice, "actor_id": "other", "actor_type": "user"}
        self.assertEqual("NOT_AVAILABLE", self.reader.snapshot(self.project_id, malformed_actor)["availability"])

    def test_snapshot_and_event_feed_are_safe_and_read_only(self):
        snapshot = self.reader.snapshot(self.project_id, self.alice)
        encoded = json.dumps(snapshot, sort_keys=True).lower()
        for value in FORBIDDEN:
            self.assertNotIn(value, encoded)
        feed = self.reader.events(self.project_id, self.alice, after=0, limit=500)
        self.assertEqual("CURRENT", feed["availability"])
        self.assertTrue(feed["bounded"])
        self.assertLessEqual(len(feed["items"]), 100)
        for event in feed["items"]:
            self.assertEqual(self.project_id, event["production_id"])
            self.assertIn("event_id", event)
            self.assertIn("production_sequence", event)
            self.assertIn("snapshot_watermark", event)
            self.assertNotIn("payload", event)
        source = Path(__file__).parents[1] / "src/hermes_runtime/infrastructure/postgres_live_production_read_model.py"
        read_source = source.read_text()
        for verb in ("INSERT INTO", "UPDATE public.", "DELETE FROM"):
            self.assertNotIn(verb, read_source)

    def test_product_api_safe_response_accepts_real_projection_without_secret_fields(self):
        class Read:
            def project_status(self, project_id, actor_scope): return {"project_id": project_id}
            def decision_explain(self, decision_id, actor_scope): return {"decision_id": decision_id}
            def human_gate_request(self, gate_request_id, actor_scope): return {"gate_request_id": gate_request_id}
            def replay_reconcile_findings(self, project_id, actor_scope): return {"project_id": project_id, "findings": []}
            def docker_process_observations(self, process_id, actor_scope): return {"process_id": process_id, "observations": []}
        class Gateway:
            def submit_human_gate_decision(self, payload): return {"status": "REJECTED"}
        facade = ProductApiFacade(Read(), Gateway(), live_production_read_model=self.reader)
        response = facade.handle(ProductApiRequest("GET", f"/factory-home/productions/{self.project_id}/live", {}, {}, Actor(ActorType.USER, self.seed.alice), verified_identity_subject=self.seed.alice))
        self.assertEqual(200, response.status_code)
        encoded = json.dumps(response.body, sort_keys=True).lower()
        for value in FORBIDDEN:
            self.assertNotIn(value, encoded)

    def test_cursor_ahead_is_stale_and_does_not_return_new_authority_fact(self):
        initial = self.reader.events(self.project_id, self.alice, after=0, limit=25)
        ahead = self.reader.events(self.project_id, self.alice, after=initial["snapshot_watermark"] + 1, limit=25)
        self.assertEqual("STALE", ahead["availability"])
        self.assertEqual("LIVE_PRODUCTION_CURSOR_AHEAD", ahead["reason"])
        self.assertEqual([], ahead["items"])


if __name__ == "__main__":
    unittest.main()
