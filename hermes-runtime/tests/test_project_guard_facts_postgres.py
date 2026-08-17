import os
import unittest
import uuid
from pathlib import Path

try:
    import psycopg
except ImportError:
    psycopg = None

from hermes_runtime.application.commands import (
    CreateProject,
    RecordProjectEvidenceFact,
    RecordProjectPolicyFact,
)
from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.application.handlers import ControlPlane
from hermes_runtime.application.project_guard_facts import ProjectGuardFactAuthority
from hermes_runtime.domain.models import Actor, ActorType, CommandEnvelope, ProjectState
from hermes_runtime.infrastructure.postgres_project import PostgresProjectStore


DATABASE_URL = os.environ.get("HERMES_TEST_DATABASE_URL")


def envelope(command_type, actor, expected_version, key, reason="p6 guard fact test"):
    return CommandEnvelope(
        "cmd-" + uuid.uuid4().hex, command_type, key, expected_version,
        actor, reason, "project-1",
    )


@unittest.skipUnless(
    DATABASE_URL and psycopg,
    "requires psycopg and explicit HERMES_TEST_DATABASE_URL pointing to PostgreSQL 14+",
)
class ProjectGuardFactPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = PostgresProjectStore(DATABASE_URL)
        cls.store.check_server_version(140000)
        migrations = Path(__file__).parents[1] / "migrations"
        for migration in sorted(migrations.glob("*.sql")):
            cls.store.apply_migration(migration)

    def setUp(self):
        self.store.reset_for_test()
        self.authority = ProjectGuardFactAuthority(PostgresProjectStore(DATABASE_URL))
        self.control = Actor(ActorType.CONTROL_PLANE, "project-manager")
        self.worker = Actor(ActorType.WORKER, "worker-1")
        self.plane = ControlPlane(PostgresProjectStore(DATABASE_URL))
        self.plane.create_project(CreateProject(
            envelope("project.create", self.control, 0, "key-create-p6"),
            "P6 guard fact project",
            Actor(ActorType.USER, "user-1"),
        ))

    def _evidence(self, suffix="1", **overrides):
        values = dict(
            envelope=dict(
                command_id="cmd-ev-" + suffix,
                command_type="project.record_evidence_fact",
                idempotency_key="key-ev-" + suffix,
                expected_version=0,
                actor=self.control,
                reason="record verification evidence fact",
                project_id="project-1",
            ),
            evidence_fact_id="evidence-p6-" + suffix,
            project_version=0,
            from_state="CREATED",
            to_state="INTAKE",
            subject_ref="subject-p6-" + suffix,
        )
        values.update(overrides)
        env = values.pop("envelope")
        return RecordProjectEvidenceFact(CommandEnvelope(**env), **values)

    def _policy(self, suffix="1", **overrides):
        values = dict(
            envelope=dict(
                command_id="cmd-pol-" + suffix,
                command_type="project.record_policy_fact",
                idempotency_key="key-pol-" + suffix,
                expected_version=0,
                actor=self.control,
                reason="record policy decision fact",
                project_id="project-1",
            ),
            policy_decision_id="policy-p6-" + suffix,
            project_version=0,
            from_state="CREATED",
            to_state="INTAKE",
            result="ALLOW",
            policy_bundle_version="policy-bundle/1.0",
            input_hash="sha256:" + uuid.uuid4().hex,
        )
        values.update(overrides)
        env = values.pop("envelope")
        return RecordProjectPolicyFact(CommandEnvelope(**env), **values)

    def _count(self, table):
        with psycopg.connect(DATABASE_URL) as connection:
            return connection.execute(
                "SELECT count(*) FROM " + table
            ).fetchone()[0]

    def _current_fact(self, table, fact_id):
        with psycopg.connect(DATABASE_URL) as connection:
            return connection.execute(
                "SELECT * FROM {} WHERE {}='{}'".format(
                    table,
                    "evidence_fact_id" if "evidence" in table else "policy_decision_id",
                    fact_id,
                )
            ).fetchone()

    def test_record_evidence_and_policy_facts_commit_atomically(self):
        evidence = self.authority.record_evidence_fact(self._evidence())
        self.assertEqual("APPLIED", evidence.status)
        self.assertEqual("PROJECT_GUARD_FACT_RECORDED", evidence.result_code)
        self.assertEqual(1, self._count("project_evidence_facts"))
        self.assertEqual(0, self._count("project_policy_decision_facts"))

        policy = self.authority.record_policy_fact(self._policy())
        self.assertEqual("APPLIED", policy.status)
        self.assertEqual(1, self._count("project_policy_decision_facts"))
        # both facts + events + receipts committed together per command
        with psycopg.connect(DATABASE_URL) as connection:
            events = connection.execute(
                "SELECT event_type FROM event_log ORDER BY sequence"
            ).fetchall()
            types = [row[0] for row in events]
        self.assertIn("project.evidence_fact_recorded", types)
        self.assertIn("project.policy_fact_recorded", types)

    def test_duplicate_command_returns_original_without_second_fact(self):
        command = self._evidence()
        first = self.authority.record_evidence_fact(command)
        second = self.authority.record_evidence_fact(command)
        self.assertEqual(first, second)
        self.assertEqual(1, self._count("project_evidence_facts"))

    def test_supersede_current_fact_and_version_conflict(self):
        self.authority.record_evidence_fact(self._evidence("a"))
        self.authority.record_evidence_fact(self._evidence("b"))
        self.assertEqual(2, self._count("project_evidence_facts"))
        with psycopg.connect(DATABASE_URL) as connection:
            superseded = connection.execute(
                "SELECT valid FROM project_evidence_facts WHERE evidence_fact_id='evidence-p6-a'"
            ).fetchone()[0]
            current = connection.execute(
                "SELECT valid FROM project_evidence_facts WHERE evidence_fact_id='evidence-p6-b'"
            ).fetchone()[0]
        self.assertFalse(superseded)
        self.assertTrue(current)

        with self.assertRaisesRegex(CommandRejected, "PROJECT_AUTHORITY_PRECONDITION_FAILED"):
            self.authority.record_evidence_fact(self._evidence("c", project_version=5))

    def test_worker_cannot_record_guard_facts(self):
        with self.assertRaisesRegex(CommandRejected, "CONTROL_PLANE_AUTHORITY_REQUIRED"):
            self.authority.record_evidence_fact(self._evidence("w", **{
                "envelope": dict(
                    command_id="cmd-ev-w",
                    command_type="project.record_evidence_fact",
                    idempotency_key="key-ev-w",
                    expected_version=0,
                    actor=self.worker,
                    reason="worker tries to record evidence",
                    project_id="project-1",
                )
            }))
        self.assertEqual(0, self._count("project_evidence_facts"))

    def test_wrong_command_type_is_rejected(self):
        with self.assertRaisesRegex(CommandRejected, "PROJECT_COMMAND_SEMANTICS_MISMATCH"):
            self.authority.record_policy_fact(self._policy("bad", **{
                "envelope": dict(
                    command_id="cmd-pol-bad",
                    command_type="project.record_evidence_fact",
                    idempotency_key="key-pol-bad",
                    expected_version=0,
                    actor=self.control,
                    reason="wrong command type",
                    project_id="project-1",
                )
            }))
        self.assertEqual(0, self._count("project_policy_decision_facts"))

    def test_policy_result_and_input_hash_validation(self):
        with self.assertRaisesRegex(CommandRejected, "PROJECT_POLICY_RESULT_INVALID"):
            self.authority.record_policy_fact(self._policy("r", result="MAYBE"))
        with self.assertRaisesRegex(CommandRejected, "PROJECT_POLICY_INPUT_HASH_INVALID"):
            self.authority.record_policy_fact(self._policy("h", input_hash="not-a-hash"))


if __name__ == "__main__":
    unittest.main()
