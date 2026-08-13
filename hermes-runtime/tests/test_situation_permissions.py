import os
import unittest
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

try:
    import psycopg
except ImportError:
    psycopg = None

from hermes_runtime.infrastructure.postgres_situation import PostgresSituationStore
from hermes_runtime.application.situations import SituationAnalyzer
from hermes_runtime.application.commands import CreateProject
from hermes_runtime.application.handlers import ControlPlane
from hermes_runtime.domain.models import Actor, ActorType, CommandEnvelope
from hermes_runtime.infrastructure.postgres_project import PostgresProjectStore
from psycopg.types.json import Jsonb


DATABASE_URL = os.environ.get("HERMES_TEST_DATABASE_URL")


def role_dsn(base_dsn, user, password):
    parsed = urlsplit(base_dsn)
    host = parsed.hostname or "127.0.0.1"
    if parsed.port:
        host = "{}:{}".format(host, parsed.port)
    return urlunsplit(
        (parsed.scheme, "{}:{}@{}".format(user, password, host), parsed.path, "", "")
    )


@unittest.skipUnless(
    DATABASE_URL and psycopg, "requires real PostgreSQL and role creation privileges"
)
class SituationPermissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = PostgresSituationStore(DATABASE_URL)
        for migration in sorted((Path(__file__).parents[1] / "migrations").glob("*.sql")):
            cls.store.apply_migration(migration)
        cls.password = "hermes-situation-role-test"
        cls.roles = {
            key: "hermes_test_situation_{}_{}".format(key, uuid.uuid4().hex[:8])
            for key in ("situation", "worker", "verifier", "accounting", "control")
        }
        memberships = {
            "situation": "hermes_situation_runtime",
            "worker": "hermes_worker_runtime",
            "verifier": "hermes_verifier_runtime",
            "accounting": "hermes_accounting_runtime",
            "control": "hermes_control_plane_runtime",
        }
        with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
            for key, role in cls.roles.items():
                connection.execute(
                    psycopg.sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                        psycopg.sql.Identifier(role), psycopg.sql.Literal(cls.password)
                    )
                )
                connection.execute(
                    psycopg.sql.SQL("GRANT {} TO {}").format(
                        psycopg.sql.Identifier(memberships[key]),
                        psycopg.sql.Identifier(role),
                    )
                )

    @classmethod
    def tearDownClass(cls):
        with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
            for role in cls.roles.values():
                connection.execute(
                    psycopg.sql.SQL("DROP ROLE IF EXISTS {}").format(
                        psycopg.sql.Identifier(role)
                    )
                )

    def connect_as(self, key):
        return psycopg.connect(role_dsn(
            DATABASE_URL, self.roles[key], self.password
        ))

    def test_non_situation_roles_cannot_write_situation_tables(self):
        for key in ("worker", "verifier", "accounting", "control", "situation"):
            with self.subTest(role=key):
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    with self.connect_as(key) as connection:
                        connection.execute(
                            "DELETE FROM situations WHERE situation_id='forged'"
                        )

    def test_situation_runtime_cannot_mutate_other_authorities_or_create_objects(self):
        for statement in (
            "UPDATE projects SET state='ACCEPTED'",
            "UPDATE tasks SET state='PASSED'",
            "UPDATE resource_accounts SET version=999",
            "CREATE TABLE forbidden_situation_shadow(id int)",
        ):
            with self.subTest(statement=statement):
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    with self.connect_as("situation") as connection:
                        connection.execute(statement)

    def test_public_has_no_sensitive_execute_and_owner_is_nologin(self):
        signatures = (
            "hermes_apply_situation_effect(text,text,text,bigint,text,jsonb,text,boolean,text,text,text,text,integer,text[],text[],text[],text[],text,text,text,text,text,text[],text[],text[],text,bigint,text)",
            "hermes_resolve_situation(text,text,bigint,text,text,text,text)",
        )
        with psycopg.connect(DATABASE_URL) as connection:
            for signature in signatures:
                self.assertFalse(connection.execute(
                    "SELECT has_function_privilege('public',%s,'EXECUTE')",
                    (signature,),
                ).fetchone()[0])
            owner = connection.execute(
                """SELECT rolcanlogin,rolsuper,rolcreaterole FROM pg_roles
                   WHERE rolname='hermes_situation_owner'"""
            ).fetchone()
        self.assertEqual((False, False, False), owner)

    def test_situation_runtime_can_apply_guarded_effect_but_not_direct_write(self):
        project_id = "permission-project-" + uuid.uuid4().hex[:8]
        task_id = "permission-task-" + uuid.uuid4().hex[:8]
        create_command = "permission-create-" + uuid.uuid4().hex[:8]
        ready_command = "permission-ready-" + uuid.uuid4().hex[:8]
        ready_event = "permission-event-" + uuid.uuid4().hex[:8]
        receipt = ControlPlane(PostgresProjectStore(DATABASE_URL)).create_project(
            CreateProject(
                CommandEnvelope(
                    create_command, "project.create", create_command, 0,
                    Actor(ActorType.CONTROL_PLANE, "permission-control"),
                    "permission fixture", project_id,
                ),
                "Permission project", Actor(ActorType.USER, "permission-user"),
            )
        )
        runtime_store = PostgresSituationStore(
            role_dsn(DATABASE_URL, self.roles["situation"], self.password),
            "permission-situation-consumer",
        )
        runtime_analyzer = SituationAnalyzer(runtime_store)
        with psycopg.connect(DATABASE_URL) as connection:
            project_envelope = connection.execute(
                "SELECT public.hermes_event_envelope(%s)", (receipt.event_ids[0],)
            ).fetchone()[0]
        self.assertEqual(
            "IGNORED_NOT_A_TRIGGER",
            runtime_analyzer.analyze(project_envelope)["classification"],
        )
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute(
                """INSERT INTO tasks(task_id,project_id,state,version)
                   VALUES (%s,%s,'READY',1)""", (task_id, project_id)
            )
            connection.execute(
                """INSERT INTO command_receipts(
                   command_id,project_id,command_type,idempotency_key,
                   request_hash,status,result,completed_at)
                   VALUES (%s,%s,'task.recompute_readiness',%s,'fixture',
                           'APPLIED','{}',now())""",
                (ready_command, project_id, ready_command),
            )
            payload = {
                "graph_version": 0,
                "ready_state_changes": [{
                    "task_id": task_id, "from_state": "NEW", "to_state": "READY"
                }],
            }
            connection.execute(
                """INSERT INTO event_log(
                   event_id,event_type,schema_version,producer_type,producer_id,
                   project_id,partition_key,command_id,correlation_id,task_id,payload)
                   VALUES (%s,'task.readiness_recomputed','1.0','control_plane',
                           'test',%s,%s,%s,%s,%s,%s)""",
                (ready_event, project_id, project_id, ready_command,
                 ready_command, task_id, Jsonb(payload)),
            )
            envelope = connection.execute(
                "SELECT public.hermes_event_envelope(%s)", (ready_event,)
            ).fetchone()[0]
        result = runtime_analyzer.analyze(envelope)
        self.assertEqual("CREATED", result["classification"])
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            with self.connect_as("situation") as connection:
                connection.execute(
                    "UPDATE situations SET version=999 WHERE situation_id=%s",
                    (result["situation_id"],),
                )


if __name__ == "__main__":
    unittest.main()
