import os
import unittest
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

try:
    import psycopg
except ImportError:
    psycopg = None

from hermes_runtime.application.policies import EvaluatePolicy, PolicyEngine
from hermes_runtime.application.risks import AssessRisk, RiskEngine
from hermes_runtime.infrastructure.postgres_policy import PostgresPolicyStore
from hermes_runtime.infrastructure.postgres_risk import PostgresRiskStore


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
class PolicyRiskPermissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = PostgresPolicyStore(DATABASE_URL)
        for migration in sorted((Path(__file__).parents[1] / "migrations").glob("*.sql")):
            cls.store.apply_migration(migration)
        cls.password = "hermes-policy-risk-role-test"
        cls.roles = {
            key: "hermes_test_policy_risk_{}_{}".format(key, uuid.uuid4().hex[:8])
            for key in ("policy", "risk", "planner", "worker", "verifier",
                        "situation", "diagnosis", "accounting", "control")
        }
        memberships = {
            "policy": "hermes_policy_runtime",
            "risk": "hermes_risk_runtime",
            "planner": "hermes_planner_runtime",
            "worker": "hermes_worker_runtime",
            "verifier": "hermes_verifier_runtime",
            "situation": "hermes_situation_runtime",
            "diagnosis": "hermes_diagnosis_runtime",
            "accounting": "hermes_accounting_runtime",
            "control": "hermes_control_plane_runtime",
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

    def connect_as(self, key):
        return psycopg.connect(role_dsn(DATABASE_URL, self.roles[key], self.password))

    def test_runtime_roles_cannot_directly_write_policy_or_risk_tables(self):
        statements = (
            "INSERT INTO policy_decisions(policy_decision_id,evaluation_context_id,project_id,planning_run_id,action_id,action_content_hash,result,policy_bundle_version,policy_rule_version,policy_input_hash,command_id) VALUES ('p','e','project','plan','act','sha256:0','ALLOW','policy-bundle/1.0','policy-rules/1.0','sha256:1','cmd')",
            "INSERT INTO risk_assessments(risk_assessment_id,evaluation_context_id,project_id,planning_run_id,action_id,action_content_hash,risk_score_basis_points,risk_level,factors,residual_risk_basis_points,risk_model_version,risk_rule_version,risk_input_hash,command_id) VALUES ('r','e','project','plan','act','sha256:0',1,'LOW','{}',1,'risk-model/1.0','risk-rules/1.0','sha256:1','cmd')",
        )
        for role in self.roles:
            for statement in statements:
                with self.subTest(role=role, statement=statement[:30]):
                    with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                        with self.connect_as(role) as connection:
                            connection.execute(statement)

    def test_policy_and_risk_cannot_cross_write_or_mutate_upstream_downstream(self):
        for role in ("policy", "risk"):
            for statement in (
                "UPDATE planning_runs SET candidate_count=1",
                "UPDATE candidate_actions SET reason_code='x'",
                "UPDATE projects SET state='ACCEPTED'",
                "UPDATE tasks SET state='PASSED'",
                "UPDATE situations SET version=999",
                "UPDATE resource_accounts SET version=999",
                "INSERT INTO resource_reservations(reservation_id,account_id,project_id,owner_type,owner_id,status,account_version,command_id) VALUES ('r','a','p','action','a','ACTIVE',1,'c')",
                "CREATE TABLE forbidden_policy_risk_shadow(id int)",
            ):
                with self.subTest(role=role, statement=statement):
                    with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                        with self.connect_as(role) as connection:
                            connection.execute(statement)

    def test_public_has_no_sensitive_execute_and_owners_are_nologin(self):
        signatures = (
            "hermes_apply_policy_decision(text,text,text,text,text,text,text,bigint,text,text[],text[],jsonb,text,text,text,text,text,text,text,text,text,text)",
            "hermes_apply_risk_assessment(text,text,text,text,text,text,text,bigint,integer,text,jsonb,text[],text[],text[],integer,text,text,text,text,text,text,text,text,text,text)",
        )
        with psycopg.connect(DATABASE_URL) as connection:
            for signature in signatures:
                self.assertFalse(connection.execute(
                    "SELECT has_function_privilege('public',%s,'EXECUTE')",
                    (signature,),
                ).fetchone()[0])
            rows = connection.execute(
                """SELECT rolname,rolcanlogin,rolsuper,rolcreaterole FROM pg_roles
                   WHERE rolname IN ('hermes_policy_owner','hermes_risk_owner')
                   ORDER BY rolname"""
            ).fetchall()
        self.assertEqual([
            ("hermes_policy_owner", False, False, False),
            ("hermes_risk_owner", False, False, False),
        ], rows)

    def test_runtime_can_execute_only_its_guarded_function(self):
        policy = PolicyEngine(PostgresPolicyStore(
            role_dsn(DATABASE_URL, self.roles["policy"], self.password)
        ))
        with self.assertRaisesRegex(Exception, "POLICY_ACTION_NOT_FOUND"):
            policy.evaluate(EvaluatePolicy(
                command_id="permission-policy-" + uuid.uuid4().hex[:8],
                idempotency_key="permission-policy-" + uuid.uuid4().hex[:8],
                project_id="missing-project",
                planning_run_id="missing-plan",
                action_id="missing-action",
                expected_situation_version=1,
                expected_action_content_hash="sha256:" + "0" * 64,
            ))
        risk = RiskEngine(PostgresRiskStore(
            role_dsn(DATABASE_URL, self.roles["risk"], self.password)
        ))
        with self.assertRaisesRegex(Exception, "RISK_ACTION_NOT_FOUND"):
            risk.assess(AssessRisk(
                command_id="permission-risk-" + uuid.uuid4().hex[:8],
                idempotency_key="permission-risk-" + uuid.uuid4().hex[:8],
                project_id="missing-project",
                planning_run_id="missing-plan",
                action_id="missing-action",
                expected_situation_version=1,
                expected_action_content_hash="sha256:" + "0" * 64,
            ))


if __name__ == "__main__":
    unittest.main()
