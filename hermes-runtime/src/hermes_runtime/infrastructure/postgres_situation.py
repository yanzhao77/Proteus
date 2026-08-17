import hashlib
import json
from enum import Enum
from typing import Any, Dict, Mapping, Optional

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.application.situations import AnalyzeSituationEvent, ResolveSituation
from hermes_runtime.domain.situation import (
    CANONICALIZATION_VERSION,
    RULE_SET_VERSION,
    SituationRejected,
    TriggerFact,
    canonical_fingerprint,
    classify_trigger,
)
from hermes_runtime.infrastructure.postgres import PostgresRuntimeStore
from hermes_runtime.infrastructure.postgres_delivery import (
    envelope_to_mapping,
    event_envelope_from_mapping,
)


class SituationFaultPoint(str, Enum):
    AFTER_CONTEXT_BEFORE_SITUATION = "after_context_before_situation"
    AFTER_SITUATION_BEFORE_EVENT = "after_situation_before_event"
    AFTER_EVENT_BEFORE_OUTBOX = "after_event_before_outbox"
    AFTER_OUTBOX_BEFORE_INBOX = "after_outbox_before_inbox"
    AFTER_INBOX_BEFORE_CHECKPOINT = "after_inbox_before_checkpoint"
    AFTER_OLD_SUPERSEDED_BEFORE_NEW = "after_old_superseded_before_new"


