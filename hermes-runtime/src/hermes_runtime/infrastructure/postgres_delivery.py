import json
import uuid
from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from hermes_runtime.application.delivery import PublishFailure
from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.domain.models import (
    ActorType,
    CommandReceipt,
    EventEnvelope,
    OutboxClaim,
    PublishResult,
    RedriveOutbox,
)
from hermes_runtime.infrastructure.postgres import PostgresRuntimeStore


REQUIRED_ENVELOPE_FIELDS = frozenset(
    {
        "event_id",
        "event_type",
        "schema_version",
        "occurred_at",
        "recorded_at",
        "producer",
        "project_id",
        "partition_key",
        "sequence",
        "idempotency_key",
        "payload",
    }
)


def event_envelope_from_mapping(data: Mapping[str, Any]) -> EventEnvelope:
    missing = sorted(REQUIRED_ENVELOPE_FIELDS.difference(data))
    if missing:
        raise CommandRejected("EVENT_SCHEMA_REQUIRED_FIELD_MISSING", ",".join(missing))
    major = str(data["schema_version"]).split(".", 1)[0]
    if major != "1":
        raise CommandRejected("EVENT_SCHEMA_MAJOR_UNSUPPORTED", major)
    producer = data["producer"]
    if not isinstance(producer, Mapping) or not producer.get("type") or not producer.get("id"):
        raise CommandRejected("EVENT_SCHEMA_PRODUCER_INVALID")
    if not isinstance(data["payload"], Mapping):
        raise CommandRejected("EVENT_SCHEMA_PAYLOAD_INVALID")
    return EventEnvelope(
        str(data["event_id"]),
        str(data["event_type"]),
        str(data["schema_version"]),
        str(data["occurred_at"]),
        str(data["recorded_at"]),
        {"type": str(producer["type"]), "id": str(producer["id"])},
        str(data["project_id"]),
        str(data["partition_key"]),
        int(data["sequence"]),
        str(data["idempotency_key"]),
        dict(data["payload"]),
        data.get("correlation_id"),
        data.get("causation_id"),
        data.get("trace_id"),
        data.get("task_id"),
        data.get("run_id"),
        str(data.get("classification", "INTERNAL")),
    )


def envelope_to_mapping(envelope: EventEnvelope) -> Dict[str, Any]:
    return {
        "event_id": envelope.event_id,
        "event_type": envelope.event_type,
        "schema_version": envelope.schema_version,
        "occurred_at": envelope.occurred_at,
        "recorded_at": envelope.recorded_at,
        "producer": dict(envelope.producer),
        "project_id": envelope.project_id,
        "partition_key": envelope.partition_key,
        "sequence": envelope.sequence,
        "idempotency_key": envelope.idempotency_key,
        "payload": dict(envelope.payload),
        "correlation_id": envelope.correlation_id,
        "causation_id": envelope.causation_id,
        "trace_id": envelope.trace_id,
        "task_id": envelope.task_id,
        "run_id": envelope.run_id,
        "classification": envelope.classification,
    }


