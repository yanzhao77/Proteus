import os
import unittest
from pathlib import Path

try:
    import psycopg
except ImportError:
    psycopg = None

from hermes_runtime.infrastructure.postgres_scheduler import PostgresSchedulerStore


DATABASE_URL = os.environ.get("HERMES_TEST_DATABASE_URL")


@unittest.skipUnless(DATABASE_URL and psycopg, "requires real PostgreSQL 14+")
class SchedulerPermissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.admin = PostgresSchedulerStore(DATABASE_URL)
        for migration in sorted((Path(__file__).parents[1] / "migrations").glob("*.sql")):
            cls.admin.apply_migration(migration)

    def assert_role_forbidden(self, role, statement):
        with psycopg.connect(DATABASE_URL) as connection:
            with self.assertRaises(psycopg.Error):
                connection.execute("SET ROLE " + role)
                connection.execute(statement)

    def test_scheduler_runtime_cannot_directly_write_lease_token_lock_or_queue_state(self):
        for statement in (
            "INSERT INTO public.execution_leases(lease_id,execution_request_id,queue_item_id,project_id,task_id,scheduler_id,scheduler_session_id,actor_type,actor_id,profile_id,profile_version,fencing_token,lease_state,lease_version,grant_generation,granted_at,heartbeat_at,expires_at,max_expires_at,lock_scope_hash,lock_refs,command_id,idempotency_key,payload_hash,reason) VALUES ('l','e','q','p','t','s','ss','scheduler','s','p2-default',1,1,'ACTIVE',1,1,now(),now(),now(),now(),'sha256:x','[]','cmd','k','sha256:p','r')",
            "UPDATE public.execution_fencing_counters SET last_token=99",
            "INSERT INTO public.execution_lock_ownerships(lock_scope,project_id,execution_request_id,queue_item_id,lease_id,fencing_token,owner_scheduler_id,owner_session_id,lock_state,acquired_at,expires_at,command_id) VALUES ('repository:x','p','e','q','l',1,'s','ss','ACTIVE',now(),now(),'cmd')",
            "UPDATE public.execution_queue_current_states SET queue_state='LEASED'",
            "UPDATE public.execution_request_current_states SET request_state='LEASED'",
        ):
            with self.subTest(statement=statement[:40]):
                self.assert_role_forbidden("hermes_scheduler_runtime", statement)

    def test_worker_and_other_runtimes_cannot_call_scheduler_authority_functions(self):
        for role in (
            "hermes_worker_runtime",
            "hermes_verifier_runtime",
            "hermes_capability_runtime",
            "hermes_accounting_runtime",
            "hermes_selection_runtime",
            "hermes_policy_runtime",
            "hermes_risk_runtime",
            "hermes_planner_runtime",
            "hermes_execution_runtime",
            "hermes_read_only_runtime",
        ):
            with self.subTest(role=role):
                self.assert_role_forbidden(
                    role,
                    """SELECT public.hermes_scheduler_acquire_lease(
                       'project-1','sched','session','p2-default',1,
                       'cmd','key','sha256:x','scheduler','sched','reason',NULL)""",
                )

    def test_public_no_execute_owner_nologin_and_search_path_hardened(self):
        self.assert_role_forbidden(
            "public",
            """SELECT public.hermes_scheduler_acquire_lease(
               'project-1','sched','session','p2-default',1,
               'cmd','key','sha256:x','scheduler','sched','reason',NULL)""",
        )
        with psycopg.connect(DATABASE_URL) as connection:
            self.assertFalse(connection.execute(
                "SELECT rolcanlogin FROM pg_roles WHERE rolname='hermes_scheduler_owner'"
            ).fetchone()[0])
            source = connection.execute(
                """SELECT pg_get_functiondef('public.hermes_scheduler_acquire_lease(
                   TEXT,TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT)'::regprocedure)"""
            ).fetchone()[0]
        compact = source.replace(" ", "").replace("\n", "")
        self.assertIn("SECURITYDEFINER", compact)
        self.assertIn("SETsearch_pathTO'pg_catalog'", compact)


if __name__ == "__main__":
    unittest.main()
