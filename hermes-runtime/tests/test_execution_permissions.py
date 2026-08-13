import os
import unittest
from pathlib import Path

try:
    import psycopg
except ImportError:
    psycopg = None

from hermes_runtime.infrastructure.postgres_execution import PostgresExecutionStore


DATABASE_URL = os.environ.get("HERMES_TEST_DATABASE_URL")


@unittest.skipUnless(DATABASE_URL and psycopg, "requires real PostgreSQL 14+")
class ExecutionPermissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.admin = PostgresExecutionStore(DATABASE_URL)
        for migration in sorted((Path(__file__).parents[1] / "migrations").glob("*.sql")):
            cls.admin.apply_migration(migration)

    def setUp(self):
        self.admin.reset_for_test()

    def assert_role_forbidden(self, role, statement):
        with psycopg.connect(DATABASE_URL) as connection:
            with self.assertRaises(psycopg.Error):
                connection.execute("SET ROLE " + role)
                connection.execute(statement)

    def test_non_execution_roles_cannot_create_request_queue_or_binding(self):
        for role in (
            "hermes_worker_runtime",
            "hermes_verifier_runtime",
            "hermes_capability_runtime",
            "hermes_accounting_runtime",
            "hermes_selection_runtime",
            "hermes_policy_runtime",
            "hermes_risk_runtime",
            "hermes_planner_runtime",
            "hermes_read_only_runtime",
        ):
            with self.subTest(role=role):
                self.assert_role_forbidden(
                    role,
                    """INSERT INTO public.execution_requests(
                       execution_request_id,project_id,task_id,decision_id,
                       decision_version,decision_hash,action_id,action_version,
                       action_type,action_content_hash,action_requirements_hash,
                       policy_decision_id,policy_version,policy_hash,
                       risk_assessment_id,risk_version,risk_hash,
                       mandatory_mitigations_hash,reservation_id,
                       reservation_version,reservation_hash,capability_match_id,
                       capability_match_version,capability_requirements_hash,
                       worker_template_id,worker_template_revision,
                       worker_template_content_hash,
                       worker_template_availability_version,context_bundle_id,
                       context_manifest_hash,sandbox_profile_id,
                       sandbox_profile_hash,sandbox_compiler_version,
                       sandbox_compiler_target,verification_plan_id,
                       verification_plan_version,verification_plan_hash,
                       input_artifacts,lock_intents,lock_scope_hash,priority,
                       request_state,request_version,actor_type,actor_id,reason,
                       idempotency_key,payload_hash,snapshot,command_id)
                       VALUES ('x','p','t','d',1,'sha256:d','a',1,'repair',
                       'sha256:a','sha256:req','pol',1,'sha256:p','risk',1,
                       'sha256:r','sha256:m','res',1,'sha256:res','cap',1,
                       'sha256:req','tpl',1,'sha256:tpl',1,'ctx','sha256:ctx',
                       'sbx','sha256:sbx','sandbox-compiler/1.0',
                       'contract-only/1.0','plan',1,'sha256:plan','[]','[]',
                       'sha256:locks',0,'QUEUED',1,'worker','bad','bad',
                       'idem','sha256:payload','{}','cmd')""",
                )

    def test_public_and_non_execution_roles_cannot_call_prepare_function(self):
        for role in (
            "hermes_worker_runtime",
            "hermes_capability_runtime",
            "hermes_accounting_runtime",
            "hermes_planner_runtime",
            "hermes_read_only_runtime",
        ):
            with self.subTest(role=role):
                self.assert_role_forbidden(
                    role,
                    """SELECT public.hermes_prepare_execution_request(
                       'exec-x','queue-x','{}'::jsonb,'project-1','task-1',
                       0,1,'cmd','key','sha256:x','execution_preparer',
                       'prep','reason',NULL)""",
                )

    def test_execution_runtime_cannot_directly_write_authority_tables(self):
        self.assert_role_forbidden(
            "hermes_execution_runtime",
            "INSERT INTO public.execution_queue_items(queue_item_id,execution_request_id,project_id,task_id,priority,stable_order_key,request_version,payload_hash,queue_state,event_id,command_id) VALUES ('q','r','p','t',0,'k',1,'sha256:x','PENDING','evt','cmd')",
        )

    def test_owner_is_nologin_and_shadowing_cannot_hijack_search_path(self):
        with psycopg.connect(DATABASE_URL) as connection:
            self.assertFalse(connection.execute(
                "SELECT rolcanlogin FROM pg_roles WHERE rolname='hermes_execution_owner'"
            ).fetchone()[0])
            source = connection.execute(
                """SELECT pg_get_functiondef('public.hermes_prepare_execution_request(
                   TEXT,TEXT,JSONB,TEXT,TEXT,BIGINT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT)'::regprocedure)"""
            ).fetchone()[0]
        compact = source.replace(" ", "").replace("\n", "")
        self.assertIn("SECURITYDEFINER", compact)
        self.assertIn("SETsearch_pathTO'pg_catalog'", compact)


if __name__ == "__main__":
    unittest.main()
