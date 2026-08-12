import hashlib
import json
import threading
import uuid
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

try:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb
except ImportError:  # Keeps pure-domain imports usable without the DB extra.
    psycopg = None
    dict_row = None
    Jsonb = None

from hermes_runtime.application.commands import (
    AdmitAgentRun,
    ApplyVerifiedTaskTransition,
    CreateVerificationPlan,
    InvalidateAgentRun,
    RecordVerificationResult,
    ReviseVerificationPlan,
    SubmitCompletionClaim,
)
from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.domain.models import (
    Actor,
    ActorType,
    AgentRunKind,
    AgentRunStatus,
    CommandEnvelope,
    CommandReceipt,
    Evidence,
    Task,
    TaskState,
    VerificationResult,
    VerificationCheckResult,
    Verdict,
)
from hermes_runtime.domain.state_machine import (
    GuardRejected,
    evaluate_completion_claim,
    evaluate_verified_transition,
    validate_verification_result,
)


class FaultPoint(str, Enum):
    AFTER_STATE_BEFORE_EVENT = "after_state_before_event"
    AFTER_FACT_BEFORE_EVENT = "after_fact_before_event"
    AFTER_CONSUMER_EFFECT_BEFORE_CHECKPOINT = "after_consumer_effect_before_checkpoint"
    AFTER_GRAPH_BEFORE_EVENT = "after_graph_before_event"
    AFTER_EVENT_BEFORE_OUTBOX = "after_event_before_outbox"
    AFTER_GRAPH_PROCESSING_BEFORE_CHECKPOINT = "after_graph_processing_before_checkpoint"
    BEFORE_PROJECT_UPDATE = "before_project_update"
    AFTER_PROJECT_UPDATE_BEFORE_EVENT = "after_project_update_before_event"
    AFTER_PROJECT_OUTBOX_BEFORE_RECEIPT = "after_project_outbox_before_receipt"
    BEFORE_PROJECT_COMMIT = "before_project_commit"
    AFTER_AGENT_RUN_BEFORE_EVENT = "after_agent_run_before_event"
    AFTER_PLAN_BEFORE_CHECK = "after_plan_before_check"
    AFTER_PLAN_CHECK_BEFORE_EVENT = "after_plan_check_before_event"
    AFTER_VERIFICATION_RESULT_BEFORE_CHECK = "after_verification_result_before_check"
    AFTER_VERIFICATION_CHECK_BEFORE_EVENT = "after_verification_check_before_event"


