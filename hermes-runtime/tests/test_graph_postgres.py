import os
import threading
import unittest
import uuid
from pathlib import Path

try:
    import psycopg
except ImportError:
    psycopg = None

from hermes_runtime.application.commands import (
    ApplyWorkGraphPatch,
    ConsumeFeedbackCreated,
    RecomputeTaskReadiness,
)
from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.application.handlers import ControlPlane
from hermes_runtime.domain.graph import (
    AddTaskDependency,
    AddTypedWorkGraphEdge,
    CreateTask,
    GraphPatch,
    GraphTask,
    NodeRef,
)
from hermes_runtime.domain.models import Actor, ActorType, CommandEnvelope, TaskState
from hermes_runtime.infrastructure.postgres import FaultPoint
from hermes_runtime.infrastructure.postgres_graph import PostgresGraphStore


DATABASE_URL = os.environ.get("HERMES_TEST_DATABASE_URL")


def envelope(command_type, actor, version, key):
    return CommandEnvelope(
        command_id="cmd-" + str(uuid.uuid4()),
        command_type=command_type,
        idempotency_key=key,
        expected_version=version,
        actor=actor,
        reason="graph conformance test",
        project_id="project-1",
    )


@unittest.skipUnless(
    DATABASE_URL and psycopg,
    "requires psycopg and explicit HERMES_TEST_DATABASE_URL pointing to PostgreSQL 14+",
)
class GraphPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = PostgresGraphStore(DATABASE_URL)
        cls.store.check_server_version(140000)
        migrations = Path(__file__).parents[1] / "migrations"
        for migration in sorted(migrations.glob("*.sql")):
            cls.store.apply_migration(migration)

    def setUp(self):
        self.store.reset_for_test()
        self.store.seed_project("project-1")
        self.control = Actor(ActorType.CONTROL_PLANE, "control-plane-graph")
        self.plane = ControlPlane(self.store)

    def patch_command(self, operations, version=0, key="graph-patch", decision="decision-1"):
        return ApplyWorkGraphPatch(
            envelope("work_graph.apply_patch", self.control, version, key),
            GraphPatch(version, decision, tuple(operations)),
        )

    def apply(self, operations, **kwargs):
        return self.plane.apply_work_graph_patch(
            self.patch_command(operations, **kwargs)
        )

    @staticmethod
    def task(task_id, title=None):
        return CreateTask(GraphTask(task_id, "repair", title or task_id))

    @staticmethod
    def dependency(task_id, depends_on):
        return AddTaskDependency(task_id, depends_on)

    @staticmethod
    def edge(edge_id, source_type, source_id, edge_type, target_type, target_id):
        return AddTypedWorkGraphEdge(
            edge_id,
            NodeRef(source_type, source_id),
            edge_type,
            NodeRef(target_type, target_id),
        )

    def test_patch_commits_task_edges_event_outbox_receipt_and_one_version(self):
        receipt = self.apply(
            [
                self.task("task-a"),
                self.task("task-b"),
                self.dependency("task-b", "task-a"),
            ]
        )

        self.assertEqual("APPLIED", receipt.status)
        self.assertEqual(1, self.store.graph_version("project-1"))
        self.assertEqual(2, self.store.count("tasks"))
        self.assertEqual(1, self.store.count("task_dependencies"))
        self.assertEqual(1, self.store.count("work_graph_edges"))
        self.assertEqual(1, self.store.count("event_log"))
        self.assertEqual(1, self.store.count("outbox_messages"))
        self.assertEqual(1, self.store.count("command_receipts"))
        self.assertEqual(TaskState.READY, self.store.read_task("task-a").state)
        self.assertEqual(TaskState.BLOCKED, self.store.read_task("task-b").state)

    def test_patch_command_idempotency_and_payload_conflict(self):
        command = self.patch_command([self.task("task-a")])
        first = self.plane.apply_work_graph_patch(command)
        retry = self.patch_command([self.task("task-a")])
        second = self.plane.apply_work_graph_patch(retry)

        self.assertEqual(first, second)
        self.assertEqual(1, self.store.graph_version("project-1"))
        self.assertEqual(1, self.store.count("tasks"))
        self.assertEqual(1, self.store.count("outbox_messages"))

        conflicting = self.patch_command(
            [self.task("task-b")], version=0, key="graph-patch"
        )
        with self.assertRaisesRegex(CommandRejected, "IDEMPOTENCY_CONFLICT"):
            self.plane.apply_work_graph_patch(conflicting)

    def test_worker_cannot_apply_graph_patch(self):
        worker = Actor(ActorType.WORKER, "worker-graph-forgery")
        command = ApplyWorkGraphPatch(
            envelope("work_graph.apply_patch", worker, 0, "worker-graph-patch"),
            GraphPatch(0, "decision-1", (self.task("task-a"),)),
        )

        with self.assertRaisesRegex(
            CommandRejected, "CONTROL_PLANE_AUTHORITY_REQUIRED"
        ):
            self.plane.apply_work_graph_patch(command)

        self.assertEqual(0, self.store.graph_version("project-1"))
        self.assertEqual(0, self.store.count("tasks"))
        self.assertEqual(0, self.store.count("outbox_messages"))
        self.assertEqual(1, self.store.count("audit_records"))

    def test_stale_graph_version_is_rejected_without_effect(self):
        self.apply([self.task("task-a")])

        with self.assertRaisesRegex(CommandRejected, "GRAPH_VERSION_CONFLICT"):
            self.apply([self.task("task-b")], version=0, key="stale-patch")

        self.assertEqual(1, self.store.graph_version("project-1"))
        self.assertEqual(1, self.store.count("tasks"))
        self.assertEqual(1, self.store.count("outbox_messages"))

    def test_invalid_operation_is_validated_before_any_write(self):
        with self.assertRaisesRegex(CommandRejected, "TASK_NOT_FOUND"):
            self.apply(
                [
                    self.task("task-a"),
                    self.edge(
                        "invalid-edge",
                        "Task",
                        "missing-task",
                        "VERIFIED_BY",
                        "Verification",
                        "verification-1",
                    ),
                ],
                key="invalid-operation",
            )

        self.assertEqual(0, self.store.graph_version("project-1"))
        self.assertEqual(0, self.store.count("tasks"))
        self.assertEqual(0, self.store.count("work_graph_edges"))
        self.assertEqual(0, self.store.count("outbox_messages"))

    def test_failure_before_outbox_rolls_back_entire_patch(self):
        self.store.fail_once(FaultPoint.AFTER_EVENT_BEFORE_OUTBOX)

        with self.assertRaisesRegex(RuntimeError, "injected"):
            self.apply(
                [
                    self.task("task-a"),
                    self.edge(
                        "edge-a",
                        "Decision",
                        "decision-1",
                        "CREATED",
                        "Task",
                        "task-a",
                    ),
                ]
            )

        self.assertEqual(0, self.store.graph_version("project-1"))
        self.assertEqual(0, self.store.count("tasks"))
        self.assertEqual(0, self.store.count("work_graph_edges"))
        self.assertEqual(0, self.store.count("event_log"))
        self.assertEqual(0, self.store.count("outbox_messages"))
        self.assertEqual(0, self.store.count("command_receipts"))

    def test_self_two_node_and_indirect_cycles_are_atomic_rejections(self):
        scenarios = (
            (
                [self.task("task-a"), self.dependency("task-a", "task-a")],
                "self-cycle",
            ),
            (
                [
                    self.task("task-a"),
                    self.task("task-b"),
                    self.dependency("task-a", "task-b"),
                    self.dependency("task-b", "task-a"),
                ],
                "two-cycle",
            ),
            (
                [
                    self.task("task-a"),
                    self.task("task-b"),
                    self.task("task-c"),
                    self.dependency("task-a", "task-b"),
                    self.dependency("task-b", "task-c"),
                    self.dependency("task-c", "task-a"),
                ],
                "indirect-cycle",
            ),
        )
        for operations, key in scenarios:
            with self.subTest(key=key):
                self.store.reset_for_test()
                self.store.seed_project("project-1")
                with self.assertRaisesRegex(CommandRejected, "TASK_DAG_CYCLE"):
                    self.apply(operations, key=key)
                self.assertEqual(0, self.store.graph_version("project-1"))
                self.assertEqual(0, self.store.count("tasks"))
                self.assertEqual(0, self.store.count("task_dependencies"))
                self.assertEqual(0, self.store.count("work_graph_edges"))
                self.assertEqual(0, self.store.count("event_log"))
                self.assertEqual(0, self.store.count("outbox_messages"))
                self.assertEqual(1, self.store.count("audit_records"))

    def test_work_graph_feedback_cycle_is_accepted_and_does_not_affect_ready(self):
        self.apply(
            [
                self.task("task-a"),
                self.edge("e1", "Feedback", "feedback-1", "INFORMED", "Decision", "decision-1"),
                self.edge("e2", "Decision", "decision-1", "CREATED", "Task", "task-a"),
                self.edge("e3", "Task", "task-a", "VERIFIED_BY", "Verification", "verification-1"),
                self.edge("e4", "Verification", "verification-1", "EMITTED", "Feedback", "feedback-1"),
            ]
        )

        self.assertEqual(4, self.store.count("work_graph_edges"))
        self.assertEqual(0, self.store.count("task_dependencies"))
        self.assertEqual(TaskState.READY, self.store.read_task("task-a").state)

    def test_cycle_patch_preserves_prior_valid_work_graph_cycle(self):
        self.store.seed_task("task-a", TaskState.NEW, 0)
        self.store.seed_task("task-b", TaskState.NEW, 0)
        self.apply(
            [
                self.dependency("task-a", "task-b"),
                self.edge("e1", "Feedback", "feedback-1", "INFORMED", "Decision", "decision-1"),
                self.edge("e2", "Decision", "decision-1", "CREATED", "Task", "task-a"),
                self.edge("e3", "Task", "task-a", "VERIFIED_BY", "Verification", "verification-1"),
                self.edge("e4", "Verification", "verification-1", "EMITTED", "Feedback", "feedback-1"),
            ]
        )

        with self.assertRaisesRegex(CommandRejected, "TASK_DAG_CYCLE"):
            self.apply(
                [self.dependency("task-b", "task-a")],
                version=1,
                key="cycle-patch",
            )

        self.assertEqual(1, self.store.graph_version("project-1"))
        self.assertEqual(1, self.store.count("task_dependencies"))
        self.assertEqual(5, self.store.count("work_graph_edges"))
        self.assertEqual(1, self.store.count("outbox_messages"))
        self.assertEqual(TaskState.BLOCKED, self.store.read_task("task-a").state)
        self.assertEqual(TaskState.READY, self.store.read_task("task-b").state)

    def test_concurrent_patches_cannot_combine_into_a_cycle(self):
        self.store.seed_task("task-a", TaskState.NEW, 0)
        self.store.seed_task("task-b", TaskState.NEW, 0)
        barrier = threading.Barrier(2)
        outcomes = []

        def run(command):
            plane = ControlPlane(PostgresGraphStore(DATABASE_URL))
            barrier.wait()
            try:
                plane.apply_work_graph_patch(command)
                outcomes.append("APPLIED")
            except CommandRejected as exc:
                outcomes.append(exc.code)

        commands = (
            self.patch_command([self.dependency("task-a", "task-b")], key="race-a"),
            self.patch_command([self.dependency("task-b", "task-a")], key="race-b"),
        )
        threads = [threading.Thread(target=run, args=(command,)) for command in commands]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(1, outcomes.count("APPLIED"))
        self.assertEqual(1, outcomes.count("GRAPH_VERSION_CONFLICT"))
        self.assertEqual(1, self.store.graph_version("project-1"))
        self.assertEqual(1, self.store.count("task_dependencies"))

    def test_ready_recompute_uses_only_authoritative_dependencies_and_is_idempotent(self):
        self.store.seed_passed_task_authority("dep-a", 1)
        self.store.seed_task("dep-b", TaskState.RUNNING, 1)
        self.apply(
            [
                self.task("task-target"),
                self.dependency("task-target", "dep-a"),
                self.dependency("task-target", "dep-b"),
            ]
        )
        self.assertEqual(TaskState.BLOCKED, self.store.read_task("task-target").state)

        self.store.seed_passed_task_authority("dep-b", 1)
        command = RecomputeTaskReadiness(
            envelope("task.recompute_readiness", self.control, 1, "ready-event-1"),
            ("task-target",),
        )
        first = self.plane.recompute_task_readiness(command)
        second = self.plane.recompute_task_readiness(command)

        self.assertEqual(first, second)
        self.assertEqual(TaskState.READY, self.store.read_task("task-target").state)
        self.assertEqual(2, self.store.count("outbox_messages"))

    def test_duplicate_feedback_event_creates_one_stable_repair_task(self):
        self.store.seed_task("source-task", TaskState.FAILED, 2)
        self.store.seed_feedback_created(
            "feedback-event-1",
            "feedback-1",
            "source-task",
            "verification-1",
            "decision-feedback-1",
            "repair-task-1",
        )
        first = ConsumeFeedbackCreated(
            envelope("feedback.consume_created", self.control, 0, "feedback-delivery-1"),
            "graph-feedback-consumer",
            "feedback-event-1",
        )
        duplicate = ConsumeFeedbackCreated(
            envelope("feedback.consume_created", self.control, 0, "feedback-delivery-2"),
            "graph-feedback-consumer",
            "feedback-event-1",
        )

        self.assertTrue(self.plane.consume_feedback_created(first))
        self.assertFalse(self.plane.consume_feedback_created(duplicate))
        self.assertEqual(1, self.store.count_repair_tasks("feedback-event-1"))
        self.assertEqual(2, self.store.count("work_graph_edges"))
        self.assertEqual(1, self.store.graph_version("project-1"))
        self.assertEqual(2, self.store.count("outbox_messages"))
        self.assertEqual(1, self.store.count("consumer_inbox"))
        self.assertEqual(1, self.store.count("consumer_checkpoints"))
        self.assertEqual(
            1,
            self.store.scalar(
                "SELECT last_sequence FROM consumer_checkpoints WHERE consumer_id = 'graph-feedback-consumer'"
            ),
        )

    def test_feedback_consumer_crash_before_checkpoint_replays_safely(self):
        self.store.seed_task("source-task", TaskState.FAILED, 2)
        self.store.seed_feedback_created(
            "feedback-event-1", "feedback-1", "source-task", "verification-1",
            "decision-feedback-1", "repair-task-1"
        )
        self.store.fail_once(FaultPoint.AFTER_GRAPH_PROCESSING_BEFORE_CHECKPOINT)
        command = ConsumeFeedbackCreated(
            envelope("feedback.consume_created", self.control, 0, "feedback-delivery"),
            "graph-feedback-consumer",
            "feedback-event-1",
        )

        with self.assertRaisesRegex(RuntimeError, "injected"):
            self.plane.consume_feedback_created(command)
        self.assertTrue(self.plane.consume_feedback_created(command))

        self.assertEqual(1, self.store.count_repair_tasks("feedback-event-1"))
        self.assertEqual(1, self.store.graph_version("project-1"))
        self.assertEqual(2, self.store.count("outbox_messages"))
        self.assertEqual(1, self.store.count("consumer_inbox"))
        self.assertEqual(1, self.store.count("consumer_checkpoints"))

    def test_two_connections_consume_same_feedback_event_once(self):
        self.store.seed_task("source-task", TaskState.FAILED, 2)
        self.store.seed_feedback_created(
            "feedback-event-1", "feedback-1", "source-task", "verification-1",
            "decision-feedback-1", "repair-task-1"
        )
        barrier = threading.Barrier(2)
        outcomes = []

        def run(key):
            plane = ControlPlane(PostgresGraphStore(DATABASE_URL))
            command = ConsumeFeedbackCreated(
                envelope("feedback.consume_created", self.control, 0, key),
                "graph-feedback-consumer",
                "feedback-event-1",
            )
            barrier.wait()
            outcomes.append(plane.consume_feedback_created(command))

        threads = [
            threading.Thread(target=run, args=("delivery-a",)),
            threading.Thread(target=run, args=("delivery-b",)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertCountEqual([True, False], outcomes)
        self.assertEqual(1, self.store.count_repair_tasks("feedback-event-1"))
        self.assertEqual(2, self.store.count("work_graph_edges"))
        self.assertEqual(1, self.store.graph_version("project-1"))
        self.assertEqual(2, self.store.count("outbox_messages"))


if __name__ == "__main__":
    if not DATABASE_URL:
        raise SystemExit("HERMES_TEST_DATABASE_URL is required for integration tests")
    unittest.main()
