import os
import unittest
from pathlib import Path

try:
    import psycopg
except ImportError:
    psycopg = None

from hermes_runtime.infrastructure.postgres_recovery import PostgresRecoveryStore


DATABASE_URL = os.environ.get("HERMES_TEST_DATABASE_URL")


@unittest.skipUnless(DATABASE_URL and psycopg, "requires real PostgreSQL 14+")
class RecoveryPermissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.admin = PostgresRecoveryStore(DATABASE_URL)
        for migration in sorted((Path(__file__).parents[1] / "migrations").glob("*.sql")):
            cls.admin.apply_migration(migration)

    def setUp(self):
        self.admin.reset_for_test()

    def assert_role_forbidden(self, role, statement):
        with psycopg.connect(DATABASE_URL) as connection:
            with self.assertRaises(psycopg.Error):
                connection.execute("SET ROLE " + role)
                connection.execute(statement)

    def test_recovery_runtime_cannot_directly_write_authority_tables(self):
        direct_writes = (
            "INSERT INTO public.execution_feedback_records(feedback_id,project_id,task_id,source_result_id,source_event_id,failure_type,severity,recommended_actions,recovery_level,payload_hash,command_id) VALUES ('f','p','t','r','evt','test_assertion_failure','HIGH',ARRAY['repair'],'L1_REPAIR','sha256:x','cmd')",
            "INSERT INTO public.recovery_cycles(cycle_id,project_id,task_id,feedback_id,source_result_id,strategy_key,max_attempts,cycle_state,command_id,event_id) VALUES ('c','p','t','f','r','k',1,'OPEN','cmd','evt')",
            "INSERT INTO public.recovery_attempts(attempt_id,cycle_id,project_id,task_id,feedback_id,attempt_ordinal,recovery_level,action_type,attempt_state,reason_code,command_id,event_id) VALUES ('a','c','p','t','f',1,'L1_REPAIR','repair','PLANNED','x','cmd','evt')",
            "INSERT INTO public.recovery_collaboration_requests(collaboration_id,cycle_id,attempt_id,project_id,task_id,required_capability,objective,budget_envelope,status,command_id) VALUES ('co','c','a','p','t','expert_review','x','{}','REQUESTED','cmd')",
            "UPDATE public.tasks SET state='PASSED'",
            "INSERT INTO public.verification_results(verification_id,task_id,artifact_id,artifact_hash,verifier_identity,criteria,verdict,correlation_id,occurred_at,command_id) VALUES ('v','t','a','sha256:a','verifier','criteria','PASS','corr',now(),'cmd')",
            "INSERT INTO public.execution_results(result_id,project_id,task_id,execution_request_id,execution_attempt,run_id,lease_id,fencing_token,worker_agent_identity,context_identity,outcome,error_classification,artifact_candidate_refs,evidence_candidate_refs,usage_sample_refs,started_at,finished_at,adapter_identity,adapter_version,external_side_effect_refs,payload_hash,command_id,terminal_state) VALUES ('res','p','t','e',1,'r','l',1,'w','c','SUCCEEDED','','[]','[]','[]',now(),now(),'a','1','[]','sha256:x','cmd','SUCCEEDED')",
            "INSERT INTO public.event_log(event_id,event_type,schema_version,producer_type,producer_id,project_id,partition_key,command_id,correlation_id,payload) VALUES ('evt','recovery.forged','1.0','recovery_controller','r','p','p','cmd','corr','{}')",
            "INSERT INTO public.outbox_messages(message_id,event_id,topic,partition_key,sequence,payload) VALUES ('msg','evt','hermes.runtime.events','p',1,'{}')",
        )
        for statement in direct_writes:
            with self.subTest(statement=statement[:60]):
                self.assert_role_forbidden("hermes_recovery_runtime", statement)

    def test_recovery_runtime_execute_surface_is_exactly_three_public_commands(self):
        exposed = {
            "hermes_emit_execution_feedback",
            "hermes_plan_recovery_attempt",
            "hermes_complete_recovery_attempt",
        }
        internal = {
            "hermes_recovery_secret_guard",
            "hermes_reject_recovery_immutable_change",
            "hermes_recovery_append_event",
            "hermes_recovery_classification",
        }
        with psycopg.connect(DATABASE_URL) as connection:
            rows = connection.execute(
                """SELECT p.proname,
                          has_function_privilege('hermes_recovery_runtime', p.oid, 'EXECUTE'),
                          has_function_privilege('public', p.oid, 'EXECUTE')
                   FROM pg_proc p
                   JOIN pg_namespace n ON n.oid=p.pronamespace
                   WHERE n.nspname='public'
                     AND (p.proname = ANY(%s) OR p.proname = ANY(%s))""",
                (list(exposed), list(internal)),
            ).fetchall()
        privileges = {name: (recovery, public) for name, recovery, public in rows}
        self.assertEqual(exposed | internal, set(privileges))
        for name in exposed:
            with self.subTest(name=name):
                self.assertEqual((True, False), privileges[name])
        for name in internal:
            with self.subTest(name=name):
                self.assertEqual((False, False), privileges[name])

    def test_non_recovery_runtimes_cannot_call_recovery_commands(self):
        exposed = (
            "hermes_emit_execution_feedback",
            "hermes_plan_recovery_attempt",
            "hermes_complete_recovery_attempt",
        )
        roles = (
            "hermes_worker_runtime",
            "hermes_scheduler_runtime",
            "hermes_accounting_runtime",
            "hermes_verifier_runtime",
            "hermes_control_plane_runtime",
            "hermes_read_only_runtime",
            "hermes_execution_runtime",
            "hermes_capability_runtime",
            "hermes_selection_runtime",
            "hermes_policy_runtime",
            "hermes_risk_runtime",
            "hermes_planner_runtime",
            "hermes_diagnosis_runtime",
            "hermes_situation_runtime",
        )
        with psycopg.connect(DATABASE_URL) as connection:
            for role in roles:
                for function_name in exposed:
                    with self.subTest(role=role, function=function_name):
                        self.assertFalse(connection.execute(
                            """SELECT has_function_privilege(%s, p.oid, 'EXECUTE')
                               FROM pg_proc p
                               JOIN pg_namespace n ON n.oid=p.pronamespace
                               WHERE n.nspname='public' AND p.proname=%s""",
                            (role, function_name),
                        ).fetchone()[0])

    def test_owner_is_nologin_and_security_definer_search_path_is_hardened(self):
        function_names = (
            "hermes_emit_execution_feedback",
            "hermes_plan_recovery_attempt",
            "hermes_complete_recovery_attempt",
            "hermes_recovery_append_event",
            "hermes_reject_recovery_immutable_change",
        )
        with psycopg.connect(DATABASE_URL) as connection:
            self.assertFalse(connection.execute(
                "SELECT rolcanlogin FROM pg_roles WHERE rolname='hermes_recovery_owner'"
            ).fetchone()[0])
            rows = connection.execute(
                """SELECT p.proname, pg_get_userbyid(p.proowner), pg_get_functiondef(p.oid)
                   FROM pg_proc p
                   JOIN pg_namespace n ON n.oid=p.pronamespace
                   WHERE n.nspname='public' AND p.proname = ANY(%s)""",
                (list(function_names),),
            ).fetchall()
        self.assertEqual(set(function_names), {row[0] for row in rows})
        for function_name, owner, source in rows:
            with self.subTest(function=function_name):
                self.assertEqual("hermes_recovery_owner", owner)
                compact = source.replace(" ", "").replace("\n", "")
                self.assertIn("SECURITYDEFINER", compact)
                self.assertIn("SETsearch_pathTO'pg_catalog'", compact)


if __name__ == "__main__":
    unittest.main()
