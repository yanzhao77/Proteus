"""E7 source-derived Live Production projection over existing authority facts.

This adapter is read-only.  It does not own Project, Task, Gate, Execution,
Verification, Evidence, Recovery, or Event authority and issues no DML.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

import psycopg
from psycopg.rows import dict_row

from hermes_runtime.application.factory_home_read_model import ActorProjectScope

PROJECTION_SCHEMA_VERSION = "e7-live-production-projection/1"
MAX_EVENT_PAGE = 100


def _string(value: Any) -> Optional[str]:
    return None if value is None else str(value)


def _safe_timestamp(value: Any) -> Optional[str]:
    return None if value is None else value.isoformat()


class UnavailableLiveProductionReadModel:
    def snapshot(self, _project_id: str, _actor_scope: Mapping[str, Any]) -> Mapping[str, Any]:
        return {"availability": "NOT_AVAILABLE", "reason": "LIVE_PRODUCTION_READ_MODEL_NOT_CONFIGURED", "item": None}

    def events(self, _project_id: str, _actor_scope: Mapping[str, Any], _after: int = 0, _limit: int = 50) -> Mapping[str, Any]:
        return {"availability": "NOT_AVAILABLE", "reason": "LIVE_PRODUCTION_READ_MODEL_NOT_CONFIGURED", "items": []}


class PostgresLiveProductionReadModel:
    """Creator-scoped E7 projection using source tables without a second state machine."""

    def __init__(self, dsn: str, actor_project_scope: ActorProjectScope) -> None:
        self._dsn = dsn
        self._actor_project_scope = actor_project_scope

    def snapshot(self, project_id: str, actor_scope: Mapping[str, Any]) -> Mapping[str, Any]:
        if not self._visible(project_id, actor_scope):
            return self._not_available("LIVE_PRODUCTION_NOT_AVAILABLE")
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                header = connection.execute(
                    """SELECT p.project_id, p.title, p.state, p.version, p.created_at, p.updated_at,
                              b.bridge_id, b.draft_id, b.master_plan_id, b.master_plan_revision_id,
                              b.master_plan_content_hash, b.compiled_blueprint, b.materialized_at
                       FROM public.projects p
                       JOIN public.entry_approval_materialized_bindings binding ON binding.project_id = p.project_id
                       JOIN public.entry_approval_bridges b ON b.bridge_id = binding.bridge_id
                       WHERE p.project_id = %s AND b.status = 'MATERIALIZED'""",
                    (project_id,),
                ).fetchone()
                if not header:
                    return self._not_available("LIVE_PRODUCTION_NOT_AVAILABLE")
                tasks = connection.execute(
                    """SELECT task_id, title, task_type, state, version, created_at, updated_at,
                              current_artifact_id, current_artifact_hash,
                              current_verification_plan_id, current_verification_plan_version,
                              completion_worker_identity, completion_worker_run_id
                       FROM public.tasks WHERE project_id = %s ORDER BY created_at, task_id""",
                    (project_id,),
                ).fetchall()
                dependencies = connection.execute(
                    """SELECT task_id, depends_on_task_id, created_by_command_id, created_at
                       FROM public.task_dependencies WHERE project_id = %s
                       ORDER BY task_id, depends_on_task_id""",
                    (project_id,),
                ).fetchall()
                executions = connection.execute(
                    """SELECT execution_request_id, task_id, request_state, request_version,
                              current_lease_id, updated_at
                       FROM public.execution_request_current_states
                       WHERE project_id = %s ORDER BY updated_at DESC, execution_request_id ASC""",
                    (project_id,),
                ).fetchall()
                runs = connection.execute(
                    """SELECT run_id, task_id, status, agent_identity, execution_request_id,
                              execution_attempt, lease_id, lease_version, created_at, completed_at, version
                       FROM public.agent_runs WHERE project_id = %s
                       ORDER BY created_at DESC, run_id ASC LIMIT 100""",
                    (project_id,),
                ).fetchall()
                leases = connection.execute(
                    """SELECT lease_id, task_id, execution_request_id, lease_state, lease_version,
                              granted_at, heartbeat_at, expires_at, terminal_at
                       FROM public.execution_leases WHERE project_id = %s
                       ORDER BY created_at DESC, lease_id ASC LIMIT 100""",
                    (project_id,),
                ).fetchall()
                plans = connection.execute(
                    """SELECT verification_plan_id, task_id, version, status, independence, created_at
                       FROM public.verification_plans WHERE project_id = %s
                       ORDER BY created_at DESC, verification_plan_id ASC""",
                    (project_id,),
                ).fetchall()
                results = connection.execute(
                    """SELECT verification_id, task_id, verdict, authority_status, plan_id, plan_version,
                              verifier_identity, completed_at, created_at
                       FROM public.verification_results WHERE project_id = %s
                       ORDER BY created_at DESC, verification_id ASC LIMIT 100""",
                    (project_id,),
                ).fetchall()
                evidence = connection.execute(
                    """SELECT e.evidence_id, e.artifact_id, e.artifact_hash, e.valid, e.created_at,
                              e.invalidated_at, a.media_type, a.task_id
                       FROM public.evidence e
                       JOIN public.artifacts a ON a.artifact_id = e.artifact_id
                       JOIN public.tasks t ON t.task_id = a.task_id
                       WHERE t.project_id = %s ORDER BY e.created_at DESC, e.evidence_id ASC LIMIT 100""",
                    (project_id,),
                ).fetchall()
                gates = connection.execute(
                    """SELECT gate_request_id, task_id, action_scope, reason, request_state, expires_at,
                              version, updated_at
                       FROM public.human_gate_requests WHERE project_id = %s
                       ORDER BY updated_at DESC, gate_request_id ASC""",
                    (project_id,),
                ).fetchall()
                waits = connection.execute(
                    """SELECT waiting_record_id, task_id, waiting_type, blocking_reason, waiting_state,
                              gate_request_id, entered_at, resolved_at, version
                       FROM public.project_waiting_records WHERE project_id = %s
                       ORDER BY entered_at DESC, waiting_record_id ASC""",
                    (project_id,),
                ).fetchall()
                findings = connection.execute(
                    """SELECT finding_id, finding_kind, status, observed_sequence, version, created_at, resolved_at
                       FROM public.reconcile_findings WHERE scope_id = %s
                       ORDER BY created_at DESC, finding_id ASC LIMIT 100""",
                    (project_id,),
                ).fetchall()
                watermark = self._watermark(connection, project_id)
                recent_events = self._event_rows(connection, project_id, 0, 25, watermark)[0]
        except Exception:
            return {"availability": "DEGRADED", "reason": "LIVE_PRODUCTION_SOURCE_UNAVAILABLE", "item": None}

        blueprint = header["compiled_blueprint"] if isinstance(header["compiled_blueprint"], Mapping) else {}
        planned_tasks = blueprint.get("tasks", []) if isinstance(blueprint, Mapping) else []
        materialization_map = [
            {
                "source_identity": item.get("node_key") or item.get("task_key") or item.get("create_command_id"),
                "source_version": header["master_plan_revision_id"],
                "task_id": item.get("task_id"),
                "create_command_id": item.get("create_command_id"),
            }
            for item in planned_tasks if isinstance(item, Mapping)
        ]
        task_nodes = [
            {
                "node_id": row["task_id"], "task_id": row["task_id"], "title": row["title"],
                "task_type": row["task_type"], "state": row["state"], "version": int(row["version"]),
                "source_identity": row["task_id"], "source_version": int(row["version"]),
                "created_at": _safe_timestamp(row["created_at"]), "updated_at": _safe_timestamp(row["updated_at"]),
                "artifact": {"artifact_id": row["current_artifact_id"], "content_hash": row["current_artifact_hash"]},
                "verification_ref": {"plan_id": row["current_verification_plan_id"], "version": row["current_verification_plan_version"]},
                "completion_claim": {"worker_identity": row["completion_worker_identity"], "run_id": row["completion_worker_run_id"], "verified": False},
            }
            for row in tasks
        ]
        edges = [
            {"edge_id": f"{row['task_id']}:{row['depends_on_task_id']}", "task_id": row["task_id"],
             "depends_on_task_id": row["depends_on_task_id"], "source_identity": row["created_by_command_id"],
             "source_version": _safe_timestamp(row["created_at"])}
            for row in dependencies
        ]
        return {
            "availability": "CURRENT", "reason": None, "as_of": _safe_timestamp(header["updated_at"]),
            "freshness": "CURRENT", "source": "projects,entry_approval_materialized_bindings,tasks,event_log",
            "source_version": int(header["version"]), "projection_schema_version": PROJECTION_SCHEMA_VERSION,
            "snapshot_watermark": watermark,
            "item": {
                "production_id": header["project_id"], "project": {"project_id": header["project_id"], "title": header["title"], "state": header["state"], "version": int(header["version"]), "updated_at": _safe_timestamp(header["updated_at"])},
                "master_plan": {"master_plan_id": header["master_plan_id"], "revision_id": header["master_plan_revision_id"], "content_hash": header["master_plan_content_hash"]},
                "materialization": {"bridge_id": header["bridge_id"], "draft_id": header["draft_id"], "materialized_at": _safe_timestamp(header["materialized_at"]), "map": materialization_map},
                "workflow": {"nodes": task_nodes, "edges": edges, "freshness": "CURRENT", "unavailable_reason": None},
                "execution_requests": [{"execution_request_id": row["execution_request_id"], "task_id": row["task_id"], "state": row["request_state"], "version": int(row["request_version"]), "lease_ref": row["current_lease_id"], "updated_at": _safe_timestamp(row["updated_at"])} for row in executions],
                "runs": [{"run_id": row["run_id"], "task_id": row["task_id"], "status": row["status"], "worker_identity": row["agent_identity"], "capability": "NOT_AVAILABLE", "execution_request_id": row["execution_request_id"], "attempt": row["execution_attempt"], "lease_ref": row["lease_id"], "lease_version": row["lease_version"], "version": int(row["version"]), "created_at": _safe_timestamp(row["created_at"]), "completed_at": _safe_timestamp(row["completed_at"])} for row in runs],
                "leases": [{"lease_id": row["lease_id"], "task_id": row["task_id"], "execution_request_id": row["execution_request_id"], "state": row["lease_state"], "version": int(row["lease_version"]), "granted_at": _safe_timestamp(row["granted_at"]), "heartbeat_at": _safe_timestamp(row["heartbeat_at"]), "expires_at": _safe_timestamp(row["expires_at"]), "terminal_at": _safe_timestamp(row["terminal_at"])} for row in leases],
                "verification": {"plans": [{"plan_id": row["verification_plan_id"], "task_id": row["task_id"], "version": int(row["version"]), "status": row["status"], "independence": row["independence"], "created_at": _safe_timestamp(row["created_at"])} for row in plans], "results": [{"verification_id": row["verification_id"], "task_id": row["task_id"], "verdict": row["verdict"], "authority_status": row["authority_status"], "plan_id": row["plan_id"], "plan_version": row["plan_version"], "verifier_identity": row["verifier_identity"], "completed_at": _safe_timestamp(row["completed_at"]), "created_at": _safe_timestamp(row["created_at"])} for row in results]},
                "evidence": {"items": [{"evidence_id": row["evidence_id"], "artifact_id": row["artifact_id"], "artifact_hash": row["artifact_hash"], "media_type": row["media_type"], "task_id": row["task_id"], "valid": bool(row["valid"]), "created_at": _safe_timestamp(row["created_at"]), "invalidated_at": _safe_timestamp(row["invalidated_at"])} for row in evidence], "valid_count": sum(1 for row in evidence if row["valid"]), "invalidated_count": sum(1 for row in evidence if not row["valid"]), "missing_count": sum(1 for row in tasks if row["current_artifact_id"] is None)},
                "gates": [{"gate_id": row["gate_request_id"], "task_id": row["task_id"], "action_scope": row["action_scope"], "reason": row["reason"], "status": row["request_state"], "expires_at": _safe_timestamp(row["expires_at"]), "version": int(row["version"]), "updated_at": _safe_timestamp(row["updated_at"]), "review_link": f"/human-gates/{row['gate_request_id']}"} for row in gates],
                "waiting": [{"waiting_record_id": row["waiting_record_id"], "task_id": row["task_id"], "waiting_type": row["waiting_type"], "reason": row["blocking_reason"], "state": row["waiting_state"], "gate_id": row["gate_request_id"], "version": int(row["version"]), "entered_at": _safe_timestamp(row["entered_at"]), "resolved_at": _safe_timestamp(row["resolved_at"])} for row in waits],
                "recovery": [{"finding_id": row["finding_id"], "kind": row["finding_kind"], "status": row["status"], "observed_sequence": row["observed_sequence"], "version": int(row["version"]), "created_at": _safe_timestamp(row["created_at"]), "resolved_at": _safe_timestamp(row["resolved_at"])} for row in findings],
                "recent_events": recent_events,
            },
        }

    def events(self, project_id: str, actor_scope: Mapping[str, Any], after: int = 0, limit: int = 50) -> Mapping[str, Any]:
        if not self._visible(project_id, actor_scope):
            return {"availability": "NOT_AVAILABLE", "reason": "LIVE_PRODUCTION_NOT_AVAILABLE", "items": []}
        if not isinstance(after, int) or after < 0 or not isinstance(limit, int) or limit < 1:
            return {"availability": "NOT_AVAILABLE", "reason": "LIVE_PRODUCTION_CURSOR_INVALID", "items": []}
        limit = min(limit, MAX_EVENT_PAGE)
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                watermark = self._watermark(connection, project_id)
                first = connection.execute("SELECT min(sequence) AS first_sequence FROM public.event_log WHERE project_id = %s", (project_id,)).fetchone()["first_sequence"]
                if after > watermark:
                    return {"availability": "STALE", "reason": "LIVE_PRODUCTION_CURSOR_AHEAD", "items": [], "snapshot_watermark": watermark}
                if after and first is not None and after < int(first) - 1:
                    return {"availability": "STALE", "reason": "LIVE_PRODUCTION_CURSOR_EXPIRED", "items": [], "snapshot_watermark": watermark}
                rows, next_cursor = self._event_rows(connection, project_id, after, limit, watermark)
                return {"availability": "CURRENT", "reason": None, "items": rows, "after": after, "next_cursor": next_cursor, "snapshot_watermark": watermark, "projection_schema_version": PROJECTION_SCHEMA_VERSION, "bounded": True}
        except Exception:
            return {"availability": "DEGRADED", "reason": "LIVE_PRODUCTION_EVENT_SOURCE_UNAVAILABLE", "items": []}

    def _visible(self, project_id: str, actor_scope: Mapping[str, Any]) -> bool:
        scope = self._actor_project_scope.project_ids_for(actor_scope)
        return scope is not None and project_id in {str(value) for value in scope}

    @staticmethod
    def _not_available(reason: str) -> Mapping[str, Any]:
        return {"availability": "NOT_AVAILABLE", "reason": reason, "item": None, "as_of": None, "snapshot_watermark": None}

    @staticmethod
    def _watermark(connection, project_id: str) -> int:
        row = connection.execute("SELECT coalesce(max(sequence), 0) AS watermark FROM public.event_log WHERE project_id = %s", (project_id,)).fetchone()
        return int(row["watermark"])

    @staticmethod
    def _event_rows(connection, project_id: str, after: int, limit: int, watermark: int) -> tuple[list[Mapping[str, Any]], int]:
        rows = connection.execute(
            """SELECT event_id, event_type, schema_version, producer_type, producer_id, task_id, run_id,
                      sequence, occurred_at, correlation_id, causation_id,
                      CASE WHEN jsonb_typeof(payload->'aggregate_version') = 'number' THEN (payload->>'aggregate_version')::bigint
                           WHEN jsonb_typeof(payload->'version') = 'number' THEN (payload->>'version')::bigint
                           ELSE NULL END AS aggregate_version
               FROM public.event_log WHERE project_id = %s AND sequence > %s
               ORDER BY sequence ASC LIMIT %s""",
            (project_id, after, limit),
        ).fetchall()
        items = []
        for row in rows:
            aggregate_id = row["run_id"] or row["task_id"] or project_id
            aggregate_type = "run" if row["run_id"] else "task" if row["task_id"] else "project"
            items.append({
                "event_id": row["event_id"], "production_id": project_id, "aggregate_type": aggregate_type,
                "aggregate_id": aggregate_id, "aggregate_version": row["aggregate_version"],
                "production_sequence": int(row["sequence"]), "occurred_at": _safe_timestamp(row["occurred_at"]),
                "correlation_id": row["correlation_id"], "causation_id": row["causation_id"],
                "schema_version": row["schema_version"], "snapshot_watermark": watermark,
                "event_kind": row["event_type"], "safe_payload": {"producer_type": row["producer_type"], "producer_id": row["producer_id"]},
            })
        return items, (items[-1]["production_sequence"] if items else after)
