import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

import psycopg
from psycopg.rows import dict_row

from hermes_runtime.domain.entry_draft import EntryDraftRejected, EntryDraftState, require_transition


class EntryDraftStoreUnavailable(ValueError):
    pass


def _hash(value: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _required(value: object, name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise EntryDraftRejected("ENTRY_DRAFT_VALIDATION_FAILED")
    return value.strip()


class PostgresEntryDraftStore:
    """Transactional E1 authority; scoped strictly by verified creator subject."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def create(self, creator_subject: str, *, title: str, raw_input: str, idempotency_key: str, reason: str) -> Mapping[str, Any]:
        creator = _required(creator_subject, "creator", 256)
        title = _required(title, "title", 240)
        raw_input = _required(raw_input, "raw_input", 20000)
        key = _required(idempotency_key, "idempotency_key", 256)
        reason = _required(reason, "reason", 1000)
        request = {"title": title, "raw_input": raw_input, "reason": reason, "expected_version": 0}
        return self._command(creator, "entry_draft.create", key, request, None, lambda connection, command_id: self._create(connection, creator, title, raw_input, key, reason, command_id))

    def revise(self, creator_subject: str, draft_id: str, *, title: str, raw_input: str, expected_version: int, idempotency_key: str, reason: str) -> Mapping[str, Any]:
        return self._mutate(creator_subject, draft_id, "entry_draft.revise", EntryDraftState.DRAFT, expected_version, idempotency_key, reason, {"title": title, "raw_input": raw_input}, revise=True)

    def submit(self, creator_subject: str, draft_id: str, *, expected_version: int, idempotency_key: str, reason: str) -> Mapping[str, Any]:
        return self._mutate(creator_subject, draft_id, "entry_draft.submit", EntryDraftState.SUBMITTED, expected_version, idempotency_key, reason, {})

    def archive(self, creator_subject: str, draft_id: str, *, expected_version: int, idempotency_key: str, reason: str) -> Mapping[str, Any]:
        return self._mutate(creator_subject, draft_id, "entry_draft.archive", EntryDraftState.ARCHIVED, expected_version, idempotency_key, reason, {})

    def list(self, creator_subject: str) -> Mapping[str, Any]:
        creator = _required(creator_subject, "creator", 256)
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                rows = connection.execute("""SELECT draft_id,title,state,latest_revision_number,updated_at,version,created_at
                    FROM public.entry_drafts WHERE creator_subject=%s ORDER BY updated_at DESC,draft_id ASC""", (creator,)).fetchall()
            return {"availability": "CURRENT", "items": [self._summary(row) for row in rows], "as_of": _now(), "freshness": "NOT_AVAILABLE", "source": "entry_drafts", "source_version": None}
        except EntryDraftRejected:
            raise
        except Exception as exc:
            raise EntryDraftStoreUnavailable("ENTRY_DRAFT_AUTHORITY_UNAVAILABLE") from exc

    def get(self, creator_subject: str, draft_id: str) -> Mapping[str, Any]:
        creator = _required(creator_subject, "creator", 256)
        draft_id = _required(draft_id, "draft_id", 256)
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                draft = connection.execute("SELECT * FROM public.entry_drafts WHERE draft_id=%s AND creator_subject=%s", (draft_id, creator)).fetchone()
                if not draft:
                    return {"availability": "NOT_AVAILABLE", "item": None, "reason": "ENTRY_DRAFT_NOT_AVAILABLE"}
                revisions = connection.execute("SELECT revision_id,revision_number,title,raw_input,created_by_subject,draft_version,created_at FROM public.entry_draft_revisions WHERE draft_id=%s ORDER BY revision_number ASC", (draft_id,)).fetchall()
            item = self._detail(draft, revisions)
            return {"availability": "CURRENT", "item": item, "as_of": item["updated_at"], "freshness": "NOT_AVAILABLE", "source": "entry_drafts", "source_version": item["version"]}
        except EntryDraftRejected:
            raise
        except Exception as exc:
            raise EntryDraftStoreUnavailable("ENTRY_DRAFT_AUTHORITY_UNAVAILABLE") from exc

    def _mutate(self, creator_subject: str, draft_id: str, command_type: str, target: EntryDraftState, expected_version: int, idempotency_key: str, reason: str, changes: Mapping[str, Any], revise: bool = False) -> Mapping[str, Any]:
        creator = _required(creator_subject, "creator", 256)
        draft_id = _required(draft_id, "draft_id", 256)
        key = _required(idempotency_key, "idempotency_key", 256)
        reason = _required(reason, "reason", 1000)
        if not isinstance(expected_version, int) or expected_version < 1:
            raise EntryDraftRejected("ENTRY_DRAFT_VALIDATION_FAILED")
        if revise:
            changes = {"title": _required(changes.get("title"), "title", 240), "raw_input": _required(changes.get("raw_input"), "raw_input", 20000)}
        request = {"draft_id": draft_id, "expected_version": expected_version, "reason": reason, **changes}
        def apply(connection, command_id):
            draft = connection.execute("SELECT * FROM public.entry_drafts WHERE draft_id=%s AND creator_subject=%s FOR UPDATE", (draft_id, creator)).fetchone()
            if not draft:
                raise EntryDraftRejected("ENTRY_DRAFT_NOT_AVAILABLE")
            if int(draft["version"]) != expected_version:
                raise EntryDraftRejected("ENTRY_DRAFT_VERSION_CONFLICT")
            previous = EntryDraftState(draft["state"])
            next_version = expected_version + 1
            if revise:
                if previous is not EntryDraftState.DRAFT:
                    raise EntryDraftRejected("ENTRY_DRAFT_TRANSITION_FORBIDDEN")
                rev_number = int(draft["latest_revision_number"]) + 1
                connection.execute("""UPDATE public.entry_drafts SET title=%s,raw_input=%s,version=%s,latest_revision_number=%s,last_command_id=%s,updated_at=now()
                    WHERE draft_id=%s AND creator_subject=%s""", (changes["title"], changes["raw_input"], next_version, rev_number, command_id, draft_id, creator))
                connection.execute("""INSERT INTO public.entry_draft_revisions(revision_id,draft_id,revision_number,title,raw_input,created_by_subject,draft_version)
                    VALUES(%s,%s,%s,%s,%s,%s,%s)""", ("edr-" + uuid.uuid4().hex, draft_id, rev_number, changes["title"], changes["raw_input"], creator, next_version))
            else:
                require_transition(previous, target)
                connection.execute("""UPDATE public.entry_drafts SET state=%s,version=%s,last_command_id=%s,updated_at=now()
                    WHERE draft_id=%s AND creator_subject=%s""", (target.value, next_version, command_id, draft_id, creator))
                connection.execute("""INSERT INTO public.entry_draft_transition_records(transition_id,draft_id,command_id,previous_state,new_state,draft_version,actor_subject,reason,idempotency_key)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""", ("edt-" + uuid.uuid4().hex, draft_id, command_id, previous.value, target.value, next_version, creator, reason, key))
            result = self._get_locked(connection, creator, draft_id)
            return result
        return self._command(creator, command_type, key, request, draft_id, apply)

    def _create(self, connection, creator, title, raw_input, key, reason, command_id):
        draft_id = "ed-" + uuid.uuid4().hex
        connection.execute("""INSERT INTO public.entry_drafts(draft_id,creator_subject,title,raw_input,state,version,latest_revision_number,last_command_id)
            VALUES(%s,%s,%s,%s,'DRAFT',1,1,%s)""", (draft_id, creator, title, raw_input, command_id))
        connection.execute("""INSERT INTO public.entry_draft_revisions(revision_id,draft_id,revision_number,title,raw_input,created_by_subject,draft_version)
            VALUES(%s,%s,1,%s,%s,%s,1)""", ("edr-" + uuid.uuid4().hex, draft_id, title, raw_input, creator))
        connection.execute("""INSERT INTO public.entry_draft_transition_records(transition_id,draft_id,command_id,previous_state,new_state,draft_version,actor_subject,reason,idempotency_key)
            VALUES(%s,%s,%s,NULL,'DRAFT',1,%s,%s,%s)""", ("edt-" + uuid.uuid4().hex, draft_id, command_id, creator, reason, key))
        return self._get_locked(connection, creator, draft_id)

    def _command(self, creator, command_type, key, request, draft_id, apply):
        request_hash = _hash(request)
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                with connection.transaction():
                    receipt = connection.execute("SELECT * FROM public.entry_draft_command_receipts WHERE creator_subject=%s AND command_type=%s AND idempotency_key=%s FOR UPDATE", (creator, command_type, key)).fetchone()
                    if receipt:
                        if receipt["request_hash"] != request_hash:
                            raise EntryDraftRejected("ENTRY_DRAFT_IDEMPOTENCY_CONFLICT")
                        if receipt["status"] == "APPLIED":
                            return dict(receipt["result"])
                        raise EntryDraftRejected("ENTRY_DRAFT_COMMAND_REPLAY_UNAVAILABLE")
                    command_id = "edc-" + uuid.uuid4().hex
                    connection.execute("""INSERT INTO public.entry_draft_command_receipts(command_id,creator_subject,draft_id,command_type,idempotency_key,request_hash,status,result)
                        VALUES(%s,%s,%s,%s,%s,%s,'PROCESSING','{}'::jsonb)""", (command_id, creator, draft_id, command_type, key, request_hash))
                    result = apply(connection, command_id)
                    connection.execute("UPDATE public.entry_draft_command_receipts SET draft_id=%s,status='APPLIED',result=%s::jsonb,completed_at=now() WHERE command_id=%s", (result["draft_id"], json.dumps(result), command_id))
                    return result
        except EntryDraftRejected:
            raise
        except Exception as exc:
            raise EntryDraftStoreUnavailable("ENTRY_DRAFT_AUTHORITY_UNAVAILABLE") from exc

    def _get_locked(self, connection, creator, draft_id):
        draft = connection.execute("SELECT * FROM public.entry_drafts WHERE draft_id=%s AND creator_subject=%s", (draft_id, creator)).fetchone()
        revisions = connection.execute("SELECT revision_id,revision_number,title,raw_input,created_by_subject,draft_version,created_at FROM public.entry_draft_revisions WHERE draft_id=%s ORDER BY revision_number ASC", (draft_id,)).fetchall()
        return self._detail(draft, revisions)

    @staticmethod
    def _summary(row):
        return {"draft_id": row["draft_id"], "title": row["title"], "state": row["state"], "latest_revision": int(row["latest_revision_number"]), "updated_at": row["updated_at"].isoformat(), "created_at": row["created_at"].isoformat(), "version": int(row["version"]), "as_of": row["updated_at"].isoformat(), "freshness": "NOT_AVAILABLE", "source": "entry_drafts", "source_version": int(row["version"])}

    def _detail(self, draft, revisions):
        item = self._summary(draft)
        item["raw_input"] = draft["raw_input"]
        item["creator_subject"] = draft["creator_subject"]
        item["revisions"] = [{"revision_id": row["revision_id"], "revision_number": int(row["revision_number"]), "title": row["title"], "raw_input": row["raw_input"], "created_by": row["created_by_subject"], "draft_version": int(row["draft_version"]), "created_at": row["created_at"].isoformat()} for row in revisions]
        return item
