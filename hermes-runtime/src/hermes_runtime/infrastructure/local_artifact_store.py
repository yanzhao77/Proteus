from pathlib import Path
from typing import Dict, Tuple

from hermes_runtime.domain.product_artifacts import (
    ArtifactBoundaryRejected,
    ArtifactProvenance,
    StoredArtifact,
    artifact_metadata_hash,
    content_hash,
    decide_retention_action,
    validate_artifact_write,
)


class LocalContentAddressedArtifactStore:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._records: Dict[str, StoredArtifact] = {}

    def put(
        self,
        artifact_id: str,
        content: bytes,
        media_type: str,
        provenance: ArtifactProvenance,
        retention_policy: str,
        retention_until: str,
    ) -> StoredArtifact:
        validate_artifact_write(artifact_id, content, media_type, provenance, retention_policy)
        digest = content_hash(content)
        existing = self._records.get(artifact_id)
        if existing and existing.content_hash != digest:
            raise ArtifactBoundaryRejected("ARTIFACT_OVERWRITE_FORBIDDEN")
        storage_ref = self._storage_ref(digest)
        path = self._path_for_hash(digest)
        if not path.exists():
            path.write_bytes(content)
        record = existing or StoredArtifact(
            artifact_id=artifact_id,
            content_hash=digest,
            media_type=media_type,
            size_bytes=len(content),
            provenance=provenance,
            retention_policy=retention_policy,
            retention_until=retention_until,
            storage_ref=storage_ref,
        )
        self._records[artifact_id] = record
        return record

    def get_metadata(self, artifact_id: str) -> StoredArtifact:
        return self._records[artifact_id]

    def read_content(self, artifact_id: str) -> bytes:
        record = self.get_metadata(artifact_id)
        if record.purged:
            raise ArtifactBoundaryRejected("ARTIFACT_CONTENT_PURGED")
        return self._path_for_hash(record.content_hash).read_bytes()

    def archive(self, artifact_id: str, now: str) -> StoredArtifact:
        record = self.get_metadata(artifact_id)
        decision = decide_retention_action("ARCHIVE", record, now, ())
        if not decision.allowed:
            raise ArtifactBoundaryRejected(decision.reason)
        archived = StoredArtifact(**{**record.__dict__, "archived": True, "tombstone_hash": artifact_metadata_hash(record)})
        self._records[artifact_id] = archived
        return archived

    def purge_raw_content(self, artifact_id: str, now: str, dependency_refs: Tuple[str, ...]) -> StoredArtifact:
        record = self.get_metadata(artifact_id)
        decision = decide_retention_action("PURGE", record, now, dependency_refs)
        if not decision.allowed:
            raise ArtifactBoundaryRejected(decision.reason)
        path = self._path_for_hash(record.content_hash)
        if path.exists():
            path.unlink()
        purged = StoredArtifact(
            **{
                **record.__dict__,
                "purged": True,
                "archived": True,
                "tombstone_hash": artifact_metadata_hash(record),
            }
        )
        self._records[artifact_id] = purged
        return purged

    def _path_for_hash(self, digest: str) -> Path:
        return self._root / digest.replace("sha256:", "")

    def _storage_ref(self, digest: str) -> str:
        return "local-cas:{}".format(digest)
