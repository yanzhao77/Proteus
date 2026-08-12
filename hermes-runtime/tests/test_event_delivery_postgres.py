import os
import threading
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import psycopg
    from psycopg.types.json import Jsonb
except ImportError:
    psycopg = None
    Jsonb = None

from hermes_runtime.application.delivery import OutboxRelay
from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.domain.models import (
    Actor,
    ActorType,
    CommandEnvelope,
    RedriveOutbox,
)
from hermes_runtime.infrastructure.postgres_delivery import (
    PostgresContiguousConsumer,
    PostgresDeliveryStore,
    PostgresLocalPublisher,
    envelope_to_mapping,
)


DATABASE_URL = os.environ.get("HERMES_TEST_DATABASE_URL")
UTC = timezone.utc


@unittest.skipUnless(
    DATABASE_URL and psycopg,
    "requires psycopg and explicit HERMES_TEST_DATABASE_URL pointing to PostgreSQL 14+",
)
class EventDeliveryPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = PostgresDeliveryStore(DATABASE_URL)
        cls.store.check_server_version(140000)
        migrations = Path(__file__).parents[1] / "migrations"
        for migration in sorted(migrations.glob("*.sql")):
            cls.store.apply_migration(migration)

    def setUp(self):
        self.store.reset_for_test()
        self.now = datetime(2026, 8, 12, 8, 0, tzinfo=UTC)

    def seed_event(self, event_id, partition="project-1", payload=None, outbox=True):
        command_id = "cmd-" + event_id
        payload = payload or {"state": "READY"}
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute(
                """
                INSERT INTO command_receipts(
                    command_id, project_id, command_type, idempotency_key,
                    request_hash, status, result, completed_at
                ) VALUES (%s,%s,'test.event','key-' || %s,'hash','APPLIED','{}',now())
                """, (command_id, partition, event_id)
            )
            sequence = connection.execute(
                """
                INSERT INTO event_log(
                    event_id,event_type,schema_version,producer_type,producer_id,
                    project_id,partition_key,command_id,correlation_id,payload,
                    occurred_at,recorded_at
                ) VALUES (%s,'test.event','1.2','control_plane','test',%s,%s,%s,%s,%s,%s,%s)
                RETURNING sequence
                """,
                (event_id, partition, partition, command_id, "corr-" + event_id,
                 Jsonb(payload), self.now, self.now),
            ).fetchone()[0]
            if outbox:
                connection.execute(
                    """
                    INSERT INTO outbox_messages(
                        message_id,event_id,topic,partition_key,sequence,payload,
                        next_attempt_at
                    ) VALUES (%s,%s,'test.events',%s,%s,%s,%s)
                    """,
                    ("msg-" + event_id, event_id, partition, sequence,
                     Jsonb(payload), self.now),
                )
        return self.store.event_envelope(event_id)

    def status(self, message_id):
        with psycopg.connect(DATABASE_URL) as connection:
            return connection.execute(
                """SELECT status, attempt_count, lease_owner, claim_token,
                          status_version, redrive_count
                   FROM outbox_messages WHERE message_id = %s""", (message_id,)
            ).fetchone()

    def count(self, table):
        with psycopg.connect(DATABASE_URL) as connection:
            return connection.execute("SELECT count(*) FROM " + table).fetchone()[0]

    def test_partition_local_sequence_is_atomic_and_independent(self):
        first = self.seed_event("a-1", "project-a")
        other = self.seed_event("b-1", "project-b")
        second = self.seed_event("a-2", "project-a")
        self.assertEqual((1, 1, 2), (first.sequence, other.sequence, second.sequence))
        with psycopg.connect(DATABASE_URL) as connection:
            with self.assertRaisesRegex(
                psycopg.errors.RaiseException,
                "EVENT_SEQUENCE_ASSIGNED_BY_DATABASE",
            ):
                connection.execute(
                    """INSERT INTO event_log(
                       event_id,event_type,schema_version,producer_type,producer_id,
                       project_id,partition_key,command_id,correlation_id,payload,sequence)
                       VALUES ('forged','test','1.0','control_plane','test','project-a',
                       'project-a','cmd-a-1','corr','{}',99)"""
                )

    def test_claim_batch_concurrency_and_stale_claim_token(self):
        self.seed_event("claim-1")
        barrier = threading.Barrier(2)
        claims = []

        def claim(owner):
            barrier.wait()
            claims.extend(self.store.claim_outbox(owner, self.now, 30, 1, 5))

        threads = [threading.Thread(target=claim, args=("relay-a",)),
                   threading.Thread(target=claim, args=("relay-b",))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(1, len(claims))
        old = claims[0]
        old_owner = self.status("msg-claim-1")[2]
        reclaimed = self.store.claim_outbox(
            "relay-new", self.now + timedelta(seconds=31), 30, 1, 5
        )[0]
        self.assertNotEqual(old.claim_token, reclaimed.claim_token)
        self.assertFalse(self.store.mark_outbox_published(
            old, old_owner, self.now + timedelta(seconds=32)
        ))
        self.assertEqual(
            "STALE_CLAIM",
            self.store.mark_outbox_failure(
                old, old_owner, self.now + timedelta(seconds=32), True,
                "LATE", "late failure", self.now + timedelta(seconds=33), 5,
            ),
        )
        self.assertTrue(self.store.mark_outbox_published(
            reclaimed, "relay-new", self.now + timedelta(seconds=32)
        ))
        self.assertEqual("PUBLISHED", self.status("msg-claim-1")[0])

    def test_two_relays_claim_batches_without_overlap(self):
        for index in range(6):
            self.seed_event("batch-{}".format(index))
        barrier = threading.Barrier(2)
        claimed = {}

        def claim(owner):
            barrier.wait()
            claimed[owner] = {
                item.message_id
                for item in self.store.claim_outbox(owner, self.now, 30, 3, 5)
            }

        threads = [threading.Thread(target=claim, args=("relay-a",)),
                   threading.Thread(target=claim, args=("relay-b",))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(set(), claimed["relay-a"].intersection(claimed["relay-b"]))
        self.assertEqual(6, len(claimed["relay-a"] | claimed["relay-b"]))

    def test_claim_respects_next_attempt_lease_published_and_dead_lettered(self):
        self.seed_event("future")
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute(
                "UPDATE outbox_messages SET next_attempt_at = %s WHERE message_id = 'msg-future'",
                (self.now + timedelta(hours=1),),
            )
        self.assertEqual((), self.store.claim_outbox("relay", self.now, 30, 10, 5))
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute(
                "UPDATE outbox_messages SET status = 'PUBLISHED' WHERE message_id = 'msg-future'"
            )
        self.assertEqual((), self.store.claim_outbox(
            "relay", self.now + timedelta(hours=2), 30, 10, 5
        ))
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute(
                "UPDATE outbox_messages SET status = 'DEAD_LETTERED' WHERE message_id = 'msg-future'"
            )
        self.assertEqual((), self.store.claim_outbox(
            "relay", self.now + timedelta(hours=2), 30, 10, 5
        ))

    def test_relay_publish_retry_dlq_and_crash_duplicate(self):
        self.seed_event("retry")
        publisher = PostgresLocalPublisher(DATABASE_URL)
        publisher.fail_next("TRANSPORT", True)
        relay = OutboxRelay(
            self.store, publisher, "relay", lambda: self.now,
            max_attempts=3, backoff_seconds=lambda attempt: 0,
        )
        first = relay.run_once()
        self.assertEqual((1, 0, 1), (first.claimed, first.published, first.retried))
        second = relay.run_once()
        self.assertEqual(1, second.published)

        self.seed_event("poison")
        publisher.fail_next("POISON", False)
        dead = relay.run_once()
        self.assertEqual(1, dead.dead_lettered)
        self.assertEqual("DEAD_LETTERED", self.status("msg-poison")[0])
        self.assertEqual(1, self.count("outbox_delivery_dlq"))

        self.seed_event("crash", "crash-project")
        claim = self.store.claim_outbox("relay-old", self.now, 10, 1, 3)[0]
        publisher.publish(claim.envelope)
        recovered = OutboxRelay(
            self.store, publisher, "relay-new",
            lambda: self.now + timedelta(seconds=11), max_attempts=3,
        ).run_once()
        self.assertEqual(1, recovered.published)
        with psycopg.connect(DATABASE_URL) as connection:
            count = connection.execute(
                "SELECT count(*) FROM local_transport_publications WHERE event_id = 'crash'"
            ).fetchone()[0]
        self.assertEqual(2, count)
        with psycopg.connect(DATABASE_URL) as connection:
            publications = connection.execute(
                """SELECT envelope FROM local_transport_publications
                   WHERE event_id = 'crash' ORDER BY published_at"""
            ).fetchall()
        consumer = PostgresContiguousConsumer(DATABASE_URL, "crash-consumer")
        for publication in publications:
            consumer.receive(publication[0])
        with psycopg.connect(DATABASE_URL) as connection:
            effects = connection.execute(
                """SELECT count(*) FROM consumer_effects
                   WHERE consumer_id='crash-consumer' AND event_id='crash'"""
            ).fetchone()[0]
        self.assertEqual(1, effects)

    def test_retryable_failure_exhaustion_enters_dlq_with_original_identity(self):
        original = self.seed_event("exhaust")
        publisher = PostgresLocalPublisher(DATABASE_URL)
        publisher.fail_next("TRANSIENT", True)
        publisher.fail_next("TRANSIENT", True)
        relay = OutboxRelay(
            self.store, publisher, "relay", lambda: self.now,
            max_attempts=2, backoff_seconds=lambda attempt: 0,
        )
        self.assertEqual(1, relay.run_once().retried)
        self.assertEqual(1, relay.run_once().dead_lettered)
        with psycopg.connect(DATABASE_URL) as connection:
            dlq = connection.execute(
                """SELECT event_id, partition_key, sequence,
                          original_envelope->>'event_id', attempt_count
                   FROM outbox_delivery_dlq WHERE message_id='msg-exhaust'"""
            ).fetchone()
        self.assertEqual(
            (original.event_id, original.partition_key, original.sequence,
             original.event_id, 2),
            dlq,
        )

    def test_contiguous_checkpoint_parks_and_drains_gap(self):
        one = self.seed_event("gap-1")
        two = self.seed_event("gap-2")
        three = self.seed_event("gap-3")
        consumer = PostgresContiguousConsumer(DATABASE_URL, "consumer")
        self.assertEqual("APPLIED", consumer.receive(envelope_to_mapping(one))["classification"])
        parked = consumer.receive(envelope_to_mapping(three))
        self.assertEqual("GAP_PARKED", parked["classification"])
        self.assertEqual("GAP_PARKED", consumer.receive(
            envelope_to_mapping(three)
        )["classification"])
        self.assertEqual(1, self.count("consumer_effects"))
        consumer.receive(envelope_to_mapping(two))
        with psycopg.connect(DATABASE_URL) as connection:
            checkpoint = connection.execute(
                "SELECT last_sequence FROM consumer_checkpoints WHERE consumer_id='consumer'"
            ).fetchone()[0]
        self.assertEqual(3, checkpoint)
        self.assertEqual(3, self.count("consumer_effects"))
        self.assertEqual(1, self.count("consumer_pending_gaps"))

    def test_duplicate_late_and_partition_independence(self):
        a1 = self.seed_event("a1", "a")
        a2 = self.seed_event("a2", "a")
        b1 = self.seed_event("b1", "b")
        consumer = PostgresContiguousConsumer(DATABASE_URL, "consumer")
        consumer.receive(envelope_to_mapping(a1))
        duplicate = consumer.receive(envelope_to_mapping(a1))
        self.assertEqual("APPLIED", duplicate["classification"])
        consumer.receive(envelope_to_mapping(b1))
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute(
                "DELETE FROM consumer_inbox WHERE consumer_id='consumer' AND event_id='a1'"
            )
        late = consumer.receive(envelope_to_mapping(a1))
        self.assertEqual("LATE_QUARANTINED", late["classification"])
        self.assertEqual(2, self.count("consumer_effects"))

    def test_consumer_crash_points_are_atomic_and_replay_safe(self):
        for point in ("before_effect", "after_effect_before_inbox", "after_inbox_before_checkpoint"):
            with self.subTest(point=point):
                self.store.reset_for_test()
                event = self.seed_event("crash-" + point)
                consumer = PostgresContiguousConsumer(DATABASE_URL, "consumer")
                consumer.fail_once(point)
                with self.assertRaisesRegex(RuntimeError, "injected consumer crash"):
                    consumer.receive(envelope_to_mapping(event))
                self.assertEqual(0, self.count("consumer_effects"))
                self.assertEqual(0, self.count("consumer_inbox"))
                consumer.receive(envelope_to_mapping(event))
                self.assertEqual(1, self.count("consumer_effects"))

    def test_schema_additive_compatibility_and_fail_closed_quarantine(self):
        event = self.seed_event("schema")
        raw = envelope_to_mapping(event)
        raw["future_optional"] = {"preserved": True}
        consumer = PostgresContiguousConsumer(DATABASE_URL, "consumer")
        consumer.receive(raw)
        with psycopg.connect(DATABASE_URL) as connection:
            preserved = connection.execute(
                "SELECT raw_envelope->'future_optional'->>'preserved' FROM consumer_inbox"
            ).fetchone()[0]
        self.assertEqual("true", preserved)

        missing = dict(envelope_to_mapping(self.seed_event("missing")))
        missing.pop("producer")
        unsupported = dict(envelope_to_mapping(self.seed_event("major")))
        unsupported["schema_version"] = "2.0"
        unknown = dict(envelope_to_mapping(self.seed_event(
            "unknown", payload={"state": "FUTURE_UNKNOWN_STATE"}
        )))
        for raw_event in (missing, unsupported, unknown):
            result = consumer.receive(raw_event)
            self.assertEqual("QUARANTINED", result["classification"])
        consumer.receive(unknown)
        self.assertEqual(3, self.count("consumer_quarantine"))
        self.assertEqual(1, self.count("consumer_effects"))

    def test_authorized_redrive_is_idempotent_and_preserves_event(self):
        event = self.seed_event("redrive")
        publisher = PostgresLocalPublisher(DATABASE_URL)
        publisher.fail_next("POISON", False)
        relay = OutboxRelay(
            self.store, publisher, "relay", lambda: self.now, max_attempts=1
        )
        relay.run_once()
        version = self.status("msg-redrive")[4]
        envelope = CommandEnvelope(
            "redrive-command", "outbox.redrive", "redrive-key", version,
            Actor(ActorType.SYSTEM_OPERATOR, "operator"), "cause fixed", "project-1"
        )
        command = RedriveOutbox(envelope, "msg-redrive", "ticket-1", True)
        first = relay.redrive(command)
        second = relay.redrive(command)
        self.assertEqual(first, second)
        self.assertEqual(event.event_id, first.event_ids[0])
        self.assertEqual(("PENDING", 1), (self.status("msg-redrive")[0], self.status("msg-redrive")[5]))
        self.assertEqual(1, relay.run_once().published)

        consumer = PostgresContiguousConsumer(DATABASE_URL, "redrive-consumer")
        raw = envelope_to_mapping(event)
        consumer.receive(raw)
        consumer.receive(raw)
        self.assertEqual(1, self.count("consumer_effects"))

    def test_redrive_authorization_version_and_payload_conflict(self):
        self.seed_event("redrive-reject")
        publisher = PostgresLocalPublisher(DATABASE_URL)
        publisher.fail_next("POISON", False)
        relay = OutboxRelay(self.store, publisher, "relay", lambda: self.now, max_attempts=1)
        relay.run_once()
        version = self.status("msg-redrive-reject")[4]
        bad = RedriveOutbox(
            CommandEnvelope("bad-redrive", "outbox.redrive", "bad", version,
                            Actor(ActorType.WORKER, "worker"), "try", "project-1"),
            "msg-redrive-reject", "ticket", True,
        )
        with self.assertRaisesRegex(CommandRejected, "REDRIVE_NOT_AUTHORIZED"):
            relay.redrive(bad)
        good_envelope = CommandEnvelope(
            "redrive-good", "outbox.redrive", "same-key", version,
            Actor(ActorType.SYSTEM_OPERATOR, "operator"), "fixed", "project-1"
        )
        good = RedriveOutbox(good_envelope, "msg-redrive-reject", "ticket", True)
        relay.redrive(good)
        conflicting = RedriveOutbox(
            CommandEnvelope("redrive-conflict", "outbox.redrive", "same-key", version,
                            Actor(ActorType.SYSTEM_OPERATOR, "operator"), "different", "project-1"),
            "msg-redrive-reject", "other-ticket", True,
        )
        with self.assertRaisesRegex(CommandRejected, "IDEMPOTENCY_CONFLICT"):
            relay.redrive(conflicting)
        metrics = self.store.delivery_metrics(self.now)
        self.assertEqual(1, metrics["redrive_success"])
        self.assertEqual(1, metrics["redrive_failure"])

    def test_replay_and_reconcile_do_not_modify_authority(self):
        event = self.seed_event("replay", outbox=False)
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute(
                "INSERT INTO tasks(task_id,project_id,state,version) VALUES ('authority','project-1','RUNNING',7)"
            )
        consumer = PostgresContiguousConsumer(DATABASE_URL, "projection")
        consumer.replay(self.store, event.event_id)
        self.store.reconcile_delivery(self.now)
        with psycopg.connect(DATABASE_URL) as connection:
            state = connection.execute(
                "SELECT state, version FROM tasks WHERE task_id='authority'"
            ).fetchone()
            anomalies = connection.execute(
                "SELECT count(*) FROM delivery_operational_alerts WHERE category='EVENT_WITHOUT_OUTBOX'"
            ).fetchone()[0]
        self.assertEqual(("RUNNING", 7), state)
        self.assertEqual(1, anomalies)

    def test_reconcile_advances_only_proven_contiguous_inbox_prefix(self):
        events = [self.seed_event("reconcile-{}".format(index)) for index in range(1, 5)]
        consumer = PostgresContiguousConsumer(DATABASE_URL, "projection")
        consumer.receive(envelope_to_mapping(events[0]))
        with psycopg.connect(DATABASE_URL) as connection:
            for event in (events[1], events[3]):
                connection.execute(
                    """
                    INSERT INTO consumer_effects(consumer_id,event_id,effect_count)
                    VALUES ('projection',%s,1)
                    """,
                    (event.event_id,),
                )
                connection.execute(
                    """
                    INSERT INTO consumer_inbox(
                        consumer_id,event_id,partition_key,sequence,schema_version,
                        processing_result,raw_envelope
                    ) VALUES ('projection',%s,%s,%s,%s,'{}',%s)
                    """,
                    (event.event_id, event.partition_key, event.sequence,
                     event.schema_version,
                     Jsonb(envelope_to_mapping(event))),
                )
        self.store.reconcile_delivery(self.now)
        with psycopg.connect(DATABASE_URL) as connection:
            checkpoint = connection.execute(
                "SELECT last_sequence FROM consumer_checkpoints WHERE consumer_id='projection'"
            ).fetchone()[0]
        self.assertEqual(2, checkpoint)

    def test_bounded_gap_and_timeout_enter_reconcile_with_metrics(self):
        events = [self.seed_event("bounded-{}".format(index)) for index in range(1, 4)]
        consumer = PostgresContiguousConsumer(DATABASE_URL, "bounded", gap_limit=1)
        self.assertEqual(
            "GAP_PARKED",
            consumer.receive(envelope_to_mapping(events[1]))["classification"],
        )
        self.assertEqual(
            "RECONCILE_REQUIRED",
            consumer.receive(envelope_to_mapping(events[2]))["classification"],
        )
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute(
                """UPDATE consumer_pending_gaps
                   SET first_seen_at = %s WHERE consumer_id = 'bounded'""",
                (self.now - timedelta(hours=1),),
            )
        self.assertEqual(1, self.store.reconcile_gap_timeouts(self.now, 60))
        metrics = self.store.delivery_metrics(self.now)
        self.assertEqual(2, metrics["quarantine"])
        self.assertGreaterEqual(metrics["anomalies"], 2)

    def test_reconcile_detects_published_but_unconsumed_event(self):
        self.seed_event("unconsumed")
        publisher = PostgresLocalPublisher(DATABASE_URL)
        OutboxRelay(self.store, publisher, "relay", lambda: self.now).run_once()
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute(
                """INSERT INTO consumer_checkpoints(
                   consumer_id,partition_key,last_sequence
                   ) VALUES ('lagging','project-1',0)"""
            )
        self.store.reconcile_delivery(self.now)
        with psycopg.connect(DATABASE_URL) as connection:
            count = connection.execute(
                """SELECT count(*) FROM delivery_operational_alerts
                   WHERE category='PUBLISHED_UNCONSUMED'
                     AND consumer_id='lagging' AND event_id='unconsumed'"""
            ).fetchone()[0]
        self.assertEqual(1, count)

    def test_metrics_snapshot_counts_delivery_and_duplicates(self):
        event = self.seed_event("metrics")
        publisher = PostgresLocalPublisher(DATABASE_URL)
        relay = OutboxRelay(self.store, publisher, "relay", lambda: self.now)
        relay.run_once()
        consumer = PostgresContiguousConsumer(DATABASE_URL, "metrics-consumer")
        raw = envelope_to_mapping(event)
        consumer.receive(raw)
        consumer.receive(raw)
        metrics = self.store.delivery_metrics(self.now)
        self.assertEqual(1, metrics["relay_claimed"])
        self.assertEqual(1, metrics["relay_published"])
        self.assertEqual(1, metrics["consumer_duplicates"])
        self.assertEqual(0, metrics["checkpoint_lag"])


if __name__ == "__main__":
    unittest.main()
