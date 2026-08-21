"""E8 Production Entry Trial: one E4 Project through formal P6 and E7 facts.

This is deliberately a discovered unittest, not a shell demonstration.  It
uses fresh migrations, a task-owned control database and Todo database, a local
RS256 verifier, a typed deterministic test-only producer, FastAPI dispatch, the
real durable E4 bridge, and the established P6 command-port lifecycle.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
import uuid
from pathlib import Path

try:
    import jwt
    import psycopg
    from cryptography.hazmat.primitives.asymmetric import rsa
    from fastapi.testclient import TestClient
    from jwt import algorithms
    from psycopg.rows import dict_row
except ImportError:
    jwt = None
    psycopg = None

from hermes_runtime.application.durable_approval_bridge_orchestrator import DurableApprovalBridgeOrchestrator
from hermes_runtime.application.entry_approval_bridge_saga import ApprovalBridgeSaga
from hermes_runtime.application.handlers import ControlPlane
from hermes_runtime.application.product_api import ProductApiFacade
from hermes_runtime.domain.understanding_producer import (
    ProducedUnderstanding,
    ProducerProvenance,
    ProviderUsage,
    UnderstandingCandidate,
)
from hermes_runtime.infrastructure.fastapi_app import create_app
from hermes_runtime.infrastructure.oidc import OidcConfig, OidcTokenVerifier, StaticJwksProvider
from hermes_runtime.infrastructure.postgres_entry_approval_bridge import PostgresEntryApprovalBridgeStore
from hermes_runtime.infrastructure.postgres_entry_draft import PostgresEntryDraftStore
from hermes_runtime.infrastructure.postgres_entry_proposal_master_plan import PostgresEntryProposalMasterPlanStore
from hermes_runtime.infrastructure.postgres_entry_understanding import PostgresEntryUnderstandingStore
from hermes_runtime.infrastructure.postgres_factory_home_read_model import PostgresCreatorActorProjectScope, PostgresFactoryHomeReadModel
from hermes_runtime.infrastructure.postgres_live_production_read_model import PostgresLiveProductionReadModel
from hermes_runtime.infrastructure.postgres_project import PostgresProjectStore
from hermes_runtime.trial.driver import AutonomousRunDriver, WorkerFaultMode
from hermes_runtime.trial.test_database_bootstrap import create_disposable_todo_database

BASE_URL = os.environ.get("HERMES_TEST_DATABASE_URL")
TODO_DATABASE_URL = os.environ.get(
    "HERMES_P6_TODO_DATABASE_URL",
    "postgresql+psycopg://todo:todo@127.0.0.1:55432/todo_test",
)


class _ReadModel:
    def project_status(self, project_id, actor_scope):
        return {"project_id": project_id, "availability": "NOT_IMPLEMENTED"}

    def decision_explain(self, decision_id, actor_scope):
        return {"decision_id": decision_id, "availability": "NOT_IMPLEMENTED"}

    def human_gate_request(self, gate_request_id, actor_scope):
        return {"gate_request_id": gate_request_id, "availability": "NOT_IMPLEMENTED"}

    def replay_reconcile_findings(self, project_id, actor_scope):
        return {"project_id": project_id, "findings": []}

    def docker_process_observations(self, process_id, actor_scope):
        return {"process_id": process_id, "observations": []}


class _Gateway:
    def submit_human_gate_decision(self, payload):
        return {"status": "REJECTED", "reason": "E8 does not bypass Human Gate authority"}


class DeterministicE8UnderstandingProducer:
    """Typed E8-only producer: no network, credentials, provider endpoint, or model call."""

    calls = 0

    def generate(self, request):
        self.calls += 1
        now = "2026-08-21T00:00:00+00:00"
        return ProducedUnderstanding(
            UnderstandingCandidate(
                goal="Build a Golden Todo REST API",
                objectives=("Deliver the Golden Todo REST API",),
                requirements=("Build a Golden Todo REST API with JWT authentication and PostgreSQL storage",),
                unknowns=(),
                assumptions=("E8 executes only the repository Golden Todo test fixture",),
                risks=(),
                clarification_questions=(),
            ),
            ProducerProvenance(
                producer="e8-test-only-deterministic-understanding",
                provider="TEST_ONLY_NON_PROVIDER",
                model="deterministic-fixture",
                model_version="e8-v1",
                provider_request_id=None,
                correlation_id=request.correlation_id,
                prompt_version=request.prompt_version,
                schema_version=request.schema_version,
                request_started_at=now,
                completed_at=now,
                latency_ms=0,
                retry_count=0,
                usage=ProviderUsage(None, None, None),
            ),
        )


def _admin_dsn(dsn: str) -> str:
    return dsn.rsplit("/", 1)[0] + "/postgres"


@unittest.skipUnless(BASE_URL and psycopg and jwt, "requires real PostgreSQL, psycopg, JWT and explicit HERMES_TEST_DATABASE_URL")
class E8ProductionEntryTrialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.database_name = "hermes_e8_" + uuid.uuid4().hex[:16]
        admin = psycopg.connect(_admin_dsn(BASE_URL))
        admin.autocommit = True
        try:
            admin.execute("CREATE DATABASE " + cls.database_name)
        finally:
            admin.close()
        cls.database_url = BASE_URL.rsplit("/", 1)[0] + "/" + cls.database_name
        cls.addClassCleanup(cls._drop_control_database)
        bootstrap = PostgresProjectStore(cls.database_url)
        for migration in sorted((Path(__file__).parents[1] / "migrations").glob("*.sql")):
            bootstrap.apply_migration(migration)
        cls.todo_database = create_disposable_todo_database(BASE_URL, TODO_DATABASE_URL)
        cls.addClassCleanup(cls.todo_database.cleanup)

    @classmethod
    def _drop_control_database(cls):
        admin = psycopg.connect(_admin_dsn(BASE_URL))
        admin.autocommit = True
        try:
            admin.execute("DROP DATABASE IF EXISTS " + cls.database_name)
        finally:
            admin.close()

    def setUp(self):
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
        jwk.update({"kid": "e8-local-kid", "alg": "RS256"})
        self.private_key = private_key
        self.verifier = OidcTokenVerifier(
            OidcConfig(issuer="https://e8.local.test", audience="hermes-e8"),
            StaticJwksProvider({"keys": [jwk]}),
        )
        self.producer = DeterministicE8UnderstandingProducer()
        drafts = PostgresEntryDraftStore(self.database_url)
        understanding = PostgresEntryUnderstandingStore(self.database_url, self.producer)
        proposal = PostgresEntryProposalMasterPlanStore(self.database_url)
        bridge_store = PostgresEntryApprovalBridgeStore(self.database_url)
        approval = DurableApprovalBridgeOrchestrator(
            bridge_store,
            ApprovalBridgeSaga(ControlPlane(PostgresProjectStore(self.database_url)), bridge_store),
        )
        scope = PostgresCreatorActorProjectScope(self.database_url)
        facade = ProductApiFacade(
            _ReadModel(), _Gateway(),
            PostgresFactoryHomeReadModel(self.database_url, scope, drafts),
            drafts, understanding, proposal, approval,
            PostgresLiveProductionReadModel(self.database_url, scope),
        )
        self.client = TestClient(create_app(facade, oidc_verifier=self.verifier))
        self.alice = "e8-creator-a"
        self.bob = "e8-creator-b"

    def _token(self, subject: str) -> str:
        now = int(time.time())
        return jwt.encode(
            {"iss": "https://e8.local.test", "aud": "hermes-e8", "sub": subject, "exp": now + 300, "nbf": now - 1},
            self.private_key,
            algorithm="RS256",
            headers={"kid": "e8-local-kid"},
        )

    def _headers(self, subject: str, *, actor: str | None = None) -> dict:
        return {
            "Authorization": "Bearer " + self._token(subject),
            "X-Hermes-Actor-Type": "user",
            "X-Hermes-Actor-ID": actor if actor is not None else subject,
            "X-Request-ID": "e8-request-" + uuid.uuid4().hex[:12],
        }

    def _json(self, response, status: int):
        self.assertEqual(status, response.status_code, response.text)
        self.assertIsNone(response.json()["error"], response.text)
        return response.json()["data"]

    def _scalar(self, sql: str, args=()):
        with psycopg.connect(self.database_url) as connection:
            row = connection.execute(sql, args).fetchone()
        return row[0] if row else None

    def _counts(self, project_id: str | None = None):
        with psycopg.connect(self.database_url) as connection:
            if project_id is None:
                return {
                    "projects": connection.execute("SELECT count(*) FROM public.projects").fetchone()[0],
                    "tasks": connection.execute("SELECT count(*) FROM public.tasks").fetchone()[0],
                    "verification_plans": connection.execute("SELECT count(*) FROM public.verification_plans").fetchone()[0],
                }
            return {
                "projects": connection.execute("SELECT count(*) FROM public.projects WHERE project_id=%s", (project_id,)).fetchone()[0],
                "tasks": connection.execute("SELECT count(*) FROM public.tasks WHERE project_id=%s", (project_id,)).fetchone()[0],
                "verification_plans": connection.execute("SELECT count(*) FROM public.verification_plans WHERE project_id=%s", (project_id,)).fetchone()[0],
            }

    def _snapshot(self, project_id: str, subject: str):
        return self._json(
            self.client.get(f"/factory-home/productions/{project_id}/live", headers=self._headers(subject)),
            200,
        )

    def _assert_no_secrets(self, value):
        encoded = json.dumps(value, sort_keys=True).lower()
        for forbidden in ("authorization", "password", "postgresql://", "api_key", "private_key", "raw_input"):
            self.assertNotIn(forbidden, encoded)

    def test_e8_production_entry_trial_same_project(self):
        # Negative entry boundary: missing/invalid OIDC and actor override fail closed.
        self.assertEqual(401, self.client.post("/production-drafts", json={}).status_code)
        self.assertEqual(401, self.client.post("/production-drafts", headers={"Authorization": "Bearer invalid"}, json={}).status_code)
        overridden = self.client.get("/production-drafts", headers=self._headers(self.alice, actor=self.bob))
        self.assertEqual(401, overridden.status_code, overridden.text)

        create_payload = {
            "title": "Golden Todo E8",
            "raw_input": "Build a Golden Todo REST API with JWT authentication and PostgreSQL storage",
            "idempotency_key": "e8-draft-create",
            "reason": "E8 Production Entry Trial",
        }
        created = self._json(self.client.post("/production-drafts", headers=self._headers(self.alice), json=create_payload), 201)["item"]
        replay = self._json(self.client.post("/production-drafts", headers=self._headers(self.alice), json=create_payload), 201)["item"]
        self.assertEqual(created["draft_id"], replay["draft_id"])
        draft_id = created["draft_id"]
        draft_version = created["version"]

        submitted = self._json(
            self.client.post(f"/production-drafts/{draft_id}/submit", headers=self._headers(self.alice), json={
                "expected_version": draft_version, "idempotency_key": "e8-draft-submit", "reason": "ready for deterministic understanding",
            }),
            200,
        )["item"]
        self.assertGreaterEqual(submitted["version"], 2)

        understanding = self._json(
            self.client.post(f"/production-drafts/{draft_id}/understanding", headers=self._headers(self.alice), json={
                "expected_version": 0, "idempotency_key": "e8-understanding", "reason": "test-only deterministic understanding",
            }),
            202,
        )["item"]
        self.assertEqual("READY", understanding["state"])
        self.assertEqual(1, self.producer.calls)
        self.assertEqual("TEST_ONLY_NON_PROVIDER", understanding["current"]["provider_metadata"]["provider"])

        proposal = self._json(
            self.client.post(f"/production-drafts/{draft_id}/proposal", headers=self._headers(self.alice), json={
                "expected_version": 0, "idempotency_key": "e8-proposal", "reason": "compile deterministic proposal",
            }),
            201,
        )["item"]
        plan = self._json(
            self.client.post(f"/production-drafts/{draft_id}/proposal/master-plan", headers=self._headers(self.alice), json={
                "expected_version": 0, "idempotency_key": "e8-master-plan", "reason": "compile deterministic master plan",
            }),
            201,
        )["item"]
        self.assertTrue(plan["current"]["content"]["pre_approval_only"])
        self.assertEqual({"projects": 0, "tasks": 0, "verification_plans": 0}, self._counts())

        # Creator isolation never becomes a probing oracle before or after approval.
        self.assertEqual("NOT_AVAILABLE", self._json(self.client.get(f"/production-drafts/{draft_id}", headers=self._headers(self.bob)), 200)["availability"])
        self.assertEqual("NOT_AVAILABLE", self._json(self.client.get(f"/production-drafts/{draft_id}/proposal/master-plan", headers=self._headers(self.bob)), 200)["availability"])
        self.assertIn(self.client.get(f"/production-drafts/{draft_id}/proposal/master-plan/approval-preview", headers=self._headers(self.bob)).status_code, {403, 404, 422})

        preview = self._json(
            self.client.get(f"/production-drafts/{draft_id}/proposal/master-plan/approval-preview", headers=self._headers(self.alice)),
            200,
        )
        approval_payload = {
            "reason": "creator approves frozen E8 plan",
            "idempotency_key": "e8-approval",
            "expected_draft_version": submitted["version"],
            "master_plan_id": plan["master_plan_id"],
            "expected_plan_version": plan["version"],
            "plan_revision_id": plan["current"]["master_plan_revision_id"],
            "approved_plan_content_hash": plan["current"]["content_hash"],
            "proposal_revision_id": proposal["current"]["proposal_revision_id"],
            "proposal_content_hash": proposal["current"]["content_hash"],
            "compiled_blueprint_hash": preview["compiled_blueprint_hash"],
            "acknowledgements": list(preview["required_acknowledgements"]),
            "correlation_id": "e8-correlation",
        }
        before_approval = self._counts()
        approval = self._json(
            self.client.post(f"/production-drafts/{draft_id}/proposal/master-plan/approve", headers=self._headers(self.alice), json=approval_payload),
            202,
        )
        self.assertEqual("MATERIALIZED", approval["status"], approval)
        project_id = approval["project_id"]
        self.assertEqual(1, self._counts(project_id)["projects"])
        self.assertGreaterEqual(self._counts(project_id)["tasks"], 1)
        self.assertGreaterEqual(self._counts(project_id)["verification_plans"], 1)
        self.assertEqual(before_approval["projects"] + 1, self._counts()["projects"])
        replay_approval = self._json(
            self.client.post(f"/production-drafts/{draft_id}/proposal/master-plan/approve", headers=self._headers(self.alice), json=approval_payload),
            202,
        )
        self.assertEqual(project_id, replay_approval["project_id"])
        self.assertEqual(1, self._counts(project_id)["projects"])

        bridge = PostgresEntryApprovalBridgeStore(self.database_url).load_bridge(self.alice, draft_id)
        blueprint = bridge["compiled_blueprint"]
        self.assertEqual(project_id, blueprint["project_id"])
        task = blueprint["tasks"][0]
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            readiness = connection.execute(
                "SELECT event_id FROM public.event_log WHERE project_id=%s AND event_type='work_graph.patch.applied' ORDER BY sequence DESC LIMIT 1",
                (project_id,),
            ).fetchone()
            check = connection.execute(
                "SELECT check_id FROM public.verification_plan_checks WHERE verification_plan_id=%s ORDER BY ordinal LIMIT 1",
                (task["verification_plan_id"],),
            ).fetchone()
        self.assertIsNotNone(readiness)
        self.assertIsNotNone(check)

        initial_snapshot = self._snapshot(project_id, self.alice)
        self.assertEqual("CURRENT", initial_snapshot["availability"])
        self.assertEqual(project_id, initial_snapshot["item"]["production_id"])
        self.assertEqual("NOT_AVAILABLE", self._snapshot(project_id, self.bob)["availability"])
        self._assert_no_secrets(initial_snapshot)
        self.assertFalse(any(node["completion_claim"]["verified"] for node in initial_snapshot["item"]["workflow"]["nodes"]))

        observed = {"MATERIALIZED_NOT_STARTED": initial_snapshot}
        with tempfile.TemporaryDirectory(prefix="e8-workspace-") as workspace:
            driver = AutonomousRunDriver(self.database_url, Path(workspace), self.todo_database.runtime_todo_dsn)
            def observe(stage, _records):
                snapshot = self._snapshot(project_id, self.alice)
                self.assertEqual("CURRENT", snapshot["availability"])
                self.assertEqual(project_id, snapshot["item"]["production_id"])
                observed[stage] = snapshot
            records = driver.run_happy_path_from_entry(
                {"summary": "Build a Golden Todo REST API", "request": "Golden Todo E8", "acceptance": "formal pytest"},
                "e8-same-project",
                {
                    "project_id": project_id,
                    "task_id": task["task_id"],
                    "verification_plan_id": task["verification_plan_id"],
                    "verification_check_id": check["check_id"],
                    "readiness_event_id": readiness["event_id"],
                },
                WorkerFaultMode.BROKEN_TEST,
                observe,
            )
        self.assertEqual(project_id, records["project_id"])
        self.assertEqual("ACCEPTED", records["delivery"]["final_state"])
        self.assertEqual("PASSED", records["task_pass"]["state"])
        self.assertIn("RUNNING", observed)
        self.assertIn("VERIFICATION_FAILED_RECOVERING", observed)
        self.assertIn("VERIFICATION_PASSED", observed)
        self.assertIn("DELIVERED_ACCEPTED", observed)
        final_snapshot = observed["DELIVERED_ACCEPTED"]
        self.assertEqual(project_id, final_snapshot["item"]["production_id"])
        self.assertEqual("ACCEPTED", final_snapshot["item"]["project"]["state"])
        self.assertEqual(1, self._counts(project_id)["projects"])

        # Snapshot watermark is the authority boundary; feed is bounded and stale cursors rehydrate.
        events = self._json(
            self.client.get(f"/factory-home/productions/{project_id}/live-feed?after=0&limit=500", headers=self._headers(self.alice)),
            200,
        )
        self.assertEqual("CURRENT", events["availability"])
        self.assertTrue(events["bounded"])
        self.assertLessEqual(len(events["items"]), 100)
        self.assertEqual(sorted({item["event_id"] for item in events["items"]}), sorted(item["event_id"] for item in events["items"]))
        stale = self._json(
            self.client.get(f"/factory-home/productions/{project_id}/live-feed?after={events['snapshot_watermark'] + 1}&limit=50", headers=self._headers(self.alice)),
            200,
        )
        self.assertEqual("STALE", stale["availability"])
        self.assertEqual("LIVE_PRODUCTION_CURSOR_AHEAD", stale["reason"])
        self.assertEqual([], stale["items"])
        self.assertEqual("NOT_AVAILABLE", self._json(
            self.client.get(f"/factory-home/productions/{project_id}/live-feed?after=0&limit=10", headers=self._headers(self.bob)), 200,
        )["availability"])
        self._assert_no_secrets(final_snapshot)


if __name__ == "__main__":
    unittest.main()
