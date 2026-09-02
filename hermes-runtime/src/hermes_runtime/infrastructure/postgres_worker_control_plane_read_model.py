"""E14 source-derived Worker Control Plane projection over existing authority facts.

This adapter is read-only.  It does not own Worker, Scheduler, Execution,
Lease, or Fencing authority and issues no DML.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Optional

import psycopg
from psycopg.rows import dict_row

from hermes_runtime.application.factory_home_read_model import ActorProjectScope

PROJECTION_SCHEMA_VERSION = "e14-worker-control-plane/1"


def _string(value: Any) -> Optional[str]:
    return None if value is None else str(value)


def _safe_timestamp(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _safe_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class PostgresWorkerControlPlaneReadModel:
    """Creator-scoped E14 projection using source tables without a second state machine."""

    def __init__(self, dsn: str, actor_project_scope: ActorProjectScope) -> None:
        self._dsn = dsn
        self._actor_project_scope = actor_project_scope

    def list_workers(self, actor_scope: Mapping[str, Any]) -> Mapping[str, Any]:
        scoped = self._actor_project_scope.project_ids_for(actor_scope)
        if scoped is None:
            return self._not_available("WORKER_CONTROL_PLANE_SCOPE_UNAVAILABLE")
        if not scoped:
            return self._ok([])
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                rows = connection.execute(
                    """SELECT
                        awa.template_id,
                        awa.revision,
                        awa.availability_status,
                        awa.admission_status,
                        awa.availability_version,
                        awa.reason,
                        awa.updated_at,
                        wtr.runtime_kind,
                        wtr.trust_level,
                        wtr.concurrency_capacity,
                        wtr.project_id,
                        (SELECT count(*) FROM public.execution_worker_assignments ewa
                         WHERE ewa.worker_template_id = awa.template_id
                           AND ewa.worker_template_revision = awa.revision
                           AND ewa.project_id = ANY(%s)
                           AND ewa.assignment_state IN ('ASSIGNED', 'STARTED')) AS active_assignments,
                        (SELECT count(*) FROM public.execution_worker_assignments ewa
                         WHERE ewa.worker_template_id = awa.template_id
                           AND ewa.worker_template_revision = awa.revision
                           AND ewa.project_id = ANY(%s)) AS total_assignments
                    FROM public.worker_template_availability awa
                    JOIN public.worker_template_revisions wtr
                      ON wtr.template_id = awa.template_id AND wtr.revision = awa.revision
                    WHERE wtr.project_id = ANY(%s) OR wtr.project_id IS NULL
                    ORDER BY awa.template_id, awa.revision""",
                    (list(scoped), list(scoped), list(scoped)),
                ).fetchall()
                items = [self._safe_worker_payload(row) for row in rows]
                return self._ok(items)
        except Exception:
            return self._degraded("WORKER_CONTROL_PLANE_READ_FAILED")

    def worker_detail(self, worker_id: str, actor_scope: Mapping[str, Any]) -> Mapping[str, Any]:
        scoped = self._actor_project_scope.project_ids_for(actor_scope)
        if scoped is None:
            return self._not_available("WORKER_CONTROL_PLANE_SCOPE_UNAVAILABLE")
        if not scoped:
            return self._not_available("WORKER_CONTROL_PLANE_NOT_AVAILABLE")
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                template = connection.execute(
                    """SELECT
                        awa.template_id,
                        awa.revision,
                        awa.availability_status,
                        awa.admission_status,
                        awa.availability_version,
                        awa.reason,
                        awa.updated_at,
                        wtr.runtime_kind,
                        wtr.trust_level,
                        wtr.concurrency_capacity,
                        wtr.project_id,
                        wtr.capabilities,
                        wtr.allowed_tools,
                        wtr.supported_sandbox_features
                    FROM public.worker_template_availability awa
                    JOIN public.worker_template_revisions wtr
                      ON wtr.template_id = awa.template_id AND wtr.revision = awa.revision
                    WHERE awa.template_id = %s
                      AND wtr.project_id = ANY(%s)""",
                    (worker_id, list(scoped)),
                ).fetchone()
                if not template:
                    return self._not_available("WORKER_TEMPLATE_NOT_FOUND")
                assignments = connection.execute(
                    """SELECT assignment_id, project_id, task_id, execution_request_id,
                              execution_attempt, assignment_state, worker_agent_identity,
                              context_identity, started_at, terminal_at, terminal_reason
                       FROM public.execution_worker_assignments
                       WHERE worker_template_id = %s
                         AND project_id = ANY(%s)
                       ORDER BY created_at DESC
                       LIMIT 50""",
                    (worker_id, list(scoped)),
                ).fetchall()
                leases = connection.execute(
                    """SELECT el.lease_id, el.execution_request_id, el.project_id, el.task_id,
                              el.scheduler_id, el.lease_state,
                              el.granted_at, el.heartbeat_at, el.expires_at,
                              el.terminal_reason, el.terminal_at
                       FROM public.execution_leases el
                       WHERE el.project_id = ANY(%s)
                         AND EXISTS (
                           SELECT 1 FROM public.execution_worker_assignments ewa
                           WHERE ewa.worker_template_id = %s
                             AND ewa.lease_id = el.lease_id
                         )
                       ORDER BY el.created_at DESC
                       LIMIT 50""",
                    (list(scoped), worker_id),
                ).fetchall()
                return {
                    "availability": "CURRENT",
                    "item": {
                        **self._safe_worker_payload(template),
                        "assignments": [self._safe_assignment_payload(row) for row in assignments],
                        "leases": [self._safe_lease_payload(row) for row in leases],
                    },
                }
        except Exception:
            return self._degraded("WORKER_DETAIL_READ_FAILED")

    def execution_queue(self, actor_scope: Mapping[str, Any]) -> Mapping[str, Any]:
        scoped = self._actor_project_scope.project_ids_for(actor_scope)
        if scoped is None:
            return self._not_available("WORKER_CONTROL_PLANE_SCOPE_UNAVAILABLE")
        if not scoped:
            return self._ok([])
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                rows = connection.execute(
                    """SELECT
                        eqcs.queue_item_id,
                        eqcs.execution_request_id,
                        eqcs.project_id,
                        eqcs.task_id,
                        eqcs.priority,
                        eqcs.available_at,
                        eqcs.enqueued_at,
                        eqcs.queue_state,
                        eqcs.current_lease_id,
                        eqcs.updated_at,
                        ercs.request_state,
                        ercs.current_fencing_token,
                        er.worker_template_id,
                        er.worker_template_revision
                    FROM public.execution_queue_current_states eqcs
                    JOIN public.execution_requests er
                      ON er.execution_request_id = eqcs.execution_request_id
                    LEFT JOIN public.execution_request_current_states ercs
                      ON ercs.execution_request_id = eqcs.execution_request_id
                    WHERE eqcs.project_id = ANY(%s)
                    ORDER BY eqcs.priority DESC, eqcs.available_at ASC, eqcs.enqueued_at ASC
                    LIMIT 200""",
                    (list(scoped),),
                ).fetchall()
                items = [self._safe_queue_item_payload(row) for row in rows]
                return self._ok(items)
        except Exception:
            return self._degraded("EXECUTION_QUEUE_READ_FAILED")

    @staticmethod
    def _safe_worker_payload(row: dict) -> dict:
        return {
            "worker_id": _string(row.get("template_id")),
            "revision": _safe_int(row.get("revision")),
            "runtime_kind": _string(row.get("runtime_kind")),
            "trust_level": _string(row.get("trust_level")),
            "availability_status": _string(row.get("availability_status")),
            "admission_status": _string(row.get("admission_status")),
            "availability_version": _safe_int(row.get("availability_version")),
            "concurrency_capacity": _safe_int(row.get("concurrency_capacity")),
            "active_assignments": _safe_int(row.get("active_assignments")),
            "total_assignments": _safe_int(row.get("total_assignments")),
            "project_id": _string(row.get("project_id")),
            "reason": _string(row.get("reason")),
            "updated_at": _safe_timestamp(row.get("updated_at")),
        }

    @staticmethod
    def _safe_assignment_payload(row: dict) -> dict:
        return {
            "assignment_id": _string(row.get("assignment_id")),
            "project_id": _string(row.get("project_id")),
            "task_id": _string(row.get("task_id")),
            "execution_request_id": _string(row.get("execution_request_id")),
            "execution_attempt": _safe_int(row.get("execution_attempt")),
            "assignment_state": _string(row.get("assignment_state")),
            "worker_agent_identity": _string(row.get("worker_agent_identity")),
            "context_identity": _string(row.get("context_identity")),
            "started_at": _safe_timestamp(row.get("started_at")),
            "terminal_at": _safe_timestamp(row.get("terminal_at")),
            "terminal_reason": _string(row.get("terminal_reason")),
        }

    @staticmethod
    def _safe_lease_payload(row: dict) -> dict:
        return {
            "lease_id": _string(row.get("lease_id")),
            "execution_request_id": _string(row.get("execution_request_id")),
            "project_id": _string(row.get("project_id")),
            "task_id": _string(row.get("task_id")),
            "scheduler_id": _string(row.get("scheduler_id")),
            "lease_state": _string(row.get("lease_state")),
            "granted_at": _safe_timestamp(row.get("granted_at")),
            "heartbeat_at": _safe_timestamp(row.get("heartbeat_at")),
            "expires_at": _safe_timestamp(row.get("expires_at")),
            "terminal_reason": _string(row.get("terminal_reason")),
            "terminal_at": _safe_timestamp(row.get("terminal_at")),
        }

    @staticmethod
    def _safe_queue_item_payload(row: dict) -> dict:
        return {
            "queue_item_id": _string(row.get("queue_item_id")),
            "execution_request_id": _string(row.get("execution_request_id")),
            "project_id": _string(row.get("project_id")),
            "task_id": _string(row.get("task_id")),
            "priority": _safe_int(row.get("priority")),
            "available_at": _safe_timestamp(row.get("available_at")),
            "enqueued_at": _safe_timestamp(row.get("enqueued_at")),
            "queue_state": _string(row.get("queue_state")),
            "request_state": _string(row.get("request_state")),
            "worker_template_id": _string(row.get("worker_template_id")),
            "worker_template_revision": _safe_int(row.get("worker_template_revision")),
            "current_lease_id": _string(row.get("current_lease_id")),
            "updated_at": _safe_timestamp(row.get("updated_at")),
        }

    def _ok(self, items: list) -> dict:
        return {
            "availability": "CURRENT",
            "reason": None,
            "as_of": None,
            "freshness": "CURRENT",
            "source": "worker_control_plane",
            "source_version": PROJECTION_SCHEMA_VERSION,
            "items": items,
        }

    def _not_available(self, reason: str) -> dict:
        return {
            "availability": "NOT_AVAILABLE",
            "reason": reason,
            "as_of": None,
            "freshness": "NOT_AVAILABLE",
            "source": None,
            "source_version": None,
            "items": [],
        }

    def _degraded(self, reason: str) -> dict:
        return {
            "availability": "DEGRADED",
            "reason": reason,
            "as_of": None,
            "freshness": "DEGRADED",
            "source": "worker_control_plane",
            "source_version": PROJECTION_SCHEMA_VERSION,
            "items": [],
        }
