import os
import unittest
from pathlib import Path

try:
    import psycopg
except ImportError:
    psycopg = None

from hermes_runtime.infrastructure.postgres_human_gate import PostgresHumanGateStore


DATABASE_URL = os.environ.get("HERMES_TEST_DATABASE_URL")


@unittest.skipUnless(DATABASE_URL and psycopg, "requires real PostgreSQL 14+")
class HumanGatePermissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.admin = PostgresHumanGateStore(DATABASE_URL)
        for migration in sorted((Path(__file__).parents[1] / "migrations").glob("*.sql")):
            cls.admin.apply_migration(migration)

    def setUp(self):
        self.admin.reset_for_test()

    def assert_role_forbidden(self, role, statement):
        with psycopg.connect(DATABASE_URL) as connection:
            with self.assertRaises(psycopg.Error):
                connection.execute("SET ROLE " + role)
                connection.execute(statement)

    def test_human_gate_runtime_execute_surface_is_separated(self):
        request_only = {"hermes_request_human_gate"}
        decision_only = {"hermes_submit_human_gate_decision"}
        control_only = {
            "hermes_enter_project_waiting_for_gate",
            "hermes_apply_human_gate_decision",
            "hermes_expire_human_gate_request",
            "hermes_cancel_human_gate_request",
            "hermes_supersede_human_gate_request",
        }
        internal = {
            "hermes_human_gate_secret_guard",
            "hermes_human_gate_append_event",
            "hermes_human_gate_begin_command",
            "hermes_human_gate_complete_command",
            "hermes_reject_human_gate_immutable_change",
            "hermes_reject_human_gate_application_mutation",
        }
        names = request_only | decision_only | control_only | internal
        with psycopg.connect(DATABASE_URL) as connection:
            rows = connection.execute(
                """
                SELECT p.proname,
                       has_function_privilege('hermes_gate_request_runtime', p.oid, 'EXECUTE'),
                       has_function_privilege('hermes_gate_decision_runtime', p.oid, 'EXECUTE'),
                       has_function_privilege('hermes_control_plane_runtime', p.oid, 'EXECUTE'),
                       has_function_privilege('public', p.oid, 'EXECUTE')
                FROM pg_proc p
                JOIN pg_namespace n ON n.oid=p.pronamespace
                WHERE n.nspname='public' AND p.proname = ANY(%s)
                """,
                (list(names),),
            ).fetchall()
        privileges = {name: tuple(values) for name, *values in rows}
        self.assertEqual(names, set(privileges))
        for name in request_only:
            self.assertEqual((True, False, False, False), privileges[name])
        for name in decision_only:
            self.assertEqual((False, True, False, False), privileges[name])
        for name in control_only:
            self.assertEqual((False, False, True, False), privileges[name])
        for name in internal:
            self.assertEqual((False, False, False, False), privileges[name])

    def test_non_human_gate_runtimes_cannot_approve_or_apply(self):
        roles = (
            "hermes_worker_runtime",
            "hermes_scheduler_runtime",
            "hermes_verifier_runtime",
            "hermes_planner_runtime",
            "hermes_policy_runtime",
            "hermes_risk_runtime",
            "hermes_recovery_runtime",
            "hermes_read_only_runtime",
        )
        protected = ("hermes_submit_human_gate_decision", "hermes_apply_human_gate_decision")
        with psycopg.connect(DATABASE_URL) as connection:
            for role in roles:
                for function_name in protected:
                    with self.subTest(role=role, function=function_name):
                        self.assertFalse(
                            connection.execute(
                                """
                                SELECT has_function_privilege(%s, p.oid, 'EXECUTE')
                                FROM pg_proc p
                                JOIN pg_namespace n ON n.oid=p.pronamespace
                                WHERE n.nspname='public' AND p.proname=%s
                                """,
                                (role, function_name),
                            ).fetchone()[0]
                        )

    def test_runtime_roles_cannot_directly_write_gate_or_project_tables(self):
        statements = (
            "INSERT INTO public.human_gate_requests(gate_request_id,project_id,action_scope,request_type,requester_type,requester_id,approval_policy,required_approver_count,expires_at,expected_project_version,resume_context_id,resume_context_hash,reason,request_state,command_id) VALUES ('g','p','s','approval','main_hermes','m','ALL_REQUIRED',1,clock_timestamp()+interval '1 hour',1,'ctx','sha256:x','r','REQUESTED','cmd')",
            "INSERT INTO public.human_gate_decisions(gate_decision_id,gate_request_id,project_id,gate_request_version,decision,approver_type,approver_id,authorization_ref,assertion_id,assertion_hash,decision_reason,expires_at,decision_state,payload_hash,command_id) VALUES ('d','g','p',1,'APPROVE','user','u','a','assert','sha256:x','r',clock_timestamp()+interval '1 hour','CURRENT','sha256:p','cmd')",
            "INSERT INTO public.project_resume_contexts(resume_context_id,gate_request_id,project_id,project_before_state,project_before_version,original_command_type,requester_type,requester_id,context_payload,context_hash) VALUES ('ctx','g','p','IMPLEMENTING',1,'x','main_hermes','m','{}','sha256:x')",
            "UPDATE public.projects SET state='IMPLEMENTING'",
        )
        for role in ("hermes_gate_request_runtime", "hermes_gate_decision_runtime", "hermes_control_plane_runtime"):
            for statement in statements:
                with self.subTest(role=role, statement=statement[:40]):
                    self.assert_role_forbidden(role, statement)

    def test_owner_is_nologin_and_security_definer_search_path_is_hardened(self):
        function_names = (
            "hermes_request_human_gate",
            "hermes_submit_human_gate_decision",
            "hermes_enter_project_waiting_for_gate",
            "hermes_apply_human_gate_decision",
            "hermes_expire_human_gate_request",
            "hermes_cancel_human_gate_request",
            "hermes_supersede_human_gate_request",
            "hermes_human_gate_append_event",
            "hermes_reject_human_gate_application_mutation",
        )
        with psycopg.connect(DATABASE_URL) as connection:
            self.assertFalse(
                connection.execute(
                    "SELECT rolcanlogin FROM pg_roles WHERE rolname='hermes_human_gate_owner'"
                ).fetchone()[0]
            )
            rows = connection.execute(
                """
                SELECT p.proname, pg_get_userbyid(p.proowner), pg_get_functiondef(p.oid)
                FROM pg_proc p
                JOIN pg_namespace n ON n.oid=p.pronamespace
                WHERE n.nspname='public' AND p.proname = ANY(%s)
                """,
                (list(function_names),),
            ).fetchall()
        self.assertEqual(set(function_names), {row[0] for row in rows})
        for function_name, owner, source in rows:
            with self.subTest(function=function_name):
                self.assertEqual("hermes_human_gate_owner", owner)
                compact = source.replace(" ", "").replace("\n", "")
                self.assertIn("SECURITYDEFINER", compact)
                self.assertIn("SETsearch_pathTO'pg_catalog'", compact)


if __name__ == "__main__":
    unittest.main()
