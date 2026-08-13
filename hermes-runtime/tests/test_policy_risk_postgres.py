import threading
import unittest
from importlib import import_module
from pathlib import Path

import os

try:
    import psycopg
except ImportError:
    psycopg = None

from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.application.planning import ActionPlanner
from hermes_runtime.application.policies import EvaluatePolicy, PolicyEngine
from hermes_runtime.application.risks import AssessRisk, RiskEngine
from hermes_runtime.infrastructure.postgres_planner import PostgresPlannerStore
from hermes_runtime.infrastructure.postgres_policy import PolicyFaultPoint, PostgresPolicyStore
from hermes_runtime.infrastructure.postgres_risk import RiskFaultPoint, PostgresRiskStore

DATABASE_URL = os.environ.get("HERMES_TEST_DATABASE_URL")


@unittest.skipUnless(DATABASE_URL and psycopg, "requires real PostgreSQL 14+")
class PolicyRiskPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = PostgresPolicyStore(DATABASE_URL)
        for migration in sorted((Path(__file__).parents[1] / "migrations").glob("*.sql")):
            cls.store.apply_migration(migration)

    def setUp(self):
        self.store.reset_for_test()
        self.policy = PolicyEngine(PostgresPolicyStore(DATABASE_URL))
        self.risk = RiskEngine(PostgresRiskStore(DATABASE_URL))

    def make_planned(self, suffix="policy", kind="unknown"):
        planner_tests = import_module("test_planner_postgres")
        helper = planner_tests.PlannerPostgresTests(
            methodName="test_unknown_diagnosis_plans_diagnose_and_deeper_test_no_repair"
        )
        helper.store = PostgresPlannerStore(DATABASE_URL)
        helper.planner = ActionPlanner(helper.store)
        if kind == "repair":
            fixture = helper.create_verification_failed(
                suffix, ("TEST_ASSERTION_FAILURE",), ("evidence-" + suffix,)
            )
        elif kind == "ready":
            fixture = helper.create_work_available(suffix)
        elif kind == "budget":
            fixture = helper.create_budget_pressure(suffix, "HARD_STOP")
        else:
            fixture = helper.create_verification_failed(suffix)
        plan = helper.planner.plan(helper.command(fixture, suffix))
        return dict(fixture, planning_run_id=plan["planning_run_id"],
                    candidate_action_ids=plan["candidate_action_ids"])

    def candidate(self, planning_run_id, action_type=None):
        with psycopg.connect(DATABASE_URL) as connection:
            row = connection.execute(
                """SELECT action_id,content_hash,type FROM candidate_actions
                   WHERE planning_run_id=%s
                     AND (%s::text IS NULL OR type=%s::text)
                   ORDER BY ordinal LIMIT 1""",
                (planning_run_id, action_type, action_type),
            ).fetchone()
        return {"action_id": row[0], "content_hash": row[1], "type": row[2]}

    def policy_command(self, fixture, candidate, suffix="policy", **overrides):
        data = {
            "command_id": "cmd-policy-" + suffix,
            "idempotency_key": "key-policy-" + suffix,
            "project_id": "project-1",
            "planning_run_id": fixture["planning_run_id"],
            "action_id": candidate["action_id"],
            "expected_situation_version": fixture["version"],
            "expected_action_content_hash": candidate["content_hash"],
            "target_environment": "dev",
        }
        data.update(overrides)
        return EvaluatePolicy(**data)

    def risk_command(self, fixture, candidate, suffix="risk", **overrides):
        data = {
            "command_id": "cmd-risk-" + suffix,
            "idempotency_key": "key-risk-" + suffix,
            "project_id": "project-1",
            "planning_run_id": fixture["planning_run_id"],
            "action_id": candidate["action_id"],
            "expected_situation_version": fixture["version"],
            "expected_action_content_hash": candidate["content_hash"],
            "target_environment": "dev",
        }
        data.update(overrides)
        return AssessRisk(**data)

    def counts(self):
        with psycopg.connect(DATABASE_URL) as connection:
            return tuple(connection.execute(
                "SELECT count(*) FROM " + table
            ).fetchone()[0] for table in (
                "policy_evaluation_contexts", "policy_decisions",
                "policy_decision_rules", "policy_constraints",
                "current_policy_decisions", "risk_assessments",
                "risk_factors", "risk_mitigations", "current_risk_assessments",
                "event_log", "outbox_messages", "command_receipts",
                "resource_reservations",
            ))

    def test_read_only_policy_allow_and_risk_no_execution_side_effects(self):
        fixture = self.make_planned("readonly")
        candidate = self.candidate(fixture["planning_run_id"], "run_deeper_test")
        policy = self.policy.evaluate(self.policy_command(fixture, candidate, "readonly"))
        risk = self.risk.assess(self.risk_command(fixture, candidate, "readonly"))
        self.assertEqual("ALLOW", policy["result"])
        self.assertIn(risk["risk_level"], {"LOW", "MEDIUM"})
        with psycopg.connect(DATABASE_URL) as connection:
            self.assertEqual(0, connection.execute(
                "SELECT count(*) FROM resource_reservations"
            ).fetchone()[0])

    def test_repair_production_requires_human_and_risk_is_high(self):
        fixture = self.make_planned("prodrepair", "repair")
        candidate = self.candidate(fixture["planning_run_id"], "repair")
        policy = self.policy.evaluate(self.policy_command(
            fixture, candidate, "prodrepair", target_environment="production"
        ))
        risk = self.risk.assess(self.risk_command(
            fixture, candidate, "prodrepair", target_environment="production"
        ))
        self.assertEqual("REQUIRE_HUMAN", policy["result"])
        self.assertIn(risk["risk_level"], {"HIGH", "CRITICAL"})
        with psycopg.connect(DATABASE_URL) as connection:
            self.assertFalse(connection.execute(
                """SELECT EXISTS (
                   SELECT 1 FROM information_schema.tables
                   WHERE table_schema='public' AND table_name='human_gates')"""
            ).fetchone()[0])

    def test_request_resource_requires_human_without_gate(self):
        fixture = self.make_planned("budget", "budget")
        candidate = self.candidate(fixture["planning_run_id"], "request_resource")
        policy = self.policy.evaluate(self.policy_command(
            fixture, candidate, "budget", target_environment="unknown"
        ))
        self.assertEqual("REQUIRE_HUMAN", policy["result"])

    def test_ct004_policy_deny_not_overridden_by_risk_or_planner_quality(self):
        fixture = self.make_planned("ct004", "repair")
        candidate = self.candidate(fixture["planning_run_id"], "repair")
        policy = self.policy.evaluate(self.policy_command(
            fixture, candidate, "ct004", runtime_emergency_freeze=True
        ))
        risk = self.risk.assess(self.risk_command(fixture, candidate, "ct004"))
        self.assertEqual("DENY", policy["result"])
        self.assertIn(risk["risk_level"], {"MEDIUM", "HIGH", "CRITICAL"})
        with psycopg.connect(DATABASE_URL) as connection:
            self.assertEqual(0, connection.execute(
                "SELECT count(*) FROM resource_reservations"
            ).fetchone()[0])
            self.assertFalse(connection.execute(
                """SELECT EXISTS (
                   SELECT 1 FROM information_schema.tables
                   WHERE table_schema='public'
                     AND table_name IN ('selected_actions','execution_requests'))"""
            ).fetchone()[0])

    def test_hash_stale_and_version_rejections(self):
        fixture = self.make_planned("stale")
        candidate = self.candidate(fixture["planning_run_id"], "run_deeper_test")
        with self.assertRaisesRegex(CommandRejected, "POLICY_ACTION_HASH_MISMATCH"):
            self.policy.evaluate(self.policy_command(
                fixture, candidate, "hash", expected_action_content_hash="sha256:" + "0" * 64
            ))
        with self.assertRaisesRegex(CommandRejected, "RISK_ACTION_HASH_MISMATCH"):
            self.risk.assess(self.risk_command(
                fixture, candidate, "hash", expected_action_content_hash="sha256:" + "0" * 64
            ))
        with self.assertRaisesRegex(CommandRejected, "POLICY_CONTEXT_STALE"):
            self.policy.evaluate(self.policy_command(
                fixture, candidate, "version", expected_situation_version=fixture["version"] + 1
            ))

    def test_idempotency_conflict_and_concurrency(self):
        fixture = self.make_planned("idem")
        candidate = self.candidate(fixture["planning_run_id"], "run_deeper_test")
        first = self.policy.evaluate(self.policy_command(fixture, candidate, "idem"))
        second = self.policy.evaluate(self.policy_command(fixture, candidate, "idem"))
        self.assertEqual(first["policy_decision_id"], second["policy_decision_id"])
        with self.assertRaisesRegex(CommandRejected, "POLICY_IDEMPOTENCY_CONFLICT"):
            self.policy.evaluate(self.policy_command(
                fixture, candidate, "idem-conflict",
                command_id="cmd-policy-idem-other",
                idempotency_key="key-policy-idem",
                target_environment="production",
            ))

        self.store.reset_for_test()
        fixture = self.make_planned("concurrent")
        candidate = self.candidate(fixture["planning_run_id"], "run_deeper_test")
        barrier = threading.Barrier(2)
        results = []
        failures = []

        def evaluate(index):
            try:
                barrier.wait()
                results.append(PolicyEngine(PostgresPolicyStore(DATABASE_URL)).evaluate(
                    self.policy_command(fixture, candidate, "concurrent-" + str(index))
                ))
            except Exception as exc:
                failures.append(exc)

        threads = [threading.Thread(target=evaluate, args=(i,)) for i in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual([], failures)
        self.assertEqual(results[0]["policy_decision_id"], results[1]["policy_decision_id"])
        with psycopg.connect(DATABASE_URL) as connection:
            self.assertEqual(1, connection.execute(
                "SELECT count(*) FROM policy_decisions"
            ).fetchone()[0])

    def test_fault_injection_rolls_back_policy_and_risk(self):
        for point in PolicyFaultPoint:
            with self.subTest(policy=point.value):
                self.store.reset_for_test()
                fixture = self.make_planned("pfault-" + point.value[:8])
                candidate = self.candidate(fixture["planning_run_id"], "run_deeper_test")
                before = self.counts()
                store = PostgresPolicyStore(DATABASE_URL)
                store.fail_policy_once(point)
                with self.assertRaises(RuntimeError):
                    PolicyEngine(store).evaluate(
                        self.policy_command(fixture, candidate, "pfault-" + point.value[:8])
                    )
                self.assertEqual(before, self.counts())
        for point in RiskFaultPoint:
            with self.subTest(risk=point.value):
                self.store.reset_for_test()
                fixture = self.make_planned("rfault-" + point.value[:8])
                candidate = self.candidate(fixture["planning_run_id"], "run_deeper_test")
                before = self.counts()
                store = PostgresRiskStore(DATABASE_URL)
                store.fail_risk_once(point)
                with self.assertRaises(RuntimeError):
                    RiskEngine(store).assess(
                        self.risk_command(fixture, candidate, "rfault-" + point.value[:8])
                    )
                self.assertEqual(before, self.counts())

    def test_immutable_decision_and_assessment(self):
        fixture = self.make_planned("immutable")
        candidate = self.candidate(fixture["planning_run_id"], "run_deeper_test")
        policy = self.policy.evaluate(self.policy_command(fixture, candidate, "immutable"))
        risk = self.risk.assess(self.risk_command(fixture, candidate, "immutable"))
        with psycopg.connect(DATABASE_URL) as connection:
            with self.assertRaises(psycopg.errors.RaiseException):
                connection.execute(
                    "UPDATE policy_decisions SET result='DENY' WHERE policy_decision_id=%s",
                    (policy["policy_decision_id"],),
                )
        with psycopg.connect(DATABASE_URL) as connection:
            with self.assertRaises(psycopg.errors.RaiseException):
                connection.execute(
                    "UPDATE risk_assessments SET risk_level='LOW' WHERE risk_assessment_id=%s",
                    (risk["risk_assessment_id"],),
                )


if __name__ == "__main__":
    unittest.main()
