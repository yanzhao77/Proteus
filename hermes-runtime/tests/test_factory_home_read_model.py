import unittest
from unittest.mock import patch

from hermes_runtime.application.factory_home_read_model import UnavailableFactoryHomeReadModel
from hermes_runtime.application.product_api import ProductApiFacade
from hermes_runtime.domain.models import Actor, ActorType
from hermes_runtime.domain.product_api import ProductApiRequest, ProductApiRejected
from hermes_runtime.infrastructure.postgres_factory_home_read_model import PostgresFactoryHomeReadModel


class StaticScope:
    def __init__(self, project_ids):
        self.project_ids = project_ids

    def project_ids_for(self, _actor_scope):
        return self.project_ids


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class Connection:
    def __init__(self, project_rows, gate_rows):
        self.project_rows = project_rows
        self.gate_rows = gate_rows
        self.sql = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, _args):
        self.sql.append(sql)
        return Cursor(self.gate_rows if 'SELECT g.gate_request_id' in sql else self.project_rows)


class Gateway:
    def submit_human_gate_decision(self, _payload):
        return {"status": "REJECTED"}


class ExistingReadModel:
    def project_status(self, project_id, actor_scope):
        return {"project_id": project_id, "summary": "safe"}
    def decision_explain(self, decision_id, actor_scope):
        return {"decision_id": decision_id}
    def human_gate_request(self, gate_request_id, actor_scope):
        return {"gate_request_id": gate_request_id}
    def replay_reconcile_findings(self, project_id, actor_scope):
        return {"project_id": project_id, "findings": []}
    def docker_process_observations(self, process_id, actor_scope):
        return {"process_id": process_id, "observations": []}


class FactoryHomeReadModelTests(unittest.TestCase):
    def setUp(self):
        self.project_rows = [{"project_id": "p-1", "title": "Real Project", "state": "IMPLEMENTING", "version": 7, "updated_at": "2026-08-18T10:00:00Z", "gate_count": 1}]
        self.gate_rows = [{"gate_request_id": "g-1", "project_id": "p-1", "title": "Real Project", "action_scope": "database-migration", "reason": "operator review", "expires_at": "2026-08-18T12:00:00Z", "request_state": "REQUESTED", "version": 3, "updated_at": "2026-08-18T10:01:00Z"}]
        self.connection = Connection(self.project_rows, self.gate_rows)
        self.connect = patch('hermes_runtime.infrastructure.postgres_factory_home_read_model.psycopg.connect', return_value=self.connection)
        self.connect.start()
        self.addCleanup(self.connect.stop)
        self.model = PostgresFactoryHomeReadModel('postgresql://ignored', StaticScope(('p-1',)))
        self.actor = {"actor_type": "user", "actor_id": "verified-user"}

    def test_portfolio_is_source_backed_and_missing_progress_is_null(self):
        result = self.model.production_portfolio(self.actor)
        self.assertEqual("CURRENT", result["availability"])
        self.assertEqual("projects", result["source"])
        card = result["items"][0]
        self.assertEqual("p-1", card["project_id"])
        self.assertEqual("Real Project", card["display_name"])
        self.assertEqual("IMPLEMENTING", card["display_state"])
        self.assertIsNone(card["progress"])
        self.assertEqual("NOT_AVAILABLE", card["progress_basis"])
        self.assertIsNone(card["current_summary"])
        self.assertEqual("NOT_AVAILABLE", card["freshness"])
        self.assertNotIn("worker_count", card)
        self.assertNotIn("task_count", card)

    def test_gate_attention_is_source_backed_and_keeps_missing_values_null(self):
        result = self.model.gate_attention(self.actor)
        self.assertEqual("CURRENT", result["availability"])
        gate = result["items"][0]
        self.assertEqual("g-1", gate["gate_id"])
        self.assertEqual("database-migration", gate["action_summary"])
        self.assertIsNone(gate["risk"])
        self.assertIsNone(gate["evidence_count"])
        self.assertEqual("REQUESTED", gate["status"])

    def test_unauthorized_scope_does_not_query_or_return_records(self):
        model = PostgresFactoryHomeReadModel('postgresql://ignored', StaticScope(None))
        result = model.production_portfolio(self.actor)
        self.assertEqual("NOT_AVAILABLE", result["availability"])
        self.assertEqual([], result["items"])
        self.assertEqual([], self.connection.sql)

    def test_snapshot_does_not_return_unscoped_project(self):
        model = PostgresFactoryHomeReadModel('postgresql://ignored', StaticScope(('p-1',)))
        result = model.production_snapshot('p-other', self.actor)
        self.assertEqual("NOT_AVAILABLE", result["availability"])
        self.assertIsNone(result["item"])

    def test_storage_failure_degrades_without_internal_exception_leakage(self):
        self.connect.stop()
        with patch('hermes_runtime.infrastructure.postgres_factory_home_read_model.psycopg.connect', side_effect=RuntimeError('postgres internal password=secret')):
            result = self.model.production_portfolio(self.actor)
        self.assertEqual("DEGRADED", result["availability"])
        self.assertEqual("PORTFOLIO_SOURCE_UNAVAILABLE", result["reason"])
        self.assertNotIn("secret", str(result))

    def test_product_api_exposes_get_only_factory_home_routes(self):
        facade = ProductApiFacade(ExistingReadModel(), Gateway(), self.model)
        actor = Actor(ActorType.USER, "verified-user")
        response = facade.handle(ProductApiRequest("GET", "/factory-home", {}, {}, actor))
        self.assertEqual(200, response.status_code)
        self.assertEqual("SCOPED", response.body["actor_scope"])
        portfolio = facade.handle(ProductApiRequest("GET", "/factory-home/productions", {}, {}, actor))
        self.assertEqual("p-1", portfolio.body["items"][0]["project_id"])
        gates = facade.handle(ProductApiRequest("GET", "/factory-home/gates", {}, {}, actor))
        self.assertEqual("g-1", gates.body["items"][0]["gate_id"])
        drafts = facade.handle(ProductApiRequest("GET", "/factory-home/drafts", {}, {}, actor, verified_identity_subject=actor.actor_id))
        self.assertEqual("NOT_AVAILABLE", drafts.body["availability"])
        with self.assertRaises(ProductApiRejected):
            facade.handle(ProductApiRequest("POST", "/factory-home", {}, {}, actor))

    def test_default_unavailable_model_never_claims_a_portfolio(self):
        result = UnavailableFactoryHomeReadModel().factory_home_snapshot(self.actor)
        self.assertEqual("NOT_AVAILABLE", result["availability"])
        self.assertEqual([], result["continuations"])
        self.assertIsNone(result["cursor"])


if __name__ == '__main__':
    unittest.main()
