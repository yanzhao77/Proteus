import unittest

from hermes_runtime.domain.graph import (
    GraphRejected,
    calculate_ready_state,
    validate_task_dag,
)
from hermes_runtime.domain.models import TaskState


class TaskDagTests(unittest.TestCase):
    def test_acyclic_dependencies_are_accepted(self):
        validate_task_dag({"task-a", "task-b", "task-c"}, {
            ("task-a", "task-b"),
            ("task-b", "task-c"),
        })

    def test_self_cycle_is_rejected(self):
        with self.assertRaisesRegex(GraphRejected, "TASK_DAG_CYCLE"):
            validate_task_dag({"task-a"}, {("task-a", "task-a")})

    def test_two_node_cycle_is_rejected(self):
        with self.assertRaisesRegex(GraphRejected, "TASK_DAG_CYCLE"):
            validate_task_dag(
                {"task-a", "task-b"},
                {("task-a", "task-b"), ("task-b", "task-a")},
            )

    def test_indirect_cycle_is_rejected(self):
        with self.assertRaisesRegex(GraphRejected, "TASK_DAG_CYCLE"):
            validate_task_dag(
                {"task-a", "task-b", "task-c"},
                {
                    ("task-a", "task-b"),
                    ("task-b", "task-c"),
                    ("task-c", "task-a"),
                },
            )

    def test_unknown_dependency_endpoint_is_rejected(self):
        with self.assertRaisesRegex(GraphRejected, "TASK_NOT_FOUND"):
            validate_task_dag({"task-a"}, {("task-a", "task-missing")})


class ReadyCalculationTests(unittest.TestCase):
    def test_task_without_dependencies_is_ready(self):
        self.assertEqual(TaskState.READY, calculate_ready_state(TaskState.NEW, ()))

    def test_all_passed_dependencies_make_task_ready(self):
        self.assertEqual(
            TaskState.READY,
            calculate_ready_state(TaskState.BLOCKED, (TaskState.PASSED,) * 2),
        )

    def test_any_unpassed_dependency_blocks_task(self):
        self.assertEqual(
            TaskState.BLOCKED,
            calculate_ready_state(
                TaskState.NEW, (TaskState.PASSED, TaskState.RUNNING)
            ),
        )

    def test_failed_dependency_remains_blocked(self):
        self.assertEqual(
            TaskState.BLOCKED,
            calculate_ready_state(TaskState.READY, (TaskState.FAILED,)),
        )


if __name__ == "__main__":
    unittest.main()
