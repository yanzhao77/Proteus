from dataclasses import dataclass
from typing import Mapping

from botocore.exceptions import ClientError

from hermes_runtime.domain.product_artifacts import (
    ArtifactBoundaryRejected,
    ArtifactProvenance,
    StoredArtifact,
    content_hash,
    validate_artifact_write,
)


@dataclass(frozen=True)
class S3ArtifactConfig:
    bucket: str
    prefix: str = "artifacts/"


class S3ContentAddressedArtifactStore:
    def __init__(self, client, config: S3ArtifactConfig) -> None:
        self._client = client
        self._config = config

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
        key = self._key(digest)
        existing = self._head(key)
        if existing and existing.get("Metadata", {}).get("content-hash") != digest:
            raise ArtifactBoundaryRejected("ARTIFACT_HASH_MISMATCH")
        if not existing:
            self._client.put_object(
                Bucket=self._config.bucket,
                Key=key,
                Body=content,
                ContentType=media_type,
                Metadata={
                    "artifact-id": artifact_id,
                    "content-hash": digest,
                    "project-id": provenance.project_id,
                    "task-id": provenance.task_id,
                    "retention-policy": retention_policy,
                    "retention-until": retention_until,
                },
            )
        return StoredArtifact(
            artifact_id=artifact_id,
            content_hash=digest,
            media_type=media_type,
            size_bytes=len(content),
            provenance=provenance,
            retention_policy=retention_policy,
            retention_until=retention_until,
            storage_ref=f"s3://{self._config.bucket}/{key}",
        )

    def read(self, artifact: StoredArtifact) -> bytes:
        key = self._key(artifact.content_hash)
        response = self._client.get_object(Bucket=self._config.bucket, Key=key)
        content = response["Body"].read()
        if content_hash(content) != artifact.content_hash:
            raise ArtifactBoundaryRejected("ARTIFACT_HASH_MISMATCH")
        return content

    def tombstone(self, artifact: StoredArtifact) -> Mapping[str, str]:
        return {
            "artifact_id": artifact.artifact_id,
            "content_hash": artifact.content_hash,
            "storage_ref": artifact.storage_ref,
            "retention_policy": artifact.retention_policy,
        }

    def _key(self, digest: str) -> str:
        suffix = digest.replace("sha256:", "")
        if "/" in suffix or ".." in suffix:
            raise ArtifactBoundaryRejected("ARTIFACT_STORAGE_KEY_UNSAFE")
        return "{}{}".format(self._config.prefix.rstrip("/") + "/", suffix)

    def _head(self, key: str):
        try:
            return self._client.head_object(Bucket=self._config.bucket, Key=key)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise
        except KeyError:
            return None
