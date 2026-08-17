from typing import Any, Dict, Optional, Tuple

import psycopg

from hermes_runtime.application.commands import (
    CancelProject,
    CreateProject,
    PauseProject,
    RecordProjectEvidenceFact,
    RecordProjectPolicyFact,
    RequestProjectTransition,
    ResumeProject,
)
from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.domain.models import (
    Actor,
    CommandEnvelope,
    CommandReceipt,
    Project,
    ProjectState,
)
from hermes_runtime.domain.project_state_machine import (
    AUTHORITY_BUDGET,
    AUTHORITY_EVIDENCE,
    AUTHORITY_GATE,
    AUTHORITY_POLICY,
    ProjectAction,
    ProjectGuardContext,
    ProjectGuardFactSummary,
    ProjectGuardRejected,
    evaluate_project_transition,
    project_transition_requirements,
)
from hermes_runtime.infrastructure.postgres import FaultPoint
from hermes_runtime.infrastructure.postgres_graph import PostgresGraphStore


class PostgresProjectStore(PostgresGraphStore):
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
            "project_gate_decision_facts",
            "project_budget_facts",
            "project_policy_decision_facts",
            "project_evidence_facts",
            "project_transition_records",
            "projects",
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

    def count(self, table: str) -> int:
        if table in {
            "projects",
            "project_transition_records",
            "project_evidence_facts",
            "project_policy_decision_facts",
            "project_budget_facts",
            "project_gate_decision_facts",
        }:
            return int(self.scalar("SELECT count(*) FROM {}".format(table)))
        return super().count(table)

    def read_project(self, project_id: str) -> Project:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT project_id, state, version, resume_state
                FROM projects WHERE project_id = %s
                """,
                (project_id,),
            ).fetchone()
            if not row:
                raise CommandRejected("PROJECT_NOT_FOUND")
            return self._project_from_row(row)

    def create_project(self, command: CreateProject) -> CommandReceipt:
        request_hash = self._command_hash(command)
        try:
            with self._connect() as connection:
                existing = self._begin_command(
                    connection, command.envelope, request_hash
                )
                if existing:
                    return existing
                if command.envelope.expected_version != 0:
                    raise CommandRejected("VERSION_CONFLICT")
                if not command.title.strip():
                    raise CommandRejected("INVALID_PROJECT")
                self._trigger_fault(FaultPoint.BEFORE_PROJECT_UPDATE)
                actor = command.envelope.actor
                requester = command.requested_by
                connection.execute(
                    """
                    SELECT hermes_create_project_authority(
                        %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        command.envelope.project_id,
                        command.title,
                        command.envelope.command_id,
                        actor.actor_type.value,
                        actor.actor_id,
                        requester.actor_type.value,
                        requester.actor_id,
                        command.envelope.reason,
                    ),
                )
                self._trigger_fault(FaultPoint.AFTER_PROJECT_UPDATE_BEFORE_EVENT)
                event_id = self._append_project_event(
                    connection,
                    command.envelope,
                    "project.created",
                    None,
                    ProjectState.CREATED,
                    0,
                    requester,
                    (),
                )
                self._trigger_fault(FaultPoint.AFTER_PROJECT_OUTBOX_BEFORE_RECEIPT)
                receipt = self._project_receipt(
                    command.envelope,
                    "PROJECT_CREATED",
                    ProjectState.CREATED,
                    0,
                    event_id,
                )
                self._complete_command(connection, command.envelope, receipt)
                self._trigger_fault(FaultPoint.BEFORE_PROJECT_COMMIT)
                return receipt
        except CommandRejected as exc:
            self._persist_rejection(command.envelope, request_hash, exc.code, exc.detail)
            raise

    def request_project_transition(
        self, command: RequestProjectTransition
    ) -> CommandReceipt:
        return self._transition(
            command,
            ProjectAction.ADVANCE,
            command.target_state,
            "project.state_transition.applied",
            command.supporting_refs,
            "",
        )

    def pause_project(self, command: PauseProject) -> CommandReceipt:
        return self._transition(
            command, ProjectAction.PAUSE, None, "project.paused", (),
            command.authorization_ref,
        )

    def resume_project(self, command: ResumeProject) -> CommandReceipt:
        return self._transition(
            command, ProjectAction.RESUME, None, "project.resumed", (),
            command.authorization_ref,
        )

    def cancel_project(self, command: CancelProject) -> CommandReceipt:
        return self._transition(
            command, ProjectAction.CANCEL, None, "project.cancelled", (),
            command.authorization_ref,
        )

    def _transition(
        self,
        command,
        action: ProjectAction,
        target_state: Optional[ProjectState],
        event_type: str,
        supporting_refs: Tuple[str, ...],
        authorization_ref: str,
    ) -> CommandReceipt:
        request_hash = self._command_hash(command)
        try:
            with self._connect() as connection:
                existing = self._begin_command(
                    connection, command.envelope, request_hash
                )
                if existing:
                    return existing
                project = self._load_project(connection, command.envelope.project_id)
                self._check_project_version(
                    project, command.envelope.expected_version
                )
                guard = self._load_project_guard_context(
                    connection, project, action, target_state, supporting_refs
                )
                try:
                    decision = evaluate_project_transition(
                        project,
                        action,
                        target_state,
                        guard,
                    )
                except ProjectGuardRejected as exc:
                    raise CommandRejected(str(exc))
                self._trigger_fault(FaultPoint.BEFORE_PROJECT_UPDATE)
                next_version = self._execute_transition_function(
                    connection,
                    command.envelope,
                    command.requested_by,
                    project,
                    decision.target_state,
                    decision.resume_state,
                    authorization_ref,
                    guard,
                )
                self._trigger_fault(FaultPoint.AFTER_PROJECT_UPDATE_BEFORE_EVENT)
                event_id = self._append_project_event(
                    connection,
                    command.envelope,
                    event_type,
                    project.state,
                    decision.target_state,
                    next_version,
                    command.requested_by,
                    supporting_refs,
                    guard,
                )
                self._trigger_fault(FaultPoint.AFTER_PROJECT_OUTBOX_BEFORE_RECEIPT)
                receipt = self._project_receipt(
                    command.envelope,
                    "PROJECT_TRANSITION_APPLIED",
                    decision.target_state,
                    next_version,
                    event_id,
                )
                self._complete_command(connection, command.envelope, receipt)
                self._trigger_fault(FaultPoint.BEFORE_PROJECT_COMMIT)
                return receipt
        except ProjectGuardRejected as exc:
            rejected = CommandRejected(str(exc))
            self._persist_rejection(
                command.envelope, request_hash, rejected.code, rejected.detail
            )
            raise rejected
        except psycopg.errors.RaiseException as exc:
            code = exc.diag.message_primary
            if code == "PROJECT_AUTHORITY_PRECONDITION_FAILED":
                code = "VERSION_CONFLICT"
            rejected = CommandRejected(code)
            self._persist_rejection(command.envelope, request_hash, code, "")
            raise rejected
        except CommandRejected as exc:
            self._persist_rejection(command.envelope, request_hash, exc.code, exc.detail)
            raise

    def _load_project(self, connection, project_id: str) -> Project:
        row = connection.execute(
            """
            SELECT project_id, state, version, resume_state
            FROM projects WHERE project_id = %s
            """,
            (project_id,),
        ).fetchone()
        if not row:
            raise CommandRejected("PROJECT_NOT_FOUND")
        return self._project_from_row(row)

    @staticmethod
    def _project_from_row(row) -> Project:
        return Project(
            row[0],
            ProjectState(row[1]),
            int(row[2]),
            ProjectState(row[3]) if row[3] else None,
        )

    @staticmethod
    def _check_project_version(project: Project, expected_version: int) -> None:
        if project.version != expected_version:
            raise CommandRejected(
                "VERSION_CONFLICT",
                "expected {}, current {}".format(expected_version, project.version),
            )

    @staticmethod
    def _required_tasks_complete(connection, project_id: str) -> bool:
        connection.execute(
            """
            SELECT task_id FROM tasks
            WHERE project_id = %s
            ORDER BY task_id
            FOR SHARE
            """,
            (project_id,),
        ).fetchall()
        row = connection.execute(
            """
            SELECT
              EXISTS (
                SELECT 1 FROM tasks t
                WHERE t.project_id = %s
              )
              AND NOT EXISTS (
                SELECT 1 FROM tasks t
                LEFT JOIN verification_results v
                  ON v.verification_id = t.current_verification_id
                 AND v.task_id = t.task_id
                 AND v.artifact_id = t.current_artifact_id
                 AND v.artifact_hash = t.current_artifact_hash
                 AND v.verdict = 'PASS'
                 AND v.authority_status = 'AUTHORITATIVE'
                 AND v.plan_id = t.current_verification_plan_id
                 AND v.plan_version = t.current_verification_plan_version
                WHERE t.project_id = %s
                  AND (t.state <> 'PASSED' OR v.verification_id IS NULL)
              )
            """,
            (project_id, project_id),
        ).fetchone()
        return bool(row[0])

    def _load_project_guard_context(
        self,
        connection,
        project: Project,
        action: ProjectAction,
        target_state: Optional[ProjectState],
        supporting_refs: Tuple[str, ...],
    ) -> Optional[ProjectGuardContext]:
        requirements = project_transition_requirements(
            project.state, action, target_state
        )
        if not any(
            (
                requirements.evidence,
                requirements.policy,
                requirements.budget,
                requirements.gate_if_required,
                requirements.tasks_passed,
            )
        ):
            return None
        effective_target = target_state or (
            ProjectState.PAUSED if action is ProjectAction.PAUSE else project.resume_state
        )
        if effective_target is None:
            return ProjectGuardContext(project.project_id, project.version)
        evidence = (
            self._load_guard_fact(
                connection,
                "project_evidence_facts",
                "evidence_fact_id",
                "result",
                AUTHORITY_EVIDENCE,
                project,
                effective_target,
                supporting_refs,
            )
            if requirements.evidence
            else None
        )
        policy = (
            self._load_guard_fact(
                connection,
                "project_policy_decision_facts",
                "policy_decision_id",
                "result",
                AUTHORITY_POLICY,
                project,
                effective_target,
                supporting_refs,
            )
            if requirements.policy
            else None
        )
        budget = (
            self._load_guard_fact(
                connection,
                "project_budget_facts",
                "budget_fact_id",
                "status",
                AUTHORITY_BUDGET,
                project,
                effective_target,
                supporting_refs,
            )
            if requirements.budget
            else None
        )
        gate = None
        requires_human_gate = bool(policy and policy.result == "REQUIRE_HUMAN")
        if requirements.gate_if_required and requires_human_gate:
            gate = self._load_guard_fact(
                connection,
                "project_gate_decision_facts",
                "gate_decision_id",
                "status",
                AUTHORITY_GATE,
                project,
                effective_target,
                supporting_refs,
            )
        required_tasks_passed = True
        if requirements.tasks_passed:
            required_tasks_passed = self._required_tasks_complete(
                connection, project.project_id
            )
        refs = tuple(
            fact.fact_id
            for fact in (evidence, policy, budget, gate)
            if fact is not None
        )
        return ProjectGuardContext(
            project.project_id,
            project.version,
            evidence,
            policy,
            budget,
            gate,
            requires_human_gate,
            required_tasks_passed,
            refs,
        )

    @staticmethod
    def _load_guard_fact(
        connection,
        table: str,
        id_column: str,
        result_column: str,
        authority: str,
        project: Project,
        target_state: ProjectState,
        supporting_refs: Tuple[str, ...],
    ) -> Optional[ProjectGuardFactSummary]:
        allowed_tables = {
            "project_evidence_facts",
            "project_policy_decision_facts",
            "project_budget_facts",
            "project_gate_decision_facts",
        }
        if table not in allowed_tables:
            raise ValueError("unsupported guard fact table")
        refs = tuple(str(ref) for ref in supporting_refs)
        row = None
        if refs:
            row = connection.execute(
                """
                SELECT {id_column}, project_id, project_version, authority,
                       {result_column} AS result, valid, invalidated_at,
                       superseded_by, expires_at, from_state, to_state, now()
                FROM {table}
                WHERE {id_column} = ANY(%s)
                ORDER BY created_at DESC, {id_column}
                LIMIT 1
                FOR SHARE
                """.format(
                    id_column=id_column,
                    result_column=result_column,
                    table=table,
                ),
                (list(refs),),
            ).fetchone()
        if row is None:
            row = connection.execute(
                """
                SELECT {id_column}, project_id, project_version, authority,
                       {result_column} AS result, valid, invalidated_at,
                       superseded_by, expires_at, from_state, to_state, now()
                FROM {table}
                WHERE project_id = %s
                  AND project_version = %s
                  AND from_state = %s
                  AND to_state = %s
                  AND authority = %s
                ORDER BY created_at DESC, {id_column}
                LIMIT 1
                FOR SHARE
                """.format(
                    id_column=id_column,
                    result_column=result_column,
                    table=table,
                ),
                (
                    project.project_id,
                    project.version,
                    project.state.value,
                    target_state.value,
                    authority,
                ),
            ).fetchone()
        if row is None:
            return None
        current = bool(
            row[5]
            and row[6] is None
            and row[7] is None
            and (row[8] is None or row[8] > row[11])
            and row[2] == project.version
            and row[9] == project.state.value
            and row[10] == target_state.value
        )
        return ProjectGuardFactSummary(
            row[0],
            row[1],
            int(row[2]),
            bool(row[5]),
            current,
            row[3],
            row[4],
            (row[0],),
        )

    @staticmethod
    def _execute_transition_function(
        connection,
        envelope: CommandEnvelope,
        requester: Actor,
        project: Project,
        target_state: ProjectState,
        resume_state: Optional[ProjectState],
        authorization_ref: str,
        guard: Optional[ProjectGuardContext],
    ) -> int:
        evidence_fact_id = guard.evidence.fact_id if guard and guard.evidence else None
        policy_decision_id = guard.policy.fact_id if guard and guard.policy else None
        budget_fact_id = guard.budget.fact_id if guard and guard.budget else None
        gate_decision_id = guard.gate.fact_id if guard and guard.gate else None
        return int(
            connection.execute(
                """
                SELECT hermes_transition_project_authority(
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s
                )
                """,
                (
                    project.project_id,
                    project.version,
                    project.state.value,
                    target_state.value,
                    resume_state.value if resume_state else None,
                    envelope.command_id,
                    envelope.actor.actor_type.value,
                    envelope.actor.actor_id,
                    requester.actor_type.value,
                    requester.actor_id,
                    envelope.reason,
                    authorization_ref,
                    evidence_fact_id,
                    policy_decision_id,
                    budget_fact_id,
                    gate_decision_id,
                ),
            ).fetchone()[0]
        )

    def _append_project_event(
        self,
        connection,
        envelope: CommandEnvelope,
        event_type: str,
        previous_state: Optional[ProjectState],
        new_state: ProjectState,
        project_version: int,
        requester: Actor,
        supporting_refs: Tuple[str, ...],
        guard: Optional[ProjectGuardContext] = None,
    ) -> str:
        return self._append_event_and_outbox(
            connection,
            envelope,
            event_type,
            {
                "project_id": envelope.project_id,
                "project_version": project_version,
                "previous_state": previous_state.value if previous_state else None,
                "new_state": new_state.value,
                "actor": self._actor_dict(envelope.actor),
                "requested_by": self._actor_dict(requester),
                "reason": envelope.reason,
                "supporting_refs": list(supporting_refs),
                "guard_fact_refs": list(guard.fact_refs) if guard else [],
                "command_id": envelope.command_id,
            },
        )

    @staticmethod
    def _project_receipt(
        envelope: CommandEnvelope,
        result_code: str,
        state: ProjectState,
        version: int,
        event_id: str,
    ) -> CommandReceipt:
        return CommandReceipt(
            envelope.command_id,
            "APPLIED",
            result_code,
            version,
            (event_id,),
            {
                "project_id": envelope.project_id,
                "state": state.value,
                "version": version,
            },
        )

    def record_evidence_fact(self, command: RecordProjectEvidenceFact) -> CommandReceipt:
        return self._record_guard_fact(
            command,
            command_type="project.record_evidence_fact",
            event_type="project.evidence_fact_recorded",
            call=(
                "SELECT public.hermes_record_project_evidence_fact_authority("
                "%s,%s,%s,%s,%s,%s,%s,%s,%s)"
            ),
            args=(
                command.evidence_fact_id,
                command.envelope.project_id,
                command.project_version,
                command.from_state,
                command.to_state,
                command.subject_ref,
                command.envelope.command_id,
                command.envelope.actor.actor_type.value,
                command.envelope.reason,
            ),
        )

    def record_policy_fact(self, command: RecordProjectPolicyFact) -> CommandReceipt:
        return self._record_guard_fact(
            command,
            command_type="project.record_policy_fact",
            event_type="project.policy_fact_recorded",
            call=(
                "SELECT public.hermes_record_project_policy_fact_authority("
                "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
            ),
            args=(
                command.policy_decision_id,
                command.envelope.project_id,
                command.project_version,
                command.from_state,
                command.to_state,
                command.result,
                command.policy_bundle_version,
                command.input_hash,
                command.envelope.command_id,
                command.envelope.actor.actor_type.value,
                command.envelope.reason,
            ),
        )

    def _record_guard_fact(
        self,
        command: Any,
        *,
        command_type: str,
        event_type: str,
        call: str,
        args: Tuple[Any, ...],
    ) -> CommandReceipt:
        request_hash = self._command_hash(command)
        try:
            with self._connect() as connection:
                existing = self._begin_command(
                    connection, command.envelope, request_hash
                )
                if existing:
                    return existing
                connection.execute(call, args)
                event_id = self._append_event_and_outbox(
                    connection,
                    command.envelope,
                    event_type,
                    {
                        "project_id": command.envelope.project_id,
                        "project_version": command.project_version,
                        "from_state": command.from_state,
                        "to_state": command.to_state,
                        "actor": self._actor_dict(command.envelope.actor),
                        "reason": command.envelope.reason,
                        "command_id": command.envelope.command_id,
                    },
                )
                receipt = CommandReceipt(
                    command.envelope.command_id,
                    "APPLIED",
                    "PROJECT_GUARD_FACT_RECORDED",
                    command.project_version,
                    (event_id,),
                    {
                        "project_id": command.envelope.project_id,
                        "project_version": command.project_version,
                        "from_state": command.from_state,
                        "to_state": command.to_state,
                    },
                )
                self._complete_command(connection, command.envelope, receipt)
                return receipt
        except CommandRejected as exc:
            self._persist_rejection(
                command.envelope, request_hash, exc.code, exc.detail
            )
            raise
        except psycopg.errors.RaiseException as exc:
            code = exc.diag.message_primary
            rejected = CommandRejected(code)
            self._persist_rejection(command.envelope, request_hash, code, "")
            raise rejected

    def _command_hash(self, command: Any) -> str:
        if isinstance(command, CreateProject):
            body: Dict[str, Any] = {
                "title": command.title,
                "requested_by": self._actor_dict(command.requested_by),
            }
        elif isinstance(command, RequestProjectTransition):
            body = {
                "target_state": command.target_state.value,
                "requested_by": self._actor_dict(command.requested_by),
                "supporting_refs": list(command.supporting_refs),
            }
        elif isinstance(command, (PauseProject, ResumeProject, CancelProject)):
            body = {
                "requested_by": self._actor_dict(command.requested_by),
                "authorization_ref": command.authorization_ref,
            }
        elif isinstance(command, (RecordProjectEvidenceFact, RecordProjectPolicyFact)):
            body = {
                "project_version": command.project_version,
                "from_state": command.from_state,
                "to_state": command.to_state,
            }
            if isinstance(command, RecordProjectEvidenceFact):
                body["evidence_fact_id"] = command.evidence_fact_id
                body["subject_ref"] = command.subject_ref
            else:
                body["policy_decision_id"] = command.policy_decision_id
                body["result"] = command.result
                body["policy_bundle_version"] = command.policy_bundle_version
                body["input_hash"] = command.input_hash
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
