import time
import unittest
import json

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt import algorithms

from hermes_runtime.application.product_api import ProductApiFacade
from hermes_runtime.application.human_gate_ui import HumanGateUiRejected, HumanGateUiRenderer
from hermes_runtime.infrastructure.fastapi_app import create_app
from hermes_runtime.infrastructure.oidc import OidcConfig, OidcRejected, OidcTokenVerifier, StaticJwksProvider


class ReadModel:
    def project_status(self, project_id, actor_scope):
        return {"project_id": project_id}

    def decision_explain(self, decision_id, actor_scope):
        return {"decision_id": decision_id}

    def human_gate_request(self, gate_request_id, actor_scope):
        return {
            "gate_request_id": gate_request_id,
            "summary": "Approve deployment",
            "question": "Approve guarded resume?",
            "reason": "risk requires approval",
            "risk": "medium",
            "evidence_refs": ("evidence-1",),
            "decision_id": "decision-1",
            "status": "REQUESTED",
        }

    def replay_reconcile_findings(self, project_id, actor_scope):
        return {"findings": []}

    def docker_process_observations(self, process_id, actor_scope):
        return {"observations": []}


class Gateway:
    def submit_human_gate_decision(self, payload):
        return {"status": "ACCEPTED"}


def rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = algorithms.RSAAlgorithm.to_jwk(private_key.public_key())
    jwk = json.loads(public_jwk)
    jwk["kid"] = "kid-1"
    jwk["alg"] = "RS256"
    return private_key, {"keys": [jwk]}


class OidcAndHumanGateUiTests(unittest.TestCase):
    def setUp(self):
        self.private_key, self.jwks = rsa_keypair()
        self.verifier = OidcTokenVerifier(
            OidcConfig(issuer="https://issuer.example", audience="hermes-api"),
            StaticJwksProvider(self.jwks),
        )

    def token(self, **overrides):
        now = int(time.time())
        claims = {
            "iss": "https://issuer.example",
            "aud": "hermes-api",
            "sub": "user-1",
            "exp": now + 300,
            "nbf": now - 1,
            "role": "approver",
        }
        claims.update(overrides)
        return jwt.encode(claims, self.private_key, algorithm="RS256", headers={"kid": "kid-1"})

    def test_oidc_valid_token_maps_to_actor_and_gate_assertion(self):
        identity = self.verifier.verify(self.token())
        self.assertEqual("user-1", identity.actor.actor_id)
        assertion = self.verifier.to_gate_assertion(
            "assert-1",
            identity,
            project_id="project-1",
            task_id=None,
            gate_request_id="gate-1",
            action_scope="project:resume",
        )
        self.assertEqual("user-1", assertion.subject)
        self.assertTrue(assertion.assertion_hash.startswith("sha256:"))

    def test_oidc_negative_security_cases_fail_closed(self):
        with self.assertRaisesRegex(OidcRejected, "OIDC_ALGORITHM_FORBIDDEN"):
            self.verifier.verify(jwt.encode({"sub": "user-1"}, key="", algorithm="none"))
        with self.assertRaisesRegex(OidcRejected, "OIDC_ISSUER_MISMATCH"):
            self.verifier.verify(self.token(iss="https://evil.example"))
        with self.assertRaisesRegex(OidcRejected, "OIDC_AUDIENCE_MISMATCH"):
            self.verifier.verify(self.token(aud="other"))
        with self.assertRaisesRegex(OidcRejected, "OIDC_TOKEN_EXPIRED"):
            self.verifier.verify(self.token(exp=int(time.time()) - 1))
        with self.assertRaisesRegex(OidcRejected, "OIDC_TOKEN_NOT_YET_VALID"):
            self.verifier.verify(self.token(nbf=int(time.time()) + 300))

    def test_production_profile_rejects_local_test_issuer(self):
        with self.assertRaisesRegex(OidcRejected, "OIDC_LOCAL_TEST_ISSUER_FORBIDDEN_IN_PRODUCTION"):
            OidcConfig(
                issuer="local-test",
                audience="hermes-api",
                production_profile=True,
                allow_local_test_issuer=True,
            ).validate()

    def test_human_gate_ui_contains_required_controls_but_no_resume_or_generic_editor(self):
        app = create_app(ProductApiFacade(ReadModel(), Gateway()))
        client = TestClient(app)
        html = client.get("/ui/human-gates/gate-1", headers={"X-Hermes-Actor-ID": "user-1"}).text
        self.assertIn("Human Gate Detail", html)
        self.assertIn("evidence-1", html)
        self.assertIn("Approve", html)
        self.assertIn("Reject", html)
        self.assertIn("Explain/Audit", html)
        self.assertNotIn("project_state", html)
        self.assertNotIn("task_status", html)
        self.assertNotIn("apply_resume", html)

    def test_ui_rejects_secret_payload(self):
        with self.assertRaisesRegex(HumanGateUiRejected, "UI_SECRET_VALUE_FORBIDDEN"):
            HumanGateUiRenderer().render_detail({"gate_request_id": "gate-1", "question": "?", "secret_value": "plain"})


if __name__ == "__main__":
    unittest.main()
