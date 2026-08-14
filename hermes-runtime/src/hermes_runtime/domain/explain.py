import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence, Tuple


EXPLAIN_HASH_VERSION = "decision-explain-snapshot-hash/1.0"
MAX_EXPLAIN_NODES = 256
MAX_EXPLAIN_EDGES = 512
SECRET_PATTERN = re.compile(
    r"(api[_-]?token|password|credential|private[_-]?key|secret[_-]?value|"
    r"private key|sk-[A-Za-z0-9]{12,}|password=)",
    re.IGNORECASE,
)


class ExplainRejected(ValueError):
    pass


class ExplainNodeStatus(str, Enum):
    PRESENT = "PRESENT"
    MISSING = "MISSING"
    REDACTED = "REDACTED"


class RedactionClass(str, Enum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    RESTRICTED = "RESTRICTED"
    SECRET_HANDLE = "SECRET_HANDLE"


@dataclass(frozen=True)
class ExplainNode:
    node_id: str
    node_type: str
    ref_id: str
    ref_version: int
    ref_hash: str
    status: ExplainNodeStatus = ExplainNodeStatus.PRESENT
    missing_reason: str = ""
    safe_summary: Mapping[str, Any] = None

    def normalized(self) -> Mapping[str, Any]:
        status = self.status if isinstance(self.status, ExplainNodeStatus) else ExplainNodeStatus(self.status)
        if status is ExplainNodeStatus.MISSING and not self.missing_reason:
            raise ExplainRejected("MISSING_IMMUTABLE_FACT_LINK")
        if status is not ExplainNodeStatus.MISSING and self.missing_reason:
            raise ExplainRejected("EXPLAIN_SNAPSHOT_CONFLICT")
        return {
            "node_id": _require_atom(self.node_id, "EXPLAIN_SNAPSHOT_CONFLICT"),
            "node_type": _require_atom(self.node_type, "EXPLAIN_SNAPSHOT_CONFLICT"),
            "ref_id": str(self.ref_id or ""),
            "ref_version": int(self.ref_version),
            "ref_hash": _require_hash(self.ref_hash, "MISSING_IMMUTABLE_FACT_LINK")
            if status is not ExplainNodeStatus.MISSING
            else str(self.ref_hash or ""),
            "status": status.value,
            "missing_reason": self.missing_reason,
            "safe_summary": _safe_json(self.safe_summary or {}),
        }


@dataclass(frozen=True)
class ExplainEdge:
    from_node_id: str
    to_node_id: str
    relation: str

    def normalized(self) -> Mapping[str, Any]:
        return {
            "from_node_id": _require_atom(self.from_node_id, "EXPLAIN_SNAPSHOT_CONFLICT"),
            "to_node_id": _require_atom(self.to_node_id, "EXPLAIN_SNAPSHOT_CONFLICT"),
            "relation": _require_atom(self.relation, "EXPLAIN_SNAPSHOT_CONFLICT"),
        }


@dataclass(frozen=True)
class ExplainSnapshotInput:
    project_id: str
    source_type: str
    source_id: str
    source_version: int
    source_hash: str
    schema_version: str
    producer_version: str
    summary: Mapping[str, Any]
    nodes: Sequence[ExplainNode]
    edges: Sequence[ExplainEdge]
    redaction_class: RedactionClass
    retention_policy: str
    authorization_scope: Mapping[str, Any]


def build_explain_snapshot(snapshot: ExplainSnapshotInput) -> Mapping[str, Any]:
    nodes = tuple(node.normalized() for node in snapshot.nodes)
    edges = tuple(edge.normalized() for edge in snapshot.edges)
    if len(nodes) == 0 or len(nodes) > MAX_EXPLAIN_NODES:
        raise ExplainRejected("EXPLAIN_SNAPSHOT_CONFLICT")
    if len(edges) > MAX_EXPLAIN_EDGES:
        raise ExplainRejected("EXPLAIN_SNAPSHOT_CONFLICT")
    _assert_unique(node["node_id"] for node in nodes)
    _assert_edges_reference_nodes(nodes, edges)
    _assert_acyclic(edges)
    redaction_class = (
        snapshot.redaction_class
        if isinstance(snapshot.redaction_class, RedactionClass)
        else RedactionClass(snapshot.redaction_class)
    )
    payload = {
        "hash_version": EXPLAIN_HASH_VERSION,
        "project_id": _require_atom(snapshot.project_id, "TRACE_SCOPE_MISMATCH"),
        "source_type": _require_atom(snapshot.source_type, "EXPLAIN_SNAPSHOT_CONFLICT"),
        "source_id": _require_atom(snapshot.source_id, "EXPLAIN_SNAPSHOT_CONFLICT"),
        "source_version": int(snapshot.source_version),
        "source_hash": _require_hash(snapshot.source_hash, "EXPLAIN_SOURCE_VERSION_MISMATCH"),
        "schema_version": _require_ref(snapshot.schema_version, "EXPLAIN_SNAPSHOT_CONFLICT"),
        "producer_version": _require_ref(snapshot.producer_version, "EXPLAIN_SNAPSHOT_CONFLICT"),
        "summary": _safe_json(snapshot.summary),
        "nodes": sorted(nodes, key=lambda item: item["node_id"]),
        "edges": sorted(edges, key=lambda item: (item["from_node_id"], item["to_node_id"], item["relation"])),
        "redaction_class": redaction_class.value,
        "retention_policy": _require_ref(snapshot.retention_policy, "RETENTION_REDACTION_VIOLATION"),
        "authorization_scope": _safe_json(snapshot.authorization_scope),
    }
    _reject_secret(payload)
    return {
        "snapshot_hash": "sha256:" + hashlib.sha256(_canonical_bytes(payload)).hexdigest(),
        "ref_graph_hash": "sha256:"
        + hashlib.sha256(_canonical_bytes({"nodes": payload["nodes"], "edges": payload["edges"]})).hexdigest(),
        "payload": payload,
        "missing_links": [
            {
                "node_id": node["node_id"],
                "node_type": node["node_type"],
                "missing_reason": node["missing_reason"],
            }
            for node in payload["nodes"]
            if node["status"] == ExplainNodeStatus.MISSING.value
        ],
    }


def canonical_payload_hash(value: Mapping[str, Any]) -> str:
    _reject_secret(value)
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _safe_json(value: Mapping[str, Any]) -> Mapping[str, Any]:
    if value is None:
        return {}
    encoded = json.loads(json.dumps(value, sort_keys=True, default=str))
    _reject_secret(encoded)
    return encoded


def _reject_secret(value: Any) -> None:
    if SECRET_PATTERN.search(json.dumps(value, sort_keys=True, default=str)):
        raise ExplainRejected("RETENTION_REDACTION_VIOLATION")


def _assert_unique(values: Iterable[str]) -> None:
    seen = set()
    for value in values:
        if value in seen:
            raise ExplainRejected("EXPLAIN_SNAPSHOT_CONFLICT")
        seen.add(value)


def _assert_edges_reference_nodes(nodes: Sequence[Mapping[str, Any]], edges: Sequence[Mapping[str, Any]]) -> None:
    ids = {node["node_id"] for node in nodes}
    for edge in edges:
        if edge["from_node_id"] not in ids or edge["to_node_id"] not in ids:
            raise ExplainRejected("MISSING_IMMUTABLE_FACT_LINK")


def _assert_acyclic(edges: Sequence[Mapping[str, Any]]) -> None:
    graph = {}
    for edge in edges:
        graph.setdefault(edge["from_node_id"], set()).add(edge["to_node_id"])
    visiting = set()
    visited = set()

    def visit(node_id: str) -> None:
        if node_id in visiting:
            raise ExplainRejected("EXPLAIN_SNAPSHOT_CONFLICT")
        if node_id in visited:
            return
        visiting.add(node_id)
        for child in graph.get(node_id, ()):
            visit(child)
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in tuple(graph):
        visit(node_id)


def _require_atom(value: str, reason: str) -> str:
    text = str(value or "")
    if not re.match(r"^[A-Za-z0-9_.:/=-]{1,160}$", text):
        raise ExplainRejected(reason)
    return text


def _require_ref(value: str, reason: str) -> str:
    text = str(value or "")
    if not text or len(text) > 240:
        raise ExplainRejected(reason)
    _reject_secret(text)
    return text


def _require_hash(value: str, reason: str) -> str:
    text = str(value or "")
    if not text.startswith("sha256:"):
        raise ExplainRejected(reason)
    return text