class PostgresSituationStore(PostgresRuntimeStore):
    def __init__(self, dsn: str, consumer_id: str = "situation-analyzer") -> None:
        super().__init__(dsn)
        self._consumer_id = consumer_id
        self._situation_fault: Optional[SituationFaultPoint] = None

    def fail_situation_once(self, point: SituationFaultPoint) -> None:
        self._situation_fault = point

    def reset_for_test(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """TRUNCATE situation_versions, situations, analysis_contexts,
                   delivery_operational_alerts, delivery_metric_counters,
                   local_transport_publications, consumer_quarantine,
                   consumer_pending_gaps, outbox_redrive_records,
                   outbox_delivery_dlq, outbox_delivery_attempts,
                   consumer_checkpoints, consumer_effects, consumer_inbox,
                   audit_records, outbox_messages, event_log,
                   event_partition_sequences, command_receipts,
                   resource_reconcile_records, resource_settlement_usage,
                   resource_settlements, resource_usage_amounts,
                   resource_usage_records, resource_reservation_amounts,
                   resource_reservations, resource_preparations,
                   resource_balances, resource_accounts,
                   project_budget_facts, project_policy_decision_facts,
                   project_evidence_facts, project_gate_decision_facts,
                   project_transition_records, feedback_records,
                   task_dependencies, work_graph_edges, project_graph_versions,
                   verification_check_results, verification_evidence,
                   verification_results, evidence, completion_claims, artifacts,
                   verification_plan_checks, verification_plans, agent_runs,
                   verifier_identities, tasks, projects
                   RESTART IDENTITY CASCADE"""
            )

    def analyze_event(
        self, command: AnalyzeSituationEvent
    ) -> Mapping[str, Any]:
        raw = dict(command.raw_envelope)
        try:
            envelope = event_envelope_from_mapping(raw)
            self._validate_task_binding(envelope)
            classification = classify_trigger(TriggerFact(
                envelope.project_id,
                envelope.event_type,
                envelope.schema_version,
                envelope.task_id or self._payload_task_id(envelope),
                envelope.payload,
            ))
        except CommandRejected:
            raise
        except SituationRejected as exc:
            if str(exc) != "SITUATION_CLASSIFICATION_UNSUPPORTED":
                raise CommandRejected(str(exc))
            # P6 (ADR-0073): catalog events whose classification rule is not
            # yet implemented (policy.evaluated, agent.stalled,
            # resource.missing) are quarantine-and-continue: the classifier
            # still fails closed (pure function), but the consumer must not
            # die and stall the partition. Treating them as non-triggers
            # advances the consumer checkpoint so later events (e.g.
            # feedback.created) can still be processed.
            classification = None

        if classification is None:
            parameters = self._parameters(
                envelope, raw, None, command.expected_situation_version
            )
        else:
            parameters = self._parameters(
                envelope, raw, classification, command.expected_situation_version
            )

        fault = self._situation_fault
        self._situation_fault = None
        parameters = parameters[:-1] + (fault.value if fault else None,)
        try:
            parked = self._park_gap(envelope, raw)
            if parked is not None:
                return parked
            with self._connect(row_factory=dict_row) as connection:
                row = connection.execute(
                    """SELECT public.hermes_apply_situation_effect(
                       %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                       %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                       ) AS result""",
                    parameters,
                ).fetchone()
                result = dict(row["result"])
            self._drain_partition(envelope.partition_key)
            return result
        except psycopg.errors.RaiseException as exc:
            code = exc.diag.message_primary
            if code.startswith("INJECTED_SITUATION_CRASH_"):
                raise RuntimeError("injected situation crash: " + code)
            raise CommandRejected(code)

    def _park_gap(self, envelope, raw: Mapping[str, Any]):
        with self._connect(row_factory=dict_row) as connection:
            duplicate = connection.execute(
                """SELECT processing_result FROM consumer_inbox
                   WHERE consumer_id=%s AND event_id=%s""",
                (self._consumer_id, envelope.event_id),
            ).fetchone()
            if duplicate:
                return dict(duplicate["processing_result"])
            checkpoint = connection.execute(
                """SELECT last_sequence FROM consumer_checkpoints
                   WHERE consumer_id=%s AND partition_key=%s""",
                (self._consumer_id, envelope.partition_key),
            ).fetchone()
            checkpoint = checkpoint["last_sequence"] if checkpoint else 0
            if envelope.sequence <= checkpoint:
                return {
                    "classification": "LATE_QUARANTINED",
                    "event_id": envelope.event_id,
                }
            if envelope.sequence == checkpoint + 1:
                return None
            outcome = connection.execute(
                """SELECT public.hermes_consumer_park_gap(
                   %s,%s,%s,%s,%s,100) AS outcome""",
                (self._consumer_id, envelope.event_id, envelope.partition_key,
                 envelope.sequence, Jsonb(raw)),
            ).fetchone()["outcome"]
            return {
                "classification": outcome,
                "event_id": envelope.event_id,
                "checkpoint": checkpoint,
            }

    def _drain_partition(self, partition_key: str) -> None:
        while True:
            with self._connect(row_factory=dict_row) as connection:
                row = connection.execute(
                    """SELECT p.raw_envelope FROM consumer_pending_gaps p
                       JOIN consumer_checkpoints c
                         ON c.consumer_id=p.consumer_id
                        AND c.partition_key=p.partition_key
                       WHERE p.consumer_id=%s AND p.partition_key=%s
                         AND p.status='PENDING'
                         AND p.sequence=c.last_sequence+1""",
                    (self._consumer_id, partition_key),
                ).fetchone()
            if not row:
                return
            self.analyze_event(AnalyzeSituationEvent(dict(row["raw_envelope"])))

    def analyze_logged_event(
        self, event_id: str, expected_situation_version: Optional[int] = None
    ) -> Mapping[str, Any]:
        with self._connect() as connection:
            envelope = connection.execute(
                "SELECT public.hermes_event_envelope(%s)", (event_id,)
            ).fetchone()[0]
        if envelope is None:
            raise CommandRejected("SITUATION_CONTEXT_UNAVAILABLE")
        return self.analyze_event(AnalyzeSituationEvent(
            envelope, expected_situation_version
        ))

    def resolve_situation(self, command: ResolveSituation) -> Mapping[str, Any]:
        request_hash = self._hash_value({
            "situation_id": command.situation_id,
            "project_id": command.project_id,
            "expected_version": command.expected_version,
            "actor_type": command.actor_type,
            "actor_id": command.actor_id,
            "reason": command.reason,
        })
        try:
            with self._connect(row_factory=dict_row) as connection:
                inserted = connection.execute(
                    """INSERT INTO command_receipts(
                       command_id,project_id,command_type,idempotency_key,
                       request_hash,status,result)
                       VALUES (%s,%s,'situation.resolve',%s,%s,'PROCESSING','{}')
                       ON CONFLICT DO NOTHING RETURNING command_id""",
                    (command.command_id, command.project_id,
                     command.idempotency_key, request_hash),
                ).fetchone()
                if not inserted:
                    stored = connection.execute(
                        """SELECT request_hash,status,result FROM command_receipts
                           WHERE project_id=%s AND command_type='situation.resolve'
                             AND idempotency_key=%s FOR UPDATE""",
                        (command.project_id, command.idempotency_key),
                    ).fetchone()
                    if not stored or stored["request_hash"] != request_hash:
                        raise CommandRejected("IDEMPOTENCY_CONFLICT")
                    if stored["status"] == "APPLIED":
                        return dict(stored["result"])
                    raise CommandRejected("COMMAND_IN_PROGRESS")
                result = connection.execute(
                    """SELECT public.hermes_resolve_situation(
                       %s,%s,%s,%s,%s,%s,%s) AS result""",
                    (command.situation_id, command.project_id,
                     command.expected_version, command.command_id,
                     command.actor_type, command.actor_id, command.reason),
                ).fetchone()["result"]
                connection.execute(
                    """UPDATE command_receipts SET status='APPLIED',result=%s,
                       completed_at=now() WHERE command_id=%s""",
                    (Jsonb(result), command.command_id),
                )
                return dict(result)
        except psycopg.errors.RaiseException as exc:
            raise CommandRejected(exc.diag.message_primary)

    @staticmethod
    def _payload_task_id(envelope) -> Optional[str]:
        payload = envelope.payload
        value = payload.get("task_id") or payload.get("source_task_id")
        if value:
            return str(value)
        changes = payload.get("ready_state_changes") or payload.get("readiness_changes")
        if isinstance(changes, (list, tuple)):
            ready = sorted({
                str(item.get("task_id")) for item in changes
                if isinstance(item, Mapping)
                and item.get("task_id") is not None
                and str(item.get("to_state") or item.get("state")) == "READY"
            })
            if len(ready) == 1:
                return ready[0]
        return None

    @staticmethod
    def _validate_task_binding(envelope) -> None:
        if envelope.event_type != "task.readiness_recomputed" or not envelope.task_id:
            return
        changes = envelope.payload.get("ready_state_changes") or ()
        task_ids = {
            str(item.get("task_id")) for item in changes
            if isinstance(item, Mapping) and item.get("task_id") is not None
        }
        if envelope.task_id not in task_ids:
            raise CommandRejected("SITUATION_FACT_TASK_MISMATCH")

    def _parameters(
        self, envelope, raw: Mapping[str, Any], classification,
        expected_version: Optional[int],
    ):
        trigger_hash = "sha256:" + hashlib.sha256(
            json.dumps(envelope_to_mapping(envelope), sort_keys=True,
                       separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        ).hexdigest()
        if classification is None:
            return (
                self._consumer_id, envelope.event_id, envelope.partition_key,
                envelope.sequence, envelope.schema_version, Jsonb(raw), trigger_hash,
                False, None, None, None, None, None, [], [], [], [], None,
                RULE_SET_VERSION, CANONICALIZATION_VERSION, None, None,
                [], [], [], None, expected_version, None,
            )

        task_id = envelope.task_id or self._payload_task_id(envelope)
        payload = envelope.payload
        project_version_ref = self._version_ref("project", payload.get("project_version"))
        task_version_ref = self._version_ref("task", payload.get("task_version"))
        verification_refs = self._refs(payload.get("verification_id"))
        budget_refs = []
        if payload.get("account_id") is not None and payload.get("entity_version") is not None:
            budget_refs = ["{}:{}".format(
                payload["account_id"], payload["entity_version"]
            )]
        graph_ref = self._version_ref("work_graph", payload.get("graph_version"))
        return (
            self._consumer_id, envelope.event_id, envelope.partition_key,
            envelope.sequence, envelope.schema_version, Jsonb(raw), trigger_hash,
            True, classification.situation_type.value, task_id,
            classification.failure_type, classification.severity.value,
            classification.confidence_basis_points,
            list(classification.artifact_refs),
            list(classification.affected_components),
            list(classification.context_refs), list(classification.constraints),
            canonical_fingerprint(envelope.project_id, classification, task_id),
            RULE_SET_VERSION, CANONICALIZATION_VERSION,
            project_version_ref, task_version_ref, verification_refs,
            budget_refs, [], graph_ref, expected_version, None,
        )

    @staticmethod
    def _refs(value: object):
        if value is None:
            return []
        values = value if isinstance(value, (list, tuple)) else (value,)
        return sorted({str(item) for item in values})

    @staticmethod
    def _version_ref(kind: str, value: object) -> Optional[str]:
        return None if value is None else "{}:{}".format(kind, value)
