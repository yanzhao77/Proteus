import unittest

from fastapi.testclient import TestClient

from hermes_runtime.application.product_api import ProductApiFacade
from hermes_runtime.infrastructure.fastapi_app import StaticReadinessCheck, create_app


class Read: pass
class Gateway: pass


class E7LiveFastApiTests(unittest.TestCase):
    def test_live_routes_are_registered_and_fail_closed_without_identity_verifier(self):
        client = TestClient(create_app(ProductApiFacade(Read(), Gateway()), StaticReadinessCheck()))
        schema = client.get('/openapi.json').json()['paths']
        self.assertIn('/factory-home/productions/{project_id}/live', schema)
        self.assertIn('/factory-home/productions/{project_id}/live-feed', schema)
        self.assertNotIn('/factory-home/productions/{project_id}/events', schema)
        for path in ('/factory-home/productions/project-1/live', '/factory-home/productions/project-1/live-feed?after=0&limit=50'):
            response = client.get(path)
            self.assertEqual(503, response.status_code)
            self.assertEqual('FACTORY_HOME_IDENTITY_UNAVAILABLE', response.json()['error']['code'])


if __name__ == '__main__':
    unittest.main()
