import threading
import unittest
import uuid
from pathlib import Path

import os

try:
    import psycopg
    from psycopg.types.json import Jsonb
except ImportError:
    psycopg = None
    Jsonb = None

from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.application.situations import ResolveSituation, SituationAnalyzer
from hermes_runtime.domain.models import Actor, ActorType, CommandEnvelope
from hermes_runtime.infrastructure.postgres_project import PostgresProjectStore
from hermes_runtime.infrastructure.postgres_situation import (
    PostgresSituationStore,
    SituationFaultPoint,
)
from hermes_runtime.application.commands import CreateProject
from hermes_runtime.application.handlers import ControlPlane


DATABASE_URL = os.environ.get("HERMES_TEST_DATABASE_URL")


@unittest.skipUnless(DATABASE_URL and psycopg, "requires real PostgreSQL 14+")
class SituationPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = PostgresSituationStore(DATABASE_URL)
        for migration in sorted((Path(__file__).parents[1] / "migrations").glob("*.sql")):
            cls.store.apply_migration(migration)

    def setUp(self):
        self.store.reset_for_test()
        self.analyzer = SituationAnalyzer(self.store)
        self.create_project("project-1")
        self.seed_task("project-1", "task-1")

    def create_project(self, project_id):
        store = PostgresProjectStore(DATABASE_URL)
        receipt = ControlPlane(store).create_project(CreateProject(
            CommandEnvelope(
                "cmd-create-" + project_id, "project.create",
                "key-create-" + project_id, 0,
                Actor(ActorType.CONTROL_PLANE, "project-manager"),
                "test fixture", project_id,
            ),
            "Situation test project", Actor(ActorType.USER, "user-1"),
        ))
        self.store.analyze_logged_event(receipt.event_ids[0])

    def seed_task(self, project_id, task_id):
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute(
                """INSERT INTO tasks(task_id,project_id,state,version)
                   VALUES (%s,%s,'READY',1)""", (task_id, project_id)
            )

    def seed_ready_event(
        self, suffix, project_id="project-1", task_id="task-1",
        components=None,
    ):
        command_id = "cmd-ready-" + suffix
        event_id = "evt-ready-" + suffix
        payload = {
            "graph_version": 0,
            "ready_state_changes": [
                {"task_id": task_id, "from_state": "NEW", "to_state": "READY"}
            ],
        }
        if components is not None:
            payload["affected_components"] = components
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute(
                """INSERT INTO command_receipts(
                   command_id,project_id,command_type,idempotency_key,
                   request_hash,status,result,completed_at)
                   VALUES (%s,%s,'task.recompute_readiness',%s,'fixture',
                           'APPLIED','{}',now())""",
                (command_id, project_id, "key-ready-" + suffix),
            )
            sequence = connection.execute(
                """INSERT INTO event_log(
                   event_id,event_type,schema_version,producer_type,producer_id,
                   project_id,partition_key,command_id,correlation_id,task_id,payload)
                   VALUES (%s,'task.readiness_recomputed','1.0','control_plane',
                           'work-graph-authority',%s,%s,%s,%s,%s,%s)
                   RETURNING sequence""",
                (event_id, project_id, project_id, command_id, command_id,
                 task_id, Jsonb(payload)),
            ).fetchone()[0]
            envelope = connection.execute(
                "SELECT public.hermes_event_envelope(%s)", (event_id,)
            ).fetchone()[0]
        return event_id, sequence, envelope

    def seed_feedback_event(self, suffix, evidence_ref):
        command_id = "cmd-feedback-" + suffix
        event_id = "evt-feedback-" + suffix
        payload = {
            "feedback_id": "feedback-" + suffix,
            "source_task_id": "task-1",
            "verification_id": "verification-" + suffix,
            "failure_type": "test_failure",
            "affected_components": ["component:test"],
            "evidence_refs": [evidence_ref],
        }
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute(
                """INSERT INTO project_graph_versions(project_id,graph_version)
                   VALUES ('project-1',0) ON CONFLICT DO NOTHING"""
            )
            connection.execute(
                """INSERT INTO command_receipts(
                   command_id,project_id,command_type,idempotency_key,
                   request_hash,status,result,completed_at)
                   VALUES (%s,'project-1','feedback.create',%s,'fixture',
                           'APPLIED','{}',now())""",
                (command_id, command_id),
            )
            connection.execute(
                """INSERT INTO event_log(
                   event_id,event_type,schema_version,producer_type,producer_id,
                   project_id,partition_key,command_id,correlation_id,task_id,payload)
                   VALUES (%s,'feedback.created','1.0','verification_engine','test',
                           'project-1','project-1',%s,%s,'task-1',%s)""",
                (event_id, command_id, command_id, Jsonb(payload)),
            )
            connection.execute(
                """INSERT INTO feedback_records(
                   feedback_id,project_id,source_event_id,source_task_id,
                   verification_id,decision_id,repair_task_id)
                   VALUES (%s,'project-1',%s,'task-1',%s,%s,%s)""",
                (payload["feedback_id"], event_id, payload["verification_id"],
                 "decision-" + suffix, "repair-" + suffix),
            )
            return connection.execute(
                "SELECT public.hermes_event_envelope(%s)", (event_id,)
            ).fetchone()[0]

    def analyze_output_event(self, result):
        if result.get("output_event_id"):
            return self.store.analyze_logged_event(result["output_event_id"])
        return None

    def counts(self):
        with psycopg.connect(DATABASE_URL) as connection:
            authority = tuple(connection.execute(
                "SELECT count(*) FROM " + table
            ).fetchone()[0] for table in (
                "analysis_contexts", "situations", "situation_versions",
            ))
            trigger_inbox = connection.execute(
                """SELECT count(*) FROM consumer_inbox i
                   JOIN event_log e ON e.event_id=i.event_id
                   WHERE e.event_type='task.readiness_recomputed'"""
            ).fetchone()[0]
            return authority + (trigger_inbox,)

    def test_create_duplicate_and_context_are_atomic_and_stable(self):
        event_id, sequence, envelope = self.seed_ready_event("first")
        result = self.analyzer.analyze(envelope)
        duplicate = self.analyzer.analyze(envelope)
        self.assertEqual("CREATED", result["classification"])
        self.assertEqual(result, duplicate)
        with psycopg.connect(DATABASE_URL) as connection:
            context = connection.execute(
                """SELECT trigger_event_id,observed_at_sequence,context_hash,
                          rule_set_version FROM analysis_contexts"""
            ).fetchone()
            situation = connection.execute(
                """SELECT status,version,observed_at_sequence,type
                   FROM situations"""
            ).fetchone()
        self.assertEqual((event_id, sequence), context[:2])
        self.assertTrue(context[2].startswith("sha256:"))
        self.assertEqual("situation-rules/1.0", context[3])
        self.assertEqual(("OPEN", 1, sequence, "work_available"), situation)
        self.assertEqual((1, 1, 1, 1), self.counts())

    def test_equivalent_evidence_updates_and_semantic_change_supersedes(self):
        first = self.analyzer.analyze(self.seed_ready_event(
            "first", components=["component:a"]
        )[2])
        self.analyze_output_event(first)
        second = self.analyzer.analyze(self.seed_ready_event(
            "second", components=["component:a"]
        )[2])
        self.assertEqual("UPDATED", second["classification"])
        self.assertEqual(first["situation_id"], second["situation_id"])
        self.assertEqual(2, second["version"])
        self.analyze_output_event(second)
        third = self.analyzer.analyze(self.seed_ready_event(
            "third", components=["component:b"]
        )[2])
        self.assertEqual("SUPERSEDED", third["classification"])
        with psycopg.connect(DATABASE_URL) as connection:
            rows = connection.execute(
                """SELECT situation_id,status,superseded_by,version
                   FROM situations ORDER BY created_at"""
            ).fetchall()
            open_count = connection.execute(
                "SELECT count(*) FROM situations WHERE status='OPEN'"
            ).fetchone()[0]
        self.assertEqual(2, len(rows))
        self.assertEqual("SUPERSEDED", rows[0][1])
        self.assertEqual(third["situation_id"], rows[0][2])
        self.assertEqual(1, open_count)

    def test_equivalent_feedback_merges_new_evidence_refs_without_loss(self):
        first = self.analyzer.analyze(self.seed_feedback_event("first", "evidence-a"))
        self.analyze_output_event(first)
        second = self.analyzer.analyze(self.seed_feedback_event("second", "evidence-b"))
        self.assertEqual("UPDATED", second["classification"])
        with psycopg.connect(DATABASE_URL) as connection:
            row = connection.execute(
                """SELECT version,available_context_refs FROM situations
                   WHERE situation_id=%s""", (first["situation_id"],)
            ).fetchone()
        self.assertEqual(2, row[0])
        self.assertEqual(["evidence-a", "evidence-b"], row[1])

    def test_expected_version_conflict_rolls_back_context_and_effect(self):
        first = self.analyzer.analyze(self.seed_ready_event("first")[2])
        self.analyze_output_event(first)
        envelope = self.seed_ready_event("second")[2]
        before = self.counts()
        with self.assertRaisesRegex(CommandRejected, "SITUATION_VERSION_CONFLICT"):
            self.analyzer.analyze(envelope, expected_situation_version=99)
        self.assertEqual(before, self.counts())

    def test_concurrent_duplicate_delivery_applies_once(self):
        _, _, envelope = self.seed_ready_event("concurrent")
        barrier = threading.Barrier(2)
        results = []
        failures = []

        def analyze():
            try:
                barrier.wait()
                results.append(SituationAnalyzer(PostgresSituationStore(
                    DATABASE_URL
                )).analyze(envelope))
            except Exception as exc:
                failures.append(exc)

        threads = [threading.Thread(target=analyze) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual([], failures)
        self.assertEqual(2, len(results))
        self.assertEqual(results[0], results[1])
        self.assertEqual((1, 1, 1, 1), self.counts())

    def test_fault_points_rollback_all_authoritative_effects(self):
        points = (
            SituationFaultPoint.AFTER_CONTEXT_BEFORE_SITUATION,
            SituationFaultPoint.AFTER_SITUATION_BEFORE_EVENT,
            SituationFaultPoint.AFTER_EVENT_BEFORE_OUTBOX,
            SituationFaultPoint.AFTER_OUTBOX_BEFORE_INBOX,
            SituationFaultPoint.AFTER_INBOX_BEFORE_CHECKPOINT,
        )
        for index, point in enumerate(points):
            with self.subTest(point=point):
                self.store.reset_for_test()
                self.create_project("project-1")
                self.seed_task("project-1", "task-1")
                envelope = self.seed_ready_event("fault-{}".format(index))[2]
                self.store.fail_situation_once(point)
                with self.assertRaisesRegex(RuntimeError, "injected situation crash"):
                    self.analyzer.analyze(envelope)
                self.assertEqual((0, 0, 0, 0), self.counts())
                self.assertEqual("CREATED", self.analyzer.analyze(envelope)["classification"])

    def test_project_scope_is_independent(self):
        self.create_project("project-2")
        self.seed_task("project-2", "task-2")
        first = self.analyzer.analyze(self.seed_ready_event("p1")[2])
        self.analyze_output_event(first)
        second = self.analyzer.analyze(self.seed_ready_event(
            "p2", "project-2", "task-2"
        )[2])
        self.assertEqual("CREATED", second["classification"])
        with psycopg.connect(DATABASE_URL) as connection:
            projects = connection.execute(
                "SELECT project_id,count(*) FROM situations GROUP BY project_id"
            ).fetchall()
        self.assertEqual({("project-1", 1), ("project-2", 1)}, set(projects))

    def test_explicit_resolve_is_idempotent_and_does_not_reopen(self):
        first = self.analyzer.analyze(self.seed_ready_event("first")[2])
        self.analyze_output_event(first)
        command = ResolveSituation(
            first["situation_id"], "project-1", 1, "cmd-resolve",
            "key-resolve", "control_plane", "operator-1", "work accepted",
        )
        resolved = self.analyzer.resolve(command)
        self.assertEqual("RESOLVED", resolved["status"])
        self.assertEqual(resolved, self.analyzer.resolve(command))
        self.store.analyze_logged_event(resolved["event_id"])
        ignored = self.analyzer.analyze(self.seed_ready_event("after-resolve")[2])
        self.assertEqual("IGNORED_ALREADY_RESOLVED", ignored["classification"])
        with psycopg.connect(DATABASE_URL) as connection:
            row = connection.execute(
                "SELECT status,version FROM situations"
            ).fetchone()
        self.assertEqual(("RESOLVED", 2), row)

    def test_wrong_task_reference_fails_closed(self):
        _, _, envelope = self.seed_ready_event("wrong")
        envelope["task_id"] = "other-task"
        with self.assertRaisesRegex(CommandRejected, "SITUATION_FACT_TASK_MISMATCH"):
            self.analyzer.analyze(envelope)

    def test_gap_is_parked_then_drained_contiguously(self):
        first = self.seed_ready_event("gap-first")[2]
        second = self.seed_ready_event("gap-second")[2]
        parked = self.analyzer.analyze(second)
        self.assertEqual("GAP_PARKED", parked["classification"])
        self.assertEqual("CREATED", self.analyzer.analyze(first)["classification"])
        with psycopg.connect(DATABASE_URL) as connection:
            checkpoint = connection.execute(
                """SELECT last_sequence FROM consumer_checkpoints
                   WHERE consumer_id='situation-analyzer'
                     AND partition_key='project-1'"""
            ).fetchone()[0]
            gap_status = connection.execute(
                """SELECT status FROM consumer_pending_gaps
                   WHERE event_id=%s""", (second["event_id"],)
            ).fetchone()[0]
        self.assertEqual(second["sequence"], checkpoint)
        self.assertEqual("PROCESSED", gap_status)

    def test_envelope_payload_cannot_diverge_from_immutable_event(self):
        envelope = self.seed_ready_event("tamper")[2]
        envelope["payload"] = dict(envelope["payload"])
        envelope["payload"]["affected_components"] = ["forged"]
        with self.assertRaisesRegex(
            CommandRejected, "EVENT_ENVELOPE_IDENTITY_MISMATCH"
        ):
            self.analyzer.analyze(envelope)

    def test_concurrent_equivalent_events_converge_without_two_open_rows(self):
        first = self.seed_ready_event("equivalent-a")[2]
        second = self.seed_ready_event("equivalent-b")[2]
        barrier = threading.Barrier(2)
        results = []

        def analyze(envelope):
            barrier.wait()
            results.append(SituationAnalyzer(PostgresSituationStore(
                DATABASE_URL
            )).analyze(envelope))

        threads = [
            threading.Thread(target=analyze, args=(first,)),
            threading.Thread(target=analyze, args=(second,)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        with psycopg.connect(DATABASE_URL) as connection:
            rows = connection.execute(
                "SELECT status,version FROM situations"
            ).fetchall()
        self.assertEqual([("OPEN", 2)], rows)
        self.assertIn("GAP_PARKED", {item["classification"] for item in results})


if __name__ == "__main__":
    unittest.main()