class PostgresRuntimeStore:
    def __init__(self, dsn: str) -> None:
        if psycopg is None:
            raise RuntimeError("psycopg 3 is required for PostgreSQL infrastructure")
        self._dsn = dsn
        self._faults = []
        self._fault_lock = threading.Lock()

    def fail_once(self, point: FaultPoint) -> None:
        with self._fault_lock:
            self._faults.append(point)

    def _trigger_fault(self, point: FaultPoint) -> None:
        with self._fault_lock:
            if point in self._faults:
                self._faults.remove(point)
                raise RuntimeError("injected failure: {}".format(point.value))

    def check_server_version(self, minimum: int) -> None:
        with self._connect() as connection:
            version = int(connection.execute("SHOW server_version_num").fetchone()[0])
            if version < minimum:
                raise RuntimeError(
                    "PostgreSQL {}+ required, got {}".format(minimum, version)
                )

    def apply_migration(self, path: Path) -> None:
        with self._connect() as connection:
            connection.execute(path.read_text())

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
            "consumer_checkpoints",
            "consumer_effects",
            "consumer_inbox",
            "audit_records",
            "outbox_messages",
            "event_log",
            "event_partition_sequences",
            "command_receipts",
            "verification_check_results",
            "verification_evidence",
            "verification_results",
            "verification_check_results",
            "verification_plan_checks",
            "verification_plans",
            "agent_runs",
            "evidence",
            "completion_claims",
            "artifacts",
            "verification_plan_checks",
            "verification_plans",
            "agent_runs",
            "verifier_identities",
            "tasks",
        )
        with self._connect() as connection:
            connection.execute(
                "TRUNCATE {} RESTART IDENTITY CASCADE".format(
                    ", ".join(tables)
                )
            )

    def seed_verifier(self, verifier_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO verifier_identities (verifier_id, active) VALUES (%s, true)",
                (verifier_id,),
            )

    def seed_task(self, task_id: str, state: TaskState, version: int) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO tasks (task_id, project_id, state, version) VALUES (%s, %s, %s, %s)",
                (task_id, "project-1", state.value, version),
            )

    def seed_closure_authority(
        self, task_id: str, worker_identity: str = "worker-1",
        verifier_identity: str = "verifier-1",
    ) -> None:
        """Test-only fixture for legacy slice tests; production uses Commands."""
        plan_id = "plan-" + task_id
        worker_run_id = "run-" + task_id
        verifier_run_id = "verifier-run-" + task_id
        with self._connect() as connection:
            for command_id, command_type, key in (
                ("seed-worker-run-" + task_id, "test.seed_run", "seed-worker-" + task_id),
                ("seed-verifier-run-" + task_id, "test.seed_run", "seed-verifier-" + task_id),
                ("seed-plan-" + task_id, "test.seed_plan", "seed-plan-" + task_id),
            ):
                connection.execute(
                    """INSERT INTO command_receipts(
                       command_id,project_id,command_type,idempotency_key,request_hash,
                       status,result,completed_at
                       ) VALUES (%s,'project-1',%s,%s,'seed','APPLIED','{}',now())""",
                    (command_id, command_type, key),
                )
            connection.execute(
                """INSERT INTO agent_runs(
                   run_id,project_id,task_id,run_kind,agent_identity,context_identity,
                   status,created_by,command_id
                   ) VALUES (%s,'project-1',%s,'WORKER',%s,%s,'ADMITTED',
                            'test-fixture',%s),
                            (%s,'project-1',%s,'VERIFIER',%s,%s,'ADMITTED',
                            'test-fixture',%s)""",
                (worker_run_id, task_id, worker_identity, "worker-context-" + task_id,
                 "seed-worker-run-" + task_id, verifier_run_id, task_id,
                 verifier_identity, "verifier-context-" + task_id,
                 "seed-verifier-run-" + task_id),
            )
            connection.execute(
                """INSERT INTO verification_plans(
                   verification_plan_id,task_id,project_id,version,status,
                   artifact_selectors,aggregation_rule,independence,created_by,command_id
                   ) VALUES (%s,%s,'project-1',1,'ACTIVE','[\"artifact\"]',
                             'all_required_pass','worker_context_excluded',
                             'test-fixture',%s)""",
                (plan_id, task_id, "seed-plan-" + task_id),
            )
            connection.execute(
                """INSERT INTO verification_plan_checks(
                   verification_plan_id,plan_version,check_id,type,runner_profile,
                   required,timeout_seconds,pass_condition,evidence_level,ordinal
                   ) VALUES (%s,1,'required-check','integration_test','test-runner',
                             true,60,'exit_code == 0','E2',0)""",
                (plan_id,),
            )
            connection.execute(
                """UPDATE tasks SET current_verification_plan_id=%s,
                   current_verification_plan_version=1 WHERE task_id=%s""",
                (plan_id, task_id),
            )

    def seed_passed_task_authority(self, task_id: str, version: int = 1) -> None:
        """Test-only complete authority fixture for dependency/Project Guard tests."""
        worker = "worker-" + task_id
        verifier = "verifier-" + task_id
        with self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM tasks WHERE task_id=%s", (task_id,)
            ).fetchone()
        if not exists:
            self.seed_task(task_id, TaskState.RUNNING, version)
        self.seed_verifier(verifier)
        self.seed_closure_authority(task_id, worker, verifier)
        plan_id = "plan-" + task_id
        worker_run_id = "run-" + task_id
        verifier_run_id = "verifier-run-" + task_id
        artifact_id = "artifact-" + task_id
        artifact_hash = "sha256:" + task_id
        verification_id = "verification-" + task_id
        command_id = "seed-verification-" + task_id
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO command_receipts(
                   command_id,project_id,command_type,idempotency_key,request_hash,
                   status,result,completed_at
                   ) VALUES (%s,'project-1','test.seed_verification',%s,'seed',
                             'APPLIED','{}',now())""",
                (command_id, command_id),
            )
            connection.execute(
                """INSERT INTO artifacts(
                   artifact_id,task_id,content_hash,media_type,produced_by,produced_by_run_id
                   ) VALUES (%s,%s,%s,'text/plain',%s,%s)""",
                (artifact_id, task_id, artifact_hash, worker, worker_run_id),
            )
            connection.execute(
                """INSERT INTO verification_results(
                   verification_id,task_id,artifact_id,artifact_hash,
                   verifier_identity,criteria,verdict,correlation_id,occurred_at,
                   command_id,authority_status,plan_id,plan_version,project_id,
                   verifier_run_id,started_at,completed_at
                   ) VALUES (%s,%s,%s,%s,%s,%s,'PASS',%s,now(),%s,
                             'AUTHORITATIVE',%s,1,'project-1',%s,now(),now())""",
                (verification_id, task_id, artifact_id, artifact_hash, verifier,
                 plan_id + ":1", "correlation-" + task_id, command_id,
                 plan_id, verifier_run_id),
            )
            connection.execute(
                """INSERT INTO verification_check_results(
                   verification_id,check_id,status,finding_codes,evidence_refs,
                   started_at,completed_at
                   ) VALUES (%s,'required-check','PASS','[]','[]',now(),now())""",
                (verification_id,),
            )
            connection.execute(
                """UPDATE tasks SET state='PASSED',current_artifact_id=%s,
                   current_artifact_hash=%s,current_verification_id=%s
                   WHERE task_id=%s""",
                (artifact_id, artifact_hash, verification_id, task_id),
            )

    def admit_agent_run(self, command: AdmitAgentRun) -> CommandReceipt:
        request_hash = self._command_hash(command)
        run = command.run
        try:
            with self._connect() as connection:
                existing = self._begin_command(connection, command.envelope, request_hash)
                if existing:
                    return existing
                task = self._load_task_for_update(connection, run.task_id)
                self._check_version(task, command.envelope.expected_version)
                if run.project_id != task.project_id or run.project_id != command.envelope.project_id:
                    raise CommandRejected("AGENT_RUN_PROJECT_MISMATCH")
                if run.status is not AgentRunStatus.ADMITTED or run.version != 1:
                    raise CommandRejected("AGENT_RUN_ADMISSION_STATE_INVALID")
                connection.execute(
                    """
                    INSERT INTO agent_runs(
                        run_id,project_id,task_id,run_kind,agent_identity,
                        context_identity,status,created_by,command_id,version
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (run.run_id, run.project_id, run.task_id, run.run_kind.value,
                     run.agent_identity, run.context_identity, run.status.value,
                     run.created_by.actor_id, command.envelope.command_id, run.version),
                )
                self._trigger_fault(FaultPoint.AFTER_AGENT_RUN_BEFORE_EVENT)
                event_id = self._append_event_and_outbox(
                    connection, command.envelope, "agent_run.admitted",
                    {"run_id": run.run_id, "task_id": run.task_id,
                     "run_kind": run.run_kind.value, "entity_version": run.version},
                )
                receipt = CommandReceipt(
                    command.envelope.command_id, "APPLIED", "AGENT_RUN_ADMITTED",
                    run.version, (event_id,), {"run_id": run.run_id},
                )
                self._complete_command(connection, command.envelope, receipt)
                return receipt
        except CommandRejected as exc:
            self._persist_rejection(command.envelope, request_hash, exc.code, exc.detail)
            raise

    def invalidate_agent_run(self, command: InvalidateAgentRun) -> CommandReceipt:
        request_hash = self._command_hash(command)
        try:
            with self._connect() as connection:
                existing = self._begin_command(connection, command.envelope, request_hash)
                if existing:
                    return existing
                row = connection.execute(
                    """SELECT project_id,task_id,status,version FROM agent_runs
                       WHERE run_id=%s FOR UPDATE""", (command.run_id,)
                ).fetchone()
                if not row:
                    raise CommandRejected("AGENT_RUN_NOT_FOUND")
                if row[0] != command.envelope.project_id:
                    raise CommandRejected("AGENT_RUN_PROJECT_MISMATCH")
                if row[3] != command.envelope.expected_version:
                    raise CommandRejected("VERSION_CONFLICT")
                if row[2] == AgentRunStatus.INVALIDATED.value:
                    raise CommandRejected("AGENT_RUN_ALREADY_INVALIDATED")
                target_version = row[3] + 1
                connection.execute(
                    """UPDATE agent_runs SET status='INVALIDATED',version=%s
                       WHERE run_id=%s AND version=%s""",
                    (target_version, command.run_id, row[3]),
                )
                event_id = self._append_event_and_outbox(
                    connection, command.envelope, "agent_run.invalidated",
                    {"run_id": command.run_id, "task_id": row[1],
                     "entity_version": target_version},
                )
                receipt = CommandReceipt(
                    command.envelope.command_id, "APPLIED", "AGENT_RUN_INVALIDATED",
                    target_version, (event_id,), {"run_id": command.run_id},
                )
                self._complete_command(connection, command.envelope, receipt)
                return receipt
        except CommandRejected as exc:
            self._persist_rejection(command.envelope, request_hash, exc.code, exc.detail)
            raise

    def create_verification_plan(
        self, command: CreateVerificationPlan
    ) -> CommandReceipt:
        return self._write_verification_plan(command, revise=False)

    def revise_verification_plan(
        self, command: ReviseVerificationPlan
    ) -> CommandReceipt:
        return self._write_verification_plan(command, revise=True)

    def _write_verification_plan(self, command, revise: bool) -> CommandReceipt:
        request_hash = self._command_hash(command)
        plan = command.plan
        try:
            with self._connect() as connection:
                existing = self._begin_command(connection, command.envelope, request_hash)
                if existing:
                    return existing
                task = self._load_task_for_update(connection, plan.task_id)
                self._check_version(task, command.envelope.expected_version)
                if plan.project_id != task.project_id or plan.project_id != command.envelope.project_id:
                    raise CommandRejected("VERIFICATION_PLAN_PROJECT_MISMATCH")
                self._validate_plan(plan)
                current = connection.execute(
                    """SELECT verification_plan_id,version FROM verification_plans
                       WHERE task_id=%s AND status='ACTIVE' FOR UPDATE""",
                    (plan.task_id,),
                ).fetchone()
                if revise:
                    if not current:
                        raise CommandRejected("CURRENT_VERIFICATION_PLAN_REQUIRED")
                    if plan.verification_plan_id != current[0] or plan.version != current[1] + 1:
                        raise CommandRejected("VERIFICATION_PLAN_REVISION_MISMATCH")
                    connection.execute(
                        """UPDATE verification_plans SET status='SUPERSEDED',superseded_at=now()
                           WHERE verification_plan_id=%s AND version=%s AND status='ACTIVE'""",
                        current,
                    )
                elif current or plan.version != 1:
                    raise CommandRejected("VERIFICATION_PLAN_ALREADY_EXISTS")
                connection.execute(
                    """INSERT INTO verification_plans(
                       verification_plan_id,task_id,project_id,version,status,
                       artifact_selectors,aggregation_rule,independence,created_by,command_id
                       ) VALUES (%s,%s,%s,%s,'ACTIVE',%s,%s,%s,%s,%s)""",
                    (plan.verification_plan_id, plan.task_id, plan.project_id, plan.version,
                     Jsonb(list(plan.artifact_selectors)), plan.aggregation_rule,
                     plan.independence, plan.created_by.actor_id, command.envelope.command_id),
                )
                self._trigger_fault(FaultPoint.AFTER_PLAN_BEFORE_CHECK)
                for check in plan.checks:
                    connection.execute(
                        """INSERT INTO verification_plan_checks(
                           verification_plan_id,plan_version,check_id,type,runner_profile,
                           required,timeout_seconds,pass_condition,evidence_level,ordinal
                           ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (plan.verification_plan_id, plan.version, check.check_id,
                         check.check_type, check.runner_profile, check.required,
                         check.timeout_seconds, check.pass_condition,
                         check.evidence_level, check.ordinal),
                    )
                target_version = task.version + 1
                connection.execute(
                    """UPDATE tasks SET current_verification_plan_id=%s,
                       current_verification_plan_version=%s,version=%s,updated_at=now()
                       WHERE task_id=%s""",
                    (plan.verification_plan_id, plan.version, target_version, task.task_id),
                )
                self._trigger_fault(FaultPoint.AFTER_PLAN_CHECK_BEFORE_EVENT)
                event_id = self._append_event_and_outbox(
                    connection, command.envelope,
                    "verification_plan.revised" if revise else "verification_plan.created",
                    {"verification_plan_id": plan.verification_plan_id,
                     "plan_version": plan.version, "task_id": task.task_id,
                     "entity_version": target_version},
                )
                receipt = CommandReceipt(
                    command.envelope.command_id, "APPLIED",
                    "VERIFICATION_PLAN_REVISED" if revise else "VERIFICATION_PLAN_CREATED",
                    target_version, (event_id,),
                    {"verification_plan_id": plan.verification_plan_id,
                     "plan_version": plan.version, "task_id": task.task_id},
                )
                self._complete_command(connection, command.envelope, receipt)
                return receipt
        except CommandRejected as exc:
            self._persist_rejection(command.envelope, request_hash, exc.code, exc.detail)
            raise

    @staticmethod
    def _validate_plan(plan) -> None:
        if plan.status != "ACTIVE":
            raise CommandRejected("VERIFICATION_PLAN_STATUS_INVALID")
        if plan.aggregation_rule != "all_required_pass":
            raise CommandRejected("UNSUPPORTED_AGGREGATION_RULE")
        if plan.independence != "worker_context_excluded":
            raise CommandRejected("UNSUPPORTED_INDEPENDENCE_POLICY")
        if not plan.checks or not any(check.required for check in plan.checks):
            raise CommandRejected("REQUIRED_VERIFICATION_CHECK_MISSING")
        ids = [check.check_id for check in plan.checks]
        ordinals = [check.ordinal for check in plan.checks]
        if len(ids) != len(set(ids)) or len(ordinals) != len(set(ordinals)):
            raise CommandRejected("DUPLICATE_VERIFICATION_PLAN_CHECK")
        if any(check.timeout_seconds <= 0 for check in plan.checks):
            raise CommandRejected("VERIFICATION_CHECK_INVALID")

    @staticmethod
    def _validate_check_results(connection, result: VerificationResult) -> None:
        rows = connection.execute(
            """SELECT check_id,required FROM verification_plan_checks
               WHERE verification_plan_id=%s AND plan_version=%s""",
            (result.plan_id, result.plan_version),
        ).fetchall()
        plan_checks = {row[0]: bool(row[1]) for row in rows}
        result_checks = [check.check_id for check in result.check_results]
        if len(result_checks) != len(set(result_checks)):
            raise CommandRejected("DUPLICATE_VERIFICATION_CHECK_RESULT")
        unknown = set(result_checks) - set(plan_checks)
        if unknown:
            raise CommandRejected("UNKNOWN_VERIFICATION_CHECK")
        required = {check_id for check_id, is_required in plan_checks.items() if is_required}
        if not required.issubset(result_checks):
            raise CommandRejected("REQUIRED_VERIFICATION_CHECK_RESULT_MISSING")
        evidence = {item.evidence_id: item for item in result.evidence}
        for check in result.check_results:
            if check.check_id in required and not check.evidence_refs:
                raise CommandRejected("REQUIRED_CHECK_EVIDENCE_MISSING")
            for evidence_ref in check.evidence_refs:
                item = evidence.get(evidence_ref)
                if not item:
                    raise CommandRejected("CHECK_EVIDENCE_REFERENCE_UNKNOWN")
                if (not item.valid or item.artifact_id != result.artifact_id
                        or item.artifact_hash != result.artifact_hash):
                    raise CommandRejected("CHECK_EVIDENCE_ARTIFACT_MISMATCH")
        required_statuses = [
            check.status for check in result.check_results if check.check_id in required
        ]
        if all(status is Verdict.PASS for status in required_statuses):
            aggregate = Verdict.PASS
        elif Verdict.FAIL in required_statuses:
            aggregate = Verdict.FAIL
        elif Verdict.ERROR in required_statuses:
            aggregate = Verdict.ERROR
        elif Verdict.INCONCLUSIVE in required_statuses:
            aggregate = Verdict.INCONCLUSIVE
        else:
            aggregate = Verdict.CANCELLED
        if result.verdict is not aggregate:
            raise CommandRejected("VERIFICATION_AGGREGATE_MISMATCH")

    def submit_completion_claim(
        self, command: SubmitCompletionClaim
    ) -> CommandReceipt:
        request_hash = self._command_hash(command)
        try:
            with self._connect() as connection:
                existing = self._begin_command(
                    connection, command.envelope, request_hash
                )
                if existing:
                    return existing
                task = self._load_task_for_update(connection, command.claim.task_id)
                self._check_version(task, command.envelope.expected_version)
                run = connection.execute(
                    """SELECT project_id,task_id,run_kind,agent_identity,
                              context_identity,status
                       FROM agent_runs WHERE run_id=%s FOR SHARE""",
                    (command.claim.run_id,),
                ).fetchone()
                if not run:
                    raise CommandRejected("WORKER_AGENT_RUN_NOT_FOUND")
                if run[0] != task.project_id or run[0] != command.envelope.project_id:
                    raise CommandRejected("WORKER_AGENT_RUN_PROJECT_MISMATCH")
                if run[1] != task.task_id:
                    raise CommandRejected("WORKER_AGENT_RUN_TASK_MISMATCH")
                if run[2] != AgentRunKind.WORKER.value:
                    raise CommandRejected("WORKER_AGENT_RUN_KIND_REQUIRED")
                if run[3] != command.claim.worker_identity.actor_id:
                    raise CommandRejected("WORKER_AGENT_RUN_IDENTITY_MISMATCH")
                if command.claim.artifact.produced_by != run[3]:
                    raise CommandRejected("ARTIFACT_PROVENANCE_RUN_MISMATCH")
                if run[5] not in {AgentRunStatus.ADMITTED.value, AgentRunStatus.COMPLETED.value}:
                    raise CommandRejected("WORKER_AGENT_RUN_NOT_ACTIVE")
                try:
                    decision = evaluate_completion_claim(
                        task,
                        command.claim.artifact.artifact_id,
                        command.claim.artifact.content_hash,
                    )
                except GuardRejected as exc:
                    raise CommandRejected(str(exc))
                if command.claim.artifact.task_id != task.task_id:
                    raise CommandRejected("ARTIFACT_TASK_MISMATCH")
                connection.execute(
                    """
                    INSERT INTO artifacts
                      (artifact_id, task_id, content_hash, media_type, produced_by,
                       produced_by_run_id)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        command.claim.artifact.artifact_id,
                        task.task_id,
                        command.claim.artifact.content_hash,
                        command.claim.artifact.media_type,
                        command.claim.artifact.produced_by,
                        command.claim.run_id,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO completion_claims
                      (claim_id, task_id, run_id, worker_identity, artifact_id,
                       artifact_hash, summary, command_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        command.claim.claim_id,
                        task.task_id,
                        command.claim.run_id,
                        command.claim.worker_identity.actor_id,
                        command.claim.artifact.artifact_id,
                        command.claim.artifact.content_hash,
                        command.claim.summary,
                        command.envelope.command_id,
                    ),
                )
                target_version = task.version + 1
                connection.execute(
                    """
                    UPDATE tasks
                    SET state = %s, version = %s, current_artifact_id = %s,
                        current_artifact_hash = %s,
                        completion_worker_identity = %s,
                        completion_worker_run_id = %s,
                        completion_worker_context_identity = %s, updated_at = now()
                    WHERE task_id = %s
                    """,
                    (
                        decision.target_state.value,
                        target_version,
                        command.claim.artifact.artifact_id,
                        command.claim.artifact.content_hash,
                        command.claim.worker_identity.actor_id,
                        command.claim.run_id,
                        run[4],
                        task.task_id,
                    ),
                )
                self._trigger_fault(FaultPoint.AFTER_STATE_BEFORE_EVENT)
                event_id = self._append_event_and_outbox(
                    connection,
                    command.envelope,
                    "task.completion_claimed",
                    {
                        "task_id": task.task_id,
                        "claim_id": command.claim.claim_id,
                        "artifact_id": command.claim.artifact.artifact_id,
                        "artifact_hash": command.claim.artifact.content_hash,
                        "from_state": task.state.value,
                        "to_state": decision.target_state.value,
                        "entity_version": target_version,
                    },
                )
                receipt = CommandReceipt(
                    command.envelope.command_id,
                    "APPLIED",
                    "COMPLETION_CLAIM_ADMITTED",
                    target_version,
                    (event_id,),
                    {
                        "task_id": task.task_id,
                        "state": decision.target_state.value,
                    },
                )
                self._complete_command(connection, command.envelope, receipt)
                return receipt
        except CommandRejected as exc:
            self._persist_rejection(command.envelope, request_hash, exc.code, exc.detail)
            raise

    def record_verification_result(
        self, command: RecordVerificationResult
    ) -> CommandReceipt:
        request_hash = self._command_hash(command)
        try:
            with self._connect() as connection:
                existing = self._begin_command(
                    connection, command.envelope, request_hash
                )
                if existing:
                    return existing
                task = self._load_task_for_update(connection, command.result.task_id)
                self._check_version(task, command.envelope.expected_version)
                result = command.result
                if result.project_id != task.project_id or result.project_id != command.envelope.project_id:
                    raise CommandRejected("VERIFICATION_PROJECT_MISMATCH")
                authorized = connection.execute(
                    "SELECT active FROM verifier_identities WHERE verifier_id = %s",
                    (command.result.verifier_identity.actor_id,),
                ).fetchone()
                if not authorized or not authorized[0]:
                    raise CommandRejected("VERIFIER_NOT_AUTHORIZED")
                plan_row = connection.execute(
                    """SELECT status,aggregation_rule,independence
                       FROM verification_plans
                       WHERE verification_plan_id=%s AND version=%s
                         AND task_id=%s AND project_id=%s FOR SHARE""",
                    (result.plan_id, result.plan_version, task.task_id, task.project_id),
                ).fetchone()
                if not plan_row or plan_row[0] != "ACTIVE":
                    raise CommandRejected("CURRENT_VERIFICATION_PLAN_REQUIRED")
                if (result.plan_id != task.current_verification_plan_id
                        or result.plan_version != task.current_verification_plan_version):
                    raise CommandRejected("VERIFICATION_PLAN_MISMATCH")
                verifier_run = connection.execute(
                    """SELECT project_id,task_id,run_kind,agent_identity,
                              context_identity,status
                       FROM agent_runs WHERE run_id=%s FOR SHARE""",
                    (result.verifier_run_id,),
                ).fetchone()
                if not verifier_run:
                    raise CommandRejected("VERIFIER_AGENT_RUN_NOT_FOUND")
                if verifier_run[0] != task.project_id:
                    raise CommandRejected("VERIFIER_AGENT_RUN_PROJECT_MISMATCH")
                if verifier_run[1] != task.task_id:
                    raise CommandRejected("VERIFIER_AGENT_RUN_TASK_MISMATCH")
                if verifier_run[2] != AgentRunKind.VERIFIER.value:
                    raise CommandRejected("VERIFIER_AGENT_RUN_KIND_REQUIRED")
                if verifier_run[3] != result.verifier_identity.actor_id:
                    raise CommandRejected("VERIFIER_AGENT_RUN_IDENTITY_MISMATCH")
                if verifier_run[5] not in {AgentRunStatus.ADMITTED.value, AgentRunStatus.COMPLETED.value}:
                    raise CommandRejected("VERIFIER_AGENT_RUN_NOT_ACTIVE")
                if result.verifier_run_id == task.completion_worker_run_id:
                    raise CommandRejected("WORKER_VERIFIER_RUN_NOT_INDEPENDENT")
                if verifier_run[4] == task.completion_worker_context_identity:
                    raise CommandRejected("WORKER_VERIFIER_CONTEXT_NOT_INDEPENDENT")
                self._validate_check_results(connection, result)
                try:
                    validate_verification_result(task, command.result)
                except GuardRejected as exc:
                    raise CommandRejected(str(exc))
                connection.execute(
                    """
                    INSERT INTO verification_results
                      (verification_id, task_id, artifact_id, artifact_hash,
                       verifier_identity, criteria, verdict, correlation_id,
                       occurred_at, command_id, authority_status,plan_id,
                       plan_version,project_id,verifier_run_id,started_at,completed_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::timestamptz,%s,
                            'AUTHORITATIVE',%s,%s,%s,%s,%s::timestamptz,%s::timestamptz)
                    """,
                    (
                        command.result.verification_id,
                        task.task_id,
                        command.result.artifact_id,
                        command.result.artifact_hash,
                        command.result.verifier_identity.actor_id,
                        "{}:{}".format(result.plan_id, result.plan_version),
                        command.result.verdict.value,
                        command.result.correlation_id,
                        command.result.completed_at,
                        command.envelope.command_id,
                        result.plan_id,
                        result.plan_version,
                        result.project_id,
                        result.verifier_run_id,
                        result.started_at,
                        result.completed_at,
                    ),
                )
                self._trigger_fault(FaultPoint.AFTER_VERIFICATION_RESULT_BEFORE_CHECK)
                for check in result.check_results:
                    connection.execute(
                        """INSERT INTO verification_check_results(
                           verification_id,check_id,status,finding_codes,evidence_refs,
                           started_at,completed_at
                           ) VALUES (%s,%s,%s,%s,%s,%s::timestamptz,%s::timestamptz)""",
                        (result.verification_id, check.check_id, check.status.value,
                         Jsonb(list(check.finding_codes)), Jsonb(list(check.evidence_refs)),
                         check.started_at, check.completed_at),
                    )
                for evidence in command.result.evidence:
                    connection.execute(
                        """
                        INSERT INTO evidence
                          (evidence_id, artifact_id, artifact_hash,
                           producer_identity, valid)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (evidence_id) DO NOTHING
                        """,
                        (
                            evidence.evidence_id,
                            evidence.artifact_id,
                            evidence.artifact_hash,
                            evidence.producer_identity,
                            evidence.valid,
                        ),
                    )
                    stored_evidence = connection.execute(
                        """SELECT artifact_id,artifact_hash,producer_identity,valid
                           FROM evidence WHERE evidence_id=%s""",
                        (evidence.evidence_id,),
                    ).fetchone()
                    if stored_evidence != (
                        evidence.artifact_id, evidence.artifact_hash,
                        evidence.producer_identity, evidence.valid,
                    ):
                        raise CommandRejected("EVIDENCE_ID_CONFLICT")
                    connection.execute(
                        """
                        INSERT INTO verification_evidence
                          (verification_id, evidence_id)
                        VALUES (%s, %s)
                        """,
                        (command.result.verification_id, evidence.evidence_id),
                    )
                self._trigger_fault(FaultPoint.AFTER_VERIFICATION_CHECK_BEFORE_EVENT)
                self._trigger_fault(FaultPoint.AFTER_FACT_BEFORE_EVENT)
                event_id = self._append_event_and_outbox(
                    connection,
                    command.envelope,
                    "verification.recorded",
                    {
                        "verification_id": command.result.verification_id,
                        "task_id": task.task_id,
                        "artifact_id": command.result.artifact_id,
                        "artifact_hash": command.result.artifact_hash,
                        "verdict": command.result.verdict.value,
                        "verification_plan_id": result.plan_id,
                        "plan_version": result.plan_version,
                        "verifier_run_id": result.verifier_run_id,
                        "evidence_refs": [
                            item.evidence_id for item in command.result.evidence
                        ],
                    },
                )
                receipt = CommandReceipt(
                    command.envelope.command_id,
                    "APPLIED",
                    "VERIFICATION_RESULT_RECORDED",
                    task.version,
                    (event_id,),
                    {
                        "task_id": task.task_id,
                        "verification_id": command.result.verification_id,
                        "task_state": task.state.value,
                    },
                )
                self._complete_command(connection, command.envelope, receipt)
                return receipt
        except CommandRejected as exc:
            self._persist_rejection(command.envelope, request_hash, exc.code, exc.detail)
            raise

    def apply_verified_task_transition(
        self, command: ApplyVerifiedTaskTransition
    ) -> CommandReceipt:
        request_hash = self._command_hash(command)
        try:
            with self._connect() as connection:
                existing = self._begin_command(
                    connection, command.envelope, request_hash
                )
                if existing:
                    return existing
                task = self._load_task_for_update(connection, command.task_id)
                self._check_version(task, command.envelope.expected_version)
                result = self._load_verification_result(
                    connection, command.verification_id
                )
                plan = connection.execute(
                    """SELECT status FROM verification_plans
                       WHERE verification_plan_id=%s AND version=%s
                         AND task_id=%s AND project_id=%s FOR SHARE""",
                    (result.plan_id, result.plan_version, task.task_id, task.project_id),
                ).fetchone()
                if not plan or plan[0] != "ACTIVE":
                    raise CommandRejected("CURRENT_VERIFICATION_PLAN_REQUIRED")
                try:
                    decision = evaluate_verified_transition(task, result)
                except GuardRejected as exc:
                    raise CommandRejected(str(exc))
                target_version = task.version + 1
                connection.execute(
                    """
                    UPDATE tasks
                    SET state = %s, version = %s, current_verification_id = %s,
                        updated_at = now()
                    WHERE task_id = %s
                    """,
                    (
                        decision.target_state.value,
                        target_version,
                        result.verification_id,
                        task.task_id,
                    ),
                )
                self._trigger_fault(FaultPoint.AFTER_STATE_BEFORE_EVENT)
                event_type = (
                    "task.passed"
                    if decision.target_state is TaskState.PASSED
                    else "task.failed"
                )
                event_id = self._append_event_and_outbox(
                    connection,
                    command.envelope,
                    event_type,
                    {
                        "task_id": task.task_id,
                        "verification_id": result.verification_id,
                        "artifact_hash": result.artifact_hash,
                        "from_state": task.state.value,
                        "to_state": decision.target_state.value,
                        "entity_version": target_version,
                    },
                )
                receipt = CommandReceipt(
                    command.envelope.command_id,
                    "APPLIED",
                    "TASK_TRANSITIONED",
                    target_version,
                    (event_id,),
                    {
                        "task_id": task.task_id,
                        "state": decision.target_state.value,
                    },
                )
                self._complete_command(connection, command.envelope, receipt)
                return receipt
        except CommandRejected as exc:
            self._persist_rejection(command.envelope, request_hash, exc.code, exc.detail)
            raise

    def record_security_rejection(
        self, command: Any, code: str, detail: str
    ) -> None:
        envelope = command.envelope
        self._persist_rejection(
            envelope,
            self._command_hash(command),
            code,
            detail,
        )

    def consume_event(
        self, consumer_id: str, event_id: str, fail_before_checkpoint: bool = False
    ) -> bool:
        with self._connect() as connection:
            event = connection.execute(
                """SELECT event_id, partition_key, sequence, schema_version,
                          public.hermes_event_envelope(event_id)
                   FROM event_log WHERE event_id = %s""",
                (event_id,),
            ).fetchone()
            if not event:
                raise CommandRejected("EVENT_NOT_FOUND")
            connection.execute(
                """
                INSERT INTO consumer_checkpoints
                  (consumer_id, partition_key, last_sequence)
                VALUES (%s, %s, 0) ON CONFLICT DO NOTHING
                """,
                (consumer_id, event[1]),
            )
            checkpoint = connection.execute(
                """
                SELECT last_sequence FROM consumer_checkpoints
                WHERE consumer_id = %s AND partition_key = %s FOR UPDATE
                """,
                (consumer_id, event[1]),
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
                (consumer_id, event_id, event[1], event[2], event[3], Jsonb(event[4])),
            ).fetchone()
            effect_applied = bool(inserted)
            if effect_applied:
                if event[2] != checkpoint + 1:
                    raise CommandRejected("CONSUMER_SEQUENCE_NOT_CONTIGUOUS")
                connection.execute(
                    """
                    INSERT INTO consumer_effects (consumer_id, event_id, effect_count)
                    VALUES (%s, %s, 1)
                    """,
                    (consumer_id, event_id),
                )
                if fail_before_checkpoint:
                    self._trigger_fault(FaultPoint.AFTER_CONSUMER_EFFECT_BEFORE_CHECKPOINT)
                connection.execute(
                    """
                    UPDATE consumer_checkpoints
                    SET last_sequence = %s, updated_at = now()
                    WHERE consumer_id = %s AND partition_key = %s
                      AND last_sequence = %s
                    """,
                    (event[2], consumer_id, event[1], checkpoint),
                )
            elif event[2] == checkpoint + 1:
                connection.execute(
                    """
                    UPDATE consumer_checkpoints
                    SET last_sequence = %s, updated_at = now()
                    WHERE consumer_id = %s AND partition_key = %s
                      AND last_sequence = %s
                    """,
                    (event[2], consumer_id, event[1], checkpoint),
                )
        return effect_applied

    def read_task(self, task_id: str) -> Task:
        with self._connect(row_factory=dict_row) as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE task_id = %s", (task_id,)
            ).fetchone()
            if not row:
                raise CommandRejected("TASK_NOT_FOUND")
            return self._task_from_row(row)

    def count(self, table: str) -> int:
        allowed = {
            "tasks",
            "artifacts",
            "completion_claims",
            "evidence",
            "verification_results",
            "verification_check_results",
            "verification_plan_checks",
            "verification_plans",
            "agent_runs",
            "command_receipts",
            "event_log",
            "outbox_messages",
            "audit_records",
            "consumer_inbox",
            "consumer_effects",
            "consumer_checkpoints",
        }
        if table not in allowed:
            raise ValueError("unsupported table")
        return int(self.scalar("SELECT count(*) FROM {}".format(table)))

    def scalar(self, query: str) -> Any:
        with self._connect() as connection:
            return connection.execute(query).fetchone()[0]

    def _connect(self, row_factory=None):
        kwargs = {"row_factory": row_factory} if row_factory else {}
        return psycopg.connect(self._dsn, **kwargs)

    def _begin_command(
        self, connection, envelope: CommandEnvelope, request_hash: str
    ) -> Optional[CommandReceipt]:
        inserted = connection.execute(
            """
            INSERT INTO command_receipts
              (command_id, project_id, command_type, idempotency_key,
               request_hash, status, result)
            VALUES (%s, %s, %s, %s, %s, 'PROCESSING', '{}'::jsonb)
            ON CONFLICT DO NOTHING
            RETURNING command_id
            """,
            (
                envelope.command_id,
                envelope.project_id,
                envelope.command_type,
                envelope.idempotency_key,
                request_hash,
            ),
        ).fetchone()
        if inserted:
            return None
        row = connection.execute(
            """
            SELECT * FROM command_receipts
            WHERE project_id = %s AND command_type = %s AND idempotency_key = %s
            FOR UPDATE
            """,
            (
                envelope.project_id,
                envelope.command_type,
                envelope.idempotency_key,
            ),
        ).fetchone()
        if not row:
            raise CommandRejected("COMMAND_ID_CONFLICT")
        columns = [item.name for item in connection.execute(
            "SELECT * FROM command_receipts LIMIT 0"
        ).description]
        receipt_row = dict(zip(columns, row))
        if receipt_row["request_hash"] != request_hash:
            raise CommandRejected("IDEMPOTENCY_CONFLICT")
        if receipt_row["status"] == "REJECTED":
            result = receipt_row["result"]
            raise CommandRejected(result["result_code"], result.get("detail", ""))
        if receipt_row["status"] != "APPLIED":
            raise CommandRejected("COMMAND_IN_PROGRESS")
        return self._receipt_from_json(receipt_row["result"])

    def _complete_command(
        self, connection, envelope: CommandEnvelope, receipt: CommandReceipt
    ) -> None:
        connection.execute(
            """
            UPDATE command_receipts
            SET status = 'APPLIED', result = %s, completed_at = now()
            WHERE command_id = %s AND status = 'PROCESSING'
            """,
            (Jsonb(self._receipt_dict(receipt)), envelope.command_id),
        )

    def _persist_rejection(
        self,
        envelope: CommandEnvelope,
        request_hash: str,
        code: str,
        detail: str,
    ) -> None:
        idempotency_conflict = False
        actor_type = (
            envelope.actor.actor_type.value if envelope.actor is not None else "missing"
        )
        actor_id = envelope.actor.actor_id if envelope.actor is not None else "<missing>"
        with self._connect() as connection:
            inserted = connection.execute(
                """
                INSERT INTO command_receipts
                  (command_id, project_id, command_type, idempotency_key,
                   request_hash, status, result, completed_at)
                VALUES (%s, %s, %s, %s, %s, 'REJECTED', %s, now())
                ON CONFLICT DO NOTHING
                RETURNING command_id
                """,
                (
                    envelope.command_id,
                    envelope.project_id,
                    envelope.command_type,
                    envelope.idempotency_key,
                    request_hash,
                    Jsonb({"result_code": code, "detail": detail}),
                ),
            ).fetchone()
            if inserted:
                connection.execute(
                    """
                    INSERT INTO audit_records
                      (audit_id, project_id, source_command_id, actor_type,
                       actor_id, action, outcome, reason_code, detail)
                    VALUES (%s, %s, %s, %s, %s, %s, 'REJECTED', %s, %s)
                    ON CONFLICT (source_command_id, reason_code) DO NOTHING
                    """,
                    (
                        "audit-" + str(uuid.uuid4()),
                        envelope.project_id,
                        envelope.command_id,
                        actor_type,
                        actor_id,
                        envelope.command_type,
                        code,
                        detail,
                    ),
                )
            else:
                existing = connection.execute(
                    """
                    SELECT request_hash FROM command_receipts
                    WHERE project_id = %s AND command_type = %s
                      AND idempotency_key = %s
                    FOR UPDATE
                    """,
                    (
                        envelope.project_id,
                        envelope.command_type,
                        envelope.idempotency_key,
                    ),
                ).fetchone()
                if existing and existing[0] != request_hash:
                    connection.execute(
                        """
                        INSERT INTO audit_records
                          (audit_id, project_id, source_command_id, actor_type,
                           actor_id, action, outcome, reason_code, detail)
                        VALUES (%s, %s, %s, %s, %s, %s, 'REJECTED',
                                'IDEMPOTENCY_CONFLICT',
                                'same scoped key was reused with a different payload')
                        ON CONFLICT (source_command_id, reason_code) DO NOTHING
                        """,
                        (
                            "audit-" + str(uuid.uuid4()),
                            envelope.project_id,
                            envelope.command_id,
                            actor_type,
                            actor_id,
                            envelope.command_type,
                        ),
                    )
                    idempotency_conflict = True
                elif not existing:
                    raise CommandRejected("COMMAND_ID_CONFLICT")
        if idempotency_conflict:
            raise CommandRejected("IDEMPOTENCY_CONFLICT")

    def _load_task_for_update(self, connection, task_id: str) -> Task:
        row = connection.execute(
            "SELECT * FROM tasks WHERE task_id = %s FOR UPDATE", (task_id,)
        ).fetchone()
        if not row:
            raise CommandRejected("TASK_NOT_FOUND")
        columns = [item.name for item in connection.execute(
            "SELECT * FROM tasks LIMIT 0"
        ).description]
        return self._task_from_row(dict(zip(columns, row)))

    def _load_verification_result(
        self, connection, verification_id: str
    ) -> VerificationResult:
        row = connection.execute(
            "SELECT * FROM verification_results WHERE verification_id = %s",
            (verification_id,),
        ).fetchone()
        if not row:
            raise CommandRejected("VERIFICATION_NOT_FOUND")
        columns = [item.name for item in connection.execute(
            "SELECT * FROM verification_results LIMIT 0"
        ).description]
        data = dict(zip(columns, row))
        evidence_rows = connection.execute(
            """
            SELECT e.* FROM evidence e
            JOIN verification_evidence ve ON ve.evidence_id = e.evidence_id
            WHERE ve.verification_id = %s
            ORDER BY e.evidence_id
            """,
            (verification_id,),
        ).fetchall()
        evidence_columns = [item.name for item in connection.execute(
            "SELECT * FROM evidence LIMIT 0"
        ).description]
        evidence = tuple(
            Evidence(
                item["evidence_id"],
                item["artifact_id"],
                item["artifact_hash"],
                item["producer_identity"],
                item["valid"],
            )
            for item in (dict(zip(evidence_columns, row)) for row in evidence_rows)
        )
        check_rows = connection.execute(
            """SELECT check_id,status,finding_codes,evidence_refs,started_at,completed_at
               FROM verification_check_results WHERE verification_id=%s
               ORDER BY check_id""",
            (verification_id,),
        ).fetchall()
        if data.get("authority_status") != "AUTHORITATIVE":
            raise CommandRejected("LEGACY_VERIFICATION_NOT_AUTHORITATIVE")
        check_results = tuple(
            VerificationCheckResult(
                row[0], Verdict(row[1]), tuple(row[2]), tuple(row[3]),
                row[4].isoformat(), row[5].isoformat(),
            )
            for row in check_rows
        )
        return VerificationResult(
            data["verification_id"],
            data["plan_id"],
            data["plan_version"],
            data["task_id"],
            data["project_id"],
            data["artifact_id"],
            data["artifact_hash"],
            Actor(ActorType.VERIFIER, data["verifier_identity"]),
            data["verifier_run_id"],
            Verdict(data["verdict"]),
            check_results,
            evidence,
            data["started_at"].isoformat(),
            data["completed_at"].isoformat(),
            data["correlation_id"],
        )

    def _check_version(self, task: Task, expected_version: int) -> None:
        if task.version != expected_version:
            raise CommandRejected(
                "VERSION_CONFLICT",
                "expected {}, current {}".format(expected_version, task.version),
            )

    def _append_event_and_outbox(
        self,
        connection,
        envelope: CommandEnvelope,
        event_type: str,
        payload: Dict[str, Any],
    ) -> str:
        event_id = "evt-" + str(uuid.uuid4())
        row = connection.execute(
            """
            INSERT INTO event_log
              (event_id, event_type, schema_version, producer_type, producer_id,
               project_id, partition_key, command_id, correlation_id, payload)
            VALUES (%s, %s, '1.0', 'control_plane', 'p0-command-handler',
                    %s, %s, %s, %s, %s)
            RETURNING sequence
            """,
            (
                event_id,
                event_type,
                envelope.project_id,
                envelope.project_id,
                envelope.command_id,
                envelope.command_id,
                Jsonb(payload),
            ),
        ).fetchone()
        self._trigger_fault(FaultPoint.AFTER_EVENT_BEFORE_OUTBOX)
        connection.execute(
            """
            INSERT INTO outbox_messages
              (message_id, event_id, topic, partition_key, sequence, payload)
            VALUES (%s, %s, 'hermes.runtime.events', %s, %s, %s)
            """,
            (
                "msg-" + str(uuid.uuid4()),
                event_id,
                envelope.project_id,
                row[0],
                Jsonb(payload),
            ),
        )
        return event_id

    @staticmethod
    def _task_from_row(row: Dict[str, Any]) -> Task:
        return Task(
            row["task_id"],
            TaskState(row["state"]),
            row["version"],
            row.get("current_artifact_id"),
            row.get("current_artifact_hash"),
            row.get("completion_worker_identity"),
            row.get("project_id"),
            row.get("current_verification_plan_id"),
            row.get("current_verification_plan_version"),
            row.get("completion_worker_run_id"),
            row.get("completion_worker_context_identity"),
        )

    def _command_hash(self, command: Any) -> str:
        envelope = command.envelope
        body: Dict[str, Any]
        if isinstance(command, AdmitAgentRun):
            body = {
                "run_id": command.run.run_id,
                "project_id": command.run.project_id,
                "task_id": command.run.task_id,
                "run_kind": command.run.run_kind.value,
                "agent_identity": command.run.agent_identity,
                "context_identity": command.run.context_identity,
                "status": command.run.status.value,
                "created_by": self._actor_dict(command.run.created_by),
                "version": command.run.version,
            }
        elif isinstance(command, InvalidateAgentRun):
            body = {"run_id": command.run_id}
        elif isinstance(command, (CreateVerificationPlan, ReviseVerificationPlan)):
            body = {
                "verification_plan_id": command.plan.verification_plan_id,
                "task_id": command.plan.task_id,
                "project_id": command.plan.project_id,
                "version": command.plan.version,
                "status": command.plan.status,
                "artifact_selectors": list(command.plan.artifact_selectors),
                "aggregation_rule": command.plan.aggregation_rule,
                "independence": command.plan.independence,
                "created_by": self._actor_dict(command.plan.created_by),
                "checks": [
                    {"check_id": check.check_id, "type": check.check_type,
                     "runner_profile": check.runner_profile,
                     "required": check.required,
                     "timeout_seconds": check.timeout_seconds,
                     "pass_condition": check.pass_condition,
                     "evidence_level": check.evidence_level,
                     "ordinal": check.ordinal}
                    for check in command.plan.checks
                ],
            }
        elif isinstance(command, SubmitCompletionClaim):
            body = {
                "claim_id": command.claim.claim_id,
                "task_id": command.claim.task_id,
                "run_id": command.claim.run_id,
                "worker_identity": self._actor_dict(command.claim.worker_identity),
                "artifact": {
                    "artifact_id": command.claim.artifact.artifact_id,
                    "task_id": command.claim.artifact.task_id,
                    "content_hash": command.claim.artifact.content_hash,
                    "media_type": command.claim.artifact.media_type,
                    "produced_by": command.claim.artifact.produced_by,
                },
                "summary": command.claim.summary,
            }
        elif isinstance(command, RecordVerificationResult):
            body = {
                "verification_id": command.result.verification_id,
                "task_id": command.result.task_id,
                "artifact_id": command.result.artifact_id,
                "artifact_hash": command.result.artifact_hash,
                "plan_id": command.result.plan_id,
                "plan_version": command.result.plan_version,
                "project_id": command.result.project_id,
                "verifier_identity": self._actor_dict(
                    command.result.verifier_identity
                ),
                "verifier_run_id": command.result.verifier_run_id,
                "verdict": command.result.verdict.value,
                "check_results": [
                    {"check_id": item.check_id, "status": item.status.value,
                     "finding_codes": list(item.finding_codes),
                     "evidence_refs": list(item.evidence_refs),
                     "started_at": item.started_at,
                     "completed_at": item.completed_at}
                    for item in command.result.check_results
                ],
                "evidence": [
                    {
                        "evidence_id": item.evidence_id,
                        "artifact_id": item.artifact_id,
                        "artifact_hash": item.artifact_hash,
                        "producer_identity": item.producer_identity,
                        "valid": item.valid,
                    }
                    for item in command.result.evidence
                ],
                "correlation_id": command.result.correlation_id,
                "started_at": command.result.started_at,
                "completed_at": command.result.completed_at,
            }
        elif isinstance(command, ApplyVerifiedTaskTransition):
            body = {
                "task_id": command.task_id,
                "verification_id": command.verification_id,
            }
        else:
            raise TypeError("unsupported command")
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
    def _actor_dict(actor: Actor) -> Dict[str, str]:
        if actor is None:
            return {"type": "missing", "id": "<missing>"}
        return {"type": actor.actor_type.value, "id": actor.actor_id}

    @staticmethod
    def _hash_value(value: Dict[str, Any]) -> str:
        encoded = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _receipt_dict(receipt: CommandReceipt) -> Dict[str, Any]:
        return {
            "command_id": receipt.command_id,
            "status": receipt.status,
            "result_code": receipt.result_code,
            "target_version": receipt.target_version,
            "event_ids": list(receipt.event_ids),
            "response": dict(receipt.response),
        }

    @staticmethod
    def _receipt_from_json(value: Dict[str, Any]) -> CommandReceipt:
        return CommandReceipt(
            value["command_id"],
            value["status"],
            value["result_code"],
            value.get("target_version"),
            tuple(value.get("event_ids", [])),
            value.get("response", {}),
        )
