import unittest

from botocore.exceptions import ClientError

from hermes_runtime.domain.observability import ObservabilityRecord, ObservabilityRejected, missing_link
from hermes_runtime.domain.product_artifacts import ArtifactBoundaryRejected, ArtifactProvenance
from hermes_runtime.domain.secret_handles import SecretBoundaryRejected
from hermes_runtime.infrastructure.otlp_exporter import OtlpExporter, OtlpExporterConfig
from hermes_runtime.infrastructure.s3_artifact_store import S3ArtifactConfig, S3ContentAddressedArtifactStore
from hermes_runtime.infrastructure.vault_secrets import VaultKv2Config, VaultKv2SecretManager


class FakeS3:
    def __init__(self):
        self.objects = {}

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        obj = self.objects[Key]
        return {"Metadata": obj["Metadata"]}

    def put_object(self, Bucket, Key, Body, ContentType, Metadata):
        self.objects[Key] = {"Body": Body, "ContentType": ContentType, "Metadata": Metadata}

    def get_object(self, Bucket, Key):
        class Body:
            def __init__(self, value):
                self._value = value

            def read(self):
                return self._value

        return {"Body": Body(self.objects[Key]["Body"])}


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


class FakeHttp:
    def __init__(self, status_code=200, fail=False):
        self.requests = []
        self.status_code = status_code
        self.fail = fail

    def post(self, endpoint, json, timeout):
        if self.fail:
            raise RuntimeError("backend down secret=not-leaked")
        self.requests.append((endpoint, json, timeout))
        return type("Response", (), {"status_code": self.status_code})()


class ProductionAdaptersTests(unittest.TestCase):
    def provenance(self):
        return ArtifactProvenance("project-1", "task-1", "worker", "worker-1", "evt-1", "corr-1")

    def test_s3_artifact_adapter_is_content_addressed_and_hash_checked(self):
        fake = FakeS3()
        store = S3ContentAddressedArtifactStore(fake, S3ArtifactConfig(bucket="hermes-artifacts"))
        artifact = store.put("artifact-1", b"payload", "text/plain", self.provenance(), "short", "2026-01-01T00:00:00Z")
        self.assertTrue(artifact.storage_ref.startswith("s3://hermes-artifacts/artifacts/"))
        self.assertEqual(b"payload", store.read(artifact))
        fake.objects[next(iter(fake.objects))]["Body"] = b"tampered"
        with self.assertRaisesRegex(ArtifactBoundaryRejected, "ARTIFACT_HASH_MISMATCH"):
            store.read(artifact)

    def test_vault_secret_adapter_returns_handles_and_requires_execution_auth_to_resolve(self):
        vault = FakeVault()
        manager = VaultKv2SecretManager(vault, VaultKv2Config())
        handle = manager.register("secret-1", "plain-secret", "project-1", {"purpose": "docker"})
        metadata = manager.get_metadata("secret-1")
        self.assertEqual(handle, metadata)
        self.assertNotIn("plain-secret", repr(metadata))
        with self.assertRaisesRegex(SecretBoundaryRejected, "SECRET_RESOLUTION_UNAUTHORIZED"):
            manager.resolve_for_execution("secret-1", authorized_execution=False)
        self.assertEqual("plain-secret", manager.resolve_for_execution("secret-1", authorized_execution=True))

    def test_otlp_exporter_redacts_bounds_and_backend_failure_does_not_raise(self):
        client = FakeHttp()
        exporter = OtlpExporter(OtlpExporterConfig("http://otlp.example/v1/traces", max_queue_size=1), client)
        record = ObservabilityRecord(
            trace_id="trace-1",
            span_id="span-1",
            parent_span_id="",
            name="api.request",
            timestamp="2026-08-14T00:00:00Z",
            attributes={"token": "secret-token"},
            missing_links=(missing_link("evidence", "e1", "redacted"),),
        )
        self.assertEqual("QUEUED", exporter.enqueue(record)["status"])
        self.assertEqual("DROPPED", exporter.enqueue(record)["status"])
        self.assertEqual("EXPORTED", exporter.flush_once()["status"])
        self.assertEqual("[REDACTED]", client.requests[0][1]["attributes"]["token"])

        failing = OtlpExporter(OtlpExporterConfig("http://otlp.example/v1/traces"), FakeHttp(fail=True))
        failing.enqueue(record)
        self.assertEqual("EXPORT_FAILED", failing.flush_once()["status"])
        self.assertEqual(1, failing.stats["failed_exports"])

    def test_otlp_exporter_rejects_authorizing_metric_payloads(self):
        exporter = OtlpExporter(OtlpExporterConfig("http://otlp.example/v1/traces"), FakeHttp())
        with self.assertRaisesRegex(ObservabilityRejected, "OBSERVABILITY_CANNOT_AUTHORIZE"):
            exporter.enqueue(
                ObservabilityRecord(
                    trace_id="trace-1",
                    span_id="span-1",
                    parent_span_id="",
                    name="unsafe",
                    timestamp="2026-08-14T00:00:00Z",
                    attributes={"task_passed": True},
                )
            )


if __name__ == "__main__":
    unittest.main()
