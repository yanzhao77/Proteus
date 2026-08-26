import unittest

from hermes_runtime.application.user_project_command_transport import (
    UserProjectCommandRejected,
    UserProjectCommandTransport,
)
from hermes_runtime.domain.models import Actor, ActorType, CommandReceipt


class _Scope:
    def __init__(self, project_ids=("project-1",)):
        self.project_ids = project_ids
        self.calls = []

    def project_ids_for(self, actor_scope):
        self.calls.append(dict(actor_scope))
        return self.project_ids


class _Plane:
    def __init__(self):
        self.commands = []

    def _receipt(self, command):
        self.commands.append(command)
        return CommandReceipt(
            command.envelope.command_id,
            "APPLIED",
            "PROJECT_TRANSITION_APPLIED",
            command.envelope.expected_version + 1,
            ("event-1",),
            {"project_id": command.envelope.project_id, "state": "PAUSED", "version": command.envelope.expected_version + 1},
        )

    def pause_project(self, command):
        return self._receipt(command)

    def resume_project(self, command):
        return self._receipt(command)

    def cancel_project(self, command):
        return self._receipt(command)


class _Reader:
    def __init__(self, receipt=None):
        self.receipt = receipt
        self.calls = []

    def read_command_receipt(self, command_id, project_id):
        self.calls.append((command_id, project_id))
        return self.receipt


class UserProjectCommandTransportTests(unittest.TestCase):
    def setUp(self):
        self.scope = _Scope()
        self.plane = _Plane()
        self.reader = _Reader()
        self.transport = UserProjectCommandTransport(self.plane, self.scope, self.reader)
        self.user = Actor(ActorType.USER, "creator-1")

    def _submit(self, **overrides):
        payload = {
            "action": "pause",
            "project_id": "project-1",
            "verified_identity_subject": "creator-1",
            "actor": self.user,
            "command_id": "cmd-1",
            "expected_version": 3,
            "idempotency_key": "idem-1",
            "reason": "creator requested pause",
            "authorization_ref": "",
        }
        payload.update(overrides)
        return self.transport.submit(**payload)

    def test_delegates_only_existing_semantic_command_with_split_identities(self):
        response = self._submit()
        command = self.plane.commands[0]
        self.assertEqual(ActorType.CONTROL_PLANE, command.envelope.actor.actor_type)
        self.assertEqual("e11-user-command-proxy", command.envelope.actor.actor_id)
        self.assertEqual(self.user, command.requested_by)
        self.assertEqual("project.pause", command.envelope.command_type)
        self.assertEqual("AWAITING_E7_RECONCILIATION", response["projection_status"])
        self.assertEqual("APPLIED", response["receipt_status"])
        self.assertEqual("RECEIPT_IS_NOT_PROJECTION_STATE", response["completion_claim"])

    def test_scope_is_server_derived_and_foreign_target_is_not_available(self):
        with self.assertRaisesRegex(UserProjectCommandRejected, "E11_COMMAND_NOT_AVAILABLE"):
            self._submit(project_id="project-foreign")
        self.assertEqual("creator-1", self.scope.calls[0]["identity_subject"])
        self.assertTrue(self.scope.calls[0]["identity_verified"])

    def test_identity_mismatch_and_forbidden_action_fail_closed(self):
        with self.assertRaisesRegex(UserProjectCommandRejected, "E11_COMMAND_IDENTITY_REQUIRED"):
            self._submit(actor=Actor(ActorType.USER, "different"))
        with self.assertRaisesRegex(UserProjectCommandRejected, "E11_COMMAND_ACTION_FORBIDDEN"):
            self._submit(action="retry")

    def test_metadata_reason_and_cancel_authorization_are_required(self):
        with self.assertRaisesRegex(UserProjectCommandRejected, "E11_COMMAND_EXPECTED_VERSION_INVALID"):
            self._submit(expected_version=-1)
        with self.assertRaisesRegex(UserProjectCommandRejected, "E11_COMMAND_REASON_REQUIRED"):
            self._submit(reason=" ")
        with self.assertRaisesRegex(UserProjectCommandRejected, "CANCELLATION_AUTHORIZATION_REQUIRED"):
            self._submit(action="cancel")

    def test_receipt_read_is_creator_scoped_and_never_claims_projection_applied(self):
        self.reader.receipt = CommandReceipt("cmd-1", "APPLIED", "PROJECT_TRANSITION_APPLIED", 4, ("event-1",), {"project_id": "project-1", "state": "PAUSED"})
        response = self.transport.receipt(project_id="project-1", command_id="cmd-1", verified_identity_subject="creator-1", actor=self.user)
        self.assertEqual([("cmd-1", "project-1")], self.reader.calls)
        self.assertEqual("AWAITING_E7_RECONCILIATION", response["projection_status"])
        self.assertNotIn("new_state", response)


if __name__ == "__main__":
    unittest.main()