class PostgresDeliveryStore(PostgresRuntimeStore):
    DELIVERY_TABLES = (
        "delivery_operational_alerts",
        "delivery_metric_counters",
        "local_transport_publications",
        "consumer_quarantine",
        "consumer_pending_gaps",
        "outbox_redrive_records",
        "outbox_delivery_dlq",
        "outbox_delivery_attempts",
    )

    def reset_for_test(self) -> None:
        with self._connect() as connection:
            connection.execute(
                "TRUNCATE {} RESTART IDENTITY CASCADE".format(
                    ", ".join(self.DELIVERY_TABLES + (
                        "consumer_checkpoints", "consumer_effects", "consumer_inbox",
                        "audit_records", "outbox_messages", "event_log",
                        "event_partition_sequences", "command_receipts",
                        "verification_evidence", "verification_results", "evidence",
                        "completion_claims", "artifacts", "verifier_identities", "tasks",
                    ))
                )
            )

    def claim_outbox(
        self, owner: str, now: datetime, lease_seconds: int,
        batch_size: int, max_attempts: int
    ) -> Tuple[OutboxClaim, ...]:
        with self._connect(row_factory=dict_row) as connection:
            rows = connection.execute(
                "SELECT * FROM public.hermes_claim_outbox(%s, %s, %s, %s, %s)",
                (owner, now, lease_seconds, batch_size, max_attempts),
            ).fetchall()
        return tuple(
            OutboxClaim(
                row["message_id"], row["event_id"], row["topic"],
                row["partition_key"], int(row["sequence"]), row["claim_token"],
                int(row["attempt_count"]), event_envelope_from_mapping(row["envelope"]),
            )
            for row in rows
        )

    def mark_outbox_published(
        self, claim: OutboxClaim, owner: str, now: datetime
    ) -> bool:
        with self._connect() as connection:
            return bool(connection.execute(
                "SELECT public.hermes_mark_outbox_published(%s, %s, %s, %s)",
                (claim.message_id, owner, claim.claim_token, now),
            ).fetchone()[0])

    def mark_outbox_failure(
        self, claim: OutboxClaim, owner: str, now: datetime,
        retryable: bool, category: str, message: str,
        next_attempt_at: datetime, max_attempts: int
    ) -> str:
        with self._connect() as connection:
            return connection.execute(
                "SELECT public.hermes_mark_outbox_failure(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (claim.message_id, owner, claim.claim_token, now, retryable,
                 category, message, next_attempt_at, max_attempts),
            ).fetchone()[0]

    def redrive_outbox(self, command: RedriveOutbox, now: datetime) -> CommandReceipt:
        envelope = command.envelope
        request_hash = self._redrive_hash(command)
        if envelope.actor is None or envelope.actor.actor_type not in {
            ActorType.CONTROL_PLANE, ActorType.SYSTEM_OPERATOR
        }:
            self._persist_rejection(
                envelope, request_hash, "REDRIVE_NOT_AUTHORIZED", ""
            )
            raise CommandRejected("REDRIVE_NOT_AUTHORIZED")
        if not envelope.reason.strip() or not command.authorization_ref.strip():
            self._persist_rejection(
                envelope, request_hash, "REDRIVE_AUTHORIZATION_REQUIRED", ""
            )
            raise CommandRejected("REDRIVE_AUTHORIZATION_REQUIRED")
        if envelope.command_type != "outbox.redrive":
            self._persist_rejection(
                envelope, request_hash, "REDRIVE_COMMAND_REQUIRED", ""
            )
            raise CommandRejected("REDRIVE_COMMAND_REQUIRED")
        try:
            with self._connect() as connection:
                existing = self._begin_command(connection, envelope, request_hash)
                if existing:
                    return existing
                event_id = connection.execute(
                    "SELECT public.hermes_redrive_outbox(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (command.message_id, envelope.expected_version, envelope.command_id,
                     envelope.actor.actor_type.value, envelope.actor.actor_id,
                     envelope.reason, command.authorization_ref,
                     command.cause_resolved, now),
                ).fetchone()[0]
                receipt = CommandReceipt(
                    envelope.command_id, "APPLIED", "OUTBOX_REDRIVEN",
                    envelope.expected_version + 1, (event_id,),
                    {"message_id": command.message_id, "event_id": event_id},
                )
                self._complete_command(connection, envelope, receipt)
                return receipt
        except psycopg.errors.RaiseException as exc:
            rejected = CommandRejected(exc.diag.message_primary)
            self._persist_rejection(
                envelope, request_hash, rejected.code, rejected.detail
            )
            raise rejected

    def _redrive_hash(self, command: RedriveOutbox) -> str:
        envelope = command.envelope
        return self._hash_value({
            "command_type": envelope.command_type,
            "project_id": envelope.project_id,
            "expected_version": envelope.expected_version,
            "actor": {"type": envelope.actor.actor_type.value, "id": envelope.actor.actor_id},
            "reason": envelope.reason,
            "message_id": command.message_id,
            "authorization_ref": command.authorization_ref,
            "cause_resolved": command.cause_resolved,
        })

    def delivery_metrics(self, now: datetime) -> Mapping[str, int]:
        with self._connect(row_factory=dict_row) as connection:
            return dict(connection.execute(
                """
                SELECT
                  count(*) FILTER (WHERE status = 'PENDING')::int AS pending,
                  count(*) FILTER (WHERE status = 'LEASED')::int AS leased,
                  count(*) FILTER (WHERE status = 'LEASED' AND lease_expires_at <= %s)::int AS expired_leases,
                  count(*) FILTER (WHERE status = 'PUBLISHED')::int AS published,
                  count(*) FILTER (WHERE status = 'DEAD_LETTERED')::int AS dead_lettered,
                  COALESCE(EXTRACT(EPOCH FROM (%s - min(created_at) FILTER (WHERE status = 'PENDING')))::int, 0) AS oldest_pending_seconds,
                  (SELECT count(*)::int FROM consumer_pending_gaps WHERE status = 'PENDING') AS pending_gaps,
                  (SELECT count(*)::int FROM consumer_quarantine WHERE status = 'OPEN') AS quarantine,
                  (SELECT count(*)::int FROM delivery_operational_alerts WHERE resolved_at IS NULL) AS anomalies,
                  (SELECT count(*)::int FROM outbox_delivery_attempts WHERE outcome = 'CLAIMED') AS relay_claimed,
                  (SELECT count(*)::int FROM outbox_delivery_attempts WHERE outcome = 'PUBLISHED') AS relay_published,
                  (SELECT count(*)::int FROM outbox_delivery_attempts WHERE outcome = 'RETRY_SCHEDULED') AS relay_retried,
                  (SELECT count(*)::int FROM outbox_delivery_attempts WHERE outcome = 'DEAD_LETTERED') AS relay_dead_lettered,
                  COALESCE((SELECT metric_value::int FROM delivery_metric_counters WHERE metric_name = 'consumer_duplicate'), 0) AS consumer_duplicates,
                  (SELECT count(*)::int FROM outbox_redrive_records) AS redrive_success,
                  (SELECT count(*)::int FROM command_receipts
                   WHERE command_type = 'outbox.redrive'
                     AND status = 'REJECTED') AS redrive_failure,
                  (SELECT count(*)::int FROM consumer_quarantine WHERE failure_category IN ('SCHEMA','UNSUPPORTED_SCHEMA','UNKNOWN_CRITICAL_VALUE')) AS schema_quarantine,
                  COALESCE((SELECT sum(
                      (SELECT max(e.sequence) FROM event_log e WHERE e.partition_key = c.partition_key)
                      - c.last_sequence
                  )::int FROM consumer_checkpoints c), 0) AS checkpoint_lag
                FROM outbox_messages
                """, (now, now)
            ).fetchone())

    def reconcile_gap_timeouts(self, now: datetime, max_age_seconds: int) -> int:
        if max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be positive")
        with self._connect() as connection:
            rows = connection.execute(
                """
                UPDATE consumer_pending_gaps
                SET status = 'RECONCILE_REQUIRED', last_seen_at = %s
                WHERE status = 'PENDING'
                  AND first_seen_at <= %s - make_interval(secs => %s)
                RETURNING consumer_id, event_id, partition_key, sequence,
                          raw_envelope
                """,
                (now, now, max_age_seconds),
            ).fetchall()
            for consumer_id, event_id, partition_key, sequence, raw_envelope in rows:
                connection.execute(
                    """
                    SELECT public.hermes_consumer_quarantine(
                        %s,%s,%s,%s,%s,'GAP_TIMEOUT',%s
                    )
                    """,
                    (consumer_id, event_id, partition_key, sequence,
                     Jsonb(raw_envelope),
                     "missing predecessor before sequence {}".format(sequence)),
                )
                connection.execute(
                    """
                    INSERT INTO delivery_operational_alerts(
                        alert_id, category, consumer_id, event_id,
                        partition_key, detail
                    ) VALUES (%s, 'GAP_TIMEOUT', %s, %s, %s, %s)
                    """,
                    ("alert-" + str(uuid.uuid4()), consumer_id, event_id,
                     partition_key, "missing predecessor before sequence {}".format(sequence)),
                )
                connection.execute(
                    """
                    INSERT INTO audit_records(
                        audit_id, project_id, source_command_id, actor_type,
                        actor_id, action, outcome, reason_code, detail
                    ) VALUES (%s,%s,%s,'control_plane','delivery-reconcile',
                              'consumer.gap.reconcile','REJECTED',
                              'GAP_TIMEOUT',%s)
                    ON CONFLICT (source_command_id, reason_code) DO NOTHING
                    """,
                    ("audit-" + str(uuid.uuid4()), partition_key,
                     "gap-timeout-{}-{}".format(consumer_id, event_id),
                     "missing predecessor before sequence {}".format(sequence)),
                )
            return len(rows)

    def reconcile_delivery(self, now: datetime) -> Mapping[str, int]:
        with self._connect() as connection:
            checkpoint_rows = connection.execute(
                """
                SELECT consumer_id, partition_key, last_sequence
                FROM consumer_checkpoints
                FOR UPDATE
                """
            ).fetchall()
            for consumer_id, partition_key, checkpoint in checkpoint_rows:
                next_sequence = checkpoint + 1
                while connection.execute(
                    """
                    SELECT 1 FROM consumer_inbox
                    WHERE consumer_id = %s AND partition_key = %s
                      AND sequence = %s
                    """,
                    (consumer_id, partition_key, next_sequence),
                ).fetchone():
                    next_sequence += 1
                contiguous = next_sequence - 1
                if contiguous > checkpoint:
                    connection.execute(
                        """
                        UPDATE consumer_checkpoints
                        SET last_sequence = %s, updated_at = now()
                        WHERE consumer_id = %s AND partition_key = %s
                          AND last_sequence = %s
                        """,
                        (contiguous, consumer_id, partition_key, checkpoint),
                    )
                    connection.execute(
                        """
                        INSERT INTO audit_records(
                            audit_id, project_id, source_command_id, actor_type,
                            actor_id, action, outcome, reason_code, detail
                        ) VALUES (%s, %s, %s, 'control_plane',
                                  'delivery-reconcile', 'consumer.checkpoint.reconcile',
                                  'APPLIED', 'CHECKPOINT_CONTIGUOUSLY_ADVANCED', %s)
                        ON CONFLICT (source_command_id, reason_code) DO NOTHING
                        """,
                        (
                            "audit-" + str(uuid.uuid4()),
                            partition_key,
                            "reconcile-{}-{}-{}".format(
                                consumer_id, partition_key, contiguous
                            ),
                            "{}:{}->{}".format(
                                consumer_id, checkpoint, contiguous
                            ),
                        ),
                    )
            connection.execute(
                """
                INSERT INTO delivery_operational_alerts(
                    alert_id, category, consumer_id, event_id, partition_key, detail
                )
                SELECT 'alert-' || gen_random_uuid()::text, 'EVENT_WITHOUT_OUTBOX',
                       NULL, e.event_id, e.partition_key, 'immutable Event lacks Outbox'
                FROM event_log e LEFT JOIN outbox_messages o ON o.event_id = e.event_id
                WHERE o.event_id IS NULL
                  AND NOT EXISTS (SELECT 1 FROM delivery_operational_alerts a
                                  WHERE a.category = 'EVENT_WITHOUT_OUTBOX'
                                    AND a.event_id = e.event_id AND a.resolved_at IS NULL)
                """
            )
            connection.execute(
                """
                INSERT INTO delivery_operational_alerts(
                    alert_id, category, consumer_id, event_id, partition_key, detail
                )
                SELECT 'alert-' || gen_random_uuid()::text,
                       'PUBLISHED_UNCONSUMED', c.consumer_id, o.event_id,
                       o.partition_key, 'published Event is ahead of Consumer Inbox'
                FROM consumer_checkpoints c
                JOIN outbox_messages o
                  ON o.partition_key = c.partition_key AND o.status = 'PUBLISHED'
                 AND o.sequence > c.last_sequence
                LEFT JOIN consumer_inbox i
                  ON i.consumer_id = c.consumer_id AND i.event_id = o.event_id
                WHERE i.event_id IS NULL
                  AND NOT EXISTS (
                    SELECT 1 FROM delivery_operational_alerts a
                    WHERE a.category = 'PUBLISHED_UNCONSUMED'
                      AND a.consumer_id = c.consumer_id
                      AND a.event_id = o.event_id AND a.resolved_at IS NULL
                  )
                """
            )
            connection.execute(
                """
                INSERT INTO delivery_operational_alerts(
                    alert_id, category, consumer_id, event_id, partition_key, detail
                )
                SELECT 'alert-' || gen_random_uuid()::text, 'CHECKPOINT_LAG',
                       i.consumer_id, NULL, i.partition_key,
                       'Inbox contiguous prefix is ahead of checkpoint'
                FROM consumer_inbox i
                JOIN consumer_checkpoints c USING (consumer_id, partition_key)
                GROUP BY i.consumer_id, i.partition_key, c.last_sequence
                HAVING max(i.sequence) > c.last_sequence
                  AND NOT EXISTS (
                    SELECT 1 FROM delivery_operational_alerts a
                    WHERE a.category = 'CHECKPOINT_LAG'
                      AND a.consumer_id = i.consumer_id
                      AND a.partition_key = i.partition_key
                      AND a.resolved_at IS NULL
                  )
                """
            )
        return self.delivery_metrics(now)

    def event_envelope(self, event_id: str) -> EventEnvelope:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT public.hermes_event_envelope(%s)", (event_id,)
            ).fetchone()
        if not row or row[0] is None:
            raise CommandRejected("EVENT_NOT_FOUND")
        return event_envelope_from_mapping(row[0])


