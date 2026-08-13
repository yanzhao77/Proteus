import os
import unittest
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

try:
    import psycopg
except ImportError:
    psycopg = None

from hermes_runtime.application.capabilities import (
    ExecutionPreparationAuthority,
    RegisterCapabilitySchema,
)
from hermes_runtime.infrastructure.postgres_capability import PostgresCapabilityStore


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
class CapabilityPermissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.admin = PostgresCapabilityStore(DATABASE_URL)
        for migration in sorted((Path(__file__).parents[1] / "migrations").glob("*.sql")):
            cls.admin.apply_migration(migration)
        cls.password = "hermes-capability-role-test"
        cls.roles = {
            key: "hermes_test_capability_{}_{}".format(key, uuid.uuid4().hex[:8])
            for key in ("capability", "worker", "verifier", "control", "reader", "selection", "public")
        }
        memberships = {
            "capability": "hermes_capability_runtime",
            "worker": "hermes_worker_runtime",
            "verifier": "hermes_verifier_runtime",
            "control": "hermes_control_plane_runtime",
            "reader": "hermes_read_only_runtime",
            "selection": "hermes_selection_runtime",
        }
        with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
            for key, role in cls.roles.items():
                connection.execute(
                    psycopg.sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                        psycopg.sql.Identifier(role), psycopg.sql.Literal(cls.password)
                    )
                )
                if key in memberships:
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
        return psycopg.connect(role_dsn(DATABASE_URL, self.roles[key], self.password))

    def test_runtime_can_call_guarded_schema_command_but_cannot_directly_write_or_shadow(self):
        authority = ExecutionPreparationAuthority(PostgresCapabilityStore(
            role_dsn(DATABASE_URL, self.roles["capability"], self.password)
        ))
        result = authority.register_capability_schema(RegisterCapabilitySchema(
            "perm-cap-schema-" + uuid.uuid4().hex[:8],
            "perm-cap-schema-" + uuid.uuid4().hex[:8],
            "perm-project", "repair.code", "capability-schema/1.0",
            "permission probe",
        ))
        self.assertEqual("repair.code", result["capability_name"])
        direct_writes = (
            "INSERT INTO capability_schemas(capability_name,schema_version,description,content_hash,command_id,actor_type,actor_id) VALUES ('x','capability-schema/1.0','x','sha256:x','cmd','capability_registry','a')",
            "UPDATE worker_template_revisions SET trust_level='PRIVILEGED'",
            "INSERT INTO context_bundles(bundle_id,project_id,task_id,decision_id,action_id,template_id,template_revision,selector_schema_version,builder_version,manifest,manifest_hash,command_id,actor_type,actor_id) VALUES ('b','p','t','d','a','tpl',1,'context-selector/1.0','context-builder/1.0','{}','sha256:b','cmd','context_builder','a')",
            "UPDATE tasks SET state='PASSED'",
            "CREATE TABLE forbidden_capability_shadow(id int)",
        )
        for statement in direct_writes:
            with self.subTest(statement=statement[:40]):
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    with self.connect_as("capability") as connection:
                        connection.execute(statement)

    def test_public_and_other_runtimes_cannot_forge_capability_facts(self):
        signatures = (
            "hermes_register_capability_schema(jsonb,text,bigint,text,text,text,text,text,text,text)",
            "hermes_create_worker_template_revision(jsonb,text,bigint,text,text,text,text,text,text,text)",
            "hermes_change_worker_template_availability(jsonb,text,bigint,text,text,text,text,text,text,text)",
            "hermes_record_capability_match(jsonb,text,bigint,text,text,text,text,text,text,text)",
            "hermes_create_context_bundle(jsonb,text,bigint,text,text,text,text,text,text,text)",
            "hermes_compile_sandbox_profile(jsonb,text,bigint,text,text,text,text,text,text,text)",
            "hermes_apply_execution_preparation_fact_internal(text,jsonb,text,bigint,text,text,text,text,text,text,text)",
        )
        with psycopg.connect(DATABASE_URL) as connection:
            for signature in signatures:
                with self.subTest(signature=signature):
                    self.assertFalse(connection.execute(
                        "SELECT has_function_privilege('public',%s,'EXECUTE')",
                        (signature,),
                    ).fetchone()[0])
            roles = connection.execute(
                """SELECT rolname,rolcanlogin,rolsuper,rolcreaterole FROM pg_roles
                   WHERE rolname IN ('hermes_capability_owner','hermes_capability_runtime')
                   ORDER BY rolname"""
            ).fetchall()
        self.assertEqual([
            ("hermes_capability_owner", False, False, False),
            ("hermes_capability_runtime", False, False, False),
        ], roles)
        for key in ("worker", "verifier", "control", "reader", "selection", "public"):
            with self.subTest(role=key):
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    with self.connect_as(key) as connection:
                        connection.execute(
                            """SELECT public.hermes_register_capability_schema(
                               '{}'::jsonb,'p',0,'cmd','key','hash',
                               'capability.register_schema',
                               'capability_registry','a',NULL)"""
                        )

    def test_security_definer_search_path_and_secret_error_redaction(self):
        with self.connect_as("capability") as connection:
            connection.execute(
                "CREATE TEMP TABLE command_receipts(command_id text)"
            )
        authority = ExecutionPreparationAuthority(PostgresCapabilityStore(
            role_dsn(DATABASE_URL, self.roles["capability"], self.password)
        ))
        with self.assertRaisesRegex(Exception, "SECRET_VALUE_FORBIDDEN"):
            authority.register_capability_schema(RegisterCapabilitySchema(
                "perm-secret-" + uuid.uuid4().hex[:8],
                "perm-secret-" + uuid.uuid4().hex[:8],
                "perm-project", "repair.secret", "capability-schema/1.0",
                "sk-123456789012",
            ))
        with psycopg.connect(DATABASE_URL) as connection:
            rejected = connection.execute(
                """SELECT result::text FROM command_receipts
                   WHERE command_type='capability.register_schema'
                     AND status='REJECTED'
                   ORDER BY completed_at DESC LIMIT 1"""
            ).fetchone()[0]
        self.assertNotIn("sk-123456789012", rejected)


if __name__ == "__main__":
    unittest.main()
