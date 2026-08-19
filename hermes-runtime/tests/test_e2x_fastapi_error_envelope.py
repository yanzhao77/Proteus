import json
import time
import unittest

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt import algorithms

from hermes_runtime.application.product_api import ProductApiFacade
from hermes_runtime.domain.entry_understanding import EntryUnderstandingRejected
from hermes_runtime.infrastructure.fastapi_app import create_app
from hermes_runtime.infrastructure.oidc import OidcConfig, OidcTokenVerifier, StaticJwksProvider


class EmptyReadModel:
    def project_status(self, project_id, actor_scope): return {"project_id": project_id}
    def decision_explain(self, decision_id, actor_scope): return {"decision_id": decision_id}
    def human_gate_request(self, gate_request_id, actor_scope): return {"gate_request_id": gate_request_id}
    def replay_reconcile_findings(self, project_id, actor_scope): return {"project_id": project_id, "findings": []}
    def docker_process_observations(self, process_id, actor_scope): return {"process_id": process_id, "observations": []}


class Gateway:
    def submit_human_gate_decision(self, payload): return {"status": "REJECTED"}


class ErrorUnderstandingApi:
    def __init__(self, code): self.code = code; self.calls = 0
    def generate(self, *args): self.calls += 1; raise EntryUnderstandingRejected(self.code)
    def answer_clarification(self, *args): self.calls += 1; raise EntryUnderstandingRejected(self.code)
    def get(self, *args): raise EntryUnderstandingRejected(self.code)
    def list_revisions(self, *args): raise EntryUnderstandingRejected(self.code)
    def list_clarifications(self, *args): raise EntryUnderstandingRejected(self.code)


def verifier_and_key():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk.update({"kid": "e2x-envelope-kid", "alg": "RS256"})
    return OidcTokenVerifier(OidcConfig(issuer="https://issuer.example", audience="hermes-api"), StaticJwksProvider({"keys": [jwk]})), private_key


class E2xFastApiErrorEnvelopeTests(unittest.TestCase):
    matrix = {
        "ENTRY_UNDERSTANDING_PROVIDER_UNAVAILABLE": 503,
        "ENTRY_UNDERSTANDING_CONFIGURATION_ERROR": 503,
        "ENTRY_UNDERSTANDING_PROVIDER_TIMEOUT": 503,
        "ENTRY_UNDERSTANDING_PROVIDER_RATE_LIMITED": 503,
        "ENTRY_UNDERSTANDING_PROVIDER_SERVER_ERROR": 503,
        "ENTRY_UNDERSTANDING_PROVIDER_AUTH_FAILED": 502,
        "ENTRY_UNDERSTANDING_PROVIDER_BAD_REQUEST": 502,
        "ENTRY_UNDERSTANDING_PROVIDER_INVALID_RESPONSE": 502,
        "ENTRY_UNDERSTANDING_PROVIDER_REQUEST_FAILED": 502,
        "ENTRY_UNDERSTANDING_SCHEMA_INVALID": 422,
        "ENTRY_UNDERSTANDING_DOMAIN_INVALID": 422,
    }

    def token(self):
        now = int(time.time())
        return jwt.encode({"iss": "https://issuer.example", "aud": "hermes-api", "sub": "e2x-user", "exp": now + 300, "nbf": now - 1}, self.key, algorithm="RS256", headers={"kid": "e2x-envelope-kid"})

    def test_representative_stable_codes_use_redacted_semantic_envelope(self):
        for code, expected_status in self.matrix.items():
            with self.subTest(code=code):
                fake = ErrorUnderstandingApi(code)
                app = create_app(ProductApiFacade(EmptyReadModel(), Gateway(), entry_understanding_api=fake), oidc_verifier=self.verifier)
                client = TestClient(app)
                response = client.post('/production-drafts/draft-e2x/understanding', headers={"Authorization": "Bearer " + self.token(), "Idempotency-Key": "e2x-envelope-" + code}, json={"expected_version": 0, "reason": "envelope test", "idempotency_key": "e2x-envelope-" + code, "raw_provider_response": "super-secret-key Authorization: Bearer leaked"})
                self.assertEqual(expected_status, response.status_code)
                body = response.json()
                self.assertIsNone(body["data"])
                self.assertEqual(code, body["error"]["code"])
                self.assertEqual("request rejected", body["error"]["message"])
                self.assertNotIn("super-secret-key", response.text)
                self.assertNotIn("Authorization: Bearer", response.text)
                self.assertEqual(1, fake.calls)

    def test_unauthenticated_request_does_not_call_provider(self):
        fake = ErrorUnderstandingApi("ENTRY_UNDERSTANDING_PROVIDER_SERVER_ERROR")
        app = create_app(ProductApiFacade(EmptyReadModel(), Gateway(), entry_understanding_api=fake), oidc_verifier=self.verifier)
        response = TestClient(app).post('/production-drafts/draft-e2x/understanding', headers={"Idempotency-Key": "e2x-no-auth"}, json={"expected_version": 0, "reason": "no auth"})
        self.assertEqual(401, response.status_code)
        self.assertEqual("FACTORY_HOME_AUTH_REQUIRED", response.json()["error"]["code"])
        self.assertEqual(0, fake.calls)

    def setUp(self):
        self.verifier, self.key = verifier_and_key()


if __name__ == '__main__':
    unittest.main()