class PostgresLocalPublisher:
    """Durable local transport adapter used for one-shot runtime and PG tests."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._failures: List[PublishFailure] = []

    def fail_next(self, category: str, retryable: bool, message: str = "injected") -> None:
        self._failures.append(PublishFailure(category, message, retryable))

    def publish(self, envelope: EventEnvelope) -> PublishResult:
        if self._failures:
            raise self._failures.pop(0)
        publication_id = "pub-" + str(uuid.uuid4())
        with psycopg.connect(self._dsn) as connection:
            connection.execute(
                """
                INSERT INTO local_transport_publications(
                    publication_id, event_id, partition_key, sequence, envelope
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                (publication_id, envelope.event_id, envelope.partition_key,
                 envelope.sequence, Jsonb(envelope_to_mapping(envelope))),
            )
        return PublishResult(publication_id)


class PostgresContiguousConsumer:
    def __init__(self, dsn: str, consumer_id: str, gap_limit: int = 100) -> None:
        self._dsn = dsn
        self._consumer_id = consumer_id
        self._gap_limit = gap_limit
        self._fault: Optional[str] = None

    def fail_once(self, point: str) -> None:
        self._fault = point

    def _trigger(self, point: str) -> None:
        if self._fault == point:
            self._fault = None
            raise RuntimeError("injected consumer crash: " + point)

    def receive(self, raw_envelope: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            envelope = event_envelope_from_mapping(raw_envelope)
            self._validate_critical_values(envelope)
        except CommandRejected as exc:
            self._quarantine(raw_envelope, exc.code, exc.detail)
            return {"classification": "QUARANTINED", "reason": exc.code}

        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            connection.execute(
                """
                INSERT INTO consumer_checkpoints(consumer_id, partition_key, last_sequence)
                VALUES (%s, %s, 0) ON CONFLICT DO NOTHING
                """, (self._consumer_id, envelope.partition_key)
            )
            checkpoint = connection.execute(
                """
                SELECT last_sequence FROM consumer_checkpoints
                WHERE consumer_id = %s AND partition_key = %s FOR UPDATE
                """, (self._consumer_id, envelope.partition_key)
            ).fetchone()["last_sequence"]
            duplicate = connection.execute(
                """
                SELECT processing_result FROM consumer_inbox
                WHERE consumer_id = %s AND event_id = %s
                """, (self._consumer_id, envelope.event_id)
            ).fetchone()
            if duplicate:
                connection.execute(
                    "SELECT public.hermes_increment_delivery_metric('consumer_duplicate')"
                )
                return dict(duplicate["processing_result"])
            if envelope.sequence <= checkpoint:
                self._insert_quarantine(
                    connection, raw_envelope, envelope, "LATE_EVENT",
                    "sequence is at or below checkpoint without Inbox record"
                )
                return {"classification": "LATE_QUARANTINED"}
            if envelope.sequence > checkpoint + 1:
                classification = connection.execute(
                    """
                    SELECT public.hermes_consumer_park_gap(
                        %s,%s,%s,%s,%s,%s
                    ) AS classification
                    """,
                    (self._consumer_id, envelope.event_id, envelope.partition_key,
                     envelope.sequence, Jsonb(dict(raw_envelope)), self._gap_limit),
                ).fetchone()["classification"]
                return {"classification": classification, "checkpoint": checkpoint}
            result = self._apply_next(connection, envelope, raw_envelope)
            self._drain(connection, envelope.partition_key)
            return result

    def replay(self, store: PostgresDeliveryStore, event_id: str) -> Mapping[str, Any]:
        return self.receive(envelope_to_mapping(store.event_envelope(event_id)))

    def _apply_next(self, connection, envelope, raw_envelope):
        result = {"classification": "APPLIED", "event_id": envelope.event_id}
        fault = self._fault
        self._fault = None
        try:
            outcome = connection.execute(
                """
                SELECT public.hermes_consumer_commit_next(
                    %s,%s,%s,%s,%s,%s,%s,%s
                ) AS outcome
                """,
                (self._consumer_id, envelope.event_id, envelope.partition_key,
                 envelope.sequence, envelope.schema_version, Jsonb(result),
                 Jsonb(dict(raw_envelope)), fault),
            ).fetchone()["outcome"]
        except psycopg.errors.RaiseException as exc:
            if exc.diag.message_primary.startswith("INJECTED_CONSUMER_CRASH_"):
                raise RuntimeError("injected consumer crash: " + str(fault))
            raise
        if outcome == "DUPLICATE":
            stored = connection.execute(
                """SELECT processing_result FROM consumer_inbox
                   WHERE consumer_id = %s AND event_id = %s""",
                (self._consumer_id, envelope.event_id),
            ).fetchone()
            return dict(stored["processing_result"])
        return result

    def _drain(self, connection, partition_key: str) -> None:
        while True:
            checkpoint = connection.execute(
                """SELECT last_sequence FROM consumer_checkpoints
                   WHERE consumer_id = %s AND partition_key = %s FOR UPDATE""",
                (self._consumer_id, partition_key),
            ).fetchone()["last_sequence"]
            parked = connection.execute(
                """
                SELECT raw_envelope FROM consumer_pending_gaps
                WHERE consumer_id = %s AND partition_key = %s
                  AND sequence = %s AND status = 'PENDING'
                FOR UPDATE
                """, (self._consumer_id, partition_key, checkpoint + 1)
            ).fetchone()
            if not parked:
                return
            envelope = event_envelope_from_mapping(parked["raw_envelope"])
            self._validate_critical_values(envelope)
            self._apply_next(connection, envelope, parked["raw_envelope"])

    @staticmethod
    def _validate_critical_values(envelope: EventEnvelope) -> None:
        for field in ("state", "from_state", "to_state", "new_state"):
            value = envelope.payload.get(field)
            if value is not None and value not in {
                "NEW", "READY", "ASSIGNED", "RUNNING", "COMPLETION_CLAIMED",
                "WAITING", "VERIFYING", "PASSED", "FAILED", "RETRYING",
                "BLOCKED", "CANCELLED", "SUPERSEDED", "CREATED", "INTAKE",
                "DISCOVERY", "PLANNING", "DESIGNING", "IMPLEMENTING",
                "HARDENING", "PACKAGING", "DELIVERING", "ACCEPTED",
                "WAITING_FOR_HUMAN", "WAITING_FOR_RESOURCE", "PAUSED",
                "RECOVERING",
            }:
                raise CommandRejected("UNKNOWN_CRITICAL_EVENT_VALUE", str(value))

    def _quarantine(self, raw, category, detail):
        event_id = str(raw.get("event_id", "invalid-" + str(uuid.uuid4())))
        with psycopg.connect(self._dsn) as connection:
            self._insert_quarantine(connection, raw, None, self._category(category), detail)

    def _insert_quarantine(self, connection, raw, envelope, category, detail):
        event_id = envelope.event_id if envelope else str(raw.get("event_id", "invalid"))
        partition = envelope.partition_key if envelope else raw.get("partition_key")
        sequence = envelope.sequence if envelope else raw.get("sequence")
        connection.execute(
            """
            SELECT public.hermes_consumer_quarantine(%s,%s,%s,%s,%s,%s,%s)
            """,
            (self._consumer_id, event_id, partition, sequence,
             Jsonb(dict(raw)), category, detail or category),
        )

    @staticmethod
    def _category(code: str) -> str:
        if code == "EVENT_SCHEMA_MAJOR_UNSUPPORTED":
            return "UNSUPPORTED_SCHEMA"
        if code == "UNKNOWN_CRITICAL_EVENT_VALUE":
            return "UNKNOWN_CRITICAL_VALUE"
        return "SCHEMA"
