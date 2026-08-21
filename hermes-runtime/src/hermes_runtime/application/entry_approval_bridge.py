from __future__ import annotations

from typing import Mapping, Protocol


class EntryApprovalBridgeUnavailable(RuntimeError):
    pass


class EntryApprovalBridgeApi(Protocol):
    def preview(self, creator_subject: str, draft_id: str) -> Mapping[str, object]: ...
    def approve(self, creator_subject: str, draft_id: str, payload: Mapping[str, object]) -> Mapping[str, object]: ...
    def get_approval(self, creator_subject: str, draft_id: str) -> Mapping[str, object]: ...
    def reconcile(self, creator_subject: str, draft_id: str, payload: Mapping[str, object]) -> Mapping[str, object]: ...


class UnavailableEntryApprovalBridgeApi:
    def _raise(self) -> None:
        raise EntryApprovalBridgeUnavailable("ENTRY_APPROVAL_UNAVAILABLE")

    def preview(self, creator_subject: str, draft_id: str) -> Mapping[str, object]: self._raise()
    def approve(self, creator_subject: str, draft_id: str, payload: Mapping[str, object]) -> Mapping[str, object]: self._raise()
    def get_approval(self, creator_subject: str, draft_id: str) -> Mapping[str, object]: self._raise()
    def reconcile(self, creator_subject: str, draft_id: str, payload: Mapping[str, object]) -> Mapping[str, object]: self._raise()
