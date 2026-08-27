"""E11 receipt to E7 source-derived projection evidence against disposable PostgreSQL."""
from __future__ import annotations

import os
import unittest

try:
    import psycopg
except ImportError:  # pragma: no cover
    psycopg = None

from hermes_runtime.application.handlers import ControlPlane
from hermes_runtime.application.user_project_command_transport import UserProjectCommandTransport
from hermes_runtime.domain.models import Actor, ActorType, ProjectState
from hermes_runtime.infrastructure.postgres_factory_home_read_model import PostgresCreatorActorProjectScope
from hermes_runtime.infrastructure.postgres_live_production_read_model import PostgresLiveProductionReadModel
from hermes_runtime.infrastructure.postgres_project import PostgresProjectStore

try:
    import tests.test_e4_approval_bridge_postgres as e4_approval_bridge_postgres
except ModuleNotFoundError:  # repository-root unittest discovery
    import test_e4_approval_bridge_postgres as e4_approval_bridge_postgres

DATABASE_URL = os.getenv("HERMES_TEST_DATABASE_URL", "")


@unittest.skipUnless(DATABASE_URL and psycopg, "requires explicit PostgreSQL")
class E11PostCommandE7ReconciliationPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        e4_approval_bridge_postgres.E4ApprovalBridgePostgresDurabilityTests.setUpClass()

    def setUp(self):
        self.seed = e4_approval_bridge_postgres.E4ApprovalBridgePostgresDurabilityTests(
            "test_01_receipt_commits_before_any_child_side_effect"
        )
        self.seed.setUp()
        materialized = self.seed._fresh_orchestrator().approve(
            self.seed.alice,
            self.seed.draft_id,
            self.seed._payload("e11-e7-reconciliation-materialization"),
        )
        self.assertEqual("MATERIALIZED", materialized["status"])
        self.project_id = materialized["project_id"]
        self.store = PostgresProjectStore(DATABASE_URL)
        self.plane = ControlPlane(self.store)
        self.creator = Actor(ActorType.USER, self.seed.alice)
        self._seed_guard(ProjectState.CREATED, 0, ProjectState.PAUSED, "pause")
        self.transport = UserProjectCommandTransport(
            self.plane,
            PostgresCreatorActorProjectScope(DATABASE_URL),
            self.store,
        )
        self.reader = PostgresLiveProductionReadModel(
            DATABASE_URL,
            PostgresCreatorActorProjectScope(DATABASE_URL),
        )
        self.actor_scope = {
            "identity_verified": True,
            "identity_subject": self.seed.alice,
            "actor_type": "user",
            "actor_id": self.seed.alice,
        }

    def _seed_guard(self, from_state, version, to_state, suffix):
        with self.store._connect() as connection:
            connection.execute(
                "INSERT INTO project_evidence_facts (evidence_fact_id, project_id, project_version, from_state, to_state, result, authority, subject_ref) VALUES (%s,%s,%s,%s,%s,'VALID','verification_engine',%s)",
                (f"e11-e7-evidence-{suffix}", self.project_id, version, from_state.value, to_state.value, f"e11-e7-subject-{suffix}"),
            )
            connection.execute(
                "INSERT INTO project_policy_decision_facts (policy_decision_id, project_id, project_version, from_state, to_state, result, authority, policy_bundle_version, input_hash) VALUES (%s,%s,%s,%s,%s,'ALLOW','policy_engine','policy-test',%s)",
                (f"e11-e7-policy-{suffix}", self.project_id, version, from_state.value, to_state.value, f"sha256:e11-e7-{suffix}"),
            )
            connection.execute(
                "INSERT INTO project_budget_facts (budget_fact_id, project_id, project_version, from_state, to_state, status, authority, budget_scope_id, version) VALUES (%s,%s,%s,%s,%s,'OK','budget_engine',%s,1)",
                (f"e11-e7-budget-{suffix}", self.project_id, version, from_state.value, to_state.value, f"e11-e7-budget-{self.project_id}"),
            )

    def test_pause_receipt_can_be_confirmed_only_by_current_creator_scoped_e7_snapshot(self):
        receipt = self.transport.submit(
            action="pause",
            project_id=self.project_id,
            verified_identity_subject=self.seed.alice,
            actor=self.creator,
            command_id="e11-e7-pause-command",
            expected_version=0,
            idempotency_key="e11-e7-pause-idempotency",
            reason="creator requested pause",
        )
        self.assertEqual("AWAITING_E7_RECONCILIATION", receipt["projection_status"])
        self.assertEqual("RECEIPT_IS_NOT_PROJECTION_STATE", receipt["completion_claim"])

        snapshot = self.reader.snapshot(self.project_id, self.actor_scope)
        self.assertEqual("CURRENT", snapshot["availability"])
        self.assertEqual("CURRENT", snapshot["freshness"])
        self.assertEqual("e7-live-production-projection/1", snapshot["projection_schema_version"])
        self.assertEqual(receipt["target_version"], snapshot["item"]["project"]["version"])
        self.assertEqual("PAUSED", snapshot["item"]["project"]["state"])

        feed = self.reader.events(self.project_id, self.actor_scope, after=0, limit=50)
        self.assertEqual("CURRENT", feed["availability"])
        self.assertTrue(feed["bounded"])
        self.assertGreaterEqual(feed["snapshot_watermark"], max(event["production_sequence"] for event in feed["items"]))
        self.assertTrue(set(receipt["event_ids"]).issubset({event["event_id"] for event in feed["items"]}))


if __name__ == "__main__":
    unittest.main()
