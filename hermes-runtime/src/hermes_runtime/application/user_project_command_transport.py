"""E11 creator-scoped command transport over the existing Control Plane.

This module intentionally does not create a second authority plane.  It accepts
only a verified OIDC user request, derives both requester and executor server
side, delegates to the existing Project ControlPlane, and returns a durable
receipt that must later be reconciled through E7 read projections.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol, Sequence

from hermes_runtime.application.commands import CancelProject, PauseProject, ResumeProject
from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.domain.models import Actor, ActorType, CommandEnvelope, CommandReceipt


class UserProjectCommandRejected(ValueError):
    """Stable rejection surfaced by the E11 Product API transport."""


class ActorProjectScope(Protocol):
    def project_ids_for(self, actor_scope: Mapping[str, Any]) -> Sequence[str] | None:
        ...


class ProjectReceiptReader(Protocol):
    def read_command_receipt(self, command_id: str, project_id: str) -> CommandReceipt | None:
        ...


class ProjectControlPlane(Protocol):
    def pause_project(self, command: PauseProject) -> CommandReceipt:
        ...

    def resume_project(self, command: ResumeProject) -> CommandReceipt:
        ...

    def cancel_project(self, command: CancelProject) -> CommandReceipt:
        ...


class UnavailableUserProjectCommandTransport:
    def submit(self, **_kwargs):
        raise UserProjectCommandRejected("E11_COMMAND_AUTHORITY_UNAVAILABLE")

    def receipt(self, **_kwargs):
        raise UserProjectCommandRejected("E11_COMMAND_AUTHORITY_UNAVAILABLE")


class UserProjectCommandTransport:
    """Trusted server-side bridge to existing Project semantic commands."""

    _ACTIONS = {"pause": "project.pause", "resume": "project.resume", "cancel": "project.cancel"}

    def __init__(
        self,
        control_plane: ProjectControlPlane,
        actor_project_scope: ActorProjectScope,
        receipt_reader: ProjectReceiptReader,
        *,
        executor_id: str = "e11-user-command-proxy",
    ) -> None:
        self._control_plane = control_plane
        self._actor_project_scope = actor_project_scope
        self._receipt_reader = receipt_reader
        self._executor = Actor(ActorType.CONTROL_PLANE, executor_id)

    def submit(
        self,
        *,
        action: str,
        project_id: str,
        verified_identity_subject: str,
        actor: Actor,
        command_id: str,
        expected_version: int,
        idempotency_key: str,
        reason: str,
        authorization_ref: str = "",
    ) -> Mapping[str, Any]:
        self._require_verified_creator(verified_identity_subject, actor)
        self._require_scope(verified_identity_subject, project_id)
        command_type = self._ACTIONS.get(action)
        if command_type is None:
            raise UserProjectCommandRejected("E11_COMMAND_ACTION_FORBIDDEN")
        if not isinstance(expected_version, int) or expected_version < 0:
            raise UserProjectCommandRejected("E11_COMMAND_EXPECTED_VERSION_INVALID")
        if not command_id or not idempotency_key:
            raise UserProjectCommandRejected("E11_COMMAND_METADATA_MISSING")
        if not reason.strip():
            raise UserProjectCommandRejected("E11_COMMAND_REASON_REQUIRED")
        if action == "cancel" and not authorization_ref.strip():
            raise UserProjectCommandRejected("CANCELLATION_AUTHORIZATION_REQUIRED")

        requester = Actor(ActorType.USER, verified_identity_subject)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type=command_type,
            idempotency_key=idempotency_key,
            expected_version=expected_version,
            actor=self._executor,
            reason=reason.strip(),
            project_id=project_id,
        )
        try:
            if action == "pause":
                receipt = self._control_plane.pause_project(PauseProject(envelope, requester, authorization_ref))
            elif action == "resume":
                receipt = self._control_plane.resume_project(ResumeProject(envelope, requester, authorization_ref))
            else:
                receipt = self._control_plane.cancel_project(CancelProject(envelope, requester, authorization_ref))
        except CommandRejected as exc:
            raise UserProjectCommandRejected(exc.code) from exc
        return self._receipt_payload(project_id, action, receipt)

    def receipt(
        self,
        *,
        project_id: str,
        command_id: str,
        verified_identity_subject: str,
        actor: Actor,
    ) -> Mapping[str, Any]:
        self._require_verified_creator(verified_identity_subject, actor)
        self._require_scope(verified_identity_subject, project_id)
        receipt = self._receipt_reader.read_command_receipt(command_id, project_id)
        if receipt is None:
            raise UserProjectCommandRejected("E11_COMMAND_RECEIPT_NOT_AVAILABLE")
        return self._receipt_payload(project_id, "", receipt)

    def _require_verified_creator(self, subject: str, actor: Actor) -> None:
        if not subject or actor.actor_type is not ActorType.USER or actor.actor_id != subject:
            raise UserProjectCommandRejected("E11_COMMAND_IDENTITY_REQUIRED")

    def _require_scope(self, subject: str, project_id: str) -> None:
        scoped = self._actor_project_scope.project_ids_for(
            {"identity_verified": True, "identity_subject": subject, "actor_id": subject}
        )
        if scoped is None:
            raise UserProjectCommandRejected("E11_COMMAND_SCOPE_UNAVAILABLE")
        if project_id not in {str(item) for item in scoped}:
            raise UserProjectCommandRejected("E11_COMMAND_NOT_AVAILABLE")

    @staticmethod
    def _receipt_payload(project_id: str, action: str, receipt: CommandReceipt) -> Mapping[str, Any]:
        return {
            "availability": "CURRENT",
            "command_id": receipt.command_id,
            "action": action or None,
            "receipt_status": receipt.status,
            "result_code": receipt.result_code,
            "target_version": receipt.target_version,
            "event_ids": list(receipt.event_ids),
            "project_id": project_id,
            "projection_status": "AWAITING_E7_RECONCILIATION",
            "completion_claim": "RECEIPT_IS_NOT_PROJECTION_STATE",
        }
