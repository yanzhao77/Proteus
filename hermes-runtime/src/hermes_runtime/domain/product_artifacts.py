import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping, Tuple


ARTIFACT_METADATA_HASH_VERSION = "product-artifact-metadata-hash/1.0"


class ArtifactBoundaryRejected(ValueError):
    pass


@dataclass(frozen=True)
class ArtifactProvenance:
    project_id: str
    task_id: str
    producer_type: str
    producer_id: str
    causation_id: str
    correlation_id: str
    evidence_refs: Tuple[str, ...] = ()


@dataclass(frozen=True)
class StoredArtifact:
    artifact_id: str
    content_hash: str
    media_type: str
    size_bytes: int
    provenance: ArtifactProvenance
    retention_policy: str
    retention_until: str
    storage_ref: str
    archived: bool = False
    purged: bool = False
    tombstone_hash: str = ""


@dataclass(frozen=True)
class RetentionDecision:
    allowed: bool
    action: str
    reason: str
    tombstone_required: bool = True


def content_hash(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def artifact_metadata_hash(artifact: StoredArtifact) -> str:
    material = {
        "hash_version": ARTIFACT_METADATA_HASH_VERSION,
        "artifact_id": artifact.artifact_id,
        "content_hash": artifact.content_hash,
        "media_type": artifact.media_type,
        "size_bytes": artifact.size_bytes,
        "project_id": artifact.provenance.project_id,
        "task_id": artifact.provenance.task_id,
        "producer_type": artifact.provenance.producer_type,
        "producer_id": artifact.provenance.producer_id,
        "causation_id": artifact.provenance.causation_id,
        "correlation_id": artifact.provenance.correlation_id,
        "evidence_refs": sorted(artifact.provenance.evidence_refs),
        "retention_policy": artifact.retention_policy,
        "retention_until": artifact.retention_until,
        "archived": artifact.archived,
        "purged": artifact.purged,
    }
    return "sha256:" + hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def validate_artifact_write(
    artifact_id: str,
    content: bytes,
    media_type: str,
    provenance: ArtifactProvenance,
    retention_policy: str,
) -> None:
    if not artifact_id or not content:
        raise ArtifactBoundaryRejected("ARTIFACT_CONTENT_REQUIRED")
    if not media_type:
        raise ArtifactBoundaryRejected("ARTIFACT_MEDIA_TYPE_REQUIRED")
    if not provenance.project_id or not provenance.producer_id:
        raise ArtifactBoundaryRejected("ARTIFACT_PROVENANCE_REQUIRED")
    if not retention_policy:
        raise ArtifactBoundaryRejected("ARTIFACT_RETENTION_POLICY_REQUIRED")


def decide_retention_action(
    action: str,
    artifact: StoredArtifact,
    now: str,
    dependency_refs: Tuple[str, ...],
) -> RetentionDecision:
    if artifact.purged:
        return RetentionDecision(False, action, "ARTIFACT_ALREADY_PURGED")
    if action not in {"ARCHIVE", "PURGE"}:
        return RetentionDecision(False, action, "RETENTION_ACTION_UNSUPPORTED")
    if artifact.retention_until and now < artifact.retention_until:
        return RetentionDecision(False, action, "RETENTION_NOT_EXPIRED")
    if action == "PURGE" and dependency_refs:
        return RetentionDecision(False, action, "RETENTION_AUTHORITY_DEPENDENCY_ACTIVE")
    return RetentionDecision(True, action, "RETENTION_ALLOWED")


def reject_secret_material(payload: Any) -> None:
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            lowered = str(key).lower()
            if lowered in {"secret", "secret_value", "password", "token", "api_key"} and value:
                raise ArtifactBoundaryRejected("SECRET_VALUE_FORBIDDEN")
            reject_secret_material(value)
    elif isinstance(payload, (tuple, list)):
        for item in payload:
            reject_secret_material(item)
