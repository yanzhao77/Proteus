import os
import unittest
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

try:
    import psycopg
except ImportError:
    psycopg = None

from hermes_runtime.application.planning import ActionPlanner, PlanCandidates
from hermes_runtime.infrastructure.postgres_planner import PostgresPlannerStore


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
class PlannerPermissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = PostgresPlannerStore(DATABASE_URL)
        for migration in sorted((Path(__file__).parents[1] / "migrations").glob("*.sql")):
            cls.store.apply_migration(migration)
        cls.password = "hermes-planner-role-test"
        cls.roles = {
            key: "hermes_test_planner_{}_{}".format(key, uuid.uuid4().hex[:8])
            for key in ("planner", "worker", "verifier", "situation", "diagnosis",
                        "accounting", "control")
        }
        memberships = {
            "planner": "hermes_planner_runtime",
            "worker": "hermes_worker_runtime",
            "verifier": "hermes_verifier_runtime",
            "situation": "hermes_situation_runtime",
            "diagnosis": "hermes_diagnosis_runtime",
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

    def test_runtime_roles_cannot_directly_write_planning_tables(self):
        sql = (
            "INSERT INTO planning_runs("
            "planning_run_id,project_id,situation_id,situation_version,"
            "analysis_context_id,analysis_context_hash,registry_version,"
            "planner_rule_version,resource_estimator_version,input_hash,"
            "candidate_count,created_by,command_id) "
            "VALUES ('forged','project','situation',1,'ctx','sha256:"
            + "0" * 64
            + "','action-registry/1.0','planner-rules/1.0',"
            "'resource-estimator/1.0','sha256:"
            + "1" * 64
            + "',1,'forged','cmd')"
        )
        for key in ("worker", "verifier", "situation", "diagnosis",
                    "accounting", "control", "planner"):
            with self.subTest(role=key):
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    with self.connect_as(key) as connection:
                        connection.execute(sql)

    def test_planner_runtime_cannot_mutate_upstream_or_reserve_or_create_objects(self):
        for statement in (
            "UPDATE situations SET version=999",
            "UPDATE diagnoses SET confidence_basis_points=1",
            "UPDATE projects SET state='ACCEPTED'",
            "UPDATE tasks SET state='PASSED'",
            "UPDATE artifacts SET media_type='x'",
            "UPDATE evidence SET valid=false",
            "INSERT INTO resource_reservations(reservation_id,account_id,project_id,owner_type,owner_id,status,account_version,command_id) VALUES ('r','a','p','action','a','ACTIVE',1,'c')",
            "CREATE TABLE forbidden_planner_shadow(id int)",
        ):
            with self.subTest(statement=statement):
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    with self.connect_as("planner") as connection:
                        connection.execute(statement)

    def test_public_has_no_sensitive_execute_and_owner_is_nologin(self):
        signature = (
            "hermes_apply_planning_run(text,text,text,bigint,text,text,text,text,"
            "text,text,text,text,integer,text,jsonb,text,text,text,text)"
        )
        with psycopg.connect(DATABASE_URL) as connection:
            self.assertFalse(connection.execute(
                "SELECT has_function_privilege('public',%s,'EXECUTE')",
                (signature,),
            ).fetchone()[0])
            owner = connection.execute(
                """SELECT rolcanlogin,rolsuper,rolcreaterole FROM pg_roles
                   WHERE rolname='hermes_planner_owner'"""
            ).fetchone()
        self.assertEqual((False, False, False), owner)

    def test_search_path_shadowing_fails(self):
        with self.connect_as("planner") as connection:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                connection.execute("CREATE TABLE planning_runs(id int)")

    def test_planner_runtime_may_execute_guarded_path_but_authority_rejects_missing(self):
        runtime = ActionPlanner(PostgresPlannerStore(
            role_dsn(DATABASE_URL, self.roles["planner"], self.password)
        ))
        with self.assertRaisesRegex(Exception, "PLANNER_SITUATION_NOT_FOUND"):
            runtime.plan(PlanCandidates(
                command_id="permission-planner-" + uuid.uuid4().hex[:8],
                idempotency_key="permission-planner-" + uuid.uuid4().hex[:8],
                project_id="missing-project",
                situation_id="missing-situation",
                expected_situation_version=1,
                analysis_context_id="missing-context",
                analysis_context_hash="sha256:" + "0" * 64,
            ))


if __name__ == "__main__":
    unittest.main()
