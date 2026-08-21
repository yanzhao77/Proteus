from __future__ import annotations

import json
from typing import Any, Mapping

import psycopg
from psycopg.rows import dict_row

from hermes_runtime.application.entry_approval_bridge import EntryApprovalBridgeUnavailable
from hermes_runtime.domain.entry_approval_bridge import (
    ApprovalSource,
    ApproveEntryPlan,
    BridgeStatus,
    EntryE4Rejected,
    content_hash,
    preview_approval,
    stable_id,
    validate_approval,
)


class PostgresEntryApprovalBridgeStore:
    """E4 owns only entry_approval_* tables; child authority is called elsewhere."""

    def __init__(self, dsn: str):
        self._dsn = dsn

    def _connect(self):
        return psycopg.connect(self._dsn, row_factory=dict_row)

    def _source(self, c: Any, creator: str, draft_id: str) -> ApprovalSource:
        draft = c.execute(
            "SELECT d.*,dr.revision_id AS draft_revision_id FROM public.entry_drafts d "
            "JOIN public.entry_draft_revisions dr ON dr.draft_id=d.draft_id AND dr.revision_number=d.latest_revision_number "
            "WHERE d.draft_id=%s AND d.creator_subject=%s FOR UPDATE OF d",
            (draft_id, creator),
        ).fetchone()
        if not draft or draft["state"] != "SUBMITTED":
            raise EntryE4Rejected("ENTRY_APPROVAL_SOURCE_NOT_CURRENT")
        understanding = c.execute(
            "SELECT u.*,ur.understanding_revision_id,ur.source_draft_revision_number FROM public.entry_understandings u "
            "JOIN public.entry_understanding_revisions ur ON ur.understanding_id=u.understanding_id AND ur.revision_number=u.latest_revision_number "
            "WHERE u.draft_id=%s AND u.creator_subject=%s FOR UPDATE OF u",
            (draft_id, creator),
        ).fetchone()
        if not understanding or understanding["state"] != "READY" or int(understanding["source_draft_revision_number"]) != int(draft["latest_revision_number"]):
            raise EntryE4Rejected("ENTRY_APPROVAL_SOURCE_STALE")
        proposal = c.execute(
            "SELECT p.proposal_id,p.version,p.latest_revision_number,pr.proposal_revision_id,pr.canonical_content_hash "
            "FROM public.entry_proposals p JOIN public.entry_proposal_revisions pr ON pr.proposal_id=p.proposal_id AND pr.revision_number=p.latest_revision_number "
            "WHERE p.draft_id=%s AND p.creator_subject=%s FOR UPDATE OF p",
            (draft_id, creator),
        ).fetchone()
        if not proposal:
            raise EntryE4Rejected("ENTRY_APPROVAL_SOURCE_NOT_CURRENT")
        plan = c.execute(
            "SELECT mp.master_plan_id,mp.version,mpr.master_plan_revision_id,mpr.proposal_revision_id,mpr.proposal_content_hash,mpr.canonical_content_hash,mpr.canonical_content "
            "FROM public.entry_master_plans mp JOIN public.entry_master_plan_revisions mpr ON mpr.master_plan_id=mp.master_plan_id AND mpr.revision_number=mp.latest_revision_number "
            "WHERE mp.draft_id=%s AND mp.creator_subject=%s FOR UPDATE OF mp",
            (draft_id, creator),
        ).fetchone()
        if not plan or plan["proposal_revision_id"] != proposal["proposal_revision_id"]:
            raise EntryE4Rejected("ENTRY_APPROVAL_SOURCE_STALE")
        return ApprovalSource(
            creator, draft_id, int(draft["version"]), draft["draft_revision_id"], understanding["understanding_revision_id"],
            proposal["proposal_revision_id"], proposal["canonical_content_hash"], plan["master_plan_id"], int(plan["version"]),
            plan["master_plan_revision_id"], plan["canonical_content_hash"], dict(plan["canonical_content"]),
        )

    def preview(self, creator_subject: str, draft_id: str):
        try:
            with self._connect() as c:
                return preview_approval(self._source(c, creator_subject, draft_id))
        except EntryE4Rejected:
            raise
        except Exception as exc:
            raise EntryApprovalBridgeUnavailable("ENTRY_APPROVAL_UNAVAILABLE") from exc

    def _approve_frozen(self, source: ApprovalSource, request: ApproveEntryPlan) -> Mapping[str, object]:
        preview = preview_approval(source)
        validate_approval(source, request, preview)
        fingerprint = content_hash({"request": request.__dict__, "blueprint": preview.compiled_blueprint_hash})
        try:
            with self._connect() as c:
                existing = c.execute(
                    "SELECT * FROM public.entry_approval_command_receipts WHERE creator_subject=%s AND command_type='APPROVE_ENTRY_PLAN' AND idempotency_key=%s FOR UPDATE",
                    (source.creator_subject, request.idempotency_key),
                ).fetchone()
                if existing:
                    if existing["request_fingerprint"] != fingerprint:
                        raise EntryE4Rejected("ENTRY_APPROVAL_IDEMPOTENCY_CONFLICT")
                    if existing["result_payload"]:
                        return dict(existing["result_payload"])
                    raise EntryE4Rejected(existing["error_code"] or "ENTRY_APPROVAL_INTERNAL_FAILURE")
                bridge_id = preview.bridge_id
                command_id = stable_id("approval", bridge_id, request.idempotency_key)
                c.execute(
                    "INSERT INTO public.entry_approval_command_receipts(command_id,creator_subject,command_type,idempotency_key,request_fingerprint,status,correlation_id) VALUES(%s,%s,'APPROVE_ENTRY_PLAN',%s,%s,'PROCESSING',%s)",
                    (command_id, source.creator_subject, request.idempotency_key, fingerprint, request.correlation_id),
                )
                c.execute(
                    "INSERT INTO public.entry_approval_bridges(bridge_id,approval_command_id,creator_subject,approver_subject,draft_id,source_draft_revision_id,source_understanding_revision_id,proposal_revision_id,proposal_content_hash,master_plan_id,master_plan_revision_id,master_plan_content_hash,compiler_version,policy_version,compiled_blueprint,compiled_blueprint_hash,required_acknowledgements,acknowledged_refs,intended_project_id,project_command_id,graph_command_id,status,correlation_id) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb,%s::jsonb,%s,%s,%s,'PROCESSING',%s)",
                    (bridge_id, command_id, source.creator_subject, request.verified_subject, source.draft_id, source.draft_revision_id, source.understanding_revision_id, source.proposal_revision_id, source.proposal_content_hash, source.plan_id, source.plan_revision_id, source.plan_content_hash, preview.compiler_version, preview.policy_version, json.dumps(preview.blueprint), preview.compiled_blueprint_hash, json.dumps(preview.required_acknowledgements), json.dumps(request.acknowledgements), preview.blueprint["project_id"], preview.blueprint["project_command_id"], preview.blueprint["graph_command_id"], request.correlation_id),
                )
                c.execute("INSERT INTO public.entry_approval_bridge_transitions(transition_id,bridge_id,to_status,reason_code,correlation_id) VALUES(%s,%s,'PROCESSING','APPROVAL_RECORDED',%s)", (stable_id("transition", bridge_id, "processing"), bridge_id, request.correlation_id))
                result = {"bridge_id": bridge_id, "status": BridgeStatus.PROCESSING.value, "project_id": None, "compiled_blueprint_hash": preview.compiled_blueprint_hash}
                c.execute("UPDATE public.entry_approval_command_receipts SET result_payload=%s::jsonb,updated_at=now() WHERE command_id=%s", (json.dumps(result), command_id))
                return result
        except EntryE4Rejected:
            raise
        except Exception as exc:
            raise EntryApprovalBridgeUnavailable("ENTRY_APPROVAL_UNAVAILABLE") from exc

    def approve(self, creator_subject: str, draft_id: str, payload: Mapping[str, object]) -> Mapping[str, object]:
        allowed = {"reason", "idempotency_key", "expected_draft_version", "master_plan_id", "expected_plan_version", "plan_revision_id", "approved_plan_content_hash", "proposal_revision_id", "proposal_content_hash", "compiled_blueprint_hash", "acknowledgements", "correlation_id"}
        if set(payload) - allowed:
            raise EntryE4Rejected("ENTRY_APPROVAL_SCHEMA_INVALID")
        try:
            with self._connect() as c:
                source = self._source(c, creator_subject, draft_id)
            acknowledgements = payload.get("acknowledgements")
            if not isinstance(acknowledgements, list):
                raise EntryE4Rejected("ENTRY_APPROVAL_SCHEMA_INVALID")
            request = ApproveEntryPlan(
                creator_subject, str(payload.get("reason", "")), str(payload.get("idempotency_key", "")),
                int(payload.get("expected_draft_version", -1)), str(payload.get("master_plan_id", "")), int(payload.get("expected_plan_version", -1)),
                str(payload.get("plan_revision_id", "")), str(payload.get("approved_plan_content_hash", "")),
                str(payload.get("proposal_revision_id", "")), str(payload.get("proposal_content_hash", "")),
                str(payload.get("compiled_blueprint_hash", "")), tuple(str(item) for item in acknowledgements), str(payload.get("correlation_id", "")),
            )
            return self._approve_frozen(source, request)
        except (EntryE4Rejected, ValueError):
            raise
        except Exception as exc:
            raise EntryApprovalBridgeUnavailable("ENTRY_APPROVAL_UNAVAILABLE") from exc

    def reconcile(self, creator_subject: str, draft_id: str, payload: Mapping[str, object]) -> Mapping[str, object]:
        # Child receipt/source reconciliation is intentionally fail-closed until the saga adapter records a durable reconciliation outcome.
        if set(payload) - {"reason", "idempotency_key", "correlation_id"}:
            raise EntryE4Rejected("ENTRY_APPROVAL_SCHEMA_INVALID")
        raise EntryE4Rejected("ENTRY_APPROVAL_RECONCILIATION_REQUIRED")

    def record_child_step(self, bridge_id: str, step: str, command_id: str, receipt: Mapping[str, object]) -> None:
        with self._connect() as c:
            target = str(receipt.get("project_id") or receipt.get("task_id") or receipt.get("verification_plan_id") or bridge_id)
            c.execute("INSERT INTO public.entry_approval_bridge_steps(step_id,bridge_id,step_name,child_command_id,child_receipt_ref,intended_target_id,request_hash,result_code,status,completed_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'SUCCEEDED',now()) ON CONFLICT DO NOTHING", (stable_id("step", bridge_id, step, command_id), bridge_id, step, command_id, str(receipt.get("receipt_id") or command_id), target, content_hash(dict(receipt)), str(receipt.get("result_code") or "SUCCEEDED")))

    def transition(self, bridge_id: str, status: str, reason: str) -> None:
        with self._connect() as c:
            prior = c.execute("SELECT status,correlation_id FROM public.entry_approval_bridges WHERE bridge_id=%s FOR UPDATE", (bridge_id,)).fetchone()
            if not prior: raise EntryE4Rejected("ENTRY_APPROVAL_NOT_AVAILABLE")
            if prior["status"] == status:
                return
            c.execute("UPDATE public.entry_approval_bridges SET status=%s,updated_at=now() WHERE bridge_id=%s", (status, bridge_id))
            c.execute("INSERT INTO public.entry_approval_bridge_transitions(transition_id,bridge_id,from_status,to_status,reason_code,correlation_id) VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT (transition_id) DO NOTHING", (stable_id("transition", bridge_id, status, reason), bridge_id, prior["status"], status, reason, prior["correlation_id"]))

    def materialize(self, bridge_id: str, project_id: str) -> None:
        with self._connect() as c:
            bridge=c.execute("SELECT draft_id,master_plan_id,master_plan_revision_id,correlation_id FROM public.entry_approval_bridges WHERE bridge_id=%s FOR UPDATE", (bridge_id,)).fetchone()
            if not bridge: raise EntryE4Rejected("ENTRY_APPROVAL_NOT_AVAILABLE")
            c.execute("UPDATE public.entry_approval_bridges SET status='MATERIALIZED',project_id=%s,materialized_at=now(),updated_at=now() WHERE bridge_id=%s", (project_id, bridge_id))
            c.execute("INSERT INTO public.entry_approval_materialized_bindings(bridge_id,draft_id,master_plan_id,master_plan_revision_id,project_id) VALUES(%s,%s,%s,%s,%s) ON CONFLICT (bridge_id) DO NOTHING", (bridge_id, bridge["draft_id"], bridge["master_plan_id"], bridge["master_plan_revision_id"], project_id))
            c.execute("INSERT INTO public.entry_approval_bridge_transitions(transition_id,bridge_id,from_status,to_status,reason_code,correlation_id) VALUES(%s,%s,'VERIFICATION_APPLYING','MATERIALIZED','CHILD_RECEIPTS_RECORDED',%s) ON CONFLICT (transition_id) DO NOTHING", (stable_id("transition", bridge_id, "materialized"), bridge_id, bridge["correlation_id"]))

    def load_bridge(self, creator_subject: str, draft_id: str) -> Mapping[str, object]:
        """Creator-scoped durable bridge load for a fresh orchestrator instance."""
        try:
            with self._connect() as c:
                row = c.execute(
                    "SELECT bridge_id,status,project_id,compiled_blueprint,compiled_blueprint_hash,"
                    "correlation_id,project_command_id,graph_command_id FROM public.entry_approval_bridges "
                    "WHERE creator_subject=%s AND draft_id=%s ORDER BY created_at DESC LIMIT 1 FOR UPDATE",
                    (creator_subject, draft_id),
                ).fetchone()
                if not row:
                    raise EntryE4Rejected("ENTRY_APPROVAL_NOT_AVAILABLE")
                return dict(row)
        except EntryE4Rejected:
            raise
        except Exception as exc:
            raise EntryApprovalBridgeUnavailable("ENTRY_APPROVAL_UNAVAILABLE") from exc

    def get_approval(self, creator_subject: str, draft_id: str) -> Mapping[str, object]:
        try:
            with self._connect() as c:
                row = c.execute("SELECT bridge_id,status,project_id,compiled_blueprint_hash,created_at,updated_at FROM public.entry_approval_bridges WHERE creator_subject=%s AND draft_id=%s ORDER BY created_at DESC LIMIT 1", (creator_subject, draft_id)).fetchone()
                if not row:
                    return {"availability": "NOT_AVAILABLE", "reason": "ENTRY_APPROVAL_NOT_AVAILABLE", "item": None}
                return {"availability": "CURRENT", "item": dict(row)}
        except Exception as exc:
            raise EntryApprovalBridgeUnavailable("ENTRY_APPROVAL_UNAVAILABLE") from exc
