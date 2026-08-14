from typing import Any, Mapping

import psycopg
from psycopg.types.json import Jsonb

from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.application.replay_reconcile import (
    ActivateReplay,
    ApplyReconcilePlan,
    CreateReconcilePlan,
    ExecuteReplay,
    ObserveReconcile,
    RequestReplay,
)
from hermes_runtime.infrastructure.postgres_delivery import PostgresDeliveryStore


class PostgresReplayReconcileStore(PostgresDeliveryStore):
    P3_REPLAY_TABLES = (
        "reconcile_plan_repairs",
        "reconcile_plan_findings",
        "reconcile_plans",
        "reconcile_findings",
        "replay_shadow_projection_events",
        "replay_sessions",
        "replay_generations",
        "replay_generation_pointers",
        "consumer_checkpoint_versions",
    )

    def reset_for_test(self) -> None:
        with self._connect() as connection:
            connection.execute(
                "TRUNCATE {} RESTART IDENTITY CASCADE".format(
                    ", ".join(
                        self.P3_REPLAY_TABLES
                        + self.DELIVERY_TABLES
                        + (
                            "consumer_checkpoints",
                            "consumer_effects",
                            "consumer_inbox",
                            "audit_records",
                            "outbox_messages",
                            "event_log",
                            "event_partition_sequences",
                            "command_receipts",
                        )
                    )
                )
            )

    def request_replay(self, command: RequestReplay) -> Mapping[str, Any]:
        return self._call_json(
            "SELECT public.hermes_request_replay_session(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                command.command_id,
                command.idempotency_key,
                command.replay_session_id,
                command.consumer_id,
                command.stream_name,
                command.partition_key,
                command.source_generation_id,
                command.target_generation_id,
                command.start_sequence,
                command.end_sequence,
                command.consumer_version,
                command.schema_version,
                command.mode,
                command.dry_run,
                command.expected_checkpoint_version,
                command.actor.actor_type.value,
                command.actor.actor_id,
                command.reason,
                command.authorization_ref,
            ),
        )

    def execute_replay(self, command: ExecuteReplay) -> Mapping[str, Any]:
        return self._call_json(
            "SELECT public.hermes_execute_replay_session(%s,%s,%s,%s,%s)",
            (
                command.command_id,
                command.idempotency_key,
                command.replay_session_id,
                command.expected_replay_version,
                command.fault_point or None,
            ),
        )

    def activate_replay(self, command: ActivateReplay) -> Mapping[str, Any]:
        return self._call_json(
            "SELECT public.hermes_activate_replay_generation(%s,%s,%s,%s,%s,%s)",
            (
                command.command_id,
                command.idempotency_key,
                command.replay_session_id,
                command.expected_replay_version,
                command.authorization_ref,
                command.fault_point or None,
            ),
        )

    def observe_reconcile(self, command: ObserveReconcile) -> Mapping[str, Any]:
        return self._call_json(
            "SELECT public.hermes_observe_reconcile_findings(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                command.command_id,
                command.idempotency_key,
                command.scope_id,
                command.actor.actor_type.value,
                command.actor.actor_id,
                command.reason,
                command.authorization_ref,
                command.consumer_id or None,
                command.partition_key or None,
            ),
        )

    def create_reconcile_plan(self, command: CreateReconcilePlan) -> Mapping[str, Any]:
        return self._call_json(
            "SELECT public.hermes_create_reconcile_plan(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                command.command_id,
                command.idempotency_key,
                command.plan_id,
                list(command.finding_ids),
                list(command.repair_actions),
                command.dry_run,
                command.actor.actor_type.value,
                command.actor.actor_id,
                command.reason,
                command.authorization_ref,
                command.expires_at,
            ),
        )

    def apply_reconcile_plan(self, command: ApplyReconcilePlan) -> Mapping[str, Any]:
        return self._call_json(
            "SELECT public.hermes_apply_reconcile_plan(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                command.command_id,
                command.idempotency_key,
                command.plan_id,
                command.expected_plan_version,
                command.actor.actor_type.value,
                command.actor.actor_id,
                command.reason,
                command.authorization_ref,
                command.fault_point or None,
            ),
        )

    def seed_event(self, event_id: str, project_id: str, sequence_payload: Mapping[str, Any], event_type: str = "test.event") -> int:
        command_id = "cmd-" + event_id
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO public.command_receipts(
                    command_id,project_id,command_type,idempotency_key,
                    request_hash,status,result,completed_at
                ) VALUES (%s,%s,'test.seed_event',%s,'seed','APPLIED','{}',now())
                """,
                (command_id, project_id, command_id),
            )
            row = connection.execute(
                """
                INSERT INTO public.event_log(
                    event_id,event_type,schema_version,producer_type,producer_id,
                    project_id,partition_key,command_id,correlation_id,payload
                ) VALUES (%s,%s,'1.0','control_plane','seed',%s,%s,%s,%s,%s)
                RETURNING sequence
                """,
                (
                    event_id,
                    event_type,
                    project_id,
                    project_id,
                    command_id,
                    command_id,
                    Jsonb(dict(sequence_payload)),
                ),
            ).fetchone()
            connection.execute(
                """
                INSERT INTO public.outbox_messages(message_id,event_id,topic,partition_key,sequence,payload)
                VALUES (%s,%s,'hermes.runtime.events',%s,%s,%s)
                """,
                ("msg-" + event_id, event_id, project_id, row[0], Jsonb(dict(sequence_payload))),
            )
            return int(row[0])

    def _call_json(self, sql: str, params: tuple) -> Mapping[str, Any]:
        try:
            with self._connect() as connection:
                row = connection.execute(sql, params).fetchone()
                return dict(row[0])
        except psycopg.errors.RaiseException as exc:
            raise CommandRejected(exc.diag.message_primary)
