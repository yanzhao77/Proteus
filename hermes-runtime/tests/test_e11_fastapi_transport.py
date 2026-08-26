import json
import time
import unittest

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt import algorithms

from hermes_runtime.application.product_api import ProductApiFacade
from hermes_runtime.application.user_project_command_transport import UserProjectCommandRejected
from hermes_runtime.infrastructure.fastapi_app import create_app
from hermes_runtime.infrastructure.oidc import OidcConfig, OidcTokenVerifier, StaticJwksProvider


class _ReadModel:
    pass


class _Gateway:
    pass


class _Transport:
    def __init__(self):
        self.submit_calls = []
        self.receipt_calls = []

    def submit(self, **kwargs):
        self.submit_calls.append(kwargs)
        if kwargs["project_id"] == "foreign":
            raise UserProjectCommandRejected("E11_COMMAND_NOT_AVAILABLE")
        return {
            "availability": "CURRENT",
            "command_id": kwargs["command_id"],
            "action": kwargs["action"],
            "receipt_status": "APPLIED",
            "result_code": "PROJECT_TRANSITION_APPLIED",
            "target_version": kwargs["expected_version"] + 1,
            "event_ids": ["event-1"],
            "project_id": kwargs["project_id"],
            "projection_status": "AWAITING_E7_RECONCILIATION",
            "completion_claim": "RECEIPT_IS_NOT_PROJECTION_STATE",
        }

    def receipt(self, **kwargs):
        self.receipt_calls.append(kwargs)
        return {
            "availability": "CURRENT",
            "command_id": kwargs["command_id"],
            "action": None,
            "receipt_status": "APPLIED",
            "result_code": "PROJECT_TRANSITION_APPLIED",
            "target_version": 4,
            "event_ids": ["event-1"],
            "project_id": kwargs["project_id"],
            "projection_status": "AWAITING_E7_RECONCILIATION",
            "completion_claim": "RECEIPT_IS_NOT_PROJECTION_STATE",
        }


def _local_issuer():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(algorithms.RSAAlgorithm.to_jwk(private.public_key()))
    jwk.update({"kid": "e11-test", "alg": "RS256"})
    verifier = OidcTokenVerifier(
        OidcConfig(issuer="https://e11-issuer.proteus.invalid", audience="proteus-test", production_profile=False, allow_local_test_issuer=True),
        StaticJwksProvider({"keys": [jwk]}),
    )
    now = int(time.time())
    token = jwt.encode({"iss": "https://e11-issuer.proteus.invalid", "aud": "proteus-test", "sub": "creator-1", "exp": now + 300, "nbf": now - 1}, private, algorithm="RS256", headers={"kid": "e11-test"})
    return verifier, token


class E11FastApiTransportTests(unittest.TestCase):
    def setUp(self):
        verifier, self.token = _local_issuer()
        self.transport = _Transport()
        self.client = TestClient(create_app(ProductApiFacade(_ReadModel(), _Gateway(), user_project_command_transport=self.transport), oidc_verifier=verifier, session_cookie_secure=False))
        created = self.client.post("/session", headers={"Authorization": f"Bearer {self.token}"})
        self.assertEqual(201, created.status_code)

    def _body(self):
        return {"command_id": "cmd-1", "expected_version": 3, "idempotency_key": "idem-1", "reason": "creator requested pause"}

    def test_verified_session_submits_receipt_first_transport_without_client_actor(self):
        response = self.client.post("/factory-home/productions/project-1/commands/pause", json=self._body())
        self.assertEqual(202, response.status_code)
        data = response.json()["data"]
        self.assertEqual("AWAITING_E7_RECONCILIATION", data["projection_status"])
        self.assertEqual("RECEIPT_IS_NOT_PROJECTION_STATE", data["completion_claim"])
        call = self.transport.submit_calls[0]
        self.assertEqual("creator-1", call["verified_identity_subject"])
        self.assertEqual("creator-1", call["actor"].actor_id)
        self.assertNotIn("actor", self._body())

    def test_client_actor_override_and_foreign_project_fail_closed(self):
        body = self._body() | {"actor": {"type": "control_plane", "id": "forged"}}
        forged = self.client.post("/factory-home/productions/project-1/commands/pause", json=body)
        self.assertEqual(400, forged.status_code)
        self.assertEqual("E11_COMMAND_CLIENT_AUTHORITY_FIELD_FORBIDDEN", forged.json()["error"]["code"])
        foreign = self.client.post("/factory-home/productions/foreign/commands/pause", json=self._body())
        self.assertEqual(404, foreign.status_code)
        self.assertEqual("E11_COMMAND_NOT_AVAILABLE", foreign.json()["error"]["code"])

    def test_receipt_status_is_creator_session_scoped(self):
        response = self.client.get("/factory-home/productions/project-1/commands/cmd-1")
        self.assertEqual(200, response.status_code)
        self.assertEqual(("cmd-1", "project-1"), (self.transport.receipt_calls[0]["command_id"], self.transport.receipt_calls[0]["project_id"]))


if __name__ == "__main__":
    unittest.main()
