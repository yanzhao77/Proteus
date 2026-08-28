import json
import time
import unittest

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt import algorithms

from hermes_runtime.application.product_api import ProductApiFacade
from hermes_runtime.application.supervisor import OneShotCallableRole, RuntimeSupervisor, ServiceCriticality, ServiceLoopConfig, SupervisedServiceLoop
from hermes_runtime.domain.models import Actor, ActorType
from hermes_runtime.domain.observability import ObservabilityRecord, ObservabilityRejected, missing_link
from hermes_runtime.domain.product_artifacts import ArtifactBoundaryRejected, ArtifactProvenance
from hermes_runtime.domain.product_api import ProductApiRejected
from hermes_runtime.infrastructure.fastapi_app import create_app
from hermes_runtime.infrastructure.oidc import OidcConfig, OidcRejected, OidcTokenVerifier, StaticJwksProvider
from hermes_runtime.infrastructure.otlp_exporter import OtlpExporter, OtlpExporterConfig
from hermes_runtime.infrastructure.s3_artifact_store import S3ArtifactConfig, S3ContentAddressedArtifactStore
from hermes_runtime.infrastructure.vault_secrets import VaultKv2Config, VaultKv2SecretManager


class ReadModel:
    def project_status(self, project_id, actor_scope):
        return {"project_id": project_id, "state_summary": "WAITING_FOR_HUMAN"}

    def decision_explain(self, decision_id, actor_scope):
        return {"decision_id": decision_id, "snapshot_id": "explain-fixed", "missing_links": [{"kind": "MISSING"}]}

    def human_gate_request(self, gate_request_id, actor_scope):
        return {
            "gate_request_id": gate_request_id,
            "summary": "Approve verified artifact",
            "question": "Approve guarded continuation?",
            "reason": "policy requires human approval",
            "risk": "medium",
            "evidence_refs": ("evidence-1",),
            "decision_id": "decision-1",
            "status": "REQUESTED",
        }

    def replay_reconcile_findings(self, project_id, actor_scope):
        return {"project_id": project_id, "findings": [{"kind": "EFFECT_BEFORE_RECEIPT", "status": "OBSERVED"}]}

    def docker_process_observations(self, process_id, actor_scope):
        return {"process_id": process_id, "observations": [{"state": "EXITED", "task_authority": "NONE"}]}


class Gateway:
    def __init__(self):
        self.payloads = []

    def submit_human_gate_decision(self, payload):
        self.payloads.append(dict(payload))
        return {"status": "ACCEPTED", "command_id": payload["command_id"]}


class FakeS3:
    def __init__(self):
        self.objects = {}

    def head_object(self, Bucket, Key):
        from botocore.exceptions import ClientError

        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        return {"Metadata": self.objects[Key]["Metadata"]}

    def put_object(self, Bucket, Key, Body, ContentType, Metadata):
        self.objects[Key] = {"Body": Body, "ContentType": ContentType, "Metadata": Metadata}

    def get_object(self, Bucket, Key):
        class Body:
            def __init__(self, value):
                self._value = value

            def read(self):
                return self._value

        return {"Body": Body(self.objects[Key]["Body"])}


class FakeHttp:
    def __init__(self, fail=False):
        self.fail = fail
        self.requests = []

    def post(self, endpoint, json, timeout):
        if self.fail:
            raise RuntimeError("backend down")
        self.requests.append((endpoint, json, timeout))
        return type("Response", (), {"status_code": 200})()


class FakeVaultKv2:
    def __init__(self):
        self.data = {}

    def create_or_update_secret(self, mount_point, path, secret):
        self.data[(mount_point, path)] = secret

    def read_secret_version(self, mount_point, path):
        return {"data": {"data": self.data[(mount_point, path)]}}


class FakeVault:
    def __init__(self):
        self.secrets = type("Secrets", (), {})()
        self.secrets.kv = type("Kv", (), {})()
        self.secrets.kv.v2 = FakeVaultKv2()


def rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk["kid"] = "kid-1"
    jwk["alg"] = "RS256"
    return private_key, {"keys": [jwk]}


