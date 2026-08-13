import threading
import unittest
from importlib import import_module
from pathlib import Path

import os

try:
    import psycopg
    from psycopg.types.json import Jsonb
except ImportError:
    psycopg = None
    Jsonb = None

from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.application.planning import ActionPlanner
from hermes_runtime.application.policies import EvaluatePolicy, PolicyEngine
from hermes_runtime.application.risks import AssessRisk, RiskEngine
from hermes_runtime.application.selections import (
    ActionSelection,
    CandidateAccountBinding,
    SelectActions,
)
from hermes_runtime.infrastructure.postgres_planner import PostgresPlannerStore
from hermes_runtime.infrastructure.postgres_policy import PostgresPolicyStore
from hermes_runtime.infrastructure.postgres_risk import PostgresRiskStore
from hermes_runtime.infrastructure.postgres_selection import (
    PostgresSelectionStore,
    SelectionFaultPoint,
)


DATABASE_URL = os.environ.get("HERMES_TEST_DATABASE_URL")


@unittest.skipUnless(DATABASE_URL and psycopg, "requires real PostgreSQL 14+")
class SelectionPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = PostgresSelectionStore(DATABASE_URL)
        for migration in sorted((Path(__file__).parents[1] / "migrations").glob("*.sql")):
            cls.store.apply_migration(migration)

    def setUp(self):
        self.store.reset_for_test()
        self.selection = ActionSelection(PostgresSelectionStore(DATABASE_URL))
        self.policy = PolicyEngine(PostgresPolicyStore(DATABASE_URL))
        self.risk = RiskEngine(PostgresRiskStore(DATABASE_URL))

    def make_planned(self, suffix="selection", kind="unknown"):
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
        elif kind == "budget":
            fixture = helper.create_budget_pressure(suffix, "NORMAL")
        else:
            fixture = helper.create_verification_failed(suffix)
        plan = helper.planner.plan(helper.command(fixture, suffix))
        return dict(fixture, planning_run_id=plan["planning_run_id"],
                    candidate_action_ids=plan["candidate_action_ids"])

    def candidates(self, planning_run_id):
        with psycopg.connect(DATABASE_URL) as connection:
            return [
                {"action_id": row[0], "content_hash": row[1], "type": row[2]}
                for row in connection.execute(
                    """SELECT action_id,content_hash,type FROM candidate_actions
                       WHERE planning_run_id=%s ORDER BY ordinal""",
                    (planning_run_id,),
                ).fetchall()
            ]

    def create_account(self, suffix, limits=None, scope_type="project", scope_id="project-1",
                       currency=None, threshold_status="NORMAL"):
        limits = limits or {
            "agent_runs": 10,
            "execution_time_ms": 3_600_000,
            "cpu_time_ms": 3_600_000,
            "docker_runtime_ms": 3_600_000,
            "storage_bytes": 10_000_000,
        }
        with psycopg.connect(DATABASE_URL) as connection:
            account_id = "account-" + suffix
            connection.execute(
                """INSERT INTO resource_accounts(
                   account_id,project_id,scope_type,scope_id,currency,version,threshold_status)
                   VALUES (%s,'project-1',%s,%s,%s,0,%s)""",
                (account_id, scope_type, scope_id, currency, threshold_status),
            )
            for dimension, amount in limits.items():
                connection.execute(
                    """INSERT INTO resource_balances(account_id,dimension,limit_amount)
                       VALUES (%s,%s,%s)""",
                    (account_id, dimension, amount),
                )
        return account_id

    def evaluate_all(self, fixture, *, environment="dev", deny_action=None,
                     require_human_action=None, high_risk_action=None):
        for candidate in self.candidates(fixture["planning_run_id"]):
            self.policy.evaluate(EvaluatePolicy(
                "cmd-policy-" + fixture["situation_id"] + "-" + candidate["action_id"],
                "key-policy-" + fixture["situation_id"] + "-" + candidate["action_id"],
                "project-1", fixture["planning_run_id"], candidate["action_id"],
                fixture["version"], candidate["content_hash"],
                target_environment="production" if candidate["action_id"] == require_human_action else environment,
                runtime_emergency_freeze=candidate["action_id"] == deny_action,
            ))
            self.risk.assess(AssessRisk(
                "cmd-risk-" + fixture["situation_id"] + "-" + candidate["action_id"],
                "key-risk-" + fixture["situation_id"] + "-" + candidate["action_id"],
                "project-1", fixture["planning_run_id"], candidate["action_id"],
                fixture["version"], candidate["content_hash"],
                target_environment="unknown" if candidate["action_id"] == high_risk_action else environment,
            ))

    def command(self, fixture, suffix, account_id, expected_version=0):
        bindings = tuple(
            CandidateAccountBinding(row["action_id"], account_id, expected_version)
            for row in self.candidates(fixture["planning_run_id"])
        )
        return SelectActions(
            "cmd-selection-" + suffix, "key-selection-" + suffix, "project-1",
            fixture["planning_run_id"], fixture["version"], 0,
            bindings,
        )

    def counts(self):
        with psycopg.connect(DATABASE_URL) as connection:
            return tuple(connection.execute("SELECT count(*) FROM " + table).fetchone()[0]
                         for table in (
                             "decision_records", "decision_candidate_dispositions",
                             "action_scores", "action_score_dimensions",
                             "selected_action_refs", "decision_reservation_mappings",
                             "resource_reservations", "resource_reservation_amounts",
                             "event_log", "outbox_messages", "command_receipts",
                         ))

    def test_allow_risk_budget_feasible_creates_decision_reservation_event_outbox_receipt(self):
        fixture = self.make_planned("happy")
        self.evaluate_all(fixture)
        account_id = self.create_account("happy")
        result = self.selection.select(self.command(fixture, "happy", account_id))
        self.assertTrue(result["selected_action_ids"])
        with psycopg.connect(DATABASE_URL) as connection:
            self.assertEqual(1, connection.execute(
                "SELECT count(*) FROM decision_records WHERE decision_id=%s",
                (result["decision_id"],),
            ).fetchone()[0])
            self.assertEqual(len(result["reservation_ids"]), connection.execute(
                "SELECT count(*) FROM resource_reservations WHERE owner_type='decision'"
            ).fetchone()[0])
            self.assertEqual(1, connection.execute(
                "SELECT count(*) FROM event_log WHERE event_type='decision.recorded'"
            ).fetchone()[0])
            self.assertEqual(0, connection.execute(
                """SELECT count(*) FROM event_log
                   WHERE event_type IN ('execution.queued','execution.requested')"""
            ).fetchone()[0])

    def test_ct004_policy_deny_high_score_filtered_no_reservation_or_execution(self):
        fixture = self.make_planned("ct004", "repair")
        repair = next(row for row in self.candidates(fixture["planning_run_id"])
                      if row["type"] == "repair")
        self.evaluate_all(fixture, deny_action=repair["action_id"])
        account_id = self.create_account("ct004")
        result = self.selection.select(self.command(fixture, "ct004", account_id))
        with psycopg.connect(DATABASE_URL) as connection:
            row = connection.execute(
                """SELECT disposition,reason_codes,reservation_id
                   FROM decision_candidate_dispositions
                   WHERE decision_id=%s AND action_id=%s""",
                (result["decision_id"], repair["action_id"]),
            ).fetchone()
            self.assertEqual("FILTERED", row[0])
            self.assertIn("POLICY_DENY", row[1])
            self.assertIsNone(row[2])
            self.assertEqual(0, connection.execute(
                """SELECT count(*) FROM decision_reservation_mappings
                   WHERE action_id=%s""",
                (repair["action_id"],),
            ).fetchone()[0])
            self.assertEqual(0, connection.execute(
                "SELECT count(*) FROM execution_requests"
            ).fetchone()[0])
            self.assertEqual(0, connection.execute(
                "SELECT count(*) FROM execution_queue_items"
            ).fetchone()[0])
            self.assertEqual(0, connection.execute(
                """SELECT count(*) FROM event_log
                   WHERE event_type IN ('execution.queued','execution.requested')"""
            ).fetchone()[0])

    def test_require_human_candidate_is_filtered_without_gate(self):
        fixture = self.make_planned("human", "repair")
        repair = next(row for row in self.candidates(fixture["planning_run_id"])
                      if row["type"] == "repair")
        self.evaluate_all(fixture, environment="production")
        account_id = self.create_account("human")
        result = self.selection.select(self.command(fixture, "human", account_id))
        with psycopg.connect(DATABASE_URL) as connection:
            reasons = connection.execute(
                """SELECT reason_codes FROM decision_candidate_dispositions
                   WHERE decision_id=%s AND action_id=%s""",
                (result["decision_id"], repair["action_id"]),
            ).fetchone()[0]
        self.assertIn("POLICY_REQUIRE_HUMAN", reasons)

    def test_budget_scope_currency_hard_stop_infeasible_and_version_conflicts(self):
        for suffix, setup, code in (
            ("scope", lambda: self.create_account("scope", scope_type="action", scope_id="other"), "BUDGET_ACCOUNT_SCOPE_MISMATCH"),
            ("hard", lambda: self.create_account("hard", threshold_status="HARD_STOP"), "BUDGET_HARD_STOP"),
            ("small", lambda: self.create_account("small", {"agent_runs": 0, "execution_time_ms": 10}), "BUDGET_INFEASIBLE"),
            ("version", lambda: self.create_account("version"), "BUDGET_ACCOUNT_VERSION_CONFLICT"),
        ):
            with self.subTest(suffix=suffix):
                self.store.reset_for_test()
                fixture = self.make_planned(suffix)
                self.evaluate_all(fixture)
                account_id = setup()
                version = 1 if suffix == "version" else 0
                result_or_exc = None
                try:
                    result_or_exc = self.selection.select(
                        self.command(fixture, suffix, account_id, version)
                    )
                except CommandRejected as exc:
                    result_or_exc = exc.code
                if suffix == "version":
                    self.assertEqual(code, result_or_exc)
                else:
                    with psycopg.connect(DATABASE_URL) as connection:
                        reasons = [
                            item for row in connection.execute(
                                """SELECT reason_codes FROM decision_candidate_dispositions
                                   WHERE decision_id=%s""",
                                (result_or_exc["decision_id"],),
                            ).fetchall()
                            for item in row[0]
                        ]
                    self.assertIn(code, reasons)

    def test_idempotency_convergence_and_concurrency(self):
        fixture = self.make_planned("idem")
        self.evaluate_all(fixture)
        account_id = self.create_account("idem")
        first = self.selection.select(self.command(fixture, "idem", account_id))
        second = self.selection.select(self.command(fixture, "idem", account_id))
        self.assertEqual(first["decision_id"], second["decision_id"])
        third = self.selection.select(self.command(fixture, "idem-other", account_id))
        self.assertEqual(first["decision_id"], third["decision_id"])
        with self.assertRaisesRegex(CommandRejected, "SELECTION_IDEMPOTENCY_CONFLICT"):
            self.selection.select(SelectActions(
                "cmd-selection-idem-conflict", "key-selection-idem", "project-1",
                fixture["planning_run_id"], fixture["version"], 0, (),
            ))

    def test_fault_injection_rolls_back_precommit_effects(self):
        for point in SelectionFaultPoint:
            with self.subTest(point=point.value):
                self.store.reset_for_test()
                fixture = self.make_planned("fault-" + point.value[:8])
                self.evaluate_all(fixture)
                account_id = self.create_account("fault-" + point.value[:8])
                before = self.counts()
                store = PostgresSelectionStore(DATABASE_URL)
                store.fail_selection_once(point)
                with self.assertRaises(RuntimeError):
                    ActionSelection(store).select(
                        self.command(fixture, "fault-" + point.value[:8], account_id)
                    )
                self.assertEqual(before, self.counts())

    def test_concurrent_budget_competition_does_not_overspend(self):
        fixture = self.make_planned("race")
        self.evaluate_all(fixture)
        account_id = self.create_account("race", {"agent_runs": 1, "execution_time_ms": 3_600_000})
        barrier = threading.Barrier(2)
        results = []

        def attempt(suffix):
            barrier.wait()
            try:
                results.append(ActionSelection(PostgresSelectionStore(DATABASE_URL)).select(
                    self.command(fixture, "race-" + suffix, account_id)
                )["decision_id"])
            except CommandRejected as exc:
                results.append(exc.code)

        threads = [threading.Thread(target=attempt, args=(suffix,)) for suffix in ("a", "b")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(15)
            self.assertFalse(thread.is_alive())
        self.assertTrue(any(item.startswith("decision-") for item in results))
        with psycopg.connect(DATABASE_URL) as connection:
            self.assertLessEqual(connection.execute(
                """SELECT reserved_amount FROM resource_balances
                   WHERE account_id=%s AND dimension='agent_runs'""",
                (account_id,),
            ).fetchone()[0], 1)

    def test_immutable_decision_and_score(self):
        fixture = self.make_planned("immutable")
        self.evaluate_all(fixture)
        account_id = self.create_account("immutable")
        result = self.selection.select(self.command(fixture, "immutable", account_id))
        with psycopg.connect(DATABASE_URL) as connection:
            with self.assertRaises(psycopg.errors.RaiseException):
                connection.execute(
                    "UPDATE decision_records SET decision_reason_codes='{}' WHERE decision_id=%s",
                    (result["decision_id"],),
                )
            connection.rollback()
            with self.assertRaises(psycopg.errors.RaiseException):
                connection.execute(
                    "UPDATE action_scores SET final_score_basis_points=0 WHERE decision_id=%s",
                    (result["decision_id"],),
                )


if __name__ == "__main__":
    unittest.main()
