from typing import Any, Dict, List, Optional, Set, Tuple

from psycopg.types.json import Jsonb

from hermes_runtime.application.commands import (
    ApplyWorkGraphPatch,
    ConsumeFeedbackCreated,
    RecomputeTaskReadiness,
)
from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.domain.graph import (
    AddTaskDependency,
    AddTypedWorkGraphEdge,
    CreateTask,
    GraphTask,
    GraphOperation,
    GraphPatch,
    GraphRejected,
    NodeRef,
    calculate_ready_state,
    validate_task_dag,
)
from hermes_runtime.domain.models import CommandEnvelope, CommandReceipt, TaskState
from hermes_runtime.infrastructure.postgres import FaultPoint, PostgresRuntimeStore


class PostgresGraphStore(PostgresRuntimeStore):
    def reset_for_test(self) -> None:
        tables = (
            "delivery_operational_alerts",
            "delivery_metric_counters",
            "local_transport_publications",
            "consumer_quarantine",
            "consumer_pending_gaps",
            "outbox_redrive_records",
            "outbox_delivery_dlq",
            "outbox_delivery_attempts",
            "feedback_records",
            "task_dependencies",
            "work_graph_edges",
            "project_graph_versions",
            "consumer_checkpoints",
            "consumer_effects",
            "consumer_inbox",
            "audit_records",
            "outbox_messages",
            "event_log",
            "event_partition_sequences",
            "verification_evidence",
            "verification_results",
            "evidence",
            "completion_claims",
            "artifacts",
            "command_receipts",
            "verifier_identities",
            "tasks",
        )
        with self._connect() as connection:
            connection.execute(
                "TRUNCATE {} RESTART IDENTITY CASCADE".format(", ".join(tables))
            )

    def seed_project(self, project_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO project_graph_versions (project_id, graph_version)
                VALUES (%s, 0)
                """,
                (project_id,),
            )

    def seed_task_state_for_test(self, task_id: str, state: TaskState) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE tasks SET state = %s, version = version + 1 WHERE task_id = %s",
                (state.value, task_id),
            )

    def graph_version(self, project_id: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT graph_version FROM project_graph_versions WHERE project_id = %s",
                (project_id,),
            ).fetchone()
            if not row:
                raise CommandRejected("PROJECT_NOT_FOUND")
            return int(row[0])

    def count(self, table: str) -> int:
        graph_tables = {
            "project_graph_versions",
            "task_dependencies",
            "work_graph_edges",
            "feedback_records",
        }
        if table in graph_tables:
            return int(self.scalar("SELECT count(*) FROM {}".format(table)))
        return super().count(table)

    def count_repair_tasks(self, source_event_id: str) -> int:
        with self._connect() as connection:
            return int(
                connection.execute(
                    """
                    SELECT count(*) FROM tasks
                    WHERE source_feedback_event_id = %s AND task_type = 'repair'
                    """,
                    (source_event_id,),
                ).fetchone()[0]
            )

    def apply_work_graph_patch(
        self, command: ApplyWorkGraphPatch
    ) -> CommandReceipt:
        request_hash = self._command_hash(command)
        try:
            with self._connect() as connection:
                existing = self._begin_command(
                    connection, command.envelope, request_hash
                )
                if existing:
                    return existing
                new_version, affected, readiness_changes = self._apply_patch_in_transaction(
                    connection,
                    command.envelope,
                    command.patch,
                )
                self._trigger_fault(FaultPoint.AFTER_GRAPH_BEFORE_EVENT)
                event_id = self._append_event_and_outbox(
                    connection,
                    command.envelope,
                    "work_graph.patch.applied",
                    {
                        "base_graph_version": command.patch.base_graph_version,
                        "graph_version": new_version,
                        "decision_id": command.patch.decision_id,
                        "affected_task_ids": sorted(affected),
                        "readiness_changes": readiness_changes,
                        "operation_count": len(command.patch.operations),
                    },
                )
                receipt = CommandReceipt(
                    command.envelope.command_id,
                    "APPLIED",
                    "WORK_GRAPH_PATCH_APPLIED",
                    new_version,
                    (event_id,),
                    {
                        "project_id": command.envelope.project_id,
                        "graph_version": new_version,
                        "affected_task_ids": sorted(affected),
                    },
                )
                self._complete_command(connection, command.envelope, receipt)
                return receipt
        except GraphRejected as exc:
            rejected = CommandRejected(str(exc))
            self._persist_rejection(
                command.envelope, request_hash, rejected.code, rejected.detail
            )
            raise rejected
        except CommandRejected as exc:
            self._persist_rejection(command.envelope, request_hash, exc.code, exc.detail)
            raise

    def recompute_task_readiness(
        self, command: RecomputeTaskReadiness
    ) -> CommandReceipt:
        request_hash = self._command_hash(command)
        try:
            with self._connect() as connection:
                existing = self._begin_command(
                    connection, command.envelope, request_hash
                )
                if existing:
                    return existing
                graph_version = self._lock_graph_version(
                    connection,
                    command.envelope.project_id,
                    command.envelope.expected_version,
                )
                changed = self._recompute_readiness(
                    connection,
                    command.envelope.project_id,
                    set(command.task_ids),
                )
                event_ids: Tuple[str, ...] = ()
                if changed:
                    event_ids = (
                        self._append_event_and_outbox(
                            connection,
                            command.envelope,
                            "task.readiness_recomputed",
                            {
                                "graph_version": graph_version,
                                "ready_state_changes": changed,
                            },
                        ),
                    )
                receipt = CommandReceipt(
                    command.envelope.command_id,
                    "APPLIED",
                    "TASK_READINESS_RECOMPUTED",
                    graph_version,
                    event_ids,
                    {"changed": changed},
                )
                self._complete_command(connection, command.envelope, receipt)
                return receipt
        except CommandRejected as exc:
            self._persist_rejection(command.envelope, request_hash, exc.code, exc.detail)
            raise

    def consume_feedback_created(
        self, command: ConsumeFeedbackCreated
    ) -> bool:
        event: Optional[Tuple[str, int]] = None
        effect_applied = False
        with self._connect() as connection:
            event_row = connection.execute(
                """
                SELECT partition_key, sequence, payload, schema_version,
                       public.hermes_event_envelope(event_id)
                FROM event_log
                WHERE event_id = %s AND event_type = 'feedback.created'
                """,
                (command.event_id,),
            ).fetchone()
            if not event_row:
                raise CommandRejected("FEEDBACK_EVENT_NOT_FOUND")
            event = (event_row[0], event_row[1])
            connection.execute(
                """
                INSERT INTO consumer_checkpoints
                  (consumer_id, partition_key, last_sequence)
                VALUES (%s, %s, 0) ON CONFLICT DO NOTHING
                """,
                (command.consumer_id, event[0]),
            )
            checkpoint = connection.execute(
                """
                SELECT last_sequence FROM consumer_checkpoints
                WHERE consumer_id = %s AND partition_key = %s FOR UPDATE
                """,
                (command.consumer_id, event[0]),
            ).fetchone()[0]
            inserted = connection.execute(
                """
                INSERT INTO consumer_inbox(
                    consumer_id, event_id, partition_key, sequence,
                    schema_version, processing_result, raw_envelope
                ) VALUES (%s, %s, %s, %s, %s,
                          '{"classification":"APPLIED"}'::jsonb, %s)
                ON CONFLICT DO NOTHING
                RETURNING event_id
                """,
                (
                    command.consumer_id,
                    command.event_id,
                    event_row[0],
                    event_row[1],
                    event_row[3],
                    Jsonb(event_row[4]),
                ),
            ).fetchone()
            if inserted:
                if event[1] != checkpoint + 1:
                    raise CommandRejected("CONSUMER_SEQUENCE_NOT_CONTIGUOUS")
                effect_applied = True
                request_hash = self._command_hash(command)
                existing = self._begin_command(
                    connection, command.envelope, request_hash
                )
                if existing:
                    raise CommandRejected("FEEDBACK_EFFECT_WITH_EXISTING_COMMAND")
                payload = event_row[2]
                patch = GraphPatch(
                    int(payload["base_graph_version"]),
                    payload["decision_id"],
                    self._feedback_operations(payload),
                )
                new_version, affected, readiness_changes = self._apply_patch_in_transaction(
                    connection, command.envelope, patch
                )
                connection.execute(
                    """
                    UPDATE tasks SET source_feedback_event_id = %s
                    WHERE task_id = %s AND project_id = %s
                    """,
                    (
                        command.event_id,
                        payload["repair_task_id"],
                        command.envelope.project_id,
                    ),
                )
                event_id = self._append_event_and_outbox(
                    connection,
                    command.envelope,
                    "work_graph.patch.applied",
                    {
                        "causation_event_id": command.event_id,
                        "graph_version": new_version,
                        "decision_id": patch.decision_id,
                        "affected_task_ids": sorted(affected),
                        "readiness_changes": readiness_changes,
                    },
                )
                receipt = CommandReceipt(
                    command.envelope.command_id,
                    "APPLIED",
                    "FEEDBACK_REPAIR_TASK_CREATED",
                    new_version,
                    (event_id,),
                    {
                        "repair_task_id": payload["repair_task_id"],
                        "graph_version": new_version,
                    },
                )
                self._complete_command(connection, command.envelope, receipt)
                connection.execute(
                    """
                    INSERT INTO consumer_effects (consumer_id, event_id, effect_count)
                    VALUES (%s, %s, 1)
                    """,
                    (command.consumer_id, command.event_id),
                )
                self._trigger_fault(FaultPoint.AFTER_GRAPH_PROCESSING_BEFORE_CHECKPOINT)
                connection.execute(
                    """
                    UPDATE consumer_checkpoints
                    SET last_sequence = %s, updated_at = now()
                    WHERE consumer_id = %s AND partition_key = %s
                      AND last_sequence = %s
                    """,
                    (event[1], command.consumer_id, event[0], checkpoint),
                )
            elif event[1] == checkpoint + 1:
                connection.execute(
                    """
                    UPDATE consumer_checkpoints
                    SET last_sequence = %s, updated_at = now()
                    WHERE consumer_id = %s AND partition_key = %s
                      AND last_sequence = %s
                    """,
                    (event[1], command.consumer_id, event[0], checkpoint),
                )
        return effect_applied

    def seed_feedback_created(
        self,
        event_id: str,
        feedback_id: str,
        source_task_id: str,
        verification_id: str,
        decision_id: str,
        repair_task_id: str,
    ) -> None:
        command_id = "cmd-seed-" + event_id
        payload = {
            "feedback_id": feedback_id,
            "source_task_id": source_task_id,
            "verification_id": verification_id,
            "decision_id": decision_id,
            "repair_task_id": repair_task_id,
            "repair_title": "Repair from {}".format(feedback_id),
            "base_graph_version": self.graph_version("project-1"),
        }
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO command_receipts
                  (command_id, project_id, command_type, idempotency_key,
                   request_hash, status, result, completed_at)
                VALUES (%s, 'project-1', 'test.seed_feedback', %s, %s,
                        'APPLIED', '{}'::jsonb, now())
                """,
                (command_id, event_id, self._hash_value(payload)),
            )
            sequence = connection.execute(
                """
                INSERT INTO event_log
                  (event_id, event_type, schema_version, producer_type, producer_id,
                   project_id, partition_key, command_id, correlation_id, payload)
                VALUES (%s, 'feedback.created', '1.2', 'verification_engine',
                        'verifier-seed', 'project-1', 'project-1', %s, %s, %s)
                RETURNING sequence
                """,
                (event_id, command_id, event_id, Jsonb(payload)),
            ).fetchone()[0]
            connection.execute(
                """
                INSERT INTO outbox_messages
                  (message_id, event_id, topic, partition_key, sequence, payload)
                VALUES (%s, %s, 'hermes.runtime.events', 'project-1', %s, %s)
                """,
                ("msg-" + event_id, event_id, sequence, Jsonb(payload)),
            )
            connection.execute(
                """
                INSERT INTO feedback_records
                  (feedback_id, project_id, source_event_id, source_task_id,
                   verification_id, decision_id, repair_task_id)
                VALUES (%s, 'project-1', %s, %s, %s, %s, %s)
                """,
                (
                    feedback_id,
                    event_id,
                    source_task_id,
                    verification_id,
                    decision_id,
                    repair_task_id,
                ),
            )

    def seed_consumer_checkpoint(
        self, consumer_id: str, partition_key: str, sequence: int
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO consumer_checkpoints
                  (consumer_id, partition_key, last_sequence)
                VALUES (%s, %s, %s)
                """,
                (consumer_id, partition_key, sequence),
            )

    def _apply_patch_in_transaction(
        self,
        connection,
        envelope: CommandEnvelope,
        patch: GraphPatch,
    ) -> Tuple[int, Set[str], List[Dict[str, str]]]:
        if envelope.expected_version != patch.base_graph_version:
            raise CommandRejected("GRAPH_VERSION_ENVELOPE_MISMATCH")
        if not envelope.reason.strip():
            raise CommandRejected("COMMAND_REASON_REQUIRED")
        if not patch.decision_id or not patch.operations:
            raise GraphRejected("INVALID_GRAPH_PATCH")
        self._lock_graph_version(
            connection, envelope.project_id, patch.base_graph_version
        )
        existing_tasks = {
            row[0]
            for row in connection.execute(
                "SELECT task_id FROM tasks WHERE project_id = %s",
                (envelope.project_id,),
            ).fetchall()
        }
        existing_dependencies = {
            (row[0], row[1])
            for row in connection.execute(
                """
                SELECT task_id, depends_on_task_id FROM task_dependencies
                WHERE project_id = %s
                """,
                (envelope.project_id,),
            ).fetchall()
        }
        proposed_tasks = set(existing_tasks)
        proposed_dependencies = set(existing_dependencies)
        existing_edges = {
            (row[0], (row[1], row[2], row[3], row[4], row[5]))
            for row in connection.execute(
                """
                SELECT edge_id, source_type, source_id, edge_type,
                       target_type, target_id
                FROM work_graph_edges WHERE project_id = %s
                """,
                (envelope.project_id,),
            ).fetchall()
        }
        proposed_edge_ids = {edge_id for edge_id, _ in existing_edges}
        proposed_edge_keys = {edge_key for _, edge_key in existing_edges}
        affected = set()
        for operation in patch.operations:
            self._validate_operation(operation)
            if isinstance(operation, CreateTask):
                if operation.task.task_id in proposed_tasks:
                    raise GraphRejected("TASK_ALREADY_EXISTS")
                proposed_tasks.add(operation.task.task_id)
                affected.add(operation.task.task_id)
            elif isinstance(operation, AddTaskDependency):
                dependency = (operation.task_id, operation.depends_on_task_id)
                if dependency in proposed_dependencies:
                    raise GraphRejected("TASK_DEPENDENCY_ALREADY_EXISTS")
                proposed_dependencies.add(dependency)
                affected.update((operation.task_id, operation.depends_on_task_id))
            else:
                edge_key = (
                    operation.source.node_type,
                    operation.source.node_id,
                    operation.edge_type,
                    operation.target.node_type,
                    operation.target.node_id,
                )
                if (
                    operation.edge_id in proposed_edge_ids
                    or edge_key in proposed_edge_keys
                ):
                    raise GraphRejected("WORK_GRAPH_EDGE_ALREADY_EXISTS")
                proposed_edge_ids.add(operation.edge_id)
                proposed_edge_keys.add(edge_key)
                for node in (operation.source, operation.target):
                    if node.node_type == "Task" and node.node_id not in proposed_tasks:
                        raise GraphRejected("TASK_NOT_FOUND")
        validate_task_dag(proposed_tasks, proposed_dependencies)

        for operation in patch.operations:
            if isinstance(operation, CreateTask):
                connection.execute(
                    """
                    INSERT INTO tasks
                      (task_id, project_id, state, version, task_type, title,
                       created_by_graph_command_id)
                    VALUES (%s, %s, 'NEW', 0, %s, %s, %s)
                    """,
                    (
                        operation.task.task_id,
                        envelope.project_id,
                        operation.task.task_type,
                        operation.task.title,
                        envelope.command_id,
                    ),
                )
            elif isinstance(operation, AddTaskDependency):
                connection.execute(
                    """
                    INSERT INTO task_dependencies
                      (project_id, task_id, depends_on_task_id, created_by_command_id)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (
                        envelope.project_id,
                        operation.task_id,
                        operation.depends_on_task_id,
                        envelope.command_id,
                    ),
                )
                self._insert_work_edge(
                    connection,
                    envelope,
                    "dependency:{}:{}".format(
                        operation.task_id, operation.depends_on_task_id
                    ),
                    "Task",
                    operation.task_id,
                    "DEPENDS_ON",
                    "Task",
                    operation.depends_on_task_id,
                )
            else:
                self._insert_work_edge(
                    connection,
                    envelope,
                    operation.edge_id,
                    operation.source.node_type,
                    operation.source.node_id,
                    operation.edge_type,
                    operation.target.node_type,
                    operation.target.node_id,
                )
        readiness_changes = self._recompute_readiness(
            connection, envelope.project_id, affected
        )
        new_version = patch.base_graph_version + 1
        connection.execute(
            """
            UPDATE project_graph_versions
            SET graph_version = %s, updated_at = now()
            WHERE project_id = %s
            """,
            (new_version, envelope.project_id),
        )
        return new_version, affected, readiness_changes

    def _lock_graph_version(
        self, connection, project_id: str, expected_version: int
    ) -> int:
        row = connection.execute(
            """
            SELECT graph_version FROM project_graph_versions
            WHERE project_id = %s FOR UPDATE
            """,
            (project_id,),
        ).fetchone()
        if not row:
            raise CommandRejected("PROJECT_NOT_FOUND")
        current = int(row[0])
        if current != expected_version:
            raise CommandRejected(
                "GRAPH_VERSION_CONFLICT",
                "expected {}, current {}".format(expected_version, current),
            )
        return current

    @staticmethod
    def _validate_operation(operation: GraphOperation) -> None:
        if isinstance(operation, CreateTask):
            if not operation.task.task_id or not operation.task.title:
                raise GraphRejected("INVALID_TASK")
        elif isinstance(operation, AddTaskDependency):
            if not operation.task_id or not operation.depends_on_task_id:
                raise GraphRejected("INVALID_TASK_DEPENDENCY")
        elif isinstance(operation, AddTypedWorkGraphEdge):
            if operation.edge_type == "DEPENDS_ON":
                raise GraphRejected("DEPENDENCY_REQUIRES_TASK_OPERATION")
            if not all(
                (
                    operation.edge_id,
                    operation.source.node_type,
                    operation.source.node_id,
                    operation.edge_type,
                    operation.target.node_type,
                    operation.target.node_id,
                )
            ):
                raise GraphRejected("INVALID_WORK_GRAPH_EDGE")
        else:
            raise GraphRejected("UNKNOWN_GRAPH_OPERATION")

    def _insert_work_edge(
        self,
        connection,
        envelope: CommandEnvelope,
        edge_id: str,
        source_type: str,
        source_id: str,
        edge_type: str,
        target_type: str,
        target_id: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO work_graph_edges
              (edge_id, project_id, source_type, source_id, edge_type,
               target_type, target_id, created_by_command_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                edge_id,
                envelope.project_id,
                source_type,
                source_id,
                edge_type,
                target_type,
                target_id,
                envelope.command_id,
            ),
        )

    def _recompute_readiness(
        self, connection, project_id: str, task_ids: Set[str]
    ) -> List[Dict[str, str]]:
        changes = []
        for task_id in sorted(task_ids):
            task_row = connection.execute(
                "SELECT state FROM tasks WHERE project_id = %s AND task_id = %s",
                (project_id, task_id),
            ).fetchone()
            if not task_row:
                raise GraphRejected("TASK_NOT_FOUND")
            dependency_rows = connection.execute(
                """
                SELECT dependency.state
                FROM task_dependencies edge
                JOIN tasks dependency ON dependency.task_id = edge.depends_on_task_id
                WHERE edge.project_id = %s AND edge.task_id = %s
                ORDER BY dependency.task_id
                """,
                (project_id, task_id),
            ).fetchall()
            current = TaskState(task_row[0])
            target = calculate_ready_state(
                current, (TaskState(row[0]) for row in dependency_rows)
            )
            if target is current:
                continue
            connection.execute(
                """
                UPDATE tasks SET state = %s, version = version + 1, updated_at = now()
                WHERE project_id = %s AND task_id = %s
                """,
                (target.value, project_id, task_id),
            )
            changes.append(
                {"task_id": task_id, "from_state": current.value, "to_state": target.value}
            )
        return changes

    @staticmethod
    def _feedback_operations(payload: Dict[str, Any]) -> Tuple[GraphOperation, ...]:
        task = CreateTask(
            GraphTask(
                payload["repair_task_id"], "repair", payload["repair_title"]
            )
        )
        return (
            task,
            AddTypedWorkGraphEdge(
                "feedback-informed-" + payload["feedback_id"],
                NodeRef("Feedback", payload["feedback_id"]),
                "INFORMED",
                NodeRef("Decision", payload["decision_id"]),
            ),
            AddTypedWorkGraphEdge(
                "decision-created-" + payload["repair_task_id"],
                NodeRef("Decision", payload["decision_id"]),
                "CREATED",
                NodeRef("Task", payload["repair_task_id"]),
            ),
        )

    def _command_hash(self, command: Any) -> str:
        if isinstance(command, ApplyWorkGraphPatch):
            body = self._patch_dict(command.patch)
        elif isinstance(command, RecomputeTaskReadiness):
            body = {"task_ids": list(command.task_ids)}
        elif isinstance(command, ConsumeFeedbackCreated):
            body = {"consumer_id": command.consumer_id, "event_id": command.event_id}
        else:
            return super()._command_hash(command)
        envelope = command.envelope
        return self._hash_value(
            {
                "command_type": envelope.command_type,
                "expected_version": envelope.expected_version,
                "actor": self._actor_dict(envelope.actor),
                "reason": envelope.reason,
                "project_id": envelope.project_id,
                "body": body,
            }
        )

    @staticmethod
    def _patch_dict(patch: GraphPatch) -> Dict[str, Any]:
        operations = []
        for operation in patch.operations:
            if isinstance(operation, CreateTask):
                value = {
                    "operation": "CreateTask",
                    "task_id": operation.task.task_id,
                    "task_type": operation.task.task_type,
                    "title": operation.task.title,
                }
            elif isinstance(operation, AddTaskDependency):
                value = {
                    "operation": "AddTaskDependency",
                    "task_id": operation.task_id,
                    "depends_on_task_id": operation.depends_on_task_id,
                }
            else:
                value = {
                    "operation": "AddTypedWorkGraphEdge",
                    "edge_id": operation.edge_id,
                    "source_type": operation.source.node_type,
                    "source_id": operation.source.node_id,
                    "edge_type": operation.edge_type,
                    "target_type": operation.target.node_type,
                    "target_id": operation.target.node_id,
                }
            operations.append(value)
        return {
            "base_graph_version": patch.base_graph_version,
            "decision_id": patch.decision_id,
            "operations": operations,
        }
