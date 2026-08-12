from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.domain.models import ActorType


class ResourceAccounting:
    def __init__(self, store) -> None:
        self._store = store

    def create_account(self, command):
        return self._apply(command, "resource_account.create", "create_account")

    def reserve(self, command):
        return self._apply(command, "resource.reserve", "reserve")

    def release(self, command):
        return self._apply(command, "resource.release", "release")

    def record_usage(self, command):
        return self._apply(command, "resource.usage.record", "record_usage")

    def settle(self, command):
        return self._apply(command, "resource.settle", "settle")

    def reconcile(self, command):
        actor = command.envelope.actor
        if actor.actor_type not in {
            ActorType.CONTROL_PLANE, ActorType.RECOVERY_CONTROLLER
        }:
            raise CommandRejected("ACCOUNTING_AUTHORITY_REQUIRED")
        return self._apply(command, "resource.reconcile", "reconcile", False)

    def issue_budget_fact(self, command):
        return self._apply(
            command, "resource.budget_fact.issue", "issue_budget_fact"
        )

    def _apply(self, command, command_type, method, check_actor=True):
        envelope = command.envelope
        if check_actor and envelope.actor.actor_type is not ActorType.CONTROL_PLANE:
            raise CommandRejected("ACCOUNTING_AUTHORITY_REQUIRED")
        if envelope.command_type != command_type:
            raise CommandRejected("ACCOUNTING_COMMAND_SEMANTICS_MISMATCH")
        if not envelope.reason.strip():
            raise CommandRejected("COMMAND_REASON_REQUIRED")
        return getattr(self._store, method)(command)
