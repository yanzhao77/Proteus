import os
import unittest
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

try:
    import psycopg
except ImportError:
    psycopg = None

from hermes_runtime.infrastructure.postgres_worker_execution import PostgresWorkerExecutionStore


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
class WorkerExecutionPermissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.admin = PostgresWorkerExecutionStore(DATABASE_URL)
        for migration in sorted((Path(__file__).parents[1] / "migrations").glob("*.sql")):
            cls.admin.apply_migration(migration)
        cls.password = "hermes-worker-execution-role-test"
        cls.roles = {
            key: "hermes_test_worker_exec_{}_{}".format(key, uuid.uuid4().hex[:8])
            for key in (
                "worker",
                "scheduler",
                "accounting",
                "verifier",
                "control",
                "reader",
                "execution",
                "public",
            )
        }
        memberships = {
            "worker": "hermes_worker_runtime",
            "scheduler": "hermes_scheduler_runtime",
            "accounting": "hermes_accounting_runtime",
            "verifier": "hermes_verifier_runtime",
            "control": "hermes_control_plane_runtime",
            "reader": "hermes_read_only_runtime",
            "execution": "hermes_execution_runtime",
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
        if not (DATABASE_URL and psycopg):
            return
        with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
            for role in cls.roles.values():
                connection.execute(
                    psycopg.sql.SQL("DROP ROLE IF EXISTS {}").format(
                        psycopg.sql.Identifier(role)
                    )
                )

    def connect_as(self, key):
        return psycopg.connect(role_dsn(DATABASE_URL, self.roles[key], self.password))

    def assert_direct_write_forbidden(self, statement):
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            with self.connect_as("worker") as connection:
                connection.execute(statement)

    def test_worker_runtime_cannot_directly_write_authority_tables(self):
        direct_writes = (
            "INSERT INTO public.agent_runs(run_id,project_id,task_id,run_kind,agent_identity,context_identity,status,created_by,command_id,version) VALUES ('r','p','t','WORKER','w','c','RUNNING','w','cmd',1)",
            "INSERT INTO public.execution_results(result_id,project_id,task_id,execution_request_id,execution_attempt,run_id,lease_id,fencing_token,worker_agent_identity,context_identity,outcome,error_classification,artifact_candidate_refs,evidence_candidate_refs,usage_sample_refs,started_at,finished_at,adapter_identity,adapter_version,external_side_effect_refs,payload_hash,command_id,terminal_state) VALUES ('res','p','t','e',1,'r','l',1,'w','c','SUCCEEDED','','[]','[]','[]',now(),now(),'a','1','[]','sha256:x','cmd','SUCCEEDED')",
            "INSERT INTO public.execution_artifact_candidates(candidate_id,project_id,task_id,execution_request_id,execution_attempt,run_id,lease_id,fencing_token,artifact_kind,content_hash,storage_ref,provenance,payload_hash,admission_status,command_id) VALUES ('a','p','t','e',1,'r','l',1,'patch','sha256:a','object://a','{}','sha256:a','ADMITTED','cmd')",
            "INSERT INTO public.execution_evidence_candidates(candidate_id,project_id,task_id,execution_request_id,execution_attempt,run_id,lease_id,fencing_token,evidence_type,source_ref,source_hash,observed_at,payload_hash,admission_status,command_id) VALUES ('e','p','t','e',1,'r','l',1,'log','object://e','sha256:e',now(),'sha256:e','ADMITTED','cmd')",
            "INSERT INTO public.execution_usage_admissions(usage_id,sample_id,project_id,task_id,reservation_id,execution_request_id,execution_attempt,run_id,lease_id,fencing_token,worker_agent_identity,context_identity,payload_hash,command_id) VALUES ('u','s','p','t','rr','e',1,'r','l',1,'w','c','sha256:u','cmd')",
            "INSERT INTO public.execution_quarantine_records(quarantine_id,payload_kind,project_id,reason_code,payload_hash,safe_payload_envelope,source_command_id,idempotency_key,processing_state) VALUES ('q','EXECUTION_RESULT','p','STALE','sha256:q','{}','cmd','key','P2_MINIMAL')",
            "INSERT INTO public.resource_usage_records(usage_id,sample_id,reservation_id,project_id,owner_type,owner_id,command_id) VALUES ('u','s','r','p','worker','w','cmd')",
            "INSERT INTO public.resource_settlements(settlement_id,reservation_id,account_id,project_id,account_version,over_limit,command_id) VALUES ('s','r','a','p',1,false,'cmd')",
            "INSERT INTO public.completion_claims(claim_id,task_id,run_id,worker_identity,artifact_id,artifact_hash,summary,command_id) VALUES ('c','t','r','w','a','sha256:a','claim','cmd')",
            "INSERT INTO public.verification_results(verification_id,task_id,artifact_id,artifact_hash,verifier_identity,criteria,verdict,correlation_id,occurred_at,command_id) VALUES ('v','t','a','sha256:a','verifier','criteria','PASS','corr',now(),'cmd')",
            "UPDATE public.tasks SET state='PASSED'",
            "INSERT INTO public.event_log(event_id,event_type,schema_version,producer_type,producer_id,project_id,partition_key,command_id,correlation_id,payload,sequence,idempotency_key) VALUES ('evt','execution.forged','1.0','worker','w','p','p','cmd','corr','{}',1,'idem')",
            "INSERT INTO public.outbox_messages(message_id,event_id,topic,partition_key,sequence,payload) VALUES ('msg','evt','hermes.runtime.events','p',1,'{}')",
        )
        for statement in direct_writes:
            with self.subTest(statement=statement[:60]):
                self.assert_direct_write_forbidden(statement)

    def test_worker_runtime_execute_surface_is_exactly_five_admission_functions(self):
        exposed = {
            "hermes_start_worker_run",
            "hermes_record_execution_artifact_candidate",
            "hermes_record_execution_evidence_candidate",
            "hermes_record_execution_usage_sample",
            "hermes_submit_execution_result",
        }
        internal = {
            "hermes_execution_settle_or_release",
            "hermes_quarantine_worker_payload",
            "hermes_validate_current_worker_execution",
            "hermes_worker_accounting_status",
            "hermes_worker_append_event",
            "hermes_worker_complete_command",
        }
        with psycopg.connect(DATABASE_URL) as connection:
            rows = connection.execute(
                """SELECT p.proname,
                          has_function_privilege('hermes_worker_runtime', p.oid, 'EXECUTE'),
                          has_function_privilege('public', p.oid, 'EXECUTE')
                   FROM pg_proc p
                   JOIN pg_namespace n ON n.oid=p.pronamespace
                   WHERE n.nspname='public'
                     AND (p.proname = ANY(%s) OR p.proname = ANY(%s))""",
                (list(exposed), list(internal)),
            ).fetchall()
        privileges = {name: (worker, public) for name, worker, public in rows}
        self.assertEqual(exposed | internal, set(privileges))
        for name in exposed:
            with self.subTest(name=name):
                self.assertEqual((True, False), privileges[name])
        for name in internal:
            with self.subTest(name=name):
                self.assertEqual((False, False), privileges[name])

    def test_non_worker_runtimes_cannot_call_worker_admission_functions(self):
        exposed = (
            "hermes_start_worker_run",
            "hermes_record_execution_artifact_candidate",
            "hermes_record_execution_evidence_candidate",
            "hermes_record_execution_usage_sample",
            "hermes_submit_execution_result",
        )
        roles = (
            "hermes_scheduler_runtime",
            "hermes_accounting_runtime",
            "hermes_verifier_runtime",
            "hermes_control_plane_runtime",
            "hermes_read_only_runtime",
            "hermes_execution_runtime",
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

    def test_worker_cannot_call_internal_settlement_helper(self):
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            with self.connect_as("worker") as connection:
                connection.execute(
                    "SELECT public.hermes_execution_settle_or_release('p','r','res','cmd',1,'SUCCEEDED')"
                )

    def test_worker_execution_owner_cannot_call_legacy_accounting_helper(self):
        with psycopg.connect(DATABASE_URL) as connection:
            allowed = connection.execute(
                """SELECT has_function_privilege(
                           'hermes_worker_execution_owner',
                           'public.hermes_accounting_status(text,boolean)',
                           'EXECUTE'
                       )"""
            ).fetchone()[0]
        self.assertFalse(allowed)

    def test_owner_is_nologin_and_security_definer_search_path_is_hardened(self):
        function_names = (
            "hermes_start_worker_run",
            "hermes_record_execution_artifact_candidate",
            "hermes_record_execution_evidence_candidate",
            "hermes_record_execution_usage_sample",
            "hermes_submit_execution_result",
            "hermes_execution_settle_or_release",
            "hermes_quarantine_worker_payload",
            "hermes_worker_accounting_status",
        )
        with psycopg.connect(DATABASE_URL) as connection:
            self.assertFalse(connection.execute(
                "SELECT rolcanlogin FROM pg_roles WHERE rolname='hermes_worker_execution_owner'"
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
                self.assertEqual("hermes_worker_execution_owner", owner)
                compact = source.replace(" ", "").replace("\n", "")
                self.assertIn("SECURITYDEFINER", compact)
                self.assertIn("SETsearch_pathTO'pg_catalog'", compact)


if __name__ == "__main__":
    unittest.main()
