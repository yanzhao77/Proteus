"""E5 source-derived Product API/read-model evidence against disposable PostgreSQL."""
from __future__ import annotations

import os
import unittest
import uuid
from pathlib import Path

try:
    import psycopg
except ImportError:  # pragma: no cover - CI no-db lane
    psycopg = None

from hermes_runtime.domain.models import Actor, ActorType
from hermes_runtime.domain.product_api import ProductApiRequest
from hermes_runtime.application.product_api import ProductApiFacade
from hermes_runtime.infrastructure.postgres_entry_draft import PostgresEntryDraftStore
from hermes_runtime.infrastructure.postgres_factory_home_read_model import (
    PostgresCreatorActorProjectScope,
    PostgresFactoryHomeReadModel,
)

try:
    from tests.test_e4_approval_bridge_postgres import E4ApprovalBridgePostgresDurabilityTests
except ModuleNotFoundError:  # repository-root unittest discovery
    from test_e4_approval_bridge_postgres import E4ApprovalBridgePostgresDurabilityTests

DATABASE_URL = os.getenv("HERMES_TEST_DATABASE_URL", "")


@unittest.skipUnless(psycopg is not None and DATABASE_URL, "requires HERMES_TEST_DATABASE_URL")
class E5ProductReadModelPostgresTests(unittest.TestCase):
    """Final E5 evidence uses real E4 and E1 authority commands, never read-model fixtures."""

    @classmethod
    def setUpClass(cls):
        E4ApprovalBridgePostgresDurabilityTests.setUpClass()

    def setUp(self):
        self.seed = E4ApprovalBridgePostgresDurabilityTests(
            "test_01_receipt_commits_before_any_child_side_effect"
        )
        self.seed.setUp()
        approved = self.seed._fresh_orchestrator().approve(
            self.seed.alice,
            self.seed.draft_id,
            self.seed._payload("e5-real-materialization"),
        )
        self.assertEqual("MATERIALIZED", approved["status"])
        self.project_id = approved["project_id"]
        self.drafts = PostgresEntryDraftStore(DATABASE_URL)
        self.read_model = PostgresFactoryHomeReadModel(
            DATABASE_URL,
            PostgresCreatorActorProjectScope(DATABASE_URL),
            self.drafts,
        )
        self.alice = {
            "actor_type": "user",
            "actor_id": self.seed.alice,
            "identity_verified": True,
            "identity_subject": self.seed.alice,
        }
        self.bob = {
            "actor_type": "user",
            "actor_id": "e5-bob",
            "identity_verified": True,
            "identity_subject": "e5-bob",
        }

    def test_real_e4_project_is_creator_scoped_portfolio_item(self):
        portfolio = self.read_model.production_portfolio(self.alice)
        self.assertEqual("CURRENT", portfolio["availability"])
        self.assertEqual("projects,entry_approval_materialized_bindings", portfolio["source"])
        self.assertEqual([self.project_id], [item["project_id"] for item in portfolio["items"]])
        item = portfolio["items"][0]
        self.assertIsNone(item["progress"])
        self.assertEqual("NOT_AVAILABLE", item["progress_basis"])
        self.assertIsNotNone(item["plan_revision"])

    def test_unapproved_draft_is_resumable_but_not_a_production(self):
        unapproved = self.drafts.create(
            self.seed.alice,
            title="Unapproved E5 Draft",
            raw_input="Only an entry draft; it has no approved Project.",
            idempotency_key="e5-unapproved-draft-" + uuid.uuid4().hex,
            reason="E5 source projection evidence",
        )
        drafts = self.read_model.production_drafts(self.alice)
        self.assertEqual("CURRENT", drafts["availability"])
        self.assertIn(unapproved["draft_id"], [item["draft_id"] for item in drafts["items"]])
        portfolio = self.read_model.production_portfolio(self.alice)
        self.assertNotIn(unapproved["draft_id"], [item["project_id"] for item in portfolio["items"]])

    def test_creator_b_and_project_id_probe_fail_closed(self):
        other = self.read_model.production_portfolio(self.bob)
        self.assertEqual("CURRENT", other["availability"])
        self.assertEqual([], other["items"])
        probe = self.read_model.production_snapshot(self.project_id, self.bob)
        self.assertEqual("NOT_AVAILABLE", probe["availability"])
        self.assertIsNone(probe["item"])

    def test_product_api_verified_subject_scope_cannot_be_overridden(self):
        facade = ProductApiFacade(
            read_model=object(),
            command_gateway=object(),
            factory_home_read_model=self.read_model,
            entry_draft_api=self.drafts,
        )
        response = facade.handle(ProductApiRequest(
            "GET", "/factory-home/productions", {}, {},
            Actor(ActorType.USER, self.seed.alice),
            verified_identity_subject=self.seed.alice,
        ))
        self.assertEqual(200, response.status_code)
        self.assertEqual([self.project_id], [item["project_id"] for item in response.body["items"]])
        source = (Path(__file__).parents[1] / "src/hermes_runtime/infrastructure/postgres_factory_home_read_model.py").read_text()
        self.assertNotIn("INSERT INTO public.projects", source)
        self.assertNotIn("UPDATE public.projects", source)
        self.assertNotIn("DELETE FROM public.projects", source)


if __name__ == "__main__":
    unittest.main()
