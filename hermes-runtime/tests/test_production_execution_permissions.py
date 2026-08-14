import os
import unittest
from pathlib import Path

try:
    import psycopg
except ImportError:
    psycopg = None

from hermes_runtime.infrastructure.postgres_production_execution import PostgresProductionExecutionStore


DATABASE_URL = os.environ.get("HERMES_TEST_DATABASE_URL")


@unittest.skipUnless(DATABASE_URL and psycopg, "requires real PostgreSQL 14+")
class ProductionExecutionPermissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = PostgresProductionExecutionStore(DATABASE_URL)
        cls.store.check_server_version(140000)
        for migration in sorted((Path(__file__).parents[1] / "migrations").glob("*.sql")):
            cls.store.apply_migration(migration)

    def setUp(self):
        self.store.reset_for_test()

    def _as_role(self, role):
        connection = psycopg.connect(DATABASE_URL)
        connection.execute("SET ROLE " + role)
        return connection

    def test_worker_verifier_and_read_roles_cannot_write_docker_authority(self):
        for role in ("hermes_worker_runtime", "hermes_verifier_runtime", "hermes_read_only_runtime", "hermes_docker_adapter_runtime"):
            with self.subTest(role=role):
                with self._as_role(role) as connection:
                    with self.assertRaises(psycopg.Error):
                        connection.execute(
                            """
                            INSERT INTO public.docker_process_runs(
                                process_id,project_id,execution_request_id,run_id,
                                lease_id,lease_version,fencing_token,container_name,
                                plan_hash,lifecycle_state,trace_id,correlation_id,
                                command_id,last_event_id
                            ) VALUES (
                                'forged','project-1','exec','run','lease',1,1,
                                'container','sha256:plan','RUNNING','trace','corr',
                                'cmd','evt'
                            )
                            """
                        )

    def test_public_execute_and_search_path_are_hardened(self):
        with psycopg.connect(DATABASE_URL) as connection:
            self.assertFalse(
                connection.execute(
                    """
                    SELECT has_function_privilege(
                        'public',
                        'public.hermes_record_docker_process(text,text,text,text,bigint,bigint,text,text,text,text,text,text,text,text,text,text,text,text,text,text)',
                        'EXECUTE'
                    )
                    """
                ).fetchone()[0]
            )
            self.assertEqual(
                0,
                connection.execute(
                    """
                    SELECT count(*)
                    FROM pg_proc p
                    JOIN pg_namespace n ON n.oid=p.pronamespace
                    WHERE n.nspname='public'
                      AND p.proname LIKE 'hermes_p3_docker%'
                      AND pg_get_functiondef(p.oid) NOT LIKE '%search_path TO ''pg_catalog''%'
                    """
                ).fetchone()[0],
            )


if __name__ == "__main__":
    unittest.main()