class P5EndToEndProductHardeningTests(unittest.TestCase):
    def test_authenticated_api_to_gate_artifact_secret_explain_observability_loop(self):
        key, jwks = rsa_keypair()
        now = int(time.time())
        token = jwt.encode(
            {
                "iss": "https://issuer.example",
                "aud": "hermes-api",
                "sub": "user-1",
                "exp": now + 300,
                "nbf": now - 1,
            },
            key,
            algorithm="RS256",
            headers={"kid": "kid-1"},
        )
        identity = OidcTokenVerifier(
            OidcConfig("https://issuer.example", "hermes-api"),
            StaticJwksProvider(jwks),
        ).verify(token)
        self.assertEqual("user-1", identity.actor.actor_id)

        gateway = Gateway()
        client = TestClient(create_app(ProductApiFacade(ReadModel(), gateway)))
        gate = client.get("/ui/human-gates/gate-1", headers={"X-Hermes-Actor-ID": identity.subject})
        self.assertEqual(200, gate.status_code)
        self.assertIn("Approve", gate.text)

        decision = client.post(
            "/human-gates/gate-1/decisions",
            headers={"Idempotency-Key": "idem-1", "X-Request-ID": "req-1"},
            json={
                "command_id": "cmd-1",
                "expected_version": 1,
                "actor": {"type": "user", "id": identity.subject},
                "reason": "approve after evidence review",
                "decision": "APPROVE",
            },
        )
        self.assertEqual(503, decision.status_code)
        self.assertEqual("FACTORY_HOME_IDENTITY_UNAVAILABLE", decision.json()["error"]["code"])

        s3_store = S3ContentAddressedArtifactStore(FakeS3(), S3ArtifactConfig("bucket"))
        artifact = s3_store.put(
            "artifact-1",
            b"verified output",
            "text/plain",
            ArtifactProvenance("project-1", "task-1", "worker", "worker-1", "evt-1", "corr-1"),
            "short",
            "2026-01-01T00:00:00Z",
        )
        self.assertEqual(artifact.content_hash, s3_store.tombstone(artifact)["content_hash"])

        secret_manager = VaultKv2SecretManager(FakeVault(), VaultKv2Config())
        handle = secret_manager.register("secret-1", "secret-canary-value", "project-1", {"purpose": "execution"})
        self.assertNotIn("secret-canary-value", repr(handle))

        otlp_client = FakeHttp()
        otlp = OtlpExporter(OtlpExporterConfig("http://otel/v1/traces"), otlp_client)
        otlp.enqueue(
            ObservabilityRecord(
                trace_id="trace-1",
                span_id="span-1",
                parent_span_id="",
                name="p5.e2e",
                timestamp="2026-08-14T00:00:00Z",
                attributes={"secret_value": "secret-canary-value"},
                missing_links=(missing_link("evidence", "evidence-redacted", "MISSING"),),
            )
        )
        self.assertEqual("EXPORTED", otlp.flush_once()["status"])
        exported = repr(otlp_client.requests)
        self.assertNotIn("secret-canary-value", exported)
        self.assertIn("[REDACTED]", exported)

        explain = client.get("/decisions/decision-1/explain")
        self.assertEqual("explain-fixed", explain.json()["data"]["snapshot_id"])

    def test_fault_injections_fail_closed_without_authority_bypass(self):
        key, jwks = rsa_keypair()
        expired = jwt.encode(
            {
                "iss": "https://issuer.example",
                "aud": "hermes-api",
                "sub": "user-1",
                "exp": int(time.time()) - 1,
                "nbf": int(time.time()) - 10,
            },
            key,
            algorithm="RS256",
            headers={"kid": "kid-1"},
        )
        verifier = OidcTokenVerifier(OidcConfig("https://issuer.example", "hermes-api"), StaticJwksProvider(jwks))
        with self.assertRaisesRegex(OidcRejected, "OIDC_TOKEN_EXPIRED"):
            verifier.verify(expired)

        client = TestClient(create_app(ProductApiFacade(ReadModel(), Gateway())))
        self.assertEqual(405, client.patch("/projects/project-1/status", json={"state": "ACCEPTED"}).status_code)
        denied = client.post(
            "/human-gates/gate-1/decisions",
            headers={"Idempotency-Key": "idem-1"},
            json={"command_id": "cmd", "gate_decision_id": "decision", "expected_gate_version": 1, "reason": "x", "decision": "APPROVE"},
        )
        self.assertEqual(503, denied.status_code)
        self.assertEqual("FACTORY_HOME_IDENTITY_UNAVAILABLE", denied.json()["error"]["code"])

        s3 = FakeS3()
        store = S3ContentAddressedArtifactStore(s3, S3ArtifactConfig("bucket"))
        artifact = store.put("artifact-1", b"payload", "text/plain", ArtifactProvenance("p", "t", "worker", "w", "e", "c"), "short", "")
        s3.objects[next(iter(s3.objects))]["Body"] = b"tampered"
        with self.assertRaisesRegex(ArtifactBoundaryRejected, "ARTIFACT_HASH_MISMATCH"):
            store.read(artifact)

        with self.assertRaises(Exception):
            VaultKv2SecretManager(FakeVault(), VaultKv2Config()).resolve_for_execution("missing", authorized_execution=False)

        failing_otlp = OtlpExporter(OtlpExporterConfig("http://otel/v1/traces"), FakeHttp(fail=True))
        failing_otlp.enqueue(ObservabilityRecord("trace", "span", "", "obs", "2026-08-14T00:00:00Z", {"route": "/readyz"}))
        self.assertEqual("EXPORT_FAILED", failing_otlp.flush_once()["status"])
        with self.assertRaisesRegex(ObservabilityRejected, "OBSERVABILITY_CANNOT_AUTHORIZE"):
            failing_otlp.enqueue(ObservabilityRecord("trace", "span2", "", "bad", "2026-08-14T00:00:00Z", {"gate_approved": True}))

        def failing(_batch_size, _stop_event):
            raise RuntimeError("db temporarily unavailable")

        loop = SupervisedServiceLoop(
            OneShotCallableRole("scheduler", failing, ServiceCriticality.CRITICAL, True),
            ServiceLoopConfig(initial_backoff_seconds=0, poll_interval_seconds=0, max_consecutive_failures=1),
            sleep=lambda _seconds: None,
        )
        loop.run_forever(max_iterations=1)
        self.assertFalse(RuntimeSupervisor((loop,)).readiness()["ready"])

    def test_secret_canary_absent_from_api_ui_and_openapi(self):
        client = TestClient(create_app(ProductApiFacade(ReadModel(), Gateway())))
        for response in (
            client.get("/openapi.json"),
            client.get("/ui/human-gates/gate-1"),
            client.get("/projects/project-1/status"),
        ):
            self.assertNotIn("secret-canary-value", response.text)
            self.assertNotIn("secret_value", response.text)


if __name__ == "__main__":
    unittest.main()
