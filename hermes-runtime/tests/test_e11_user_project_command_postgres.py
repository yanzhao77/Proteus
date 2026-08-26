import os
import threading
import unittest

try:
    import psycopg  # noqa: F401
except ImportError:
    psycopg = None

from hermes_runtime.application.commands import CreateProject
from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.application.handlers import ControlPlane
from hermes_runtime.application.user_project_command_transport import (
    UserProjectCommandRejected,
    UserProjectCommandTransport,
)
from hermes_runtime.domain.models import Actor, ActorType, CommandEnvelope, ProjectState
from hermes_runtime.infrastructure.postgres_project import PostgresProjectStore

DATABASE_URL = os.environ.get("HERMES_TEST_DATABASE_URL")


class _Scope:
    def __init__(self, ids):
        self.ids = ids

    def project_ids_for(self, _scope):
        return self.ids


def _envelope(command_id, command_type, expected_version, idempotency_key, actor, reason, project_id="project-1"):
    return CommandEnvelope(command_id, command_type, idempotency_key, expected_version, actor, reason, project_id)


@unittest.skipUnless(DATABASE_URL and psycopg, "requires explicit PostgreSQL")
class E11UserProjectCommandPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = PostgresProjectStore(DATABASE_URL)
        cls.store.check_server_version(140000)

    def setUp(self):
        self.store.reset_for_test()
        self.control = Actor(ActorType.CONTROL_PLANE, "project-manager")
        self.creator = Actor(ActorType.USER, "creator-1")
        self.plane = ControlPlane(self.store)
        self.plane.create_project(CreateProject(_envelope("create-1", "project.create", 0, "create-idem", self.control, "create"), "E11 Project", self.creator))
        self.transport = UserProjectCommandTransport(self.plane, _Scope(("project-1",)), self.store)
        self._seed_guard(ProjectState.CREATED, 0, ProjectState.PAUSED, "pause")
        self._seed_guard(ProjectState.PAUSED, 1, ProjectState.CREATED, "resume")

    def _seed_guard(self, from_state, version, to_state, suffix):
        with self.store._connect() as connection:
            connection.execute("INSERT INTO project_evidence_facts (evidence_fact_id, project_id, project_version, from_state, to_state, result, authority, subject_ref) VALUES (%s,%s,%s,%s,%s,'VALID','verification_engine',%s)", (f'evidence-{suffix}', 'project-1', version, from_state.value, to_state.value, f'subject-{suffix}'))
            connection.execute("INSERT INTO project_policy_decision_facts (policy_decision_id, project_id, project_version, from_state, to_state, result, authority, policy_bundle_version, input_hash) VALUES (%s,%s,%s,%s,%s,'ALLOW','policy_engine','policy-test',%s)", (f'policy-{suffix}', 'project-1', version, from_state.value, to_state.value, f'sha256:{suffix}'))
            connection.execute("INSERT INTO project_budget_facts (budget_fact_id, project_id, project_version, from_state, to_state, status, authority, budget_scope_id, version) VALUES (%s,%s,%s,%s,%s,'OK','budget_engine',%s,1)", (f'budget-{suffix}', 'project-1', version, from_state.value, to_state.value, f'budget-project-1'))


    def _submit(self, action="pause", command_id="cmd-1", expected_version=0, key="idem-1", reason="creator requested action"):
        return self.transport.submit(
            action=action,
            project_id="project-1",
            verified_identity_subject="creator-1",
            actor=self.creator,
            command_id=command_id,
            expected_version=expected_version,
            idempotency_key=key,
            reason=reason,
        )

    def test_pause_persists_control_plane_executor_creator_requester_and_receipt(self):
        response = self._submit()
        self.assertEqual("APPLIED", response["receipt_status"])
        self.assertEqual("AWAITING_E7_RECONCILIATION", response["projection_status"])
        receipt = self.store.read_command_receipt("cmd-1", "project-1")
        self.assertIsNotNone(receipt)
        with self.store._connect() as connection:
            row = connection.execute("SELECT actor_type, actor_id, requested_by_type, requested_by_id FROM project_transition_records WHERE command_id = %s", ("cmd-1",)).fetchone()
        self.assertEqual(("control_plane", "e11-user-command-proxy", "user", "creator-1"), tuple(row))

    def test_same_idempotency_key_replays_same_authoritative_receipt_without_new_event(self):
        before = (self.store.count("event_log"), self.store.count("outbox_messages"))
        first = self._submit(command_id="cmd-1", key="idem-1")
        after_first = (self.store.count("event_log"), self.store.count("outbox_messages"))
        second = self._submit(command_id="cmd-2", key="idem-1")
        self.assertEqual(first["command_id"], second["command_id"])
        self.assertEqual((before[0] + 1, before[1] + 1), after_first)
        self.assertEqual(after_first, (self.store.count("event_log"), self.store.count("outbox_messages")))

    def test_stale_expected_version_rejects_and_foreign_scope_writes_nothing(self):
        with self.assertRaisesRegex(UserProjectCommandRejected, "VERSION_CONFLICT"):
            self._submit(expected_version=99, key="stale")
        foreign = UserProjectCommandTransport(self.plane, _Scope(()), self.store)
        before = (self.store.count("command_receipts"), self.store.count("event_log"), self.store.count("outbox_messages"))
        with self.assertRaisesRegex(UserProjectCommandRejected, "E11_COMMAND_NOT_AVAILABLE"):
            foreign.submit(action="pause", project_id="project-1", verified_identity_subject="creator-1", actor=self.creator, command_id="foreign", expected_version=1, idempotency_key="foreign", reason="foreign")
        self.assertEqual(before, (self.store.count("command_receipts"), self.store.count("event_log"), self.store.count("outbox_messages")))

    def test_same_idempotency_key_with_different_request_rejects_without_new_event(self):
        before = (self.store.count("event_log"), self.store.count("outbox_messages"))
        self._submit(command_id="conflict-first", key="conflict", reason="creator requested pause")
        after_first = (self.store.count("event_log"), self.store.count("outbox_messages"))
        with self.assertRaisesRegex(UserProjectCommandRejected, "IDEMPOTENCY_CONFLICT"):
            self._submit(command_id="conflict-second", key="conflict", reason="different creator reason")
        self.assertEqual((before[0] + 1, before[1] + 1), after_first)
        self.assertEqual(after_first, (self.store.count("event_log"), self.store.count("outbox_messages")))

    def test_concurrent_same_idempotency_key_converges_to_one_receipt_and_event(self):
        before = (self.store.count("event_log"), self.store.count("outbox_messages"))
        barrier = threading.Barrier(2)
        results = []
        errors = []

        def invoke(command_id):
            try:
                barrier.wait(timeout=5)
                results.append(self._submit(command_id=command_id, key="concurrent"))
            except Exception as exc:  # test captures only to assert stable convergence
                errors.append(exc)

        threads = [threading.Thread(target=invoke, args=(f"concurrent-{index}",)) for index in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        self.assertFalse(errors, errors)
        self.assertEqual(2, len(results))
        self.assertEqual(1, len({item["command_id"] for item in results}))
        self.assertEqual((before[0] + 1, before[1] + 1), (self.store.count("event_log"), self.store.count("outbox_messages")))

    def test_resume_after_pause_and_receipt_read(self):
        self._submit(action="pause", command_id="pause", key="pause")
        resumed = self._submit(action="resume", command_id="resume", expected_version=1, key="resume")
        self.assertEqual("APPLIED", resumed["receipt_status"])
        found = self.transport.receipt(project_id="project-1", command_id="resume", verified_identity_subject="creator-1", actor=self.creator)
        self.assertEqual("resume", found["command_id"])
        self.assertEqual("AWAITING_E7_RECONCILIATION", found["projection_status"])


if __name__ == "__main__":
    unittest.main()
