from dataclasses import dataclass
from typing import FrozenSet, Iterable, Tuple, Union

from hermes_runtime.domain.models import TaskState


class GraphRejected(ValueError):
    pass


@dataclass(frozen=True)
class NodeRef:
    node_type: str
    node_id: str


@dataclass(frozen=True)
class GraphTask:
    task_id: str
    task_type: str
    title: str


@dataclass(frozen=True)
class CreateTask:
    task: GraphTask


@dataclass(frozen=True)
class AddTaskDependency:
    task_id: str
    depends_on_task_id: str


@dataclass(frozen=True)
class AddTypedWorkGraphEdge:
    edge_id: str
    source: NodeRef
    edge_type: str
    target: NodeRef


GraphOperation = Union[CreateTask, AddTaskDependency, AddTypedWorkGraphEdge]


@dataclass(frozen=True)
class GraphPatch:
    base_graph_version: int
    decision_id: str
    operations: Tuple[GraphOperation, ...]


def validate_task_dag(
    task_ids: Iterable[str], dependencies: Iterable[Tuple[str, str]]
) -> None:
    nodes: FrozenSet[str] = frozenset(task_ids)
    adjacency = {task_id: [] for task_id in nodes}
    for task_id, depends_on_task_id in dependencies:
        if task_id not in nodes or depends_on_task_id not in nodes:
            raise GraphRejected("TASK_NOT_FOUND")
        adjacency[task_id].append(depends_on_task_id)

    visiting = set()
    visited = set()

    def visit(task_id: str) -> None:
        if task_id in visiting:
            raise GraphRejected("TASK_DAG_CYCLE")
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency_id in adjacency[task_id]:
            visit(dependency_id)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in nodes:
        visit(task_id)


def calculate_ready_state(
    current_state: TaskState, dependency_states: Iterable[TaskState]
) -> TaskState:
    if current_state not in {TaskState.NEW, TaskState.READY, TaskState.BLOCKED}:
        return current_state
    states = tuple(dependency_states)
    if all(state is TaskState.PASSED for state in states):
        return TaskState.READY
    return TaskState.BLOCKED
