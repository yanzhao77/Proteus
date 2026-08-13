import os
import unittest
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

try:
    import psycopg
except ImportError:
    psycopg = None

from hermes_runtime.application.diagnoses import DiagnosisEngine, RunDiagnosis
from hermes_runtime.infrastructure.postgres_diagnosis import PostgresDiagnosisStore


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
class DiagnosisPermissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = PostgresDiagnosisStore(DATABASE_URL)
        for migration in sorted((Path(__file__).parents[1] / "migrations").glob("*.sql")):
            cls.store.apply_migration(migration)
        cls.password = "hermes-diagnosis-role-test"
        cls.roles = {
            key: "hermes_test_diagnosis_{}_{}".format(key, uuid.uuid4().hex[:8])
            for key in ("diagnosis", "worker", "verifier", "situation", "accounting", "control")
        }
        memberships = {
            "diagnosis": "hermes_diagnosis_runtime",
            "worker": "hermes_worker_runtime",
            "verifier": "hermes_verifier_runtime",
            "situation": "hermes_situation_runtime",
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

    def test_non_diagnosis_roles_cannot_create_diagnosis(self):
        sql = (
            "INSERT INTO diagnoses("
            "diagnosis_id,project_id,situation_id,situation_version,"
            "analysis_context_id,analysis_context_hash,observed_at_sequence,"
            "confidence_basis_points,root_cause_status,diagnostic_method,"
            "diagnosis_rule_set_version,input_hash,command_id) "
            "VALUES ('forged','project','situation',1,'ctx','sha256:"
            + "0" * 64
            + "',1,0,'UNKNOWN','forged','diagnosis-rules/1.0','sha256:"
            + "1" * 64
            + "','cmd')"
        )
        for key in ("worker", "verifier", "situation", "accounting", "control", "diagnosis"):
            with self.subTest(role=key):
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    with self.connect_as(key) as connection:
                        connection.execute(sql)

    def test_diagnosis_runtime_cannot_mutate_other_authorities_or_create_objects(self):
        for statement in (
            "UPDATE situations SET version=999",
            "UPDATE projects SET state='ACCEPTED'",
            "UPDATE tasks SET state='PASSED'",
            "UPDATE artifacts SET media_type='x'",
            "UPDATE evidence SET valid=false",
            "CREATE TABLE forbidden_diagnosis_shadow(id int)",
        ):
            with self.subTest(statement=statement):
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    with self.connect_as("diagnosis") as connection:
                        connection.execute(statement)

    def test_public_has_no_sensitive_execute_and_owner_is_nologin(self):
        signature = (
            "hermes_apply_diagnosis(text,text,text,bigint,text,text,text,text,"
            "text,text,integer,text,text[],jsonb,jsonb,jsonb,jsonb,text,text,text,text)"
        )
        with psycopg.connect(DATABASE_URL) as connection:
            self.assertFalse(connection.execute(
                "SELECT has_function_privilege('public',%s,'EXECUTE')",
                (signature,),
            ).fetchone()[0])
            owner = connection.execute(
                """SELECT rolcanlogin,rolsuper,rolcreaterole FROM pg_roles
                   WHERE rolname='hermes_diagnosis_owner'"""
            ).fetchone()
        self.assertEqual((False, False, False), owner)

    def test_search_path_shadowing_does_not_affect_security_definer_function(self):
        with self.connect_as("diagnosis") as connection:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                connection.execute("CREATE TABLE situations(id int)")

    def test_diagnosis_runtime_may_execute_guarded_function_but_authority_required(self):
        runtime = DiagnosisEngine(PostgresDiagnosisStore(
            role_dsn(DATABASE_URL, self.roles["diagnosis"], self.password)
        ))
        with self.assertRaisesRegex(Exception, "DIAGNOSIS_SITUATION_NOT_FOUND"):
            runtime.run(RunDiagnosis(
                command_id="permission-diagnosis-" + uuid.uuid4().hex[:8],
                idempotency_key="permission-diagnosis-" + uuid.uuid4().hex[:8],
                project_id="missing-project",
                situation_id="missing-situation",
                situation_version=1,
                analysis_context_id="missing-context",
                analysis_context_hash="sha256:" + "0" * 64,
            ))


if __name__ == "__main__":
    unittest.main()
