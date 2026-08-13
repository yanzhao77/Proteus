import os
import unittest
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

try:
    import psycopg
except ImportError:
    psycopg = None

from hermes_runtime.application.selections import ActionSelection, SelectActions
from hermes_runtime.infrastructure.postgres_selection import PostgresSelectionStore


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
class SelectionPermissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.admin = PostgresSelectionStore(DATABASE_URL)
        for migration in sorted((Path(__file__).parents[1] / "migrations").glob("*.sql")):
            cls.admin.apply_migration(migration)
        cls.password = "hermes-selection-role-test"
        cls.roles = {
            key: "hermes_test_selection_{}_{}".format(key, uuid.uuid4().hex[:8])
            for key in ("selection", "worker", "planner", "policy", "risk",
                        "accounting", "control", "reader", "public")
        }
        memberships = {
            "selection": "hermes_selection_runtime",
            "worker": "hermes_worker_runtime",
            "planner": "hermes_planner_runtime",
            "policy": "hermes_policy_runtime",
            "risk": "hermes_risk_runtime",
            "accounting": "hermes_accounting_runtime",
            "control": "hermes_control_plane_runtime",
            "reader": "hermes_read_only_runtime",
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

    def test_selection_runtime_can_call_guarded_function_but_cannot_directly_write(self):
        selection = ActionSelection(PostgresSelectionStore(
            role_dsn(DATABASE_URL, self.roles["selection"], self.password)
        ))
        with self.assertRaisesRegex(Exception, "SELECTION_PLANNING_RUN_NOT_CURRENT"):
            selection.select(SelectActions(
                "permission-selection-" + uuid.uuid4().hex[:8],
                "permission-selection-" + uuid.uuid4().hex[:8],
                "missing-project", "missing-plan", 1, 0, (),
            ))
        direct_writes = (
            "INSERT INTO decision_records(decision_id,project_id,situation_id,situation_version,analysis_context_id,analysis_context_hash,input_observed_at_sequence,planning_run_id,planning_input_hash,selection_version,input_snapshot_hash,candidate_refs,policy_refs,risk_refs,resource_account_snapshots,score_refs,reservation_refs,weight_profile_id,normalizer_version,conflict_rule_version,max_parallel_selected_actions,command_id,actor_type,actor_id) VALUES ('d','p','s',1,'c','sha256:c',1,'pr','sha256:p',1,'sha256:i','[]','[]','[]','[]','[]','[]','selection-weight-profile/1.0','selection-normalizer/1.0','selection-conflict-rules/1.0',1,'cmd','action_selection','a')",
            "INSERT INTO action_scores(score_id,decision_id,action_id,action_content_hash,final_score_basis_points,weight_profile_id,normalizer_version,score_input_hash,default_sources,weights,contributions) VALUES ('s','d','a','sha256:a',1,'selection-weight-profile/1.0','selection-normalizer/1.0','sha256:s','{}','{}','{}')",
            "UPDATE resource_balances SET reserved_amount=99",
            "INSERT INTO resource_reservations(reservation_id,account_id,project_id,owner_type,owner_id,status,account_version,command_id) VALUES ('r','a','p','decision','d','ACTIVE',1,'c')",
            "INSERT INTO policy_decisions(policy_decision_id,evaluation_context_id,project_id,planning_run_id,action_id,action_content_hash,result,policy_bundle_version,policy_rule_version,policy_input_hash,command_id) VALUES ('p','e','project','plan','act','sha256:0','ALLOW','policy-bundle/1.0','policy-rules/1.0','sha256:1','cmd')",
            "INSERT INTO risk_assessments(risk_assessment_id,evaluation_context_id,project_id,planning_run_id,action_id,action_content_hash,risk_score_basis_points,risk_level,factors,residual_risk_basis_points,risk_model_version,risk_rule_version,risk_input_hash,command_id) VALUES ('r','e','project','plan','act','sha256:0',1,'LOW','{}',1,'risk-model/1.0','risk-rules/1.0','sha256:1','cmd')",
            "UPDATE projects SET state='ACCEPTED'",
            "UPDATE tasks SET state='PASSED'",
            "CREATE TABLE forbidden_selection_shadow(id int)",
        )
        for statement in direct_writes:
            with self.subTest(statement=statement[:40]):
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    with self.connect_as("selection") as connection:
                        connection.execute(statement)

    def test_public_and_other_runtimes_cannot_forge_decision(self):
        signature = (
            "hermes_apply_selection_decision(jsonb,jsonb,jsonb,jsonb,jsonb,jsonb,jsonb,"
            "text,text,bigint,bigint,text,text,text,text,text)"
        )
        with psycopg.connect(DATABASE_URL) as connection:
            self.assertFalse(connection.execute(
                "SELECT has_function_privilege('public',%s,'EXECUTE')",
                (signature,),
            ).fetchone()[0])
            roles = connection.execute(
                """SELECT rolname,rolcanlogin,rolsuper,rolcreaterole FROM pg_roles
                   WHERE rolname IN ('hermes_selection_owner','hermes_selection_runtime')
                   ORDER BY rolname"""
            ).fetchall()
        self.assertEqual([
            ("hermes_selection_owner", False, False, False),
            ("hermes_selection_runtime", False, False, False),
        ], roles)
        for key in ("worker", "planner", "policy", "risk", "accounting", "control", "reader", "public"):
            with self.subTest(role=key):
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    with self.connect_as(key) as connection:
                        connection.execute(
                            """SELECT public.hermes_apply_selection_decision(
                               '{}'::jsonb,'[]'::jsonb,'[]'::jsonb,'[]'::jsonb,
                               '[]'::jsonb,'[]'::jsonb,'[]'::jsonb,
                               'p','plan',1,0,'selection-weight-profile/1.0',
                               'cmd','action_selection','a',NULL)"""
                        )

    def test_security_definer_search_path_cannot_be_shadowed(self):
        with self.connect_as("selection") as connection:
            connection.execute(
                "CREATE TEMP TABLE planning_runs(planning_run_id text, project_id text)"
            )
        selection = ActionSelection(PostgresSelectionStore(
            role_dsn(DATABASE_URL, self.roles["selection"], self.password)
        ))
        with self.assertRaisesRegex(Exception, "SELECTION_PLANNING_RUN_NOT_CURRENT"):
            selection.select(SelectActions(
                "permission-shadow-" + uuid.uuid4().hex[:8],
                "permission-shadow-" + uuid.uuid4().hex[:8],
                "missing-project", "missing-plan", 1, 0, (),
            ))


if __name__ == "__main__":
    unittest.main()
