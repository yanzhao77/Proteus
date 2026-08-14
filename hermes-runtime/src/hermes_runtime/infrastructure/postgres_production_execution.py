from typing import Any, Mapping

import psycopg
from psycopg.rows import dict_row

from hermes_runtime.application.docker_execution import (
    RecordDockerProcess,
    RecordExternalSideEffectReceipt,
)
from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.domain.docker_execution import DockerProcessState
from hermes_runtime.domain.explain import canonical_payload_hash
from hermes_runtime.infrastructure.postgres_explain import PostgresExplainStore


class PostgresProductionExecutionStore(PostgresExplainStore):
    P3_PRODUCTION_TABLES = (
        "external_side_effect_receipts",
        "docker_process_reconcile_findings",
        "docker_process_observations",
        "docker_process_runs",
    )

    def reset_for_test(self) -> None:
        with self._connect() as connection:
            connection.execute(
                "TRUNCATE {} RESTART IDENTITY CASCADE".format(
                    ", ".join(self.P3_PRODUCTION_TABLES)
                )
            )
        super().reset_for_test()

    def record_process(self, command: RecordDockerProcess) -> Mapping[str, Any]:
        state = command.state if isinstance(command.state, DockerProcessState) else DockerProcessState(command.state)
        payload = {
            "command": "docker_process.record",
            "project_id": command.project_id,
            "execution_request_id": command.execution_request_id,
            "run_id": command.run_id,
            "lease_id": command.lease_id,
            "lease_version": command.lease_version,
            "fencing_token": command.fencing_token,
            "container_name": command.container_name,
            "container_id": command.container_id,
            "plan_hash": command.plan_hash,
            "state": state.value,
        }
        return self._call(
            """SELECT public.hermes_record_docker_process(
               %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
               ) AS result""",
            (
                command.project_id,
                command.execution_request_id,
                command.run_id,
                command.lease_id,
                command.lease_version,
                command.fencing_token,
                command.container_name,
                command.container_id,
                command.plan_hash,
                state.value,
                command.actor.actor_type.value,
                command.actor.actor_id,
                command.reason,
                command.trace_id,
                command.correlation_id,
                command.causation_id or None,
                command.command_id,
                command.idempotency_key,
                canonical_payload_hash(payload),
                command.fault_point or None,
            ),
        )

    def record_side_effect_receipt(self, command: RecordExternalSideEffectReceipt) -> Mapping[str, Any]:
        payload = {
            "command": "external_side_effect.receipt",
            "project_id": command.project_id,
            "execution_request_id": command.execution_request_id,
            "run_id": command.run_id,
            "lease_id": command.lease_id,
            "lease_version": command.lease_version,
            "fencing_token": command.fencing_token,
            "side_effect_key": command.side_effect_key,
            "action_class": command.action_class,
            "target_class": command.target_class,
            "reversible": command.reversible,
            "request_payload_hash": command.request_payload_hash,
            "external_receipt_ref": command.external_receipt_ref,
            "external_receipt_hash": command.external_receipt_hash,
            "observed_outcome": command.observed_outcome,
        }
        return self._call(
            """SELECT public.hermes_record_external_side_effect_receipt(
               %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
               %s,%s,%s,%s,%s,%s,%s,%s
               ) AS result""",
            (
                command.project_id,
                command.execution_request_id,
                command.run_id,
                command.lease_id,
                command.lease_version,
                command.fencing_token,
                command.side_effect_key,
                command.action_class,
                command.target_class,
                bool(command.reversible),
                command.human_gate_authorization_ref,
                command.request_payload_hash,
                command.external_receipt_ref,
                command.external_receipt_hash,
                command.observed_outcome,
                command.actor.actor_type.value,
                command.actor.actor_id,
                command.trace_id,
                command.correlation_id,
                command.causation_id or None,
                command.command_id,
                command.idempotency_key,
                canonical_payload_hash(payload),
                command.fault_point or None,
            ),
        )

    def _call(self, sql: str, args: tuple) -> Mapping[str, Any]:
        try:
            with self._connect(row_factory=dict_row) as connection:
                row = connection.execute(sql, args).fetchone()
                return dict(row["result"])
        except psycopg.Error as exc:
            raise CommandRejected(exc.diag.message_primary or exc.__class__.__name__) from exc
