import unittest

from fastapi.testclient import TestClient

from hermes_runtime.application.product_api import ProductApiFacade
from hermes_runtime.infrastructure.fastapi_app import StaticReadinessCheck, create_app


class _Read: pass
class _Gateway: pass


class E4FastApiTests(unittest.TestCase):
    def test_e4_routes_are_exact_and_fail_closed_without_oidc(self):
        client = TestClient(create_app(ProductApiFacade(_Read(), _Gateway()), StaticReadinessCheck()))
        schema = client.get('/openapi.json').json()['paths']
        base = '/production-drafts/{draft_id}/proposal/master-plan'
        self.assertIn(base + '/approval-preview', schema)
        self.assertIn(base + '/approval', schema)
        self.assertIn(base + '/approve', schema)
        self.assertIn(base + '/approval/reconcile', schema)
        self.assertFalse(any('/projects' in path and 'approval' in path for path in schema))
        response = client.post(base + '/approve', json={'reason':'approve'})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['error']['code'], 'FACTORY_HOME_IDENTITY_UNAVAILABLE')
