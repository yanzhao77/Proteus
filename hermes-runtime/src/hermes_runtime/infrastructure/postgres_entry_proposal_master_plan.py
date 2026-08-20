from __future__ import annotations

import json
import uuid
from typing import Any, Mapping

import psycopg
from psycopg.rows import dict_row

from hermes_runtime.domain.entry_proposal_master_plan import (
    EntryE3Rejected,
    ProposalSource,
    SourceAssumption,
    SourceClarification,
    compile_master_plan,
    compile_proposal,
    request_fingerprint,
)


class EntryProposalMasterPlanStoreUnavailable(RuntimeError):
    pass


class PostgresEntryProposalMasterPlanStore:
    """E3-only durable authority; it never addresses Project/P6 tables."""

    def __init__(self, dsn: str):
        self._dsn = dsn

    def _connect(self):
        return psycopg.connect(self._dsn, row_factory=dict_row)

    @staticmethod
    def _code(error: Exception) -> str:
        return str(error) if isinstance(error, EntryE3Rejected) else "ENTRY_PROPOSAL_COMPILER_FAILED"

    def _claim_receipt(
        self,
        c: Any,
        creator: str,
        command_type: str,
        key: str,
        fingerprint: str,
    ) -> Mapping[str, Any] | None:
        row = c.execute(
            "SELECT * FROM public.entry_proposal_plan_command_receipts "
            "WHERE actor_subject=%s AND command_type=%s AND idempotency_key=%s FOR UPDATE",
            (creator, command_type, key),
        ).fetchone()
        if row:
            if row["request_fingerprint"] != fingerprint:
                raise EntryE3Rejected(
                    "ENTRY_PROPOSAL_IDEMPOTENCY_CONFLICT" if command_type == "GENERATE_PROPOSAL" else "ENTRY_PLAN_IDEMPOTENCY_CONFLICT"
                )
            if row["status"] == "SUCCEEDED" and row["result_payload"]:
                return dict(row["result_payload"])
            raise EntryE3Rejected(str(row["error_code"] or "ENTRY_PROPOSAL_COMPILER_FAILED"))
        c.execute(
            "INSERT INTO public.entry_proposal_plan_command_receipts("
            "command_id,actor_subject,command_type,idempotency_key,request_fingerprint,status,error_code) "
            "VALUES(%s,%s,%s,%s,%s,'FAILED',%s)",
            ("e3c-" + uuid.uuid4().hex, creator, command_type, key, fingerprint,
             "ENTRY_PROPOSAL_COMPILER_FAILED" if command_type == "GENERATE_PROPOSAL" else "ENTRY_PLAN_COMPILER_FAILED"),
        )
        c.commit()
        return None

    def _complete_receipt(self, c: Any, creator: str, command_type: str, key: str, result: Mapping[str, Any]) -> None:
        c.execute(
            "UPDATE public.entry_proposal_plan_command_receipts SET status='SUCCEEDED',result_payload=%s::jsonb,error_code=NULL,updated_at=now() "
            "WHERE actor_subject=%s AND command_type=%s AND idempotency_key=%s",
            (json.dumps(result), creator, command_type, key),
        )

    def _fail_receipt(self, creator: str, command_type: str, key: str, code: str) -> None:
        try:
            with self._connect() as c:
                c.execute(
                    "UPDATE public.entry_proposal_plan_command_receipts SET status='FAILED',error_code=%s,updated_at=now() "
                    "WHERE actor_subject=%s AND command_type=%s AND idempotency_key=%s",
                    (code, creator, command_type, key),
                )
        except Exception:
            pass

    @staticmethod
    def _tuple(value: object) -> tuple[str, ...]:
        if not isinstance(value, list):
            return ()
        return tuple(str(item) for item in value if isinstance(item, str) and item.strip())

    def _proposal_source(self, c: Any, creator: str, draft_id: str) -> ProposalSource:
        draft = c.execute(
            "SELECT d.*,dr.revision_id AS draft_revision_id,dr.revision_number AS draft_revision_number "
            "FROM public.entry_drafts d JOIN public.entry_draft_revisions dr "
            "ON dr.draft_id=d.draft_id AND dr.revision_number=d.latest_revision_number "
            "WHERE d.draft_id=%s AND d.creator_subject=%s FOR UPDATE OF d",
            (draft_id, creator),
        ).fetchone()
        if not draft:
            raise EntryE3Rejected("ENTRY_PROPOSAL_NOT_AVAILABLE")
        understanding = c.execute(
            "SELECT u.*,ur.* FROM public.entry_understandings u JOIN public.entry_understanding_revisions ur "
            "ON ur.understanding_id=u.understanding_id AND ur.revision_number=u.latest_revision_number "
            "WHERE u.draft_id=%s AND u.creator_subject=%s FOR UPDATE OF u",
            (draft_id, creator),
        ).fetchone()
        if not understanding:
            raise EntryE3Rejected("ENTRY_PROPOSAL_SOURCE_NOT_READY")
        if int(understanding["source_draft_revision_number"]) != int(draft["latest_revision_number"]):
            raise EntryE3Rejected("ENTRY_PROPOSAL_SOURCE_STALE")
        clarifications = c.execute(
            "SELECT c.clarification_id,c.question,c.rationale,c.state,a.answer "
            "FROM public.entry_clarifications c LEFT JOIN public.entry_clarification_answers a ON a.clarification_id=c.clarification_id "
            "WHERE c.understanding_id=%s ORDER BY c.clarification_id",
            (understanding["understanding_id"],),
        ).fetchall()
        assumptions = c.execute(
            "SELECT assumption_id,statement,basis FROM public.entry_understanding_assumptions "
            "WHERE understanding_id=%s AND understanding_revision_id=%s ORDER BY assumption_id",
            (understanding["understanding_id"], understanding["understanding_revision_id"]),
        ).fetchall()
        return ProposalSource(
            creator_subject=creator,
            draft_id=draft_id,
            draft_state=draft["state"],
            draft_revision_id=draft["draft_revision_id"],
            draft_revision_number=int(draft["draft_revision_number"]),
            understanding_id=understanding["understanding_id"],
            understanding_state=understanding["state"],
            understanding_revision_id=understanding["understanding_revision_id"],
            understanding_revision_number=int(understanding["revision_number"]),
            interpreted_intent=understanding["interpreted_intent"],
            objective=understanding["objective"] or "",
            user_constraints=self._tuple(understanding["user_constraints"]),
            explicit_requirements=self._tuple(understanding["explicit_requirements"]),
            ambiguities=self._tuple(understanding["ambiguities"]),
            open_questions=self._tuple(understanding["open_questions"]),
            clarifications=tuple(SourceClarification(
                clarification_id=row["clarification_id"], question=row["question"], rationale=row["rationale"] or "",
                state=row["state"], answer=row["answer"],
            ) for row in clarifications),
            assumptions=tuple(SourceAssumption(
                assumption_id=row["assumption_id"], statement=row["statement"], basis=row["basis"] or "",
            ) for row in assumptions),
        )

    def generate_proposal(self, creator: str, draft_id: str, expected_version: int, idempotency_key: str, reason: str) -> Mapping[str, Any]:
        if not creator or not draft_id or not idempotency_key or not reason or expected_version < 0:
            raise EntryE3Rejected("ENTRY_PROPOSAL_SCHEMA_INVALID")
        command = "GENERATE_PROPOSAL"
        fingerprint = request_fingerprint(command, expected_version, reason, {"draft_id": draft_id})
        try:
            with self._connect() as c:
                replay = self._claim_receipt(c, creator, command, idempotency_key, fingerprint)
                if replay is not None:
                    return replay
                try:
                    source = self._proposal_source(c, creator, draft_id)
                    existing = c.execute(
                        "SELECT * FROM public.entry_proposals WHERE draft_id=%s AND creator_subject=%s FOR UPDATE",
                        (draft_id, creator),
                    ).fetchone()
                    actual = int(existing["version"]) if existing else 0
                    if actual != expected_version:
                        raise EntryE3Rejected("ENTRY_PROPOSAL_VERSION_CONFLICT")
                    candidate = compile_proposal(source)
                    if existing:
                        proposal_id = existing["proposal_id"]
                        revision_number = int(existing["latest_revision_number"]) + 1
                        version = actual + 1
                    else:
                        proposal_id = "ep-" + uuid.uuid4().hex
                        revision_number = 1
                        version = 1
                        c.execute(
                            "INSERT INTO public.entry_proposals(proposal_id,draft_id,creator_subject,version,latest_revision_number) "
                            "VALUES(%s,%s,%s,%s,%s)",
                            (proposal_id, draft_id, creator, version, revision_number),
                        )
                    revision_id = "epr-" + uuid.uuid4().hex
                    c.execute(
                        "INSERT INTO public.entry_proposal_revisions("
                        "proposal_revision_id,proposal_id,revision_number,source_draft_id,source_draft_revision_id,"
                        "source_understanding_id,source_understanding_revision_id,compiler_name,schema_version,canonical_content,canonical_content_hash) "
                        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)",
                        (revision_id, proposal_id, revision_number, source.draft_id, source.draft_revision_id,
                         source.understanding_id, source.understanding_revision_id, "proposal-compiler-v1", "e3-v1",
                         json.dumps(candidate.content), candidate.content_hash),
                    )
                    c.execute(
                        "UPDATE public.entry_proposals SET version=%s,latest_revision_number=%s,updated_at=now() WHERE proposal_id=%s",
                        (version, revision_number, proposal_id),
                    )
                    result = self._proposal_detail(c, creator, draft_id, proposal_id)
                    self._complete_receipt(c, creator, command, idempotency_key, result)
                    return result
                except EntryE3Rejected as error:
                    self._fail_receipt(creator, command, idempotency_key, self._code(error))
                    raise
        except EntryE3Rejected:
            raise
        except Exception as exc:
            raise EntryProposalMasterPlanStoreUnavailable("ENTRY_PROPOSAL_AUTHORITY_UNAVAILABLE") from exc

    def _proposal_detail(self, c: Any, creator: str, draft_id: str, proposal_id: str) -> Mapping[str, Any]:
        proposal = c.execute(
            "SELECT * FROM public.entry_proposals WHERE proposal_id=%s AND creator_subject=%s AND draft_id=%s",
            (proposal_id, creator, draft_id),
        ).fetchone()
        if not proposal:
            raise EntryE3Rejected("ENTRY_PROPOSAL_NOT_AVAILABLE")
        revisions = c.execute(
            "SELECT * FROM public.entry_proposal_revisions WHERE proposal_id=%s ORDER BY revision_number",
            (proposal_id,),
        ).fetchall()
        def revision(row: Mapping[str, Any]) -> Mapping[str, Any]:
            return {
                "proposal_revision_id": row["proposal_revision_id"],
                "revision_number": int(row["revision_number"]),
                "source_draft_revision_id": row["source_draft_revision_id"],
                "source_understanding_revision_id": row["source_understanding_revision_id"],
                "compiler": row["compiler_name"],
                "schema_version": row["schema_version"],
                "content_hash": row["canonical_content_hash"],
                "content": dict(row["canonical_content"]),
                "created_at": row["created_at"].isoformat(),
            }
        return {
            "proposal_id": proposal_id, "draft_id": draft_id, "version": int(proposal["version"]),
            "latest_revision_number": int(proposal["latest_revision_number"]), "current": revision(revisions[-1]),
            "revisions": [revision(row) for row in revisions], "pre_approval_only": True,
        }

    def get_proposal(self, creator: str, draft_id: str) -> Mapping[str, Any]:
        try:
            with self._connect() as c:
                row = c.execute("SELECT proposal_id FROM public.entry_proposals WHERE draft_id=%s AND creator_subject=%s", (draft_id, creator)).fetchone()
                if not row:
                    return {"availability": "NOT_AVAILABLE", "reason": "ENTRY_PROPOSAL_NOT_AVAILABLE", "item": None}
                return {"availability": "CURRENT", "item": self._proposal_detail(c, creator, draft_id, row["proposal_id"])}
        except Exception as exc:
            raise EntryProposalMasterPlanStoreUnavailable("ENTRY_PROPOSAL_AUTHORITY_UNAVAILABLE") from exc

    def list_proposal_revisions(self, creator: str, draft_id: str) -> Mapping[str, Any]:
        result = self.get_proposal(creator, draft_id)
        return {"availability": result["availability"], "reason": result.get("reason"), "items": []} if not result.get("item") else {"availability": "CURRENT", "items": result["item"]["revisions"]}

    def generate_master_plan(self, creator: str, draft_id: str, expected_version: int, idempotency_key: str, reason: str) -> Mapping[str, Any]:
        if not creator or not draft_id or not idempotency_key or not reason or expected_version < 0:
            raise EntryE3Rejected("ENTRY_PLAN_SCHEMA_INVALID")
        command = "GENERATE_MASTER_PLAN"
        fingerprint = request_fingerprint(command, expected_version, reason, {"draft_id": draft_id})
        try:
            with self._connect() as c:
                replay = self._claim_receipt(c, creator, command, idempotency_key, fingerprint)
                if replay is not None:
                    return replay
                try:
                    proposal = c.execute(
                        "SELECT * FROM public.entry_proposals WHERE draft_id=%s AND creator_subject=%s FOR UPDATE",
                        (draft_id, creator),
                    ).fetchone()
                    if not proposal:
                        raise EntryE3Rejected("ENTRY_PLAN_NOT_AVAILABLE")
                    try:
                        source = self._proposal_source(c, creator, draft_id)
                    except EntryE3Rejected as exc:
                        if str(exc) in {"ENTRY_PROPOSAL_SOURCE_NOT_READY", "ENTRY_PROPOSAL_SOURCE_STALE"}:
                            raise EntryE3Rejected("ENTRY_PLAN_SOURCE_STALE") from exc
                        raise
                    revision = c.execute(
                        "SELECT * FROM public.entry_proposal_revisions WHERE proposal_id=%s AND revision_number=%s",
                        (proposal["proposal_id"], proposal["latest_revision_number"]),
                    ).fetchone()
                    if not revision or revision["source_draft_revision_id"] != source.draft_revision_id or revision["source_understanding_revision_id"] != source.understanding_revision_id:
                        raise EntryE3Rejected("ENTRY_PLAN_SOURCE_STALE")
                    existing = c.execute(
                        "SELECT * FROM public.entry_master_plans WHERE proposal_id=%s AND creator_subject=%s FOR UPDATE",
                        (proposal["proposal_id"], creator),
                    ).fetchone()
                    actual = int(existing["version"]) if existing else 0
                    if actual != expected_version:
                        raise EntryE3Rejected("ENTRY_PLAN_VERSION_CONFLICT")
                    candidate = compile_master_plan(dict(revision["canonical_content"]), revision["canonical_content_hash"], revision["proposal_revision_id"])
                    if existing:
                        plan_id = existing["master_plan_id"]
                        revision_number = int(existing["latest_revision_number"]) + 1
                        version = actual + 1
                    else:
                        plan_id = "emp-" + uuid.uuid4().hex
                        revision_number = 1
                        version = 1
                        c.execute(
                            "INSERT INTO public.entry_master_plans(master_plan_id,proposal_id,draft_id,creator_subject,version,latest_revision_number) VALUES(%s,%s,%s,%s,%s,%s)",
                            (plan_id, proposal["proposal_id"], draft_id, creator, version, revision_number),
                        )
                    revision_id = "empr-" + uuid.uuid4().hex
                    c.execute(
                        "INSERT INTO public.entry_master_plan_revisions("
                        "master_plan_revision_id,master_plan_id,revision_number,proposal_revision_id,proposal_content_hash,"
                        "source_draft_revision_id,source_understanding_revision_id,compiler_name,schema_version,canonical_content,canonical_content_hash) "
                        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)",
                        (revision_id, plan_id, revision_number, revision["proposal_revision_id"], revision["canonical_content_hash"],
                         source.draft_revision_id, source.understanding_revision_id, "master-plan-compiler-v1", "e3-v1",
                         json.dumps(candidate.content), candidate.content_hash),
                    )
                    c.execute("UPDATE public.entry_master_plans SET version=%s,latest_revision_number=%s,updated_at=now() WHERE master_plan_id=%s", (version, revision_number, plan_id))
                    result = self._master_plan_detail(c, creator, draft_id, plan_id)
                    self._complete_receipt(c, creator, command, idempotency_key, result)
                    return result
                except EntryE3Rejected as error:
                    self._fail_receipt(creator, command, idempotency_key, self._code(error))
                    raise
        except EntryE3Rejected:
            raise
        except Exception as exc:
            raise EntryProposalMasterPlanStoreUnavailable("ENTRY_PLAN_AUTHORITY_UNAVAILABLE") from exc

    def _master_plan_detail(self, c: Any, creator: str, draft_id: str, plan_id: str) -> Mapping[str, Any]:
        plan = c.execute(
            "SELECT * FROM public.entry_master_plans WHERE master_plan_id=%s AND creator_subject=%s AND draft_id=%s",
            (plan_id, creator, draft_id),
        ).fetchone()
        if not plan:
            raise EntryE3Rejected("ENTRY_PLAN_NOT_AVAILABLE")
        revisions = c.execute("SELECT * FROM public.entry_master_plan_revisions WHERE master_plan_id=%s ORDER BY revision_number", (plan_id,)).fetchall()
        def revision(row: Mapping[str, Any]) -> Mapping[str, Any]:
            return {
                "master_plan_revision_id": row["master_plan_revision_id"], "revision_number": int(row["revision_number"]),
                "proposal_revision_id": row["proposal_revision_id"], "proposal_content_hash": row["proposal_content_hash"],
                "source_draft_revision_id": row["source_draft_revision_id"], "source_understanding_revision_id": row["source_understanding_revision_id"],
                "compiler": row["compiler_name"], "schema_version": row["schema_version"], "content_hash": row["canonical_content_hash"],
                "content": dict(row["canonical_content"]), "created_at": row["created_at"].isoformat(),
            }
        return {
            "master_plan_id": plan_id, "proposal_id": plan["proposal_id"], "draft_id": draft_id, "version": int(plan["version"]),
            "latest_revision_number": int(plan["latest_revision_number"]), "current": revision(revisions[-1]),
            "revisions": [revision(row) for row in revisions], "pre_approval_only": True,
        }

    def get_master_plan(self, creator: str, draft_id: str) -> Mapping[str, Any]:
        try:
            with self._connect() as c:
                row = c.execute(
                    "SELECT mp.master_plan_id FROM public.entry_master_plans mp JOIN public.entry_proposals p ON p.proposal_id=mp.proposal_id "
                    "WHERE mp.draft_id=%s AND mp.creator_subject=%s", (draft_id, creator),
                ).fetchone()
                if not row:
                    return {"availability": "NOT_AVAILABLE", "reason": "ENTRY_PLAN_NOT_AVAILABLE", "item": None}
                return {"availability": "CURRENT", "item": self._master_plan_detail(c, creator, draft_id, row["master_plan_id"])}
        except Exception as exc:
            raise EntryProposalMasterPlanStoreUnavailable("ENTRY_PLAN_AUTHORITY_UNAVAILABLE") from exc

    def list_master_plan_revisions(self, creator: str, draft_id: str) -> Mapping[str, Any]:
        result = self.get_master_plan(creator, draft_id)
        return {"availability": result["availability"], "reason": result.get("reason"), "items": []} if not result.get("item") else {"availability": "CURRENT", "items": result["item"]["revisions"]}
