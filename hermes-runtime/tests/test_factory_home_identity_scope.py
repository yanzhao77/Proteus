import json
import time
import unittest
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt import algorithms

from hermes_runtime.application.product_api import ProductApiFacade
from hermes_runtime.domain.models import Actor, ActorType
from hermes_runtime.infrastructure.fastapi_app import create_app
from hermes_runtime.infrastructure.oidc import OidcConfig, OidcTokenVerifier, StaticJwksProvider
from hermes_runtime.infrastructure.postgres_factory_home_read_model import PostgresCreatorActorProjectScope


def verifier_and_signer():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk.update({"kid": "factory-kid", "alg": "RS256"})
    verifier = OidcTokenVerifier(OidcConfig(issuer="https://issuer.example", audience="hermes-api"), StaticJwksProvider({"keys": [jwk]}))
    return verifier, private_key


class Cursor:
    def __init__(self, rows): self.rows = rows
    def fetchall(self): return self.rows


class Connection:
    def __init__(self, rows_by_subject): self.rows_by_subject = rows_by_subject; self.queries = []
    def __enter__(self): return self
    def __exit__(self, *_args): return False
    def execute(self, sql, args): self.queries.append((sql, args)); return Cursor([{"project_id": item} for item in self.rows_by_subject.get(args[0], ())])


class IdentityAwareFactoryReadModel:
    def _subject(self, scope):
        return scope.get("identity_subject") if scope.get("identity_verified") else None
    def factory_home_snapshot(self, scope):
        subject = self._subject(scope)
        return {"availability": "CURRENT" if subject else "NOT_AVAILABLE", "actor_scope": "SCOPED" if subject else "NOT_AVAILABLE", "attention": [], "continuations": [], "outcomes": [], "factory_status": self.factory_status(scope), "drafts": self.production_drafts(scope), "cursor": None, "freshness": "NOT_AVAILABLE", "source": None, "source_version": None, "as_of": None, "reason": None}
    def production_portfolio(self, scope):
        subject = self._subject(scope)
        if not subject: return {"availability": "NOT_AVAILABLE", "reason": "SCOPE_UNAVAILABLE", "items": []}
        project = "project-a" if subject == "user-a" else "project-b" if subject == "user-b" else None
        return {"availability": "CURRENT", "reason": None, "items": [] if project is None else [{"project_id": project, "production_id": project, "display_name": project, "display_state": "IMPLEMENTING", "phase": "IMPLEMENTING", "progress": None, "progress_basis": "NOT_AVAILABLE", "current_summary": None, "owner": None, "gate_count": None, "last_updated": "2026-08-18T10:00:00Z", "as_of": "2026-08-18T10:00:00Z", "freshness": "NOT_AVAILABLE", "source": "projects", "source_version": 1, "links": {}}]}
    def production_snapshot(self, project_id, scope):
        portfolio = self.production_portfolio(scope)
        item = next((item for item in portfolio.get("items", ()) if item["project_id"] == project_id), None)
        return {"availability": "CURRENT" if item else "NOT_AVAILABLE", "reason": None if item else "PRODUCTION_NOT_AVAILABLE", "item": item, "as_of": item["as_of"] if item else None, "freshness": "NOT_AVAILABLE", "source": "projects" if item else None, "source_version": 1 if item else None}
    def gate_attention(self, scope): return {"availability": "CURRENT" if self._subject(scope) else "NOT_AVAILABLE", "reason": None, "items": []}
    def production_drafts(self, scope): return {"availability": "NOT_IMPLEMENTED", "reason": "ENTRY_DRAFT_AUTHORITY_NOT_IMPLEMENTED", "items": []}
    def factory_status(self, scope): return {"availability": "NOT_AVAILABLE", "reason": "FACTORY_STATUS_SOURCE_NOT_IMPLEMENTED", "control_plane": "NOT_AVAILABLE", "workforce": "NOT_AVAILABLE", "event_stream": "NOT_AVAILABLE", "degraded_reasons": []}


