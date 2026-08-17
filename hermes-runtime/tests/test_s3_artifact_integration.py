import os
import socket
import time
import unittest
from urllib.parse import urlsplit

from hermes_runtime.domain.product_artifacts import ArtifactBoundaryRejected, ArtifactProvenance
from hermes_runtime.infrastructure.s3_artifact_store import S3ArtifactConfig, S3ContentAddressedArtifactStore


S3_URL = os.environ.get("HERMES_TEST_S3_URL")
S3_ACCESS_KEY = os.environ.get("HERMES_TEST_S3_ACCESS_KEY", "hermesminio")
S3_SECRET_KEY = os.environ.get("HERMES_TEST_S3_SECRET_KEY", "hermesminio-secret")
S3_BUCKET = os.environ.get("HERMES_TEST_S3_BUCKET", "hermes-p5-test")


def _s3_ready() -> bool:
    try:
        parts = urlsplit(S3_URL)
        with socket.create_connection((parts.hostname, parts.port or 9000), timeout=1):
            return True
    except OSError:
        return False


@unittest.skipUnless(S3_URL, "requires real S3-compatible endpoint via HERMES_TEST_S3_URL")
class S3ArtifactIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import boto3
        from botocore.exceptions import ClientError

        deadline = time.time() + 30
        while time.time() < deadline:
            if _s3_ready():
                break
            time.sleep(0.5)
        else:
            raise unittest.SkipTest("S3 endpoint not reachable")
        cls.client = boto3.client(
            "s3",
            endpoint_url=S3_URL,
            aws_access_key_id=S3_ACCESS_KEY,
            aws_secret_access_key=S3_SECRET_KEY,
            region_name="us-east-1",
        )
        try:
            cls.client.create_bucket(Bucket=S3_BUCKET)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code not in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
                raise
        cls.store = S3ContentAddressedArtifactStore(cls.client, S3ArtifactConfig(S3_BUCKET))

    def _provenance(self):
        return ArtifactProvenance("project-1", "task-1", "worker", "worker-1", "evt-1", "corr-1")

    def test_put_read_and_content_address(self):
        artifact = self.store.put(
            "artifact-1",
            b"verified p5 output",
            "text/plain",
            self._provenance(),
            "short",
            "2026-08-17T00:00:00Z",
        )
        self.assertTrue(artifact.content_hash.startswith("sha256:"))
        self.assertIn("s3://", artifact.storage_ref)
        self.assertEqual(b"verified p5 output", self.store.read(artifact))

    def test_duplicate_put_is_idempotent_and_hash_bound(self):
        first = self.store.put("artifact-2", b"same bytes", "text/plain", self._provenance(), "short", "")
        second = self.store.put("artifact-2", b"same bytes", "text/plain", self._provenance(), "short", "")
        self.assertEqual(first.content_hash, second.content_hash)
        self.assertEqual(first.storage_ref, second.storage_ref)

    def test_tampered_object_fails_closed_with_hash_mismatch(self):
        artifact = self.store.put("artifact-3", b"original bytes", "text/plain", self._provenance(), "short", "")
        key = artifact.storage_ref[len("s3://{}/".format(S3_BUCKET)):]
        self.client.put_object(
            Bucket=S3_BUCKET,
            Key=key,
            Body=b"tampered",
            ContentType="text/plain",
            Metadata={"content-hash": artifact.content_hash},
        )
        with self.assertRaisesRegex(ArtifactBoundaryRejected, "ARTIFACT_HASH_MISMATCH"):
            self.store.read(artifact)

    def test_tombstone_preserves_hash_and_retention(self):
        artifact = self.store.put("artifact-4", b"retained", "text/plain", self._provenance(), "long", "2027-01-01T00:00:00Z")
        tombstone = self.store.tombstone(artifact)
        self.assertEqual(tombstone["content_hash"], artifact.content_hash)
        self.assertEqual(tombstone["storage_ref"], artifact.storage_ref)
        self.assertEqual(tombstone["retention_policy"], "long")


if __name__ == "__main__":
    unittest.main()
