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


class _ReadModel: pass
class _Gateway: pass


class _WorkerTransport:
    def __init__(self):
        self.calls = []

    def list_workers(self, actor_scope):
        self.calls.append(("list_workers", dict(actor_scope)))
        return {"availability": "CURRENT", "reason": None, "items": [{"worker_id": "w-1"}]}

    def worker_detail(self, worker_id, actor_scope):
        self.calls.append(("worker_detail", worker_id, dict(actor_scope)))
        return {"availability": "CURRENT", "reason": None, "item": {"worker_id": worker_id}}

    def execution_queue(self, actor_scope):
        self.calls.append(("execution_queue", dict(actor_scope)))
        return {"availability": "CURRENT", "reason": None, "items": [{"queue_item_id": "q-1"}]}


def _issuer():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(algorithms.RSAAlgorithm.to_jwk(private.public_key()))
    jwk.update({"kid": "e14-test", "alg": "RS256"})
    verifier = OidcTokenVerifier(
        OidcConfig(issuer="https://e14-issuer.proteus.invalid", audience="proteus-test", production_profile=False, allow_local_test_issuer=True),
        StaticJwksProvider({"keys": [jwk]}),
    )
    now = int(time.time())
    token = jwt.encode(
        {"iss": "https://e14-issuer.proteus.invalid", "aud": "proteus-test", "sub": "creator-1", "exp": now + 300, "nbf": now - 1},
        private, algorithm="RS256", headers={"kid": "e14-test"},
    )
    return verifier, token


class E14FastApiTransportTests(unittest.TestCase):
    def setUp(self):
        verifier, token = _issuer()
        self.worker = _WorkerTransport()
        self.client = TestClient(
            create_app(
                ProductApiFacade(_ReadModel(), _Gateway(), worker_control_plane_read_model=self.worker),
                oidc_verifier=verifier,
                session_cookie_secure=False,
            )
        )
        self.assertEqual(201, self.client.post("/session", headers={"Authorization": f"Bearer {token}"}).status_code)

    def test_list_workers_returns_200_envelope(self):
        response = self.client.get("/factory-home/workers")
        self.assertEqual(200, response.status_code)
        data = response.json()["data"]
        self.assertEqual("CURRENT", data["availability"])
        self.assertEqual("w-1", data["items"][0]["worker_id"])
        kind, scope = self.worker.calls[0]
        self.assertEqual("list_workers", kind)
        self.assertEqual("creator-1", scope["identity_subject"])

    def test_worker_detail_returns_200_envelope(self):
        response = self.client.get("/factory-home/workers/w-1")
        self.assertEqual(200, response.status_code)
        self.assertEqual("w-1", response.json()["data"]["item"]["worker_id"])
        kind, worker_id, scope = self.worker.calls[0]
        self.assertEqual("worker_detail", kind)
        self.assertEqual("w-1", worker_id)
        self.assertEqual("creator-1", scope["identity_subject"])

    def test_execution_queue_returns_200_envelope(self):
        response = self.client.get("/factory-home/execution-queue")
        self.assertEqual(200, response.status_code)
        self.assertEqual("q-1", response.json()["data"]["items"][0]["queue_item_id"])
        kind, scope = self.worker.calls[0]
        self.assertEqual("execution_queue", kind)
        self.assertEqual("creator-1", scope["identity_subject"])

    def test_unauthenticated_fails_closed(self):
        client = TestClient(
            create_app(
                ProductApiFacade(_ReadModel(), _Gateway(), worker_control_plane_read_model=self.worker),
                oidc_verifier=None,
                session_cookie_secure=False,
            )
        )
        response = client.get("/factory-home/workers")
        self.assertEqual(503, response.status_code)
        self.assertEqual("FACTORY_HOME_IDENTITY_UNAVAILABLE", response.json()["error"]["code"])

    def test_browser_actor_header_cannot_override_verified_identity(self):
        response = self.client.get("/factory-home/workers", headers={"X-Hermes-Actor-ID": "forged"})
        self.assertEqual(401, response.status_code)
        self.assertEqual("FACTORY_HOME_ACTOR_MISMATCH", response.json()["error"]["code"])

    def test_very_long_worker_detail_id_is_safe(self):
        response = self.client.get("/factory-home/workers/w-" + "x" * 200)
        self.assertEqual(200, response.status_code)


if __name__ == "__main__":
    unittest.main()
