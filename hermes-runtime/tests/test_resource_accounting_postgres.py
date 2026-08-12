import os
import threading
import unittest
from pathlib import Path

try:
    import psycopg
except ImportError:
    psycopg = None

from hermes_runtime.application.accounting import ResourceAccounting
from hermes_runtime.application.commands import (
    CreateProject,
    CreateResourceAccount,
    IssueProjectBudgetFact,
    ReconcileReservation,
    RecordResourceUsage,
    ReserveResources,
    SettleReservation,
)
from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.application.handlers import ControlPlane
from hermes_runtime.domain.models import Actor, ActorType, CommandEnvelope
from hermes_runtime.infrastructure.postgres_accounting import (
    AccountingFaultPoint,
    PostgresResourceAccountingStore,
)


DATABASE_URL = os.environ.get("HERMES_TEST_DATABASE_URL")


@unittest.skipUnless(DATABASE_URL and psycopg, "requires real PostgreSQL 14+")
class ResourceAccountingPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = PostgresResourceAccountingStore(DATABASE_URL)
        migrations = Path(__file__).parents[1] / "migrations"
        for migration in sorted(migrations.glob("*.sql")):
            cls.store.apply_migration(migration)
        cls.accounting = ResourceAccounting(cls.store)
        cls.actor = Actor(ActorType.CONTROL_PLANE, "accounting-control")

    def setUp(self):
        self.store.reset_for_test()
        project = CreateProject(
            self.envelope("project.create", "create-project", 0),
            "Accounting test project",
            Actor(ActorType.USER, "user-1"),
        )
        ControlPlane(self.store).create_project(project)

    def envelope(self, command_type, suffix, version):
        return CommandEnvelope(
            "cmd-" + suffix,
            command_type,
            "key-" + suffix,
            version,
            self.actor,
            "resource accounting test",
            "project-1",
        )

    def create_account(self, limits=None, thresholds=(7500, 9500, 10000)):
        command = CreateResourceAccount(
            self.envelope("resource_account.create", "account", 0),
            "account-1",
            "project",
            "project-1",
            limits or {"llm_tokens": 100, "agent_runs": 4},
            "",
            thresholds,
        )
        return self.accounting.create_account(command)

    def reserve(self, suffix, version, amounts, preparation_id=""):
        command = ReserveResources(
            self.envelope("resource.reserve", suffix, version),
            "account-1",
            "reservation-" + suffix,
            "preparation",
            "owner-" + suffix,
            amounts,
            "",
            preparation_id,
        )
        return self.accounting.reserve(command)

    def usage(self, suffix, reservation_id, owner_id, amounts):
        return self.accounting.record_usage(RecordResourceUsage(
            self.envelope("resource.usage.record", suffix + "-usage", 0),
            "usage-" + suffix,
            "sample-" + suffix,
            reservation_id,
            "preparation",
            owner_id,
            amounts,
        ))

    def test_account_state_event_outbox_receipt_are_atomic_and_idempotent(self):
        command = CreateResourceAccount(
            self.envelope("resource_account.create", "atomic-account", 0),
            "account-1", "project", "project-1", {"llm_tokens": 100},
        )
        self.store.fail_once(AccountingFaultPoint.AFTER_ACCOUNT_BEFORE_EVENT)
        with self.assertRaises(RuntimeError):
            self.accounting.create_account(command)
        self.assertEqual(0, self.store.scalar("SELECT count(*) FROM resource_accounts"))
        self.assertEqual(1, self.store.count("event_log"))
        self.assertEqual(1, self.store.count("outbox_messages"))
        self.assertEqual(1, self.store.count("command_receipts"))
        first = self.accounting.create_account(command)
        second = self.accounting.create_account(command)
        self.assertEqual(first, second)
        self.assertEqual(1, self.store.scalar(
            "SELECT count(*) FROM event_log WHERE event_type='budget.account_created'"
        ))

    def test_ct005_two_connections_compete_only_one_reservation_wins(self):
        self.create_account({"llm_tokens": 100})
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute(
                """UPDATE resource_balances SET consumed_amount=20,reserved_amount=50
                   WHERE account_id='account-1' AND dimension='llm_tokens'"""
            )
            connection.execute(
                "UPDATE resource_accounts SET version=1 WHERE account_id='account-1'"
            )
        barrier = threading.Barrier(2)
        results = []

        def attempt(suffix):
            local = ResourceAccounting(PostgresResourceAccountingStore(DATABASE_URL))
            barrier.wait()
            try:
                results.append((suffix, local.reserve(ReserveResources(
                    self.envelope("resource.reserve", suffix, 1),
                    "account-1", "reservation-" + suffix,
                    "action", "action-" + suffix, {"llm_tokens": 20},
                )).result_code))
            except CommandRejected as exc:
                results.append((suffix, exc.code))

        threads = [threading.Thread(target=attempt, args=(suffix,)) for suffix in ("a", "b")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
            self.assertFalse(thread.is_alive())
        self.assertEqual(1, sum(code == "RESOURCE_RESERVED" for _, code in results))
        self.assertEqual(1, sum(code in {"RESOURCE_ACCOUNT_VERSION_CONFLICT", "RESOURCE_RESERVATION_INFEASIBLE"}
                                for _, code in results))
        self.assertEqual(70, self.store.scalar(
            "SELECT reserved_amount FROM resource_balances WHERE account_id='account-1'"
        ))
        self.assertEqual(1, self.store.scalar(
            "SELECT count(*) FROM resource_reservations WHERE status='ACTIVE'"
        ))
        self.assertEqual(1, self.store.scalar(
            "SELECT count(*) FROM event_log WHERE event_type='budget.reserved'"
        ))

    def test_multidimensional_reservation_is_all_or_nothing(self):
        self.create_account()
        with self.assertRaisesRegex(CommandRejected, "RESOURCE_RESERVATION_INFEASIBLE"):
            self.reserve("multi", 0, {"llm_tokens": 20, "agent_runs": 5})
        self.assertEqual((0, 0), tuple(self.store.scalar(query) for query in (
            "SELECT sum(reserved_amount) FROM resource_balances",
            "SELECT count(*) FROM resource_reservations",
        )))

    def test_fi16_preparation_failure_rolls_back_reservation_and_balance(self):
        self.create_account({"llm_tokens": 100})
        self.store.fail_once(AccountingFaultPoint.AFTER_PREPARATION_RESERVE)
        with self.assertRaises(RuntimeError):
            self.reserve("fi16", 0, {"llm_tokens": 40}, "preparation-fi16")
        self.assertEqual(0, self.store.scalar(
            "SELECT reserved_amount FROM resource_balances WHERE account_id='account-1'"
        ))
        self.assertEqual(0, self.store.scalar("SELECT count(*) FROM resource_reservations"))
        self.assertEqual(0, self.store.scalar("SELECT count(*) FROM resource_preparations"))
        self.assertEqual(0, self.store.scalar(
            "SELECT count(*) FROM event_log WHERE event_type='execution.queued'"
        ))
        self.assertEqual(1, self.store.scalar(
            """SELECT count(*) FROM audit_records
               WHERE reason_code='RESOURCE_TRANSACTION_ABORTED'"""
        ))

    def test_fi17_settlement_failure_and_retry_accounts_exactly_once(self):
        self.create_account({"llm_tokens": 100})
        self.reserve("fi17", 0, {"llm_tokens": 80})
        self.usage("fi17", "reservation-fi17", "owner-fi17", {"llm_tokens": 60})
        command = SettleReservation(
            self.envelope("resource.settle", "fi17-settle", 1),
            "settlement-fi17", "reservation-fi17",
        )
        self.store.fail_once(AccountingFaultPoint.AFTER_CONSUMED_BEFORE_RELEASE)
        with self.assertRaises(RuntimeError):
            self.accounting.settle(command)
        self.assertEqual((0, 80), self._balance("llm_tokens"))
        self.assertEqual(0, self.store.scalar("SELECT count(*) FROM resource_settlements"))
        first = self.accounting.settle(command)
        second = self.accounting.settle(command)
        self.assertEqual(first, second)
        self.assertEqual((60, 0), self._balance("llm_tokens"))
        self.assertEqual(1, self.store.scalar("SELECT count(*) FROM resource_settlements"))
        self.assertEqual(1, self.store.scalar(
            "SELECT count(*) FROM event_log WHERE event_type='budget.settled'"
        ))

    def test_two_reconcilers_settle_unsettled_usage_exactly_once(self):
        self.create_account({"llm_tokens": 100})
        self.reserve("reconcile", 0, {"llm_tokens": 80})
        self.usage(
            "reconcile", "reservation-reconcile", "owner-reconcile",
            {"llm_tokens": 60},
        )
        barrier = threading.Barrier(2)
        results = []

        def attempt(suffix):
            local = ResourceAccounting(PostgresResourceAccountingStore(DATABASE_URL))
            barrier.wait()
            command = ReconcileReservation(
                self.envelope("resource.reconcile", "reconcile-" + suffix, 1),
                "reconcile-" + suffix,
                "reservation-reconcile",
            )
            try:
                results.append(local.reconcile(command).result_code)
            except CommandRejected as exc:
                results.append(exc.code)

        threads = [threading.Thread(target=attempt, args=(suffix,)) for suffix in ("a", "b")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
            self.assertFalse(thread.is_alive())
        self.assertEqual(1, results.count("RESOURCE_RECONCILED"))
        self.assertEqual(1, results.count("RESOURCE_RECONCILE_NOT_REQUIRED"))
        self.assertEqual((60, 0), self._balance("llm_tokens"))
        self.assertEqual(1, self.store.scalar("SELECT count(*) FROM resource_settlements"))
        self.assertEqual(1, self.store.scalar(
            "SELECT count(*) FROM event_log WHERE event_type='budget.settled'"
        ))
        self.assertEqual(1, self.store.scalar(
            "SELECT count(*) FROM event_log WHERE event_type='budget.reconciled'"
        ))

    def test_actual_over_reservation_is_recorded_and_enters_hard_stop(self):
        self.create_account({"llm_tokens": 100})
        self.reserve("over", 0, {"llm_tokens": 80})
        self.usage("over", "reservation-over", "owner-over", {"llm_tokens": 120})
        receipt = self.accounting.settle(SettleReservation(
            self.envelope("resource.settle", "over-settle", 1),
            "settlement-over", "reservation-over",
        ))
        self.assertTrue(receipt.response["over_limit"])
        self.assertEqual((120, 0), self._balance("llm_tokens"))
        self.assertEqual("HARD_STOP", self.store.scalar(
            "SELECT threshold_status FROM resource_accounts WHERE account_id='account-1'"
        ))
        with self.assertRaisesRegex(CommandRejected, "RESOURCE_HARD_STOP"):
            self.reserve("blocked", 2, {"llm_tokens": 0})

    def test_budget_fact_binds_account_version_and_becomes_stale(self):
        self.create_account({"llm_tokens": 100})
        fact = IssueProjectBudgetFact(
            self.envelope("resource.budget_fact.issue", "fact", 0),
            "budget-fact-1", "account-1", 0, "CREATED", "INTAKE",
        )
        receipt = self.accounting.issue_budget_fact(fact)
        self.assertFalse(receipt.response["hard_stop"])
        self.assertEqual((0, True), tuple(self.store.scalar(query) for query in (
            "SELECT resource_account_version FROM project_budget_facts WHERE budget_fact_id='budget-fact-1'",
            "SELECT valid FROM project_budget_facts WHERE budget_fact_id='budget-fact-1'",
        )))
        self.reserve("stale", 0, {"llm_tokens": 10})
        self.assertFalse(self.store.scalar(
            "SELECT valid FROM project_budget_facts WHERE budget_fact_id='budget-fact-1'"
        ))

    def _balance(self, dimension):
        with psycopg.connect(DATABASE_URL) as connection:
            return tuple(connection.execute(
                """SELECT consumed_amount,reserved_amount FROM resource_balances
                   WHERE account_id='account-1' AND dimension=%s""", (dimension,)
            ).fetchone())


if __name__ == "__main__":
    unittest.main()
