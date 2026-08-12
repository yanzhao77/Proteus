import os
import unittest
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

try:
    import psycopg
except ImportError:
    psycopg = None

from hermes_runtime.infrastructure.postgres import PostgresRuntimeStore


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
    DATABASE_URL and psycopg,
    "requires real PostgreSQL and role creation privileges",
)
class VerificationClosurePermissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = PostgresRuntimeStore(DATABASE_URL)
        for migration in sorted((Path(__file__).parents[1] / "migrations").glob("*.sql")):
            cls.store.apply_migration(migration)
        cls.password = "hermes-closure-role-test"
        cls.roles = {
            key: "hermes_test_closure_{}_{}".format(key, uuid.uuid4().hex[:8])
            for key in ("worker", "verifier", "control", "reader")
        }
        memberships = {
            "worker": "hermes_worker_runtime",
            "verifier": "hermes_verifier_runtime",
            "control": "hermes_control_plane_runtime",
            "reader": "hermes_read_only_runtime",
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

    def setUp(self):
        self.store.reset_for_test()

    def connect_as(self, key):
        return psycopg.connect(role_dsn(DATABASE_URL, self.roles[key], self.password))

    def test_worker_cannot_admit_run_create_plan_or_write_verification(self):
        statements = (
            "INSERT INTO agent_runs(run_id,project_id,task_id,run_kind,agent_identity,context_identity,status,created_by,command_id) VALUES ('x','x','x','VERIFIER','x','x','ADMITTED','x','x')",
            "INSERT INTO verification_plans(verification_plan_id,task_id,project_id,version,status,artifact_selectors,aggregation_rule,independence,created_by,command_id) VALUES ('x','x','x',1,'ACTIVE','[]','all_required_pass','worker_context_excluded','x','x')",
            "INSERT INTO verification_results(verification_id,task_id,artifact_id,artifact_hash,verifier_identity,criteria,verdict,correlation_id,occurred_at,command_id) VALUES ('x','x','x','sha256:x','x','x','PASS','x',now(),'x')",
        )
        for statement in statements:
            with self.subTest(statement=statement), self.assertRaises(
                psycopg.errors.InsufficientPrivilege
            ):
                with self.connect_as("worker") as connection:
                    connection.execute(statement)

    def test_verifier_can_read_plan_inputs_but_cannot_write_result_or_task(self):
        for statement in (
            "UPDATE tasks SET state='PASSED'",
            "INSERT INTO verification_results(verification_id,task_id,artifact_id,artifact_hash,verifier_identity,criteria,verdict,correlation_id,occurred_at,command_id) VALUES ('x','x','x','sha256:x','x','x','PASS','x',now(),'x')",
            "INSERT INTO verification_check_results(verification_id,check_id,status,finding_codes,evidence_refs,started_at,completed_at) VALUES ('x','x','PASS','[]','[]',now(),now())",
            "UPDATE agent_runs SET status='INVALIDATED'",
        ):
            with self.subTest(statement=statement), self.assertRaises(
                psycopg.errors.InsufficientPrivilege
            ):
                with self.connect_as("verifier") as connection:
                    connection.execute(statement)
        with self.connect_as("verifier") as connection:
            self.assertEqual([], connection.execute("SELECT * FROM verification_plans").fetchall())

    def test_runtime_roles_cannot_tamper_with_closure_authority(self):
        for role in ("worker", "verifier", "control", "reader"):
            for statement in (
                "DELETE FROM verification_plans",
                "UPDATE verification_plan_checks SET required=false",
                "DELETE FROM agent_runs",
                "UPDATE verification_check_results SET status='PASS'",
            ):
                with self.subTest(role=role, statement=statement), self.assertRaises(
                    psycopg.errors.InsufficientPrivilege
                ):
                    with self.connect_as(role) as connection:
                        connection.execute(statement)

    def test_public_cannot_execute_closure_trigger_functions(self):
        signatures = (
            "hermes_task_pass_authority_invariant()",
            "hermes_reject_plan_content_change()",
            "hermes_guard_agent_run_update()",
        )
        with psycopg.connect(DATABASE_URL) as connection:
            for signature in signatures:
                self.assertFalse(
                    connection.execute(
                        "SELECT has_function_privilege('public',%s,'EXECUTE')",
                        (signature,),
                    ).fetchone()[0]
                )

    def test_closure_owner_is_dedicated_nonlogin_role(self):
        with psycopg.connect(DATABASE_URL) as connection:
            owner = connection.execute(
                "SELECT tableowner FROM pg_tables WHERE schemaname='public' AND tablename='verification_plans'"
            ).fetchone()[0]
            login = connection.execute(
                "SELECT rolcanlogin FROM pg_roles WHERE rolname='hermes_closure_owner'"
            ).fetchone()[0]
        self.assertEqual("hermes_closure_owner", owner)
        self.assertFalse(login)


if __name__ == "__main__":
    unittest.main()
