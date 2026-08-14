import tempfile
import unittest
from pathlib import Path

from hermes_runtime.domain.product_artifacts import (
    ArtifactBoundaryRejected,
    ArtifactProvenance,
    content_hash,
    reject_secret_material,
)
from hermes_runtime.domain.secret_handles import SecretBoundaryRejected, assert_handle_only
from hermes_runtime.infrastructure.local_artifact_store import LocalContentAddressedArtifactStore
from hermes_runtime.infrastructure.local_secrets import LocalSecretHandleProvider


class ArtifactSecretRetentionBoundaryTests(unittest.TestCase):
    def _provenance(self):
        return ArtifactProvenance(
            project_id="project-1",
            task_id="task-1",
            producer_type="worker",
            producer_id="worker-1",
            causation_id="evt-1",
            correlation_id="corr-1",
            evidence_refs=("evidence-1",),
        )

    def test_content_addressed_artifact_is_deterministic_and_immutable(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalContentAddressedArtifactStore(Path(tmp))
            left = store.put("artifact-1", b"hello", "text/plain", self._provenance(), "short", "2026-01-01T00:00:00Z")
            right = store.put("artifact-1", b"hello", "text/plain", self._provenance(), "short", "2026-01-01T00:00:00Z")
            self.assertEqual(content_hash(b"hello"), left.content_hash)
            self.assertEqual(left, right)
            with self.assertRaisesRegex(ArtifactBoundaryRejected, "ARTIFACT_OVERWRITE_FORBIDDEN"):
                store.put("artifact-1", b"changed", "text/plain", self._provenance(), "short", "2026-01-01T00:00:00Z")

    def test_secret_handle_provider_never_returns_secret_value_to_payloads(self):
        provider = LocalSecretHandleProvider()
        handle = provider.register("secret-1", "super-secret-value", "project-1", {"kind": "api-token"})
        metadata = provider.get_metadata("secret-1")
        self.assertEqual(handle, metadata)
        self.assertNotIn("super-secret-value", repr(metadata))
        assert_handle_only({"secret_handle": handle.handle_id})
        reject_secret_material({"artifact": {"secret_handle": handle.handle_id}})
        with self.assertRaisesRegex(SecretBoundaryRejected, "SECRET_VALUE_FORBIDDEN"):
            assert_handle_only({"secret_value": "super-secret-value"})
        with self.assertRaisesRegex(SecretBoundaryRejected, "SECRET_VALUE_FORBIDDEN"):
            provider.assert_no_registered_secret_value({"log": "super-secret-value"})

    def test_retention_preserves_tombstone_and_blocks_active_authority_dependency(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalContentAddressedArtifactStore(Path(tmp))
            record = store.put("artifact-1", b"payload", "text/plain", self._provenance(), "short", "2026-01-01T00:00:00Z")
            with self.assertRaisesRegex(ArtifactBoundaryRejected, "RETENTION_AUTHORITY_DEPENDENCY_ACTIVE"):
                store.purge_raw_content("artifact-1", "2027-01-01T00:00:00Z", ("verification-1",))
            archived = store.archive("artifact-1", "2027-01-01T00:00:00Z")
            self.assertTrue(archived.archived)
            purged = store.purge_raw_content("artifact-1", "2027-01-01T00:00:00Z", ())
            self.assertTrue(purged.purged)
            self.assertEqual(record.content_hash, purged.content_hash)
            self.assertTrue(purged.tombstone_hash.startswith("sha256:"))
            with self.assertRaisesRegex(ArtifactBoundaryRejected, "ARTIFACT_CONTENT_PURGED"):
                store.read_content("artifact-1")


if __name__ == "__main__":
    unittest.main()
