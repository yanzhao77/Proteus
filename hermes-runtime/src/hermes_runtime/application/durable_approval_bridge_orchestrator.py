from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from hermes_runtime.application.entry_approval_bridge import EntryApprovalBridgeApi
from hermes_runtime.application.entry_approval_bridge_saga import ApprovalBridgeSaga
from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.domain.entry_approval_bridge import EntryE4Rejected


class DurableBridgeStore(EntryApprovalBridgeApi, Protocol):
    def load_bridge(self, creator_subject: str, draft_id: str) -> Mapping[str, Any]: ...


@dataclass
class DurableApprovalBridgeOrchestrator(EntryApprovalBridgeApi):
    """Production E4 API: commit authority first, then advance/recover via ports."""

    store: DurableBridgeStore
    saga: ApprovalBridgeSaga

    def preview(self, creator_subject: str, draft_id: str) -> Mapping[str, object]:
        return self.store.preview(creator_subject, draft_id)

    def get_approval(self, creator_subject: str, draft_id: str) -> Mapping[str, object]:
        return self.store.get_approval(creator_subject, draft_id)

    def _advance(self, creator_subject: str, draft_id: str) -> Mapping[str, object]:
        bridge = self.store.load_bridge(creator_subject, draft_id)
        status = str(bridge["status"])
        if status == "MATERIALIZED":
            return {"bridge_id": bridge["bridge_id"], "status": status, "project_id": bridge.get("project_id")}
        if status == "FAILED_TERMINAL":
            raise EntryE4Rejected("ENTRY_APPROVAL_TERMINAL")
        try:
            return self.saga.materialize(bridge)
        except CommandRejected as exc:
            # A child authority explicitly rejected the deterministic request.
            # This is distinct from an unknown transport/process interruption:
            # preserve the child fact as a terminal E4 transition and never
            # manufacture a second identity or compensate via direct DML.
            self.saga.bridge_repository.transition(
                str(bridge["bridge_id"]), "FAILED_TERMINAL", exc.code
            )
            return {
                "bridge_id": bridge["bridge_id"],
                "status": "FAILED_TERMINAL",
                "project_id": None,
                "reason_code": exc.code,
            }

    def approve(self, creator_subject: str, draft_id: str, payload: Mapping[str, object]) -> Mapping[str, object]:
        # This commits the receipt/frozen blueprint before any child authority call.
        accepted = self.store.approve(creator_subject, draft_id, payload)
        try:
            return self._advance(creator_subject, draft_id)
        except EntryE4Rejected:
            raise
        except Exception:
            # The durable approval remains recoverable; no success is forged.
            return accepted

    def reconcile(self, creator_subject: str, draft_id: str, payload: Mapping[str, object]) -> Mapping[str, object]:
        if set(payload) - {"reason", "idempotency_key", "correlation_id"}:
            raise EntryE4Rejected("ENTRY_APPROVAL_SCHEMA_INVALID")
        return self._advance(creator_subject, draft_id)
