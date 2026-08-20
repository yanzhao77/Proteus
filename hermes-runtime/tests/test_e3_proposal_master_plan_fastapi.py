from fastapi.testclient import TestClient

from hermes_runtime.application.product_api import ProductApiFacade
from hermes_runtime.application.readiness import StaticReadinessCheck
from hermes_runtime.infrastructure.fastapi_app import create_app


class ReadModel:
    def project_status(self, *_): return {}
    def decision_explain(self, *_): return {}
    def human_gate_request(self, *_): return {}
    def replay_reconcile_findings(self, *_): return {}
    def docker_process_observations(self, *_): return {}


class Gateway:
    def submit_human_gate_decision(self, payload): return payload


def test_e3_routes_are_exact_allowlist_and_fail_closed_without_oidc():
    client = TestClient(create_app(ProductApiFacade(ReadModel(), Gateway()), StaticReadinessCheck()))
    schema = client.get('/openapi.json').json()['paths']
    assert '/production-drafts/{draft_id}/proposal' in schema
    assert '/production-drafts/{draft_id}/proposal/revisions' in schema
    assert '/production-drafts/{draft_id}/proposal/master-plan' in schema
    assert '/production-drafts/{draft_id}/proposal/master-plan/revisions' in schema
    assert not any('approve' in path.lower() for path in schema)
    response = client.post('/production-drafts/ed-1/proposal', json={'reason': 'review', 'idempotency_key': 'id-1', 'expected_version': 0})
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'FACTORY_HOME_IDENTITY_UNAVAILABLE'
