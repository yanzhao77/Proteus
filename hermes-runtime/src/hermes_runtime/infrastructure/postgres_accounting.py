import hashlib
import json
import uuid
from enum import Enum
from types import SimpleNamespace
from typing import Any, Dict

from psycopg.types.json import Jsonb
import psycopg

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
        warn, gate, hard_stop = command.thresholds_basis_points
        connection.execute(
            """SELECT public.hermes_create_resource_account_authority(
               %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (command.account_id, command.envelope.project_id, command.scope_type,
             command.scope_id, command.currency or None, Jsonb(command.limits),
             warn, gate, hard_stop, command.envelope.command_id,
             command.envelope.actor.actor_type.value),
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
        row = connection.execute(
            """SELECT account_version,threshold_status
               FROM public.hermes_reserve_resources_authority(
               %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (command.account_id, command.envelope.project_id,
             command.envelope.expected_version, command.reservation_id,
             command.owner_type, command.owner_id,
             command.preparation_id or None, command.currency or None,
             Jsonb(command.amounts), command.envelope.command_id,
             command.envelope.actor.actor_type.value),
        ).fetchone()
        self._trigger_fault(AccountingFaultPoint.AFTER_RESERVATION_BEFORE_BALANCE)
        self._trigger_fault(AccountingFaultPoint.AFTER_BALANCE_BEFORE_EVENT)
        self._trigger_fault(AccountingFaultPoint.AFTER_PREPARATION_RESERVE)
        next_version, status = row
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
        next_version, status, account_id, amounts = connection.execute(
            """SELECT account_version,threshold_status,account_id,amounts
               FROM public.hermes_release_reservation_authority(
               %s,%s,%s,%s,%s,%s)""",
            (command.reservation_id, command.envelope.project_id,
             command.envelope.expected_version, command.terminal_status,
             command.envelope.command_id,
             command.envelope.actor.actor_type.value),
        ).fetchone()
        event_id = self._append_event_and_outbox(
            connection, command.envelope, "budget.released",
            {"account_id": account_id, "reservation_id": command.reservation_id,
             "terminal_status": command.terminal_status, "amounts": amounts,
             "threshold_status": status, "entity_version": next_version},
        )
        return CommandReceipt(command.envelope.command_id, "APPLIED", "RESOURCE_RELEASED",
            next_version, (event_id,), {"reservation_id": command.reservation_id})

    def record_usage(self, command) -> CommandReceipt:
        self._validate_amounts(command.amounts, command.currency)
        return self._execute(command, self._record_usage)

    def _record_usage(self, connection, command):
        connection.execute(
            """SELECT public.hermes_record_resource_usage_authority(
               %s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (command.usage_id, command.sample_id, command.reservation_id,
             command.envelope.project_id, command.owner_type, command.owner_id,
             command.currency or None, Jsonb(command.amounts),
             command.envelope.command_id,
             command.envelope.actor.actor_type.value),
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
        next_version, status, account_id, actual, reserved, over_limit = (
            connection.execute(
                """SELECT account_version,threshold_status,account_id,actual,
                          released,over_limit
                   FROM public.hermes_settle_reservation_authority(
                   %s,%s,%s,%s,%s,%s)""",
                (command.settlement_id, command.reservation_id,
                 command.envelope.project_id, command.envelope.expected_version,
                 command.envelope.command_id,
                 command.envelope.actor.actor_type.value),
            ).fetchone()
        )
        self._trigger_fault(AccountingFaultPoint.AFTER_CONSUMED_BEFORE_RELEASE)
        self._trigger_fault(AccountingFaultPoint.AFTER_SETTLEMENT_BEFORE_EVENT)
        event_id = self._append_event_and_outbox(
            connection, command.envelope, "budget.settled",
            {"account_id": account_id, "reservation_id": command.reservation_id,
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
            next_version, status, _, _ = connection.execute(
                """SELECT account_version,threshold_status,account_id,amounts
                   FROM public.hermes_release_reservation_authority(
                   %s,%s,%s,'EXPIRED',%s,%s)""",
                (command.reservation_id, command.envelope.project_id,
                 command.envelope.expected_version, command.envelope.command_id,
                 command.envelope.actor.actor_type.value),
            ).fetchone()
            action = "RELEASE_ORPHAN"
            receipt = CommandReceipt(
                command.envelope.command_id, "APPLIED", "RESOURCE_RECONCILED",
                next_version, (), {"reservation_id": command.reservation_id,
                "action": action, "threshold_status": status},
            )
        connection.execute(
            """SELECT public.hermes_record_resource_reconcile_authority(
               %s,%s,%s,%s,%s,%s)""",
            (command.reconcile_id, command.reservation_id, action,
             command.envelope.project_id, command.envelope.command_id,
             command.envelope.actor.actor_type.value),
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
        hard_stop = connection.execute(
            """SELECT public.hermes_issue_budget_fact_authority(
               %s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (command.budget_fact_id, command.account_id,
             command.envelope.project_id, command.envelope.expected_version,
             command.project_version, command.from_state, command.to_state,
             command.envelope.command_id,
             command.envelope.actor.actor_type.value),
        ).fetchone()[0]
        self._trigger_fault(AccountingFaultPoint.AFTER_BUDGET_FACT_BEFORE_EVENT)
        event_id = self._append_event_and_outbox(
            connection, command.envelope, "budget.fact_issued",
            {"budget_fact_id": command.budget_fact_id, "account_id": command.account_id,
             "resource_account_version": command.envelope.expected_version,
             "hard_stop": hard_stop},
        )
        return CommandReceipt(command.envelope.command_id, "APPLIED", "BUDGET_FACT_ISSUED",
            command.envelope.expected_version, (event_id,), {"budget_fact_id": command.budget_fact_id,
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
        except psycopg.DatabaseError as exc:
            primary = getattr(exc.diag, "message_primary", "") or str(exc)
            code = primary.splitlines()[0]
            if code.startswith("duplicate key value"):
                code = "RESOURCE_ID_CONFLICT"
            elif not code.startswith("RESOURCE_") and not code.startswith("ACCOUNTING_") and not code.startswith("PROJECT_"):
                raise
            self._persist_rejection(command.envelope, request_hash, code, "")
            raise CommandRejected(code)
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