class ExistingReadModel:
    def project_status(self, project_id, actor_scope): return {"project_id": project_id}
    def decision_explain(self, decision_id, actor_scope): return {"decision_id": decision_id}
    def human_gate_request(self, gate_request_id, actor_scope): return {"gate_request_id": gate_request_id}
    def replay_reconcile_findings(self, project_id, actor_scope): return {"project_id": project_id, "findings": []}
    def docker_process_observations(self, process_id, actor_scope): return {"process_id": process_id, "observations": []}

class Gateway:
    def submit_human_gate_decision(self, payload): return {"status": "REJECTED"}


class FactoryHomeIdentityScopeTests(unittest.TestCase):
    def setUp(self):
        self.verifier, self.private_key = verifier_and_signer()
        self.client = TestClient(create_app(ProductApiFacade(ExistingReadModel(), Gateway(), IdentityAwareFactoryReadModel()), oidc_verifier=self.verifier))
    def token(self, subject):
        now = int(time.time())
        return jwt.encode({"iss": "https://issuer.example", "aud": "hermes-api", "sub": subject, "exp": now + 300, "nbf": now - 1}, self.private_key, algorithm="RS256", headers={"kid": "factory-kid"})
    def auth(self, subject): return {"Authorization": "Bearer " + self.token(subject)}
    def test_verified_identity_a_and_b_receive_distinct_scoped_portfolios(self):
        a = self.client.get("/factory-home/productions", headers=self.auth("user-a"))
        b = self.client.get("/factory-home/productions", headers=self.auth("user-b"))
        self.assertEqual("project-a", a.json()["data"]["items"][0]["project_id"])
        self.assertEqual("project-b", b.json()["data"]["items"][0]["project_id"])
    def test_missing_or_invalid_identity_fails_closed(self):
        self.assertEqual(401, self.client.get("/factory-home/productions").status_code)
        self.assertEqual(401, self.client.get("/factory-home/productions", headers={"Authorization": "Bearer malformed"}).status_code)
    def test_browser_actor_header_cannot_override_verified_identity(self):
        response = self.client.get("/factory-home/productions", headers={**self.auth("user-a"), "X-Hermes-Actor-ID": "user-b"})
        self.assertEqual(401, response.status_code)
        self.assertEqual("FACTORY_HOME_ACTOR_MISMATCH", response.json()["error"]["code"])
    def test_unauthorized_project_does_not_leak_existence(self):
        response = self.client.get("/factory-home/productions/project-b", headers=self.auth("user-a"))
        self.assertEqual(200, response.status_code)
        self.assertEqual("NOT_AVAILABLE", response.json()["data"]["availability"])
        self.assertIsNone(response.json()["data"]["item"])
    def test_missing_verifier_fails_closed_before_read_model(self):
        client = TestClient(create_app(ProductApiFacade(ExistingReadModel(), Gateway(), IdentityAwareFactoryReadModel())))
        response = client.get("/factory-home/productions", headers=self.auth("user-a"))
        self.assertEqual(503, response.status_code)
        self.assertEqual("FACTORY_HOME_IDENTITY_UNAVAILABLE", response.json()["error"]["code"])
    def test_creator_scope_resolver_uses_verified_subject_and_never_global_scope(self):
        connection = Connection({"user-a": ("project-a",), "user-b": ("project-b",)})
        with patch("hermes_runtime.infrastructure.postgres_factory_home_read_model.psycopg.connect", return_value=connection):
            resolver = PostgresCreatorActorProjectScope("postgresql://ignored")
            self.assertEqual(("project-a",), resolver.project_ids_for({"identity_verified": True, "identity_subject": "user-a", "actor_id": "user-a"}))
            self.assertEqual(("project-b",), resolver.project_ids_for({"identity_verified": True, "identity_subject": "user-b", "actor_id": "user-b"}))
            self.assertIsNone(resolver.project_ids_for({"identity_verified": False, "identity_subject": "user-a", "actor_id": "user-a"}))
            self.assertIsNone(resolver.project_ids_for({"identity_verified": True, "identity_subject": "user-a", "actor_id": "user-b"}))
        self.assertEqual(2, len(connection.queries))

if __name__ == "__main__": unittest.main()
