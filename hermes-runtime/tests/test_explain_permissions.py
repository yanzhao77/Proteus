import os
import unittest
from pathlib import Path

try:
    import psycopg
except ImportError:
    psycopg = None

from hermes_runtime.infrastructure.postgres_explain import PostgresExplainStore


DATABASE_URL = os.environ.get("HERMES_TEST_DATABASE_URL")


@unittest.skipUnless(DATABASE_URL and psycopg, "requires real PostgreSQL 14+")
class ExplainPermissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = PostgresExplainStore(DATABASE_URL)
        cls.store.check_server_version(140000)
        for migration in sorted((Path(__file__).parents[1] / "migrations").glob("*.sql")):
            cls.store.apply_migration(migration)

    def setUp(self):
        self.store.reset_for_test()

    def _as_role(self, role):
        connection = psycopg.connect(DATABASE_URL)
        connection.execute("SET ROLE " + role)
        return connection

    def test_runtime_roles_cannot_directly_write_explain_or_audit_tables(self):
        for role in (
            "hermes_worker_runtime",
            "hermes_verifier_runtime",
            "hermes_scheduler_runtime",
            "hermes_planner_runtime",
            "hermes_explain_capture_runtime",
            "hermes_explain_query_runtime",
            "hermes_metrics_runtime",
        ):
            with self.subTest(role=role):
                with self._as_role(role) as connection:
                    with self.assertRaises(psycopg.Error):
                        connection.execute(
                            """
                            INSERT INTO public.audit_trace_records(
                                audit_id,project_id,tenant_id,trace_id,correlation_id,
                                aggregate_type,aggregate_id,aggregate_version,aggregate_hash,
                                action,actor_type,actor_id,authorization_ref,redaction_class,
                                safe_summary,retention_policy,retention_until,command_id,
                                event_id,idempotency_key
                            ) VALUES (
                                'audit-forged','project-1','tenant-1','trace','corr',
                                'decision','decision-1',1,'sha256:decision','forge',
                                'worker','worker-1','authz','INTERNAL','{}',
                                'p3-standard','2099-01-01T00:00:00Z',
                                'cmd-forged','evt-forged','idem-forged'
                            )
                            """
                        )

    def test_public_worker_and_metrics_cannot_execute_capture_authority(self):
        function_call = """
            SELECT public.hermes_capture_decision_explain(
                'project-1','decision','decision-1',1,1,'sha256:decision',
                'decision-explain/1.0','explain-runtime/1.0','{}'::jsonb,
                '[{"node_id":"d1","node_type":"DecisionRecord","ref_id":"decision-1","ref_version":1,"ref_hash":"sha256:decision","status":"PRESENT","missing_reason":"","safe_summary":{}}]'::jsonb,
                '[]'::jsonb,'sha256:snapshot','sha256:graph','[]'::jsonb,
                'INTERNAL','p3-standard','2099-01-01T00:00:00Z','{"tenant_id":"tenant-1","project_id":"project-1"}'::jsonb,
                'system_operator','operator','authz','capture','cmd-perm','idem-perm',
                'sha256:payload',NULL,'corr','trace',NULL
            )
        """
        for role in ("hermes_worker_runtime", "hermes_verifier_runtime", "hermes_metrics_runtime"):
            with self.subTest(role=role):
                with self._as_role(role) as connection:
                    with self.assertRaises(psycopg.Error):
                        connection.execute(function_call)

    def test_security_definer_search_path_and_public_execute_are_hardened(self):
        with psycopg.connect(DATABASE_URL) as connection:
            self.assertEqual(
                0,
                connection.execute(
                    """
                    SELECT count(*)
                    FROM pg_proc p
                    JOIN pg_namespace n ON n.oid=p.pronamespace
                    WHERE n.nspname='public'
                      AND p.proname LIKE 'hermes_p3_explain%'
                      AND pg_get_functiondef(p.oid) NOT LIKE '%search_path TO ''pg_catalog''%'
                    """
                ).fetchone()[0],
            )
            self.assertFalse(
                connection.execute(
                    """
                    SELECT has_function_privilege(
                        'public',
                        'public.hermes_query_decision_explain(text,text,text,text,jsonb)',
                        'EXECUTE'
                    )
                    """
                ).fetchone()[0]
            )


if __name__ == "__main__":
    unittest.main()
