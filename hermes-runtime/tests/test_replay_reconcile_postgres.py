import os
import unittest
from pathlib import Path

try:
    import psycopg
    from psycopg.types.json import Jsonb
except ImportError:
    psycopg = None
    Jsonb = None

from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.application.replay_reconcile import (
    ActivateReplay,
    ApplyReconcilePlan,
    CreateReconcilePlan,
    ExecuteReplay,
    ObserveReconcile,
    ReplayReconcileAuthority,
    RequestReplay,
)
from hermes_runtime.domain.models import Actor, ActorType
from hermes_runtime.infrastructure.postgres_delivery import PostgresContiguousConsumer
from hermes_runtime.infrastructure.postgres_replay_reconcile import PostgresReplayReconcileStore


DATABASE_URL = os.environ.get("HERMES_TEST_DATABASE_URL")


@unittest.skipUnless(
    DATABASE_URL and psycopg,
    "requires psycopg and explicit HERMES_TEST_DATABASE_URL pointing to PostgreSQL 14+",
)
class ReplayReconcilePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = PostgresReplayReconcileStore(DATABASE_URL)
        cls.store.check_server_version(140000)
        for migration in sorted((Path(__file__).parents[1] / "migrations").glob("*.sql")):
            cls.store.apply_migration(migration)

    def setUp(self):
        self.store.reset_for_test()
        self.authority = ReplayReconcileAuthority(self.store)
        self.operator = Actor(ActorType.SYSTEM_OPERATOR, "operator-1")

    def _connect(self):
        return psycopg.connect(DATABASE_URL)

    def _seed_events(self, count=3, project_id="project-1"):
        for index in range(1, count + 1):
            self.store.seed_event(
                "event-{}".format(index),
                project_id,
                {"state": "READY", "ordinal": index},
            )

    def _request_replay(self, session_id="replay-1", target="generation-shadow-1", end=3, expected_checkpoint_version=0):
        return self.authority.request_replay(
            RequestReplay(
                command_id="cmd-request-" + session_id,
                idempotency_key="idem-request-" + session_id,
                replay_session_id=session_id,
                consumer_id="consumer-1",
                stream_name="hermes.runtime.events",
                partition_key="project-1",
                source_generation_id="generation-production",
                target_generation_id=target,
                start_sequence=1,
                end_sequence=end,
                consumer_version="consumer/1",
                schema_version="1.0",
                mode="READ_MODEL_REBUILD",
                dry_run=False,
                expected_checkpoint_version=expected_checkpoint_version,
                actor=self.operator,
                reason="rebuild read model",
                authorization_ref="authz-replay",
            )
        )

    def test_replay_shadow_generation_verifies_and_activates_without_authority_rebuild(self):
        self._seed_events(3)
        requested = self._request_replay()
        verified = self.authority.execute_replay(
            ExecuteReplay("cmd-execute-replay-1", "idem-execute-replay-1", "replay-1", 1)
        )
        activated = self.authority.activate_replay(
            ActivateReplay("cmd-activate-replay-1", "idem-activate-replay-1", "replay-1", 2, "authz-replay")
        )
        self.assertEqual("REPLAY_REQUESTED", requested["result_code"])
        self.assertEqual("REPLAY_VERIFIED", verified["result_code"])
        self.assertEqual("REPLAY_ACTIVATED", activated["result_code"])
        with self._connect() as connection:
            pointer = connection.execute(
                "SELECT current_generation_id FROM public.replay_generation_pointers WHERE consumer_id='consumer-1'"
            ).fetchone()[0]
            project_count = connection.execute("SELECT count(*) FROM public.projects").fetchone()[0]
            shadow_count = connection.execute("SELECT count(*) FROM public.replay_shadow_projection_events").fetchone()[0]
        self.assertEqual("generation-shadow-1", pointer)
        self.assertEqual(0, project_count)
        self.assertEqual(3, shadow_count)

    def test_replay_gap_and_unknown_schema_fail_closed(self):
        self._seed_events(2)
        self._request_replay("replay-gap", "generation-gap", end=4)
        failed = self.authority.execute_replay(
            ExecuteReplay("cmd-execute-gap", "idem-execute-gap", "replay-gap", 1)
        )
        self.assertEqual("REPLAY_FAILED", failed["result_code"])
        self.assertEqual("EVENT_GAP_DETECTED", failed["reason_code"])

        self.store.reset_for_test()
        self.store.seed_event("event-1", "project-1", {"state": "READY"})
        with self._connect() as connection:
            connection.execute("ALTER TABLE public.event_log DISABLE TRIGGER event_log_immutable")
            connection.execute("UPDATE public.event_log SET schema_version='2.0' WHERE event_id='event-1'")
            connection.execute("ALTER TABLE public.event_log ENABLE TRIGGER event_log_immutable")
        self._request_replay("replay-schema", "generation-schema", end=1)
        failed_schema = self.authority.execute_replay(
            ExecuteReplay("cmd-execute-schema", "idem-execute-schema", "replay-schema", 1)
        )
        self.assertEqual("EVENT_SCHEMA_UNSUPPORTED", failed_schema["reason_code"])
        with self._connect() as connection:
            quarantine_count = connection.execute("SELECT count(*) FROM public.consumer_quarantine").fetchone()[0]
        self.assertEqual(1, quarantine_count)

    def test_fi_12_duplicate_event_gap_and_effect_checkpoint_recovery(self):
        self._seed_events(3)
        consumer = PostgresContiguousConsumer(DATABASE_URL, "consumer-1")
        first = self.store.event_envelope("event-1")
        third = self.store.event_envelope("event-3")
        applied = consumer.receive(first.__dict__)
        duplicate = consumer.receive(first.__dict__)
        gap = consumer.receive(third.__dict__)
        self.assertEqual("APPLIED", applied["classification"])
        self.assertEqual(applied, duplicate)
        self.assertEqual("GAP_PARKED", gap["classification"])
        with self._connect() as connection:
            effect_count = connection.execute("SELECT count(*) FROM public.consumer_effects").fetchone()[0]
            checkpoint = connection.execute(
                "SELECT last_sequence FROM public.consumer_checkpoints WHERE consumer_id='consumer-1'"
            ).fetchone()[0]
            pending = connection.execute("SELECT count(*) FROM public.consumer_pending_gaps WHERE status='PENDING'").fetchone()[0]
        self.assertEqual(1, effect_count)
        self.assertEqual(1, checkpoint)
        self.assertEqual(1, pending)

        with self._connect() as connection:
            second = connection.execute("SELECT public.hermes_event_envelope('event-2')").fetchone()[0]
            connection.execute(
                """
                INSERT INTO public.consumer_effects(consumer_id,event_id,effect_count)
                VALUES ('consumer-1','event-2',1)
                """
            )
            connection.execute(
                """
                INSERT INTO public.consumer_inbox(
                    consumer_id,event_id,partition_key,sequence,schema_version,
                    processing_result,raw_envelope
                ) VALUES ('consumer-1','event-2','project-1',2,'1.0',
                          '{"classification":"APPLIED"}',%s)
                """,
                (Jsonb(second),),
            )
        observed = self.authority.observe_reconcile(
            ObserveReconcile(
                "cmd-observe-effect-lag",
                "idem-observe-effect-lag",
                "project-1",
                self.operator,
                "observe lag",
                "authz-reconcile",
                "consumer-1",
                "project-1",
            )
        )
        self.assertEqual("RECONCILE_OBSERVED", observed["result_code"])
        with self._connect() as connection:
            finding_id = connection.execute(
                "SELECT finding_id FROM public.reconcile_findings WHERE finding_kind='EFFECT_WITHOUT_CHECKPOINT'"
            ).fetchone()[0]
        plan = self.authority.create_reconcile_plan(
            CreateReconcilePlan(
                "cmd-plan-advance",
                "idem-plan-advance",
                "plan-advance",
                (finding_id,),
                ("ADVANCE_CHECKPOINT_IF_EFFECT_CONTIGUOUS",),
                False,
                self.operator,
                "advance proven checkpoint",
                "authz-reconcile",
                "2099-01-01T00:00:00+00:00",
            )
        )
        applied_plan = self.authority.apply_reconcile_plan(
            ApplyReconcilePlan(
                "cmd-apply-advance",
                "idem-apply-advance",
                "plan-advance",
                1,
                self.operator,
                "apply proven checkpoint repair",
                "authz-reconcile",
            )
        )
        self.assertEqual("RECONCILE_PLAN_CREATED", plan["result_code"])
        self.assertEqual("RECONCILE_PLAN_APPLIED", applied_plan["result_code"])
        with self._connect() as connection:
            checkpoint = connection.execute(
                "SELECT last_sequence FROM public.consumer_checkpoints WHERE consumer_id='consumer-1'"
            ).fetchone()[0]
            finding_status = connection.execute(
                "SELECT status FROM public.reconcile_findings WHERE finding_id=%s",
                (finding_id,),
            ).fetchone()[0]
        self.assertEqual(2, checkpoint)
        self.assertEqual("RESOLVED", finding_status)

    def test_checkpoint_corruption_dry_run_and_stale_plan(self):
        self._seed_events(1)
        consumer = PostgresContiguousConsumer(DATABASE_URL, "consumer-1")
        consumer.receive(self.store.event_envelope("event-1").__dict__)
        with self._connect() as connection:
            connection.execute(
                "UPDATE public.consumer_checkpoints SET checkpoint_hash='sha256:bad' WHERE consumer_id='consumer-1'"
            )
        self.authority.observe_reconcile(
            ObserveReconcile(
                "cmd-observe-corrupt",
                "idem-observe-corrupt",
                "project-1",
                self.operator,
                "observe corrupt",
                "authz-reconcile",
                "consumer-1",
                "project-1",
            )
        )
        with self._connect() as connection:
            finding_id = connection.execute(
                "SELECT finding_id FROM public.reconcile_findings WHERE finding_kind='CHECKPOINT_CORRUPT'"
            ).fetchone()[0]
        dry_run = self.authority.create_reconcile_plan(
            CreateReconcilePlan(
                "cmd-plan-dry",
                "idem-plan-dry",
                "plan-dry",
                (finding_id,),
                ("REBUILD_READ_MODEL_GENERATION",),
                True,
                self.operator,
                "dry run only",
                "authz-reconcile",
                "2099-01-01T00:00:00+00:00",
            )
        )
        self.assertEqual("RECONCILE_DRY_RUN_PLANNED", dry_run["result_code"])
        with self.assertRaisesRegex(CommandRejected, "RECONCILE_DRY_RUN_CANNOT_APPLY"):
            self.authority.apply_reconcile_plan(
                ApplyReconcilePlan(
                    "cmd-apply-dry",
                    "idem-apply-dry",
                    "plan-dry",
                    1,
                    self.operator,
                    "should fail",
                    "authz-reconcile",
                )
            )


if __name__ == "__main__":
    unittest.main()
