import os
import unittest
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

try:
    import psycopg
except ImportError:
    psycopg = None

from hermes_runtime.infrastructure.postgres_evidence_invalidation import (
    PostgresEvidenceInvalidationStore,
)


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
class EvidenceInvalidationPermissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = PostgresEvidenceInvalidationStore(DATABASE_URL)
        for migration in sorted((Path(__file__).parents[1] / "migrations").glob("*.sql")):
            cls.store.apply_migration(migration)
        cls.password = "hermes-p3-evidence-role-test"
        cls.roles = {
            "evidence": "hermes_test_evidence_" + uuid.uuid4().hex[:8],
            "worker": "hermes_test_evidence_worker_" + uuid.uuid4().hex[:8],
            "scheduler": "hermes_test_evidence_sched_" + uuid.uuid4().hex[:8],
            "planner": "hermes_test_evidence_plan_" + uuid.uuid4().hex[:8],
            "verifier": "hermes_test_evidence_verifier_" + uuid.uuid4().hex[:8],
            "reader": "hermes_test_evidence_reader_" + uuid.uuid4().hex[:8],
        }
        memberships = {
            "evidence": "hermes_evidence_invalidation_runtime",
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

    def test_only_evidence_runtime_can_execute_invalidation_surface(self):
        with self.connect_as("evidence") as connection:
            with self.assertRaises(psycopg.errors.RaiseException):
                connection.execute(
                    """
                    SELECT public.hermes_invalidate_evidence(
                      'project-1','missing-evidence',0,'system_operator','op',
                      'verification_engine','STALE','reason','UNKNOWN','{}'::jsonb,
                      '[]'::jsonb,'authz','cmd','idem','sha256:p',NULL,'corr',NULL
                    )
                    """
                )
        for role in ("worker", "scheduler", "planner", "verifier", "reader"):
            with self.subTest(role=role):
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    with self.connect_as(role) as connection:
                        connection.execute(
                            """
                            SELECT public.hermes_invalidate_evidence(
                              'project-1','missing-evidence',0,'system_operator','op',
                              'verification_engine','STALE','reason','UNKNOWN','{}'::jsonb,
                              '[]'::jsonb,'authz','cmd','idem','sha256:p',NULL,'corr',NULL
                            )
                            """
                        )

    def test_runtime_roles_cannot_directly_write_evidence_or_dependency_authority(self):
        statements = (
            "UPDATE public.evidence SET valid=false",
            "UPDATE public.verification_results SET verdict='FAIL'",
            "INSERT INTO public.evidence_current_states(evidence_id,validity_state,version) VALUES ('e','INVALIDATED',1)",
            "INSERT INTO public.evidence_invalidation_records(invalidation_id,evidence_id,project_id,artifact_id,artifact_hash,producer,reason_code,reason,scope,expected_version,resulting_version,payload_hash,affected_refs,dependency_refs,actor_type,actor_id,command_id,event_id,idempotency_key,correlation_id) VALUES ('i','e','project-1','a','sha256:a','p','r','reason','UNKNOWN',0,1,'sha256:p','{}','[]','system_operator','op','cmd','evt','idem','corr')",
            "UPDATE public.tasks SET state='FAILED'",
            "DELETE FROM public.event_log",
        )
        for role in ("evidence", "worker", "scheduler", "planner", "verifier", "reader"):
            for statement in statements:
                with self.subTest(role=role, statement=statement):
                    with self.assertRaises((psycopg.errors.InsufficientPrivilege, psycopg.errors.ForeignKeyViolation, psycopg.errors.UndefinedTable)):
                        with self.connect_as(role) as connection:
                            connection.execute(statement)

    def test_owner_public_execute_and_search_path_hardening(self):
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
                  AND routine_name LIKE 'hermes_%evidence%'
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
                    'hermes_invalidate_evidence',
                    'hermes_p3_evidence_refs_are_current'
                  )
                  AND (NOT p.prosecdef OR array_to_string(p.proconfig, ',') NOT LIKE '%search_path=pg_catalog%')
                """
            ).fetchone()[0]
            self.assertEqual(0, insecure)


if __name__ == "__main__":
    unittest.main()
