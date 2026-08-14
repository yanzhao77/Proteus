from enum import Enum
from typing import Any, Mapping, Optional

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.application.explain import CaptureDecisionExplain, QueryDecisionExplain
from hermes_runtime.domain.explain import (
    ExplainRejected,
    ExplainSnapshotInput,
    build_explain_snapshot,
    canonical_payload_hash,
)
from hermes_runtime.infrastructure.postgres_quarantine import PostgresQuarantineStore


class ExplainFaultPoint(str, Enum):
    AFTER_SNAPSHOT_BEFORE_EVENT = "after_snapshot_before_event"
    AFTER_EVENT_BEFORE_AUDIT = "after_event_before_audit"
    AFTER_AUDIT_BEFORE_RECEIPT = "after_audit_before_receipt"


class PostgresExplainStore(PostgresQuarantineStore):
    P3_EXPLAIN_TABLES = (
        "decision_explain_edges",
        "decision_explain_nodes",
        "audit_trace_records",
        "decision_explain_snapshots",
    )

    def __init__(self, dsn: str) -> None:
        super().__init__(dsn)
        self._explain_fault: Optional[ExplainFaultPoint] = None

    def fail_explain_once(self, point: str) -> None:
        self._explain_fault = ExplainFaultPoint(point)

    def reset_for_test(self) -> None:
        with self._connect() as connection:
            connection.execute(
                "TRUNCATE {} RESTART IDENTITY CASCADE".format(
                    ", ".join(self.P3_EXPLAIN_TABLES)
                )
            )
        super().reset_for_test()

    def capture(self, command: CaptureDecisionExplain) -> Mapping[str, Any]:
        try:
            snapshot = build_explain_snapshot(
                ExplainSnapshotInput(
                    project_id=command.project_id,
                    source_type=command.source_type,
                    source_id=command.source_id,
                    source_version=command.source_version,
                    source_hash=command.source_hash,
                    schema_version=command.schema_version,
                    producer_version=command.producer_version,
                    summary=command.summary,
                    nodes=command.nodes,
                    edges=command.edges,
                    redaction_class=command.redaction_class,
                    retention_policy=command.retention_policy,
                    authorization_scope=command.authorization_scope,
                )
            )
            payload = {
                "command": "decision_explain.capture",
                "project_id": command.project_id,
                "source_type": command.source_type,
                "source_id": command.source_id,
                "source_version": command.source_version,
                "expected_source_version": command.expected_source_version,
                "source_hash": command.source_hash,
                "snapshot_hash": snapshot["snapshot_hash"],
                "ref_graph_hash": snapshot["ref_graph_hash"],
                "summary": dict(command.summary),
                "nodes": snapshot["payload"]["nodes"],
                "edges": snapshot["payload"]["edges"],
                "redaction_class": command.redaction_class,
                "retention_policy": command.retention_policy,
                "authorization_scope": dict(command.authorization_scope),
            }
            payload_hash = canonical_payload_hash(payload)
            with self._connect(row_factory=dict_row) as connection:
                row = connection.execute(
                    """SELECT public.hermes_capture_decision_explain(
                       %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                       %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                       ) AS result""",
                    (
                        command.project_id,
                        command.source_type,
                        command.source_id,
                        command.source_version,
                        command.expected_source_version,
                        command.source_hash,
                        command.schema_version,
                        command.producer_version,
                        Jsonb(dict(command.summary)),
                        Jsonb(snapshot["payload"]["nodes"]),
                        Jsonb(snapshot["payload"]["edges"]),
                        snapshot["snapshot_hash"],
                        snapshot["ref_graph_hash"],
                        Jsonb(snapshot["missing_links"]),
                        command.redaction_class,
                        command.retention_policy,
                        command.retention_until,
                        Jsonb(dict(command.authorization_scope)),
                        command.actor.actor_type.value,
                        command.actor.actor_id,
                        command.authorization_ref,
                        command.reason,
                        command.command_id,
                        command.idempotency_key,
                        payload_hash,
                        command.causation_id or None,
                        command.correlation_id or command.command_id,
                        command.trace_id or command.command_id,
                        self._take_explain_fault(),
                    ),
                ).fetchone()
                return dict(row["result"])
        except (ExplainRejected, psycopg.Error) as exc:
            raise CommandRejected(_reason_from_error(exc)) from exc

    def query(self, query: QueryDecisionExplain) -> Mapping[str, Any]:
        try:
            with self._connect(row_factory=dict_row) as connection:
                row = connection.execute(
                    "SELECT public.hermes_query_decision_explain(%s,%s,%s,%s,%s) AS result",
                    (
                        query.project_id,
                        query.snapshot_id,
                        query.actor.actor_type.value,
                        query.actor.actor_id,
                        Jsonb(dict(query.authorization_scope)),
                    ),
                ).fetchone()
                return dict(row["result"])
        except psycopg.Error as exc:
            raise CommandRejected(_reason_from_error(exc)) from exc

    def _take_explain_fault(self) -> Optional[str]:
        fault = self._explain_fault
        self._explain_fault = None
        return fault.value if fault else None


def _reason_from_error(exc: BaseException) -> str:
    if isinstance(exc, ExplainRejected):
        return str(exc)
    if isinstance(exc, psycopg.Error):
        return exc.diag.message_primary or exc.__class__.__name__
    return exc.__class__.__name__
