import os
import unittest
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

try:
    import psycopg
except ImportError:
    psycopg = None

from hermes_runtime.infrastructure.postgres_quarantine import PostgresQuarantineStore


DATABASE_URL = os.environ.get("HERMES_TEST_DATABASE_URL")


def role_dsn(base_dsn, user, password):
    parsed = urlsplit(base_dsn)
    host = parsed.hostname or "127.0.0.1"
    if parsed.port:
        host = "{}:{}".format(host, parsed.port)
    return urlunsplit(
        (parsed.scheme, "{}:{}@{}".format(user, password, host), parsed.path, "", "")
    )


@unittest.skipUnless(DATABASE_URL and psycopg, "requires real PostgreSQL 14+")
class QuarantinePermissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = PostgresQuarantineStore(DATABASE_URL)
        for migration in sorted((Path(__file__).parents[1] / "migrations").glob("*.sql")):
            cls.store.apply_migration(migration)
        cls.password = "hermes-p3-quarantine-role-test"
        cls.roles = {
            "review": "hermes_test_q_review_" + uuid.uuid4().hex[:8],
            "adoption": "hermes_test_q_adopt_" + uuid.uuid4().hex[:8],
            "redrive": "hermes_test_q_redrive_" + uuid.uuid4().hex[:8],
            "worker": "hermes_test_q_worker_" + uuid.uuid4().hex[:8],
            "scheduler": "hermes_test_q_sched_" + uuid.uuid4().hex[:8],
            "planner": "hermes_test_q_plan_" + uuid.uuid4().hex[:8],
            "verifier": "hermes_test_q_verifier_" + uuid.uuid4().hex[:8],
            "reader": "hermes_test_q_reader_" + uuid.uuid4().hex[:8],
        }
        memberships = {
            "review": "hermes_quarantine_review_runtime",
            "adoption": "hermes_quarantine_adoption_runtime",
            "redrive": "hermes_quarantine_redrive_runtime",
            "worker": "hermes_worker_runtime",
            "scheduler": "hermes_scheduler_runtime",
            "planner": "hermes_planner_runtime",
            "verifier": "hermes_verifier_runtime",
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

    def test_execute_surfaces_are_separated(self):
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            with self.connect_as("review") as connection:
                connection.execute(
                    """
                    SELECT public.hermes_request_quarantine_adoption(
                      'project-1','missing',0,'system_operator','op','authz','reason',
                      'cmd-guard','idem-guard','execution.result.adopt','{}'::jsonb,
                      '2099-01-01T00:00:00+00:00','cmd','idem','sha256:p',NULL,'corr',NULL
                    )
                    """
                )
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            with self.connect_as("adoption") as connection:
                connection.execute(
                    """
                    SELECT public.hermes_start_quarantine_review(
                      'project-1','missing',0,'system_operator','op','authz','reason',
                      '2099-01-01T00:00:00+00:00','cmd','idem','sha256:p',NULL,'corr',NULL
                    )
                    """
                )
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            with self.connect_as("redrive") as connection:
                connection.execute(
                    """
                    SELECT public.hermes_request_quarantine_adoption(
                      'project-1','missing',0,'system_operator','op','authz','reason',
                      'cmd-guard','idem-guard','execution.result.adopt','{}'::jsonb,
                      '2099-01-01T00:00:00+00:00','cmd','idem','sha256:p',NULL,'corr',NULL
                    )
                    """
                )

    def test_runtime_roles_cannot_directly_write_quarantine_authority_tables(self):
        statements = (
            "INSERT INTO public.quarantine_current_states(quarantine_id,lifecycle_state,retention_until) VALUES ('q','QUARANTINED',clock_timestamp())",
            "INSERT INTO public.quarantine_operations(operation_id,quarantine_id,project_id,operation_type,from_state,to_state,expected_version,resulting_version,actor_type,actor_id,reason,operation_payload_hash,original_payload_hash,source_command_id,idempotency_key,command_id,event_id,correlation_id,retention_until) VALUES ('op','q','project-1','START_REVIEW','QUARANTINED','UNDER_REVIEW',0,1,'system_operator','op','reason','sha256:p','sha256:o','cmd-src','idem','cmd','evt','corr',clock_timestamp())",
            "UPDATE public.execution_quarantine_records SET processing_state='P2_MINIMAL'",
            "DELETE FROM public.event_log",
        )
        for role in ("review", "adoption", "redrive", "worker", "scheduler", "planner", "verifier", "reader"):
            for statement in statements:
                with self.subTest(role=role, statement=statement):
                    with self.assertRaises((psycopg.errors.InsufficientPrivilege, psycopg.errors.ForeignKeyViolation, psycopg.errors.UndefinedTable)):
                        with self.connect_as(role) as connection:
                            connection.execute(statement)

    def test_forbidden_runtime_roles_cannot_execute_quarantine_authority(self):
        for role in ("worker", "scheduler", "planner", "verifier", "reader"):
            with self.subTest(role=role):
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    with self.connect_as(role) as connection:
                        connection.execute(
                            """
                            SELECT public.hermes_start_quarantine_review(
                              'project-1','missing',0,'system_operator','op','authz','reason',
                              '2099-01-01T00:00:00+00:00','cmd','idem','sha256:p',NULL,'corr',NULL
                            )
                            """
                        )

    def test_owner_is_nologin_public_has_no_execute_and_search_path_is_hardened(self):
        with psycopg.connect(DATABASE_URL) as connection:
            self.assertFalse(
                connection.execute(
                    "SELECT rolcanlogin FROM pg_roles WHERE rolname='hermes_p3_quarantine_evidence_owner'"
                ).fetchone()[0]
            )
            public_execute = connection.execute(
                """
                SELECT count(*) FROM information_schema.routine_privileges
                WHERE routine_schema='public'
                  AND grantee='PUBLIC'
                  AND routine_name LIKE 'hermes_%quarantine%'
                  AND privilege_type='EXECUTE'
                """
            ).fetchone()[0]
            self.assertEqual(0, public_execute)
            insecure = connection.execute(
                """
                SELECT count(*) FROM pg_proc p
                JOIN pg_namespace n ON n.oid=p.pronamespace
                WHERE n.nspname='public'
                  AND p.proname IN (
                    'hermes_start_quarantine_review',
                    'hermes_discard_quarantine',
                    'hermes_request_quarantine_adoption',
                    'hermes_mark_quarantine_adopted',
                    'hermes_request_quarantine_redrive',
                    'hermes_mark_quarantine_redriven',
                    'hermes_expire_quarantine'
                  )
                  AND (NOT p.prosecdef OR array_to_string(p.proconfig, ',') NOT LIKE '%search_path=pg_catalog%')
                """
            ).fetchone()[0]
            self.assertEqual(0, insecure)


if __name__ == "__main__":
    unittest.main()
