import hashlib
import json
import uuid
from enum import Enum
from types import SimpleNamespace
from typing import Any, Dict

from psycopg.types.json import Jsonb

from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.domain.models import CommandReceipt
from hermes_runtime.domain.resource_accounting import (
    ResourceAccountingRejected,
    ThresholdPolicy,
    evaluate_threshold,
    validate_amounts,
    validate_currency,
)
from hermes_runtime.infrastructure.postgres_project import PostgresProjectStore


class AccountingFaultPoint(str, Enum):
    AFTER_ACCOUNT_BEFORE_EVENT = "after_account_before_event"
    AFTER_RESERVATION_BEFORE_BALANCE = "after_reservation_before_balance"
    AFTER_BALANCE_BEFORE_EVENT = "after_balance_before_event"
    AFTER_USAGE_BEFORE_EVENT = "after_usage_before_event"
    AFTER_CONSUMED_BEFORE_RELEASE = "after_consumed_before_release"
    AFTER_SETTLEMENT_BEFORE_EVENT = "after_settlement_before_event"
    AFTER_BUDGET_FACT_BEFORE_EVENT = "after_budget_fact_before_event"
    AFTER_PREPARATION_RESERVE = "after_preparation_reserve"


class PostgresResourceAccountingStore(PostgresProjectStore):
    def reset_for_test(self) -> None:
        tables = (
            "resource_reconcile_records", "resource_settlement_usage",
            "resource_settlements", "resource_usage_amounts",
            "resource_usage_records", "resource_reservation_amounts",
            "resource_reservations", "resource_preparations",
            "resource_balances", "resource_accounts",
        )
        with self._connect() as connection:
            connection.execute(
                "TRUNCATE {} RESTART IDENTITY CASCADE".format(", ".join(tables))
            )
        super().reset_for_test()

    def create_account(self, command) -> CommandReceipt:
        self._validate_amounts(command.limits, command.currency)
        if command.scope_type not in {"project", "task", "action"}:
            raise CommandRejected("RESOURCE_SCOPE_INVALID")
        warn, gate, hard_stop = command.thresholds_basis_points
        ThresholdPolicy(warn, gate, hard_stop).validate()
        return self._execute(command, self._create_account)

    def _create_account(self, connection, command):
        if not connection.execute(
            "SELECT 1 FROM projects WHERE project_id=%s FOR SHARE",
            (command.envelope.project_id,),
        ).fetchone():
            raise CommandRejected("PROJECT_NOT_FOUND")
        warn, gate, hard_stop = command.thresholds_basis_points
        connection.execute(
            """INSERT INTO resource_accounts(
               account_id,project_id,scope_type,scope_id,currency,
               warn_basis_points,gate_basis_points,hard_stop_basis_points)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (command.account_id, command.envelope.project_id, command.scope_type,
             command.scope_id, command.currency or None, warn, gate, hard_stop),
        )
        for dimension, limit in sorted(command.limits.items()):
            connection.execute(
                "INSERT INTO resource_balances(account_id,dimension,limit_amount) VALUES (%s,%s,%s)",
                (command.account_id, dimension, limit),
            )
        self._trigger_fault(AccountingFaultPoint.AFTER_ACCOUNT_BEFORE_EVENT)
        event_id = self._append_event_and_outbox(
            connection, command.envelope, "budget.account_created",
            {"account_id": command.account_id, "entity_version": 0},
        )
        return CommandReceipt(command.envelope.command_id, "APPLIED",
            "RESOURCE_ACCOUNT_CREATED", 0, (event_id,), {"account_id": command.account_id})

    def reserve(self, command) -> CommandReceipt:
        self._validate_amounts(command.amounts, command.currency)
        if command.owner_type not in {"decision", "action", "preparation"} or not command.owner_id:
            raise CommandRejected("RESOURCE_RESERVATION_OWNER_MISMATCH")
        return self._execute(command, self._reserve)

    def _reserve(self, connection, command):
        account = connection.execute(
            """SELECT project_id,currency,version,threshold_status,
                      warn_basis_points,gate_basis_points,hard_stop_basis_points
               FROM resource_accounts WHERE account_id=%s FOR UPDATE""",
            (command.account_id,),
        ).fetchone()
        if not account:
            raise CommandRejected("RESOURCE_ACCOUNT_NOT_FOUND")
        if account[0] != command.envelope.project_id:
            raise CommandRejected("RESOURCE_ACCOUNT_NOT_FOUND")
        if account[2] != command.envelope.expected_version:
            raise CommandRejected("RESOURCE_ACCOUNT_VERSION_CONFLICT")
        if account[3] == "HARD_STOP":
            raise CommandRejected("RESOURCE_HARD_STOP")
        if command.currency and command.currency != account[1]:
            raise CommandRejected("RESOURCE_CURRENCY_MISMATCH")
        rows = connection.execute(
            """SELECT dimension,limit_amount,consumed_amount,reserved_amount
               FROM resource_balances WHERE account_id=%s FOR UPDATE""",
            (command.account_id,),
        ).fetchall()
        balances = {row[0]: row[1:] for row in rows}
        if any(name not in balances or amount > max(0, balances[name][0] - balances[name][1] - balances[name][2])
               for name, amount in command.amounts.items()):
            raise CommandRejected("RESOURCE_RESERVATION_INFEASIBLE")
        if command.preparation_id:
            connection.execute(
                """INSERT INTO resource_preparations(
                   preparation_id,project_id,owner_type,owner_id,status)
                   VALUES (%s,%s,%s,%s,'PREPARED')""",
                (command.preparation_id, account[0], command.owner_type, command.owner_id),
            )
        next_version = account[2] + 1
        connection.execute(
            """INSERT INTO resource_reservations(
               reservation_id,account_id,project_id,owner_type,owner_id,
               preparation_id,currency,status,account_version,command_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s,'ACTIVE',%s,%s)""",
            (command.reservation_id, command.account_id, account[0], command.owner_type,
             command.owner_id, command.preparation_id or None, account[1], next_version,
             command.envelope.command_id),
        )
        for dimension, amount in sorted(command.amounts.items()):
            connection.execute(
                "INSERT INTO resource_reservation_amounts(reservation_id,dimension,amount) VALUES (%s,%s,%s)",
                (command.reservation_id, dimension, amount),
            )
        self._trigger_fault(AccountingFaultPoint.AFTER_RESERVATION_BEFORE_BALANCE)
        for dimension, amount in command.amounts.items():
            connection.execute(
                """UPDATE resource_balances SET reserved_amount=reserved_amount+%s
                   WHERE account_id=%s AND dimension=%s""",
                (amount, command.account_id, dimension),
            )
        self._trigger_fault(AccountingFaultPoint.AFTER_BALANCE_BEFORE_EVENT)
        status = self._update_account_status(connection, command.account_id, next_version)
        self._invalidate_budget_facts(connection, command.account_id)
        self._trigger_fault(AccountingFaultPoint.AFTER_PREPARATION_RESERVE)
        if command.preparation_id:
            connection.execute(
                "UPDATE resource_preparations SET status='FINALIZED',finalized_at=now() WHERE preparation_id=%s",
                (command.preparation_id,),
            )
        event_id = self._append_event_and_outbox(
            connection, command.envelope, "budget.reserved",
            {"account_id": command.account_id, "reservation_id": command.reservation_id,
             "owner_type": command.owner_type, "owner_id": command.owner_id,
             "amounts": command.amounts, "threshold_status": status,
             "entity_version": next_version},
        )
        return CommandReceipt(command.envelope.command_id, "APPLIED",
            "RESOURCE_RESERVED", next_version, (event_id,),
            {"reservation_id": command.reservation_id, "threshold_status": status})

    def release(self, command) -> CommandReceipt:
        if command.terminal_status not in {"RELEASED", "CANCELLED", "EXPIRED"}:
            raise CommandRejected("RESOURCE_RESERVATION_NOT_ACTIVE")
        return self._execute(command, self._release)

    def _release(self, connection, command):
        reservation = self._reservation_for_update(connection, command.reservation_id)
        if reservation[5] != "ACTIVE":
            raise CommandRejected("RESOURCE_RELEASE_ALREADY_APPLIED")
        account = self._account_for_update(connection, reservation[0], command.envelope.expected_version)
        amounts = self._reservation_amounts(connection, command.reservation_id)
        for dimension, amount in amounts.items():
            connection.execute(
                """UPDATE resource_balances SET reserved_amount=reserved_amount-%s
                   WHERE account_id=%s AND dimension=%s AND reserved_amount >= %s""",
                (amount, reservation[0], dimension, amount),
            )
        connection.execute(
            "UPDATE resource_reservations SET status=%s,terminal_at=now() WHERE reservation_id=%s",
            (command.terminal_status, command.reservation_id),
        )
        next_version = account[2] + 1
        status = self._update_account_status(connection, reservation[0], next_version)
        self._invalidate_budget_facts(connection, reservation[0])
        event_id = self._append_event_and_outbox(
            connection, command.envelope, "budget.released",
            {"account_id": reservation[0], "reservation_id": command.reservation_id,
             "terminal_status": command.terminal_status, "amounts": amounts,
             "threshold_status": status, "entity_version": next_version},
        )
        return CommandReceipt(command.envelope.command_id, "APPLIED", "RESOURCE_RELEASED",
            next_version, (event_id,), {"reservation_id": command.reservation_id})

    def record_usage(self, command) -> CommandReceipt:
        self._validate_amounts(command.amounts, command.currency)
        return self._execute(command, self._record_usage)

    def _record_usage(self, connection, command):
        reservation = self._reservation_for_update(connection, command.reservation_id)
        if reservation[1] != command.envelope.project_id:
            raise CommandRejected("RESOURCE_RESERVATION_OWNER_MISMATCH")
        if (reservation[2], reservation[3]) != (command.owner_type, command.owner_id):
            raise CommandRejected("RESOURCE_RESERVATION_OWNER_MISMATCH")
        if command.currency and command.currency != reservation[4]:
            raise CommandRejected("RESOURCE_CURRENCY_MISMATCH")
        conflict = connection.execute(
            "SELECT reservation_id FROM resource_usage_records WHERE sample_id=%s",
            (command.sample_id,),
        ).fetchone()
        if conflict:
            raise CommandRejected("RESOURCE_USAGE_DUPLICATE_CONFLICT")
        connection.execute(
            """INSERT INTO resource_usage_records(
               usage_id,sample_id,reservation_id,project_id,owner_type,owner_id,currency,command_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (command.usage_id, command.sample_id, command.reservation_id,
             command.envelope.project_id, command.owner_type, command.owner_id,
             reservation[4], command.envelope.command_id),
        )
        for dimension, amount in sorted(command.amounts.items()):
            connection.execute(
                "INSERT INTO resource_usage_amounts(usage_id,dimension,amount) VALUES (%s,%s,%s)",
                (command.usage_id, dimension, amount),
            )
        self._trigger_fault(AccountingFaultPoint.AFTER_USAGE_BEFORE_EVENT)
        event_id = self._append_event_and_outbox(
            connection, command.envelope, "budget.usage_recorded",
            {"reservation_id": command.reservation_id, "usage_id": command.usage_id,
             "sample_id": command.sample_id, "amounts": command.amounts},
        )
        return CommandReceipt(command.envelope.command_id, "APPLIED", "RESOURCE_USAGE_RECORDED",
            None, (event_id,), {"usage_id": command.usage_id})

    def settle(self, command) -> CommandReceipt:
        return self._execute(command, self._settle)

    def _settle(self, connection, command):
        reservation = self._reservation_for_update(connection, command.reservation_id)
        if reservation[5] != "ACTIVE":
            raise CommandRejected("RESOURCE_SETTLEMENT_ALREADY_APPLIED")
        account = self._account_for_update(connection, reservation[0], command.envelope.expected_version)
        usage_rows = connection.execute(
            """SELECT ur.usage_id,ua.dimension,ua.amount
               FROM resource_usage_records ur JOIN resource_usage_amounts ua USING(usage_id)
               LEFT JOIN resource_settlement_usage su USING(usage_id)
               WHERE ur.reservation_id=%s AND su.usage_id IS NULL
               ORDER BY ur.usage_id,ua.dimension FOR UPDATE OF ur""",
            (command.reservation_id,),
        ).fetchall()
        if not usage_rows:
            raise CommandRejected("RESOURCE_RECONCILE_NOT_REQUIRED")
        actual: Dict[str, int] = {}
        usage_ids = set()
        for usage_id, dimension, amount in usage_rows:
            usage_ids.add(usage_id)
            actual[dimension] = actual.get(dimension, 0) + amount
        reserved = self._reservation_amounts(connection, command.reservation_id)
        next_version = account[2] + 1
        over_limit = False
        for dimension in set(reserved) | set(actual):
            consumed = actual.get(dimension, 0)
            released = reserved.get(dimension, 0)
            updated = connection.execute(
                """UPDATE resource_balances
                   SET consumed_amount=consumed_amount+%s,
                       reserved_amount=reserved_amount-%s
                   WHERE account_id=%s AND dimension=%s AND reserved_amount >= %s
                   RETURNING limit_amount,consumed_amount,reserved_amount""",
                (consumed, released, reservation[0], dimension, released),
            ).fetchone()
            if not updated:
                raise CommandRejected("RESOURCE_SETTLEMENT_USAGE_CONFLICT")
            over_limit = over_limit or updated[1] + updated[2] > updated[0]
        self._trigger_fault(AccountingFaultPoint.AFTER_CONSUMED_BEFORE_RELEASE)
        connection.execute(
            """INSERT INTO resource_settlements(
               settlement_id,reservation_id,account_id,project_id,account_version,
               over_limit,command_id) VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (command.settlement_id, command.reservation_id, reservation[0], reservation[1],
             next_version, over_limit, command.envelope.command_id),
        )
        for usage_id in sorted(usage_ids):
            connection.execute(
                "INSERT INTO resource_settlement_usage(settlement_id,usage_id) VALUES (%s,%s)",
                (command.settlement_id, usage_id),
            )
        connection.execute(
            "UPDATE resource_reservations SET status='SETTLED',terminal_at=now() WHERE reservation_id=%s",
            (command.reservation_id,),
        )
        self._trigger_fault(AccountingFaultPoint.AFTER_SETTLEMENT_BEFORE_EVENT)
        status = self._update_account_status(connection, reservation[0], next_version, over_limit)
        self._invalidate_budget_facts(connection, reservation[0])
        event_id = self._append_event_and_outbox(
            connection, command.envelope, "budget.settled",
            {"account_id": reservation[0], "reservation_id": command.reservation_id,
             "settlement_id": command.settlement_id, "actual": actual,
             "released": reserved, "over_limit": over_limit,
             "threshold_status": status, "entity_version": next_version},
        )
        return CommandReceipt(command.envelope.command_id, "APPLIED", "RESOURCE_SETTLED",
            next_version, (event_id,), {"settlement_id": command.settlement_id,
            "over_limit": over_limit, "threshold_status": status})

    def reconcile(self, command) -> CommandReceipt:
        return self._execute(command, self._reconcile)

    def _reconcile(self, connection, command):
        reservation = self._reservation_for_update(
            connection, command.reservation_id
        )
        if reservation[5] != "ACTIVE":
            raise CommandRejected("RESOURCE_RECONCILE_NOT_REQUIRED")
        usage_exists = connection.execute(
            """SELECT 1 FROM resource_usage_records
               WHERE reservation_id=%s LIMIT 1""",
            (command.reservation_id,),
        ).fetchone()
        if usage_exists:
            settlement_command = SimpleNamespace(
                envelope=command.envelope,
                settlement_id="settlement-reconcile-" + command.reconcile_id,
                reservation_id=command.reservation_id,
            )
            receipt = self._settle(connection, settlement_command)
            action = "SETTLE_USAGE"
        else:
            preparation = connection.execute(
                """SELECT p.status FROM resource_reservations r
                   LEFT JOIN resource_preparations p
                     ON p.preparation_id=r.preparation_id
                   WHERE r.reservation_id=%s""",
                (command.reservation_id,),
            ).fetchone()
            if preparation and preparation[0] == "FINALIZED":
                raise CommandRejected("RESOURCE_RECONCILE_NOT_REQUIRED")
            account = self._account_for_update(
                connection, reservation[0], command.envelope.expected_version
            )
            amounts = self._reservation_amounts(
                connection, command.reservation_id
            )
            for dimension, amount in amounts.items():
                row = connection.execute(
                    """UPDATE resource_balances
                       SET reserved_amount=reserved_amount-%s
                       WHERE account_id=%s AND dimension=%s
                         AND reserved_amount >= %s RETURNING reserved_amount""",
                    (amount, reservation[0], dimension, amount),
                ).fetchone()
                if not row:
                    raise CommandRejected("RESOURCE_SETTLEMENT_USAGE_CONFLICT")
            connection.execute(
                """UPDATE resource_reservations
                   SET status='EXPIRED',terminal_at=now()
                   WHERE reservation_id=%s""",
                (command.reservation_id,),
            )
            next_version = account[2] + 1
            status = self._update_account_status(
                connection, reservation[0], next_version
            )
            self._invalidate_budget_facts(connection, reservation[0])
            action = "RELEASE_ORPHAN"
            receipt = CommandReceipt(
                command.envelope.command_id, "APPLIED", "RESOURCE_RECONCILED",
                next_version, (), {"reservation_id": command.reservation_id,
                "action": action, "threshold_status": status},
            )
        connection.execute(
            """INSERT INTO resource_reconcile_records(
               reconcile_id,reservation_id,action,command_id)
               VALUES (%s,%s,%s,%s)""",
            (command.reconcile_id, command.reservation_id, action,
             command.envelope.command_id),
        )
        event_id = self._append_event_and_outbox(
            connection, command.envelope, "budget.reconciled",
            {"reconcile_id": command.reconcile_id,
             "reservation_id": command.reservation_id, "action": action,
             "entity_version": receipt.target_version},
        )
        return CommandReceipt(
            receipt.command_id, receipt.status, "RESOURCE_RECONCILED",
            receipt.target_version, receipt.event_ids + (event_id,),
            dict(receipt.response, action=action),
        )

    def issue_budget_fact(self, command) -> CommandReceipt:
        return self._execute(command, self._issue_budget_fact)

    def _issue_budget_fact(self, connection, command):
        account = connection.execute(
            """SELECT project_id,version,threshold_status FROM resource_accounts
               WHERE account_id=%s FOR SHARE""", (command.account_id,)
        ).fetchone()
        if not account or account[0] != command.envelope.project_id:
            raise CommandRejected("RESOURCE_ACCOUNT_NOT_FOUND")
        if account[1] != command.envelope.expected_version:
            raise CommandRejected("RESOURCE_ACCOUNT_VERSION_CONFLICT")
        project = connection.execute(
            "SELECT state,version FROM projects WHERE project_id=%s FOR SHARE",
            (account[0],),
        ).fetchone()
        if not project or project[1] != command.project_version or project[0] != command.from_state:
            raise CommandRejected("PROJECT_AUTHORITY_PRECONDITION_FAILED")
        hard_stop = account[2] == "HARD_STOP"
        connection.execute(
            """UPDATE project_budget_facts SET valid=false,invalidated_at=now()
               WHERE project_id=%s AND project_version=%s AND from_state=%s
                 AND to_state=%s AND valid""",
            (account[0], command.project_version, command.from_state, command.to_state),
        )
        connection.execute(
            """INSERT INTO project_budget_facts(
               budget_fact_id,project_id,project_version,from_state,to_state,status,
               authority,budget_scope_id,version,resource_account_id,
               resource_account_version,hard_stop)
               VALUES (%s,%s,%s,%s,%s,%s,'budget_engine',%s,%s,%s,%s,%s)""",
            (command.budget_fact_id, account[0], command.project_version,
             command.from_state, command.to_state,
             "HARD_STOP" if hard_stop else "OK", command.account_id, account[1],
             command.account_id, account[1], hard_stop),
        )
        self._trigger_fault(AccountingFaultPoint.AFTER_BUDGET_FACT_BEFORE_EVENT)
        event_id = self._append_event_and_outbox(
            connection, command.envelope, "budget.fact_issued",
            {"budget_fact_id": command.budget_fact_id, "account_id": command.account_id,
             "resource_account_version": account[1], "hard_stop": hard_stop},
        )
        return CommandReceipt(command.envelope.command_id, "APPLIED", "BUDGET_FACT_ISSUED",
            account[1], (event_id,), {"budget_fact_id": command.budget_fact_id,
            "hard_stop": hard_stop})

    def _execute(self, command, operation):
        request_hash = self._accounting_hash(command)
        try:
            with self._connect() as connection:
                existing = self._begin_command(connection, command.envelope, request_hash)
                if existing:
                    return existing
                receipt = operation(connection, command)
                self._complete_command(connection, command.envelope, receipt)
                return receipt
        except ResourceAccountingRejected as exc:
            self._persist_rejection(command.envelope, request_hash, str(exc), "")
            raise CommandRejected(str(exc))
        except CommandRejected as exc:
            self._persist_rejection(command.envelope, request_hash, exc.code, exc.detail)
            raise
        except RuntimeError as exc:
            self._persist_fault_audit(command, exc)
            raise

    def _persist_fault_audit(self, command, exc):
        envelope = command.envelope
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO audit_records(
                   audit_id,project_id,source_command_id,actor_type,actor_id,
                   action,outcome,reason_code,detail)
                   VALUES (%s,%s,%s,%s,%s,%s,'REJECTED',
                           'RESOURCE_TRANSACTION_ABORTED',%s)
                   ON CONFLICT (source_command_id,reason_code) DO NOTHING""",
                ("audit-" + str(uuid.uuid4()), envelope.project_id,
                 envelope.command_id, envelope.actor.actor_type.value,
                 envelope.actor.actor_id, envelope.command_type, str(exc)),
            )

    def _account_for_update(self, connection, account_id, expected_version):
        row = connection.execute(
            "SELECT project_id,currency,version,threshold_status FROM resource_accounts WHERE account_id=%s FOR UPDATE",
            (account_id,),
        ).fetchone()
        if not row:
            raise CommandRejected("RESOURCE_ACCOUNT_NOT_FOUND")
        if row[2] != expected_version:
            raise CommandRejected("RESOURCE_ACCOUNT_VERSION_CONFLICT")
        return row

    def _reservation_for_update(self, connection, reservation_id):
        row = connection.execute(
            """SELECT account_id,project_id,owner_type,owner_id,currency,status
               FROM resource_reservations WHERE reservation_id=%s FOR UPDATE""",
            (reservation_id,),
        ).fetchone()
        if not row:
            raise CommandRejected("RESOURCE_RESERVATION_NOT_ACTIVE")
        return row

    @staticmethod
    def _reservation_amounts(connection, reservation_id):
        return dict(connection.execute(
            "SELECT dimension,amount FROM resource_reservation_amounts WHERE reservation_id=%s",
            (reservation_id,),
        ).fetchall())

    def _update_account_status(self, connection, account_id, version, force_hard_stop=False):
        account = connection.execute(
            """SELECT warn_basis_points,gate_basis_points,hard_stop_basis_points
               FROM resource_accounts WHERE account_id=%s""", (account_id,)
        ).fetchone()
        balances = {row[0]: row[1:] for row in connection.execute(
            """SELECT dimension,limit_amount,consumed_amount,reserved_amount
               FROM resource_balances WHERE account_id=%s""", (account_id,)
        ).fetchall()}
        status = "HARD_STOP" if force_hard_stop else evaluate_threshold(
            balances, ThresholdPolicy(*account)
        ).value
        connection.execute(
            "UPDATE resource_accounts SET version=%s,threshold_status=%s,updated_at=now() WHERE account_id=%s",
            (version, status, account_id),
        )
        return status

    @staticmethod
    def _invalidate_budget_facts(connection, account_id):
        connection.execute(
            """UPDATE project_budget_facts SET valid=false,invalidated_at=now()
               WHERE resource_account_id=%s AND valid""", (account_id,)
        )

    @staticmethod
    def _validate_amounts(amounts, currency):
        try:
            validate_amounts(amounts)
            validate_currency(amounts, currency or None)
        except ResourceAccountingRejected as exc:
            raise CommandRejected(str(exc))

    @staticmethod
    def _accounting_hash(command: Any) -> str:
        body = {key: value for key, value in vars(command).items() if key != "envelope"}
        envelope = command.envelope
        value = {"command_type": envelope.command_type,
                 "expected_version": envelope.expected_version,
                 "actor": {"type": envelope.actor.actor_type.value,
                           "id": envelope.actor.actor_id},
                 "reason": envelope.reason, "project_id": envelope.project_id,
                 "body": body}
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
