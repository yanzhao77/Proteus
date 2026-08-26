import json
import time
import unittest

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt import algorithms

from hermes_runtime.application.product_api import ProductApiFacade
from hermes_runtime.infrastructure.fastapi_app import create_app
from hermes_runtime.infrastructure.oidc import OidcConfig, OidcTokenVerifier, StaticJwksProvider


class ReadModel:
    def factory_status(self, actor_scope):
        return {"availability": "CURRENT", "actor": actor_scope["actor_id"]}


class Gateway:
    pass


def local_issuer():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(algorithms.RSAAlgorithm.to_jwk(private.public_key()))
    jwk.update({"kid": "wave-a-test", "alg": "RS256"})
    verifier = OidcTokenVerifier(
        OidcConfig(issuer="https://test-issuer.proteus.invalid", audience="proteus-test", production_profile=False, allow_local_test_issuer=True),
        StaticJwksProvider({"keys": [jwk]}),
    )
    now = int(time.time())
    token = jwt.encode({"iss": "https://test-issuer.proteus.invalid", "aud": "proteus-test", "sub": "wave-a-user", "exp": now + 300, "nbf": now - 1}, private, algorithm="RS256", headers={"kid": "wave-a-test"})
    return verifier, token


class E10OidcSessionTests(unittest.TestCase):
    def setUp(self):
        verifier, self.token = local_issuer()
        self.client = TestClient(create_app(ProductApiFacade(ReadModel(), Gateway()), oidc_verifier=verifier, session_cookie_secure=False))

    def test_exchange_profile_product_api_and_logout_use_only_opaque_cookie(self):
        created = self.client.post("/session", headers={"Authorization": f"Bearer {self.token}"})
        self.assertEqual(201, created.status_code)
        self.assertEqual("wave-a-user", created.json()["data"]["subject"])
        self.assertNotIn(self.token, created.text)
        cookie = self.client.cookies.get("hermes_session")
        self.assertIsNotNone(cookie)
        self.assertNotEqual(self.token, cookie)
        self.assertGreater(len(cookie), 32)
        current = self.client.get("/session")
        self.assertEqual(200, current.status_code)
        self.assertEqual({"authenticated", "subject", "issuer", "expires_at"}, set(current.json()["data"]))
        factory = self.client.get("/factory-home/status")
        self.assertEqual(200, factory.status_code)
        self.assertIn("availability", factory.json()["data"])
        no_actor_header_authority = self.client.get("/factory-home/status", headers={"X-Hermes-Actor-ID": "other"})
        self.assertEqual(401, no_actor_header_authority.status_code)
        logged_out = self.client.delete("/session")
        self.assertEqual(204, logged_out.status_code)
        self.assertEqual("", logged_out.content.decode())
        self.assertEqual(401, self.client.get("/session").status_code)

    def test_session_endpoints_fail_closed_without_verified_bearer(self):
        self.assertEqual(401, self.client.post("/session").status_code)
        self.assertEqual(401, self.client.get("/session").status_code)
        self.assertEqual(401, self.client.get("/factory-home/status", headers={"X-Hermes-Actor-ID": "wave-a-user"}).status_code)


if __name__ == "__main__":
    unittest.main()
