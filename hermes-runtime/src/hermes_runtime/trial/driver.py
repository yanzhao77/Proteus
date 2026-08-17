"""Autonomous Run driver: drives the real Proteus authority chain (P6).

The driver submits only semantic commands through the existing application
services (the same authority path the API wraps) and reads state through query
stores / the event log. It never executes raw SQL against authority tables.

Happy path (all real runtime paths):

  Software Request -> project.create
  -> work graph patch + readiness -> task.readiness_recomputed event
  -> SituationAnalyzer -> work_available situation
  -> ActionPlanner (action-registry/1.1) -> implement candidate
  -> PolicyEngine / RiskEngine / ActionSelection -> DecisionRecord + Reservation
  -> Capability match / Context bundle / Sandbox profile
  -> execution.prepare_request -> QUEUED -> Scheduler lease (fencing token)
  -> Worker start_run -> real golden-worker subprocess builds golden-todo
     in a workspace -> pytest genuinely FAILS (broken test defect) ->
     fenced result FAILED_PERMANENT
  -> RecoveryController.emit_execution_feedback -> task re-enters READY pool
     (migration 0024) + feedback.created event
  -> SituationAnalyzer -> verification_failed situation
  -> DiagnosisEngine -> diagnosis
  -> ActionPlanner -> repair candidate (worker-executable, P1 registry)
  -> RecoveryController.plan_recovery_attempt
  -> Policy / Risk / Selection / Capability / prepare / lease / start_run
  -> golden-worker subprocess builds the full correct golden-todo -> pytest PASS
  -> independent golden-verifier subprocess runs pytest -> PASS
  -> verification.recorded (PASS) -> task PASSED
  -> RecoveryController.complete_recovery_attempt (SUCCEEDED)
  -> project evidence/policy/budget guard facts -> transitions -> ACCEPTED
  -> evidence collected

The first failure is real evidence, not injection: the golden worker genuinely
writes a defective project and pytest really fails; the autonomous loop then
diagnoses and repairs. This satisfies the P6 evidence bundle (diagnosis.json is
present because a real verification_failed situation is diagnosed).
"""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from hermes_runtime.application.accounting import ResourceAccounting
from hermes_runtime.application.capabilities import (
    ExecutionPreparationAuthority as CapabilityPreparation,
    ChangeWorkerTemplateAvailability,
    CompileSandboxProfile,
    CreateContextBundle,
    CreateWorkerTemplateRevision,
    MatchCapabilityRequirements,
    RegisterCapabilitySchema,
)
from hermes_runtime.application.commands import (
    AdmitAgentRun,
    ApplyVerifiedTaskTransition,
    ApplyWorkGraphPatch,
    CreateProject,
    CreateResourceAccount,
    CreateVerificationPlan,
    IssueProjectBudgetFact,
    RecomputeTaskReadiness,
    RecordProjectEvidenceFact,
    RecordProjectPolicyFact,
    RecordVerificationResult,
    RequestProjectTransition,
)
from hermes_runtime.application.diagnoses import DiagnosisEngine, RunDiagnosis
from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.application.executions import (
    ExecutionPreparation,
    PrepareExecutionRequest,
)
from hermes_runtime.application.handlers import ControlPlane
from hermes_runtime.application.planning import ActionPlanner, PlanCandidates
from hermes_runtime.application.policies import EvaluatePolicy, PolicyEngine
from hermes_runtime.application.project_guard_facts import ProjectGuardFactAuthority
from hermes_runtime.application.recovery import (
    CompleteRecoveryAttempt,
    EmitExecutionFeedback,
    PlanRecoveryAttempt,
    RecoveryController,
)
from hermes_runtime.application.risks import AssessRisk, RiskEngine
from hermes_runtime.application.scheduling import (
    AcquireExecutionLease,
    ExecutionScheduler,
    RegisterScheduler,
    RenewExecutionLease,
)
from hermes_runtime.application.selections import (
    ActionSelection,
    CandidateAccountBinding,
    SelectActions,
)
from hermes_runtime.application.situations import SituationAnalyzer
from hermes_runtime.application.workers import (
    RecordArtifactCandidate,
    RecordUsageSample,
    StartWorkerRun,
    SubmitExecutionResult,
    WorkerExecution,
)
from hermes_runtime.domain.capability import (
    AuthorityRef,
    CapabilityRequirement,
    ContextSelector,
    SandboxCompileInput,
    WorkerTemplateRevision,
)
from hermes_runtime.domain.execution import ArtifactInputRef, LockIntent
from hermes_runtime.domain.graph import CreateTask, GraphPatch, GraphTask
from hermes_runtime.domain.models import (
    Actor,
    ActorType,
    AgentRun,
    AgentRunKind,
    AgentRunStatus,
    CommandEnvelope,
    Evidence,
    ProjectState,
    VerificationCheckResult,
    VerificationPlan,
    VerificationPlanCheck,
    VerificationResult,
    Verdict,
)
from hermes_runtime.domain.planner import P6_REGISTRY_VERSION
from hermes_runtime.domain.worker_execution import (
    ArtifactCandidateSubmission,
    ExecutionOutcome,
    ExecutionResultSubmission,
    UsageSampleSubmission,
    WorkerFrozenContext,
    WorkerLeaseBinding,
)
from hermes_runtime.infrastructure.postgres import PostgresRuntimeStore
from hermes_runtime.infrastructure.postgres_accounting import (
    PostgresResourceAccountingStore as PostgresAccountingStore,
)
from hermes_runtime.infrastructure.postgres_capability import PostgresCapabilityStore
from hermes_runtime.infrastructure.postgres_diagnosis import PostgresDiagnosisStore
from hermes_runtime.infrastructure.postgres_execution import PostgresExecutionStore
from hermes_runtime.infrastructure.postgres_planner import PostgresPlannerStore
from hermes_runtime.infrastructure.postgres_policy import PostgresPolicyStore
from hermes_runtime.infrastructure.postgres_project import PostgresProjectStore
from hermes_runtime.infrastructure.postgres_recovery import PostgresRecoveryStore
from hermes_runtime.infrastructure.postgres_risk import PostgresRiskStore
from hermes_runtime.infrastructure.postgres_scheduler import PostgresSchedulerStore
from hermes_runtime.infrastructure.postgres_selection import PostgresSelectionStore
from hermes_runtime.infrastructure.postgres_situation import PostgresSituationStore
from hermes_runtime.infrastructure.postgres_worker_execution import (
    PostgresWorkerExecutionStore,
)
from hermes_runtime.trial.golden_worker import WorkerFaultMode


SANDBOX_CONSTRAINT_KEYS = {
    "network_access", "filesystem_write", "environment", "secret_access",
    "production_access", "allowed_tools", "forbidden_paths",
    "max_external_api_calls", "required_mitigations", "lock_scopes",
    "execution_time_ms", "cpu_time_ms", "storage_bytes", "process_count",
    "output_bytes",
}


POLICY_BUNDLE_VERSION = "policy-bundle/1.0"
SANDBOX_COMPILER_VERSION = "sandbox-compiler/1.0"
WORKER_TEMPLATE_ID = "template-golden"
WORKER_TEMPLATE_REVISION = 1
WORKER_IDENTITY = "worker-golden"
VERIFIER_IDENTITY = "verifier-golden"


class TrialError(RuntimeError):
    pass


def _uuid(prefix: str) -> str:
    return prefix + "-" + uuid.uuid4().hex


def _now() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class AutonomousRunDriver:
    """Drives one autonomous run through the real Proteus authority chain."""

    def __init__(
        self, database_url: str, workspace_root: Path,
        test_database_url: str = "postgresql+psycopg://todo:todo@127.0.0.1:55432/todo_test",
    ) -> None:
        self.database_url = database_url
        self.test_database_url = test_database_url
        self.workspace_root = Path(workspace_root)
        self.control_plane = ControlPlane(PostgresProjectStore(database_url))
        self.project_store = PostgresProjectStore(database_url)
        self.situation_store = PostgresSituationStore(database_url)
        self.situation = SituationAnalyzer(self.situation_store)
        self.diagnosis = DiagnosisEngine(PostgresDiagnosisStore(database_url))
        self.planner = ActionPlanner(PostgresPlannerStore(database_url))
        self.policy = PolicyEngine(PostgresPolicyStore(database_url))
        self.risk = RiskEngine(PostgresRiskStore(database_url))
        self.selection = ActionSelection(PostgresSelectionStore(database_url))
        self.capability = CapabilityPreparation(PostgresCapabilityStore(database_url))
        self.execution = ExecutionPreparation(PostgresExecutionStore(database_url))
        self.scheduler = ExecutionScheduler(PostgresSchedulerStore(database_url))
        self.worker = WorkerExecution(PostgresWorkerExecutionStore(database_url))
        self.accounting = ResourceAccounting(PostgresAccountingStore(database_url))
        self.recovery = RecoveryController(PostgresRecoveryStore(database_url))
        self.guard_facts = ProjectGuardFactAuthority(PostgresProjectStore(database_url))
        self.runtime = PostgresRuntimeStore(database_url)
        self.control = Actor(ActorType.CONTROL_PLANE, "control-plane-1")
        self.user = Actor(ActorType.USER, "trial-user")
        self.verifier = Actor(ActorType.VERIFIER, VERIFIER_IDENTITY)
        self.records: Dict[str, Any] = {}
        self.workspace: Optional[Path] = None
        self._project_id: Optional[str] = None
        self._scenario_patch_event_ids: Dict[str, str] = {}

    # ------------------------------------------------------------------ helpers

    def _envelope(
        self, command_type: str, key: str, expected_version: int,
        actor: Actor, project_id: str, reason: str,
    ) -> CommandEnvelope:
        return CommandEnvelope(
            command_id=_uuid("cmd"), command_type=command_type,
            idempotency_key=key, expected_version=expected_version,
            actor=actor, reason=reason, project_id=project_id,
        )

    def _connect(self):
        import psycopg
        return psycopg.connect(self.database_url)

    def _scalar(self, sql: str, args: tuple):
        with self._connect() as connection:
            row = connection.execute(sql, args).fetchone()
        return row[0] if row else None

    def _project_version(self, project_id: str) -> int:
        return int(self._scalar(
            "SELECT version FROM projects WHERE project_id=%s", (project_id,)
        ))

    def _task_version(self, task_id: str, project_id: str) -> int:
        return int(self._scalar(
            "SELECT version FROM tasks WHERE task_id=%s AND project_id=%s",
            (task_id, project_id),
        ))

    def _account_version(self, account_id: str) -> int:
        return int(self._scalar(
            "SELECT version FROM resource_accounts WHERE account_id=%s",
            (account_id,),
        ))

    def _request_version(self, execution_request_id: str) -> int:
        return int(self._scalar(
            """SELECT request_version FROM execution_request_current_states
               WHERE execution_request_id=%s""",
            (execution_request_id,),
        ))

    def _refresh_binding(self, binding: WorkerLeaseBinding) -> WorkerLeaseBinding:
        """Re-read the current request version and lease version after the
        worker run (start_run bumps the request version; scheduler renewal
        bumps the lease version). Worker admissions validate both."""
        request_version = self._request_version(binding.execution_request_id)
        lease_version = int(self._scalar(
            """SELECT lease_version FROM execution_leases WHERE lease_id=%s""",
            (binding.lease_id,),
        ))
        return WorkerLeaseBinding(
            project_id=binding.project_id,
            execution_request_id=binding.execution_request_id,
            execution_attempt=binding.execution_attempt,
            run_id=binding.run_id,
            lease_id=binding.lease_id,
            lease_version=lease_version,
            fencing_token=binding.fencing_token,
            scheduler_id=binding.scheduler_id,
            scheduler_session_id=binding.scheduler_session_id,
            worker_agent_identity=binding.worker_agent_identity,
            context_identity=binding.context_identity,
            observed_request_version=request_version,
        )

    def _renewer(
        self, execution_request_id: str, lease_id: str, scheduler_id: str,
        session: str, fencing_token: int, stop_event,
    ) -> None:
        """Real scheduler behavior: renew the lease while a long-running
        worker executes (default lease TTL is 30s; golden builds take minutes).
        Runs on a daemon thread with its own idempotency key per renewal."""
        import threading
        import time
        lease_version = int(self._scalar(
            """SELECT lease_version FROM execution_leases WHERE lease_id=%s""",
            (lease_id,),
        ))
        renewals = 0
        while not stop_event.is_set() and renewals < 60:
            time.sleep(10)
            if stop_event.is_set():
                return
            try:
                result = self.scheduler.renew(RenewExecutionLease(
                    command_id=_uuid("cmd-renew"),
                    idempotency_key=_uuid("key-renew"),
                    project_id=self._project_id,
                    execution_request_id=execution_request_id,
                    lease_id=lease_id,
                    scheduler_id=scheduler_id,
                    scheduler_session_id=session,
                    fencing_token=fencing_token,
                    expected_lease_version=lease_version,
                ))
                lease_version = int(result.get("lease_version", lease_version + 1))
                renewals += 1
            except Exception:
                # A failed renewal surfaces at submit time (LEASE_EXPIRED);
                # do not mask the real worker result with renewer noise.
                pass

    def _read_candidate(self, planning_run_id: str, action_type: str) -> Dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT action_id, type, content_hash, target_refs,
                          required_capabilities, parameters
                   FROM candidate_actions
                   WHERE planning_run_id=%s AND type=%s ORDER BY ordinal LIMIT 1""",
                (planning_run_id, action_type),
            ).fetchone()
        if row is None:
            raise TrialError(
                "planner did not emit a {} candidate".format(action_type)
            )
        return {
            "action_id": row[0], "type": row[1], "content_hash": row[2],
            "target_refs": list(row[3] or ()),
            "required_capabilities": list(row[4] or ()),
            "parameters": dict(row[5] or {}),
        }

    def _situation_context(self, analysis_context_id: str) -> Dict[str, str]:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT analysis_context_id, context_hash FROM analysis_contexts
                   WHERE analysis_context_id=%s""",
                (analysis_context_id,),
            ).fetchone()
        if row is None:
            raise TrialError("analysis context not found: " + analysis_context_id)
        return {"analysis_context_id": row[0], "context_hash": row[1]}

    def _situation_for_event(self, target_event_id: str) -> Dict[str, Any]:
        """Replay the project event log in sequence order through the real
        SituationAnalyzer and return the analysis for the target event.

        The situation analyzer consumes events in partition sequence order
        (gap detection + checkpoints), so the harness replays in order just
        like the real consumer would; replayed events return their stored
        processing result (consumer_inbox), making this idempotent.
        """
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT event_id FROM event_log
                   WHERE project_id=%s ORDER BY sequence""",
                (self._project_id,),
            ).fetchall()
        target = None
        for (event_id,) in rows:
            result = self.situation_store.analyze_logged_event(event_id)
            if event_id == target_event_id:
                target = result
        if target is None:
            raise TrialError("event not found for situation analysis")
        return target

    def _ensure_verifier(self, verifier_id: str) -> None:
        # verifier_identities is a configuration table (not an authority table);
        # the insert is idempotent so multiple scenarios can share one database.
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO verifier_identities(verifier_id, active) "
                "VALUES (%s, true) ON CONFLICT (verifier_id) DO NOTHING",
                (verifier_id,),
            )

    def _seed_worker_template(self, project_id: str) -> Dict[str, Any]:
        """Register the golden builder capability schemas and worker template
        through the real CapabilityPreparation authority path."""
        for name, description in (
            ("software_builder", "golden project software builder"),
            ("code_modification", "bounded code modification for repairs"),
        ):
            self.capability.register_capability_schema(RegisterCapabilitySchema(
                command_id=_uuid("cmd-cap-schema"),
                idempotency_key=_uuid("key-cap-schema"),
                project_id=project_id,
                capability_name=name,
                schema_version="capability-schema/1.0",
                description=description,
            ))
        template = WorkerTemplateRevision(
            template_id=WORKER_TEMPLATE_ID,
            revision=WORKER_TEMPLATE_REVISION,
            project_id=None,
            runtime_kind="python-process",
            capabilities=("software_builder", "code_modification"),
            trust_level="STANDARD",
            allowed_tools=("pytest", "python"),
            supported_sandbox_features=(
                "network_access", "filesystem_write", "secret_access",
                "production_access", "allowed_tools", "max_external_api_calls",
                "required_mitigations", "lock_scopes", "execution_time_ms",
                "cpu_time_ms", "storage_bytes",
            ),
            resource_envelope={
                "execution_time_ms": 3_600_000,
                "cpu_time_ms": 3_600_000,
                "storage_bytes": 10_000_000,
            },
            constraint_ranges={
                "network_access": "disabled",
                "filesystem_write": "workspace_only",
                "secret_access": "denied",
                "production_access": "denied",
                "allowed_tools": ["pytest", "python"],
                "max_external_api_calls": 0,
            },
            concurrency_capacity=1,
        )
        # The worker template is global (project_id=None): register it once and
        # reuse it across scenarios sharing one database.
        with self._connect() as connection:
            existing = connection.execute(
                """SELECT content_hash FROM worker_template_revisions
                   WHERE template_id=%s AND revision=%s""",
                (WORKER_TEMPLATE_ID, WORKER_TEMPLATE_REVISION),
            ).fetchone()
        if existing is None:
            created = self.capability.create_worker_template_revision(
                CreateWorkerTemplateRevision(
                    command_id=_uuid("cmd-template-rev"),
                    idempotency_key=_uuid("key-template-rev"),
                    project_id=project_id,
                    template=template,
                    expected_version=0,
                )
            )
            content_hash = created["content_hash"]
            availability_version = int(created.get("availability_version", 1))
            activated = self.capability.change_worker_template_availability(
                ChangeWorkerTemplateAvailability(
                    command_id=_uuid("cmd-template-avail"),
                    idempotency_key=_uuid("key-template-avail"),
                    project_id=project_id,
                    template_id=WORKER_TEMPLATE_ID,
                    revision=WORKER_TEMPLATE_REVISION,
                    availability_status="AVAILABLE",
                    admission_status="ADMISSIBLE",
                    expected_version=availability_version,
                )
            )
            availability_version = int(activated.get("availability_version", 2))
        else:
            content_hash = existing[0]
            availability_version = int(self._scalar(
                """SELECT availability_version FROM worker_template_availability
                   WHERE template_id=%s AND revision=%s""",
                (WORKER_TEMPLATE_ID, WORKER_TEMPLATE_REVISION),
            ))
        return {
            "template": template,
            "content_hash": content_hash,
            "availability_version": availability_version,
        }

    def _evaluate_action(
        self, planning_run_id: str, action: Dict[str, Any],
        situation_version: int, tag: str,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        policy = self.policy.evaluate(EvaluatePolicy(
            command_id=_uuid("cmd-policy"),
            idempotency_key=_uuid("key-policy-" + tag),
            project_id=self._project_id,
            planning_run_id=planning_run_id,
            action_id=action["action_id"],
            expected_situation_version=situation_version,
            expected_action_content_hash=action["content_hash"],
            target_environment="dev",
        ))
        if policy["result"] != "ALLOW":
            raise TrialError("policy did not allow " + action["type"])
        risk = self.risk.assess(AssessRisk(
            command_id=_uuid("cmd-risk"),
            idempotency_key=_uuid("key-risk-" + tag),
            project_id=self._project_id,
            planning_run_id=planning_run_id,
            action_id=action["action_id"],
            expected_situation_version=situation_version,
            expected_action_content_hash=action["content_hash"],
            target_environment="dev",
            verified_mitigations=("verification_before_apply",),
        ))
        return policy, risk

    def _select_action(
        self, planning_run_id: str, action: Dict[str, Any],
        situation_version: int, account_id: str, tag: str,
    ) -> Tuple[Dict[str, Any], str]:
        account_version = self._account_version(account_id)
        selection = self.selection.select(SelectActions(
            command_id=_uuid("cmd-selection"),
            idempotency_key=_uuid("key-selection-" + tag),
            project_id=self._project_id,
            planning_run_id=planning_run_id,
            expected_situation_version=situation_version,
            expected_selection_version=0,
            candidate_account_bindings=(
                CandidateAccountBinding(action["action_id"], account_id, account_version),
            ),
        ))
        selected = list(selection.get("selected_action_ids") or ())
        if action["action_id"] not in selected:
            raise TrialError("selection did not select " + action["type"])
        reservations = selection.get("reservation_ids") or []
        if not reservations:
            raise TrialError("selection produced no reservation")
        reservation_id = reservations[0]
        return selection, reservation_id

    def _capability_freeze(
        self, task_id: str, decision_id: str, action: Dict[str, Any],
        policy: Dict[str, Any], risk: Dict[str, Any],
        reservation_id: str, plan_id: str, template: Dict[str, Any], tag: str,
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        project_id = self._project_id
        match = self.capability.match_capability_requirements(
            MatchCapabilityRequirements(
                command_id=_uuid("cmd-match"),
                idempotency_key=_uuid("key-match-" + tag),
                project_id=project_id,
                requirement=CapabilityRequirement(
                    project_id=project_id,
                    task_id=task_id,
                    decision_id=decision_id,
                    action_id=action["action_id"],
                    action_type=action["type"],
                    action_content_hash=action["content_hash"],
                    required_capabilities=tuple(action["required_capabilities"]),
                    required_tools=("pytest",),
                    minimum_trust="STANDARD",
                    sandbox_requirements={
                        "network_access": "disabled",
                        "filesystem_write": "workspace_only",
                    },
                    resource_envelope={
                        "execution_time_ms": 600_000,
                        "cpu_time_ms": 300_000,
                        "storage_bytes": 1_048_576,
                    },
                    lock_scopes=("workspace:" + project_id,),
                    mandatory_constraints=("network_access", "filesystem_write"),
                ),
                expected_version=0,
            )
        )
        if match["reason_code"] != "MATCHED":
            raise TrialError("capability match failed: " + match["reason_code"])
        context = self.capability.create_context_bundle(CreateContextBundle(
            command_id=_uuid("cmd-context"),
            idempotency_key=_uuid("key-context-" + tag),
            project_id=project_id,
            task_id=task_id,
            decision_id=decision_id,
            action_id=action["action_id"],
            template_id=WORKER_TEMPLATE_ID,
            template_revision=WORKER_TEMPLATE_REVISION,
            selectors=(
                ContextSelector("project", project_id),
                ContextSelector("task", task_id),
                ContextSelector("selected_action", action["action_id"]),
                ContextSelector("policy_decision", policy["policy_decision_id"]),
                ContextSelector("risk_assessment", risk["risk_assessment_id"]),
                ContextSelector("resource_reservation", reservation_id),
                ContextSelector("verification_plan", plan_id),
            ),
            resolved_refs=(
                AuthorityRef("project", project_id, project_id, None,
                             self._project_version(project_id), "sha256:project", {}),
                AuthorityRef("task", task_id, project_id, task_id,
                             self._task_version(task_id, project_id), "sha256:task", {}),
                AuthorityRef("selected_action", action["action_id"], project_id, task_id,
                             1, action["content_hash"], {}),
                AuthorityRef("policy_decision", policy["policy_decision_id"], project_id,
                             task_id, 1, policy["policy_input_hash"], {}),
                AuthorityRef("risk_assessment", risk["risk_assessment_id"], project_id,
                             task_id, 1, risk["risk_input_hash"], {}),
                AuthorityRef("resource_reservation", reservation_id, project_id, task_id,
                             1, "sha256:reservation", {}),
                AuthorityRef("verification_plan", plan_id, project_id, task_id,
                             1, "sha256:verification-plan", {}),
            ),
        ))
        sandbox = self.capability.compile_sandbox_profile(CompileSandboxProfile(
            command_id=_uuid("cmd-sandbox"),
            idempotency_key=_uuid("key-sandbox-" + tag),
            project_id=project_id,
            compile_input=SandboxCompileInput(
                project_id=project_id,
                task_id=task_id,
                action_id=action["action_id"],
                action_content_hash=action["content_hash"],
                policy_constraints={
                    key: value for key, value in dict(policy["constraints"]).items()
                    if key in SANDBOX_CONSTRAINT_KEYS
                },
                risk_required_mitigations=tuple(risk["required_mitigations"]),
                risk_available_mitigations=tuple(risk["available_mitigations"]),
                action_constraints={"filesystem_write": "workspace_only"},
                template=template["template"],
                context_bundle_hash=context["manifest_hash"],
                lock_scopes=("workspace:" + project_id,),
            ),
        ))
        return match, context, sandbox

    def _prepare_command(
        self, run_id: str, task_id: str, decision: Dict[str, Any],
        action: Dict[str, Any], policy: Dict[str, Any], risk: Dict[str, Any],
        reservation_id: str, match: Dict[str, Any], template: Dict[str, Any],
        context: Dict[str, Any], sandbox: Dict[str, Any], plan_id: str, tag: str,
    ) -> PrepareExecutionRequest:
        return PrepareExecutionRequest(
            command_id=_uuid("cmd-exec-prepare"),
            idempotency_key=_uuid("key-exec-prepare-" + tag),
            project_id=self._project_id,
            task_id=task_id,
            expected_project_version=self._project_version(self._project_id),
            expected_task_version=self._task_version(task_id, self._project_id),
            decision_id=decision["decision_id"],
            decision_version=int(decision["selection_version"]),
            decision_hash=decision["input_snapshot_hash"],
            action_id=action["action_id"],
            action_version=1,
            action_content_hash=action["content_hash"],
            action_type=action["type"],
            action_requirements_hash="sha256:requirements",
            policy_decision_id=policy["policy_decision_id"],
            policy_version=1,
            policy_hash=policy["policy_input_hash"],
            risk_assessment_id=risk["risk_assessment_id"],
            risk_version=1,
            risk_hash=risk["risk_input_hash"],
            mandatory_mitigations_hash="sha256:mitigations",
            reservation_id=reservation_id,
            reservation_version=1,
            reservation_hash="sha256:reservation",
            capability_match_id=match["match_id"],
            capability_match_version=1,
            capability_requirements_hash=match["requirements_hash"],
            worker_template_id=WORKER_TEMPLATE_ID,
            worker_template_revision=WORKER_TEMPLATE_REVISION,
            worker_template_content_hash=template["content_hash"],
            worker_template_availability_version=int(match["availability_version"]),
            context_bundle_id=context["bundle_id"],
            context_manifest_hash=context["manifest_hash"],
            sandbox_profile_id=sandbox["profile_id"],
            sandbox_profile_hash=sandbox["profile_hash"],
            sandbox_compiler_version=SANDBOX_COMPILER_VERSION,
            sandbox_compiler_target="contract-only/1.0",
            verification_plan_id=plan_id,
            verification_plan_version=1,
            verification_plan_hash="sha256:plan",
            lock_intents=(LockIntent("workspace:" + self._project_id),),
            priority=0,
            actor_type="execution_preparer",
            actor_id="execution-preparer",
            reason="prepare " + action["type"] + " execution",
        )

    def _lease_and_start(
        self, run_id: str, execution_request_id: str, reservation_id: str,
        template: Dict[str, Any], context: Dict[str, Any], sandbox: Dict[str, Any],
        tag: str,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        scheduler_id = "scheduler-" + tag
        self.scheduler.register(RegisterScheduler(
            command_id=_uuid("cmd-scheduler-register"),
            idempotency_key=_uuid("key-scheduler-register-" + tag),
            project_id=self._project_id,
            scheduler_id=scheduler_id,
            scheduler_session_id="session-" + tag,
            actor_id=scheduler_id,
        ))
        lease = self.scheduler.acquire(AcquireExecutionLease(
            command_id=_uuid("cmd-scheduler-acquire"),
            idempotency_key=_uuid("key-scheduler-acquire-" + tag),
            project_id=self._project_id,
            scheduler_id=scheduler_id,
            scheduler_session_id="session-" + tag,
            actor_id=scheduler_id,
        ))
        binding = WorkerLeaseBinding(
            project_id=self._project_id,
            execution_request_id=execution_request_id,
            execution_attempt=1,
            run_id="run-" + tag,
            lease_id=lease["lease_id"],
            lease_version=lease["lease_version"],
            fencing_token=lease["fencing_token"],
            scheduler_id=scheduler_id,
            scheduler_session_id="session-" + tag,
            worker_agent_identity=WORKER_IDENTITY,
            context_identity="worker-context-" + tag,
            observed_request_version=lease["request_version"],
        )
        self.worker.start_run(StartWorkerRun(
            command_id=_uuid("cmd-worker-start"),
            idempotency_key=_uuid("key-worker-start-" + tag),
            binding=binding,
            frozen_context=WorkerFrozenContext(
                worker_template_id=WORKER_TEMPLATE_ID,
                worker_template_revision=WORKER_TEMPLATE_REVISION,
                worker_template_content_hash=template["content_hash"],
                context_bundle_id=context["bundle_id"],
                context_manifest_hash=context["manifest_hash"],
                sandbox_profile_id=sandbox["profile_id"],
                sandbox_profile_hash=sandbox["profile_hash"],
                reservation_id=reservation_id,
            ),
            actor_id=WORKER_IDENTITY,
        ))
        current_version = self._request_version(execution_request_id)
        binding = WorkerLeaseBinding(
            project_id=binding.project_id,
            execution_request_id=binding.execution_request_id,
            execution_attempt=binding.execution_attempt,
            run_id=binding.run_id,
            lease_id=binding.lease_id,
            lease_version=binding.lease_version,
            fencing_token=binding.fencing_token,
            scheduler_id=binding.scheduler_id,
            scheduler_session_id=binding.scheduler_session_id,
            worker_agent_identity=binding.worker_agent_identity,
            context_identity=binding.context_identity,
            observed_request_version=current_version,
        )
        return dict(lease, scheduler_id=scheduler_id,
                    scheduler_session_id="session-" + tag), binding

    def _run_golden_worker(
        self, task_id: str, execution_request_id: str, run_id: str,
        summary: str, fault_mode: str, prepare_venv: bool, tag: str,
        renewal: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        import threading
        workspace = self.workspace
        context_path = workspace / ("worker-context-" + tag + ".json")
        result_path = workspace / ("worker-result-" + tag + ".json")
        context = {
            "workspace": str(workspace),
            "project_id": self._project_id,
            "task_id": task_id,
            "execution_request_id": execution_request_id,
            "request_summary": summary,
            "fault_mode": fault_mode,
            "prepare_venv": prepare_venv,
            "test_database_url": self.test_database_url,
            "result_path": str(result_path),
        }
        context_path.write_text(json.dumps(context, sort_keys=True))
        stop_event = threading.Event()
        renewer = None
        if renewal:
            renewer = threading.Thread(
                target=self._renewer,
                args=(renewal["execution_request_id"], renewal["lease_id"],
                      renewal["scheduler_id"], renewal["session"],
                      renewal["fencing_token"], stop_event),
                daemon=True,
            )
            renewer.start()
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "hermes_runtime.trial.golden_worker",
                 str(context_path)],
                capture_output=True, text=True, timeout=1500,
            )
        finally:
            stop_event.set()
            if renewer:
                renewer.join(timeout=5)
        if not result_path.exists():
            raise TrialError(
                "golden worker produced no result: " + completed.stderr[-2000:]
            )
        result = json.loads(result_path.read_text())
        result["returncode"] = completed.returncode
        return result

    def _verify_workspace(
        self, run_id: str, expected_manifest: List[Dict[str, Any]],
        task_id: str = "",
    ) -> Dict[str, Any]:
        context_path = self.workspace / ("verifier-context-" + run_id + ".json")
        result_path = self.workspace / ("verifier-result-" + run_id + ".json")
        context = {
            "workspace": str(self.workspace),
            "expected_manifest": expected_manifest,
            "project_id": self._project_id,
            "task_id": task_id or self.records.get("task_id", ""),
            "verification_plan_id": "plan-" + run_id,
            "test_database_url": self.test_database_url,
            "result_path": str(result_path),
        }
        context_path.write_text(json.dumps(context, sort_keys=True))
        completed = subprocess.run(
            [sys.executable, "-m", "hermes_runtime.trial.golden_verifier",
             str(context_path)],
            capture_output=True, text=True, timeout=900,
        )
        if not result_path.exists():
            raise TrialError(
                "golden verifier produced no result: " + completed.stderr[-2000:]
            )
        result = json.loads(result_path.read_text())
        result["returncode"] = completed.returncode
        return result

    # ------------------------------------------------------------------ lifecycle

    def run_happy_path(
        self, request: Mapping[str, Any], run_id: str,
        first_fault: str = WorkerFaultMode.BROKEN_TEST,
    ) -> Dict[str, Any]:
        """Execute the full autonomous happy path and return collected records.

        first_fault selects the REAL defect injected into the first
        implementation execution (BROKEN_TEST or MISSING_FEATURE); the
        autonomous loop then diagnoses and repairs it either way.
        """
        project_id = "project-" + run_id
        task_id = "task-" + run_id
        summary = str(request.get("summary") or request.get("request") or "Build a Todo API")
        self._project_id = project_id
        self.records["request"] = dict(request)
        self.records["run_id"] = run_id
        self.records["project_id"] = project_id
        self.records["task_id"] = task_id

        self._ensure_verifier(VERIFIER_IDENTITY)
        self.workspace = self.workspace_root / run_id
        self.workspace.mkdir(parents=True, exist_ok=True)

        # --- project + task graph (Software Request intake)
        create_receipt = self.control_plane.create_project(CreateProject(
            self._envelope("project.create", "key-create-" + run_id, 0,
                           self.control, project_id, "autonomous software request"),
            summary,
            self.user,
        ))
        self.records["project"] = {
            "project_id": project_id,
            "state": "CREATED",
            "receipt": create_receipt.__dict__,
            "request": dict(request),
        }
        patch_receipt = self.control_plane.apply_work_graph_patch(ApplyWorkGraphPatch(
            self._envelope("work_graph.apply_patch", "key-graph-" + run_id, 0,
                           self.control, project_id, "create golden todo task"),
            GraphPatch(
                base_graph_version=0,
                decision_id="decision-graph-" + run_id,
                operations=(CreateTask(GraphTask(task_id, "implement", summary)),),
            ),
        ))
        if not patch_receipt.event_ids:
            raise TrialError("graph patch produced no event")
        patch_event_id = patch_receipt.event_ids[0]
        self.records["task"] = {"task_id": task_id, "state": "READY"}

        # --- Situation: work_available (real analyzer over the real patch
        #     event, which records the authoritative readiness change;
        #     P6 extension classifies it as work_available)
        work_available = self._situation_for_event(patch_event_id)
        if work_available.get("classification") not in {"CREATED", "UPDATED"}:
            raise TrialError("work_available situation not created")
        ctx1 = self._situation_context(work_available["analysis_context_id"])
        self.records["situation"] = {
            "trigger": "task.readiness_recomputed",
            "situation_id": work_available["situation_id"],
            "version": work_available["version"],
        }

        # --- Plan: implement candidate (action-registry/1.1, real planner)
        plan_implement = self.planner.plan(PlanCandidates(
            command_id=_uuid("cmd-plan-implement"),
            idempotency_key=_uuid("key-plan-implement"),
            project_id=project_id,
            situation_id=work_available["situation_id"],
            expected_situation_version=work_available["version"],
            analysis_context_id=ctx1["analysis_context_id"],
            analysis_context_hash=ctx1["context_hash"],
            registry_version=P6_REGISTRY_VERSION,
        ))
        implement_action = self._read_candidate(
            plan_implement["planning_run_id"], "implement"
        )
        self.records["planning_implement"] = {
            "planning_run_id": plan_implement["planning_run_id"],
            "candidate_count": plan_implement["candidate_count"],
            "action": implement_action,
        }

        # --- Verification plan (real control-plane command)
        task_version = self._task_version(task_id, project_id)
        plan_id = "plan-" + run_id
        self.control_plane.create_verification_plan(CreateVerificationPlan(
            self._envelope("verification_plan.create", "key-plan-verif-" + run_id,
                           task_version, self.control, project_id,
                           "create pytest verification plan"),
            VerificationPlan(
                verification_plan_id=plan_id,
                task_id=task_id,
                project_id=project_id,
                version=1,
                status="ACTIVE",
                artifact_selectors=("workspace",),
                aggregation_rule="all_required_pass",
                independence="worker_context_excluded",
                created_by=self.control,
                checks=(VerificationPlanCheck(
                    check_id="pytest",
                    check_type="integration_test",
                    runner_profile="pytest",
                    required=True,
                    timeout_seconds=300,
                    pass_condition="exit_code == 0",
                    evidence_level="E2",
                    ordinal=0,
                ),),
            ),
        ))

        # --- resource account
        account_id = "account-" + run_id
        self.accounting.create_account(CreateResourceAccount(
            self._envelope("resource_account.create", "key-account-" + run_id, 0,
                           self.control, project_id, "create trial resource account"),
            account_id=account_id,
            scope_type="project",
            scope_id=project_id,
            limits={
                "execution_time_ms": 3_600_000,
                "cpu_time_ms": 3_600_000,
                "docker_runtime_ms": 3_600_000,
                "storage_bytes": 10_000_000,
                "agent_runs": 20,
            },
        ))

        # --- template capability (real authority path)
        template = self._seed_worker_template(project_id)

        # --- freeze chain for the implement execution
        policy_impl, risk_impl = self._evaluate_action(
            plan_implement["planning_run_id"], implement_action,
            work_available["version"], "implement",
        )
        selection_impl, reservation_impl = self._select_action(
            plan_implement["planning_run_id"], implement_action,
            work_available["version"], account_id, "implement",
        )
        match_impl, context_impl, sandbox_impl = self._capability_freeze(
            task_id, selection_impl["decision_id"], implement_action,
            policy_impl, risk_impl, reservation_impl, plan_id, template, "implement",
        )
        prepared_impl = self.execution.prepare(self._prepare_command(
            run_id, task_id, selection_impl, implement_action, policy_impl, risk_impl,
            reservation_impl, match_impl, template, context_impl, sandbox_impl,
            plan_id, "implement",
        ))
        lease_impl, binding_impl = self._lease_and_start(
            run_id, prepared_impl["execution_request_id"], reservation_impl,
            template, context_impl, sandbox_impl, "implement",
        )
        self.records["execution_implement"] = {
            "execution_request_id": prepared_impl["execution_request_id"],
            "lease_id": lease_impl["lease_id"],
            "fencing_token": lease_impl["fencing_token"],
            "action": "implement",
        }

        # --- execution 1: golden worker builds a DEFECTIVE project -> pytest FAILS
        worker1 = self._run_golden_worker(
            task_id, prepared_impl["execution_request_id"], run_id, summary,
            first_fault, prepare_venv=True, tag="implement",
            renewal={
                "execution_request_id": prepared_impl["execution_request_id"],
                "lease_id": lease_impl["lease_id"],
                "scheduler_id": lease_impl["scheduler_id"],
                "session": lease_impl["scheduler_session_id"],
                "fencing_token": lease_impl["fencing_token"],
            },
        )
        if worker1["pytest"]["passed"]:
            raise TrialError("expected the broken-test worker to fail pytest")
        result1_id = "result-" + run_id + "-implement"
        account_after_selection = self._account_version(account_id)
        binding_impl = self._refresh_binding(binding_impl)
        result1 = self.worker.submit_result(SubmitExecutionResult(
            command_id=_uuid("cmd-result"),
            idempotency_key=_uuid("key-result-implement"),
            binding=binding_impl,
            result=ExecutionResultSubmission(
                result_id=result1_id,
                outcome=ExecutionOutcome.FAILED_PERMANENT,
                error_classification="test_assertion_failure",
                artifact_candidate_refs=(),
                evidence_candidate_refs=(),
                usage_sample_refs=(),
                started_at=_now(),
                finished_at=_now(),
                adapter_identity="golden-builder",
                adapter_version="1.0",
            ),
            expected_account_version=account_after_selection,
            actor_id=WORKER_IDENTITY,
        ))
        self.records["worker_implement"] = {
            "outcome": "FAILED_PERMANENT",
            "result_id": result1_id,
            "pytest": worker1["pytest"],
        }

        # --- Recovery: emit feedback (task re-entry to READY happens inside
        #     hermes_emit_execution_feedback, migration 0024)
        feedback = self.recovery.emit_execution_feedback(EmitExecutionFeedback(
            command_id=_uuid("cmd-feedback"),
            idempotency_key=_uuid("key-feedback"),
            project_id=project_id,
            result_id=result1_id,
            feedback_id="feedback-" + run_id,
            repair_task_id=task_id,
            max_attempts=2,
        ))
        self.records["recovery"] = {
            "cycle_id": feedback["cycle_id"],
            "failure_type": feedback["failure_type"],
            "recovery_level": feedback["recovery_level"],
            "event_ids": feedback["event_ids"],
        }

        # --- Situation: verification_failed (from feedback.created)
        feedback_event_id = feedback["event_ids"][0]
        verification_failed = self._situation_for_event(feedback_event_id)
        if verification_failed.get("classification") not in {"CREATED", "UPDATED"}:
            raise TrialError("verification_failed situation not created")
        ctx2 = self._situation_context(verification_failed["analysis_context_id"])
        self.records["situation_failed"] = {
            "trigger": "feedback.created",
            "situation_id": verification_failed["situation_id"],
            "version": verification_failed["version"],
            "failure_type": feedback["failure_type"],
        }

        # --- Diagnosis (real engine)
        diagnosis = self.diagnosis.run(RunDiagnosis(
            command_id=_uuid("cmd-diagnosis"),
            idempotency_key=_uuid("key-diagnosis"),
            project_id=project_id,
            situation_id=verification_failed["situation_id"],
            situation_version=verification_failed["version"],
            analysis_context_id=ctx2["analysis_context_id"],
            analysis_context_hash=ctx2["context_hash"],
        ))
        self.records["diagnosis"] = {
            "diagnosis_id": diagnosis["diagnosis_id"],
            "input_hash": diagnosis["input_hash"],
            "root_cause_status": diagnosis["root_cause_status"],
            "root_cause": diagnosis["root_cause"],
        }

        # --- Plan: repair (worker-executable, existing registry action)
        plan_repair = self.planner.plan(PlanCandidates(
            command_id=_uuid("cmd-plan-repair"),
            idempotency_key=_uuid("key-plan-repair"),
            project_id=project_id,
            situation_id=verification_failed["situation_id"],
            expected_situation_version=verification_failed["version"],
            analysis_context_id=ctx2["analysis_context_id"],
            analysis_context_hash=ctx2["context_hash"],
            expected_diagnosis_id=diagnosis["diagnosis_id"],
            expected_diagnosis_input_hash=diagnosis["input_hash"],
            registry_version=P6_REGISTRY_VERSION,
        ))
        repair_action = self._read_candidate(plan_repair["planning_run_id"], "repair")
        self.records["planning_repair"] = {
            "planning_run_id": plan_repair["planning_run_id"],
            "action": repair_action,
        }

        # --- Recovery attempt (real controller)
        attempt = self.recovery.plan_recovery_attempt(PlanRecoveryAttempt(
            command_id=_uuid("cmd-recovery-attempt"),
            idempotency_key=_uuid("key-recovery-attempt"),
            project_id=project_id,
            cycle_id=feedback["cycle_id"],
            attempt_id="attempt-" + run_id,
        ))
        self.records["recovery_attempt"] = {
            "attempt_id": attempt["attempt_id"],
            "action_type": attempt["action_type"],
            "result_code": attempt["result_code"],
        }

        # --- freeze chain for the repair execution
        policy_repair, risk_repair = self._evaluate_action(
            plan_repair["planning_run_id"], repair_action,
            verification_failed["version"], "repair",
        )
        selection_repair, reservation_repair = self._select_action(
            plan_repair["planning_run_id"], repair_action,
            verification_failed["version"], account_id, "repair",
        )
        match_repair, context_repair, sandbox_repair = self._capability_freeze(
            task_id, selection_repair["decision_id"], repair_action,
            policy_repair, risk_repair, reservation_repair, plan_id, template, "repair",
        )
        prepared_repair = self.execution.prepare(self._prepare_command(
            run_id, task_id, selection_repair, repair_action, policy_repair, risk_repair,
            reservation_repair, match_repair, template, context_repair, sandbox_repair,
            plan_id, "repair",
        ))
        lease_repair, binding_repair = self._lease_and_start(
            run_id, prepared_repair["execution_request_id"], reservation_repair,
            template, context_repair, sandbox_repair, "repair",
        )
        self.records["execution_repair"] = {
            "execution_request_id": prepared_repair["execution_request_id"],
            "lease_id": lease_repair["lease_id"],
            "fencing_token": lease_repair["fencing_token"],
            "action": "repair",
        }

        # --- execution 2: golden worker builds the full correct project -> PASS
        worker2 = self._run_golden_worker(
            task_id, prepared_repair["execution_request_id"], run_id, summary,
            WorkerFaultMode.NONE, prepare_venv=False, tag="repair",
            renewal={
                "execution_request_id": prepared_repair["execution_request_id"],
                "lease_id": lease_repair["lease_id"],
                "scheduler_id": lease_repair["scheduler_id"],
                "session": lease_repair["scheduler_session_id"],
                "fencing_token": lease_repair["fencing_token"],
            },
        )
        if not worker2["pytest"]["passed"]:
            raise TrialError("expected the repaired worker to pass pytest")
        manifest = worker2["manifest"]
        binding_repair = self._refresh_binding(binding_repair)

        # record artifact candidates from the real worker manifest
        artifact_candidate_ids = []
        for item in manifest:
            candidate_id = _uuid("artifact-cand")
            self.worker.record_artifact_candidate(RecordArtifactCandidate(
                command_id=_uuid("cmd-artifact"),
                idempotency_key=_uuid("key-artifact-" + candidate_id),
                binding=binding_repair,
                candidate=ArtifactCandidateSubmission(
                    candidate_id=candidate_id,
                    artifact_kind="source_tree",
                    content_hash=item["content_hash"],
                    storage_ref="object://artifacts/" + run_id + "/" + item["path"],
                    size_bytes=item["size_bytes"],
                    media_type="text/plain",
                ),
                actor_id=WORKER_IDENTITY,
            ))
            artifact_candidate_ids.append(candidate_id)
        primary_candidate_id = artifact_candidate_ids[0]
        primary_artifact_id = "artifact-" + primary_candidate_id
        # The task's current_artifact_hash is set from the primary candidate's
        # content hash by hermes_submit_execution_result; the first manifest
        # item is the primary candidate.
        primary_hash = manifest[0]["content_hash"]

        usage_id = _uuid("usage")
        usage_sample_id = "sample-" + run_id
        self.worker.record_usage_sample(RecordUsageSample(
            command_id=_uuid("cmd-usage"),
            idempotency_key=_uuid("key-usage-" + usage_id),
            binding=binding_repair,
            sample=UsageSampleSubmission(
                usage_id=usage_id,
                sample_id=usage_sample_id,
                reservation_id=reservation_repair,
                amounts={"execution_time_ms": 5000},
                interval_start=_now(),
                interval_end=_now(),
            ),
            actor_id=WORKER_IDENTITY,
        ))
        result2_id = "result-" + run_id + "-repair"
        account_before_submit = self._account_version(account_id)
        result2 = self.worker.submit_result(SubmitExecutionResult(
            command_id=_uuid("cmd-result"),
            idempotency_key=_uuid("key-result-repair"),
            binding=binding_repair,
            result=ExecutionResultSubmission(
                result_id=result2_id,
                outcome=ExecutionOutcome.SUCCEEDED,
                error_classification="",
                artifact_candidate_refs=tuple(artifact_candidate_ids),
                evidence_candidate_refs=(),
                usage_sample_refs=(usage_sample_id,),
                started_at=_now(),
                finished_at=_now(),
                adapter_identity="golden-builder",
                adapter_version="1.0",
                primary_artifact_candidate_id=primary_candidate_id,
                completion_claim_id="claim-golden-" + run_id,
            ),
            expected_account_version=account_before_submit,
            actor_id=WORKER_IDENTITY,
        ))
        self.records["worker_repair"] = {
            "outcome": "SUCCEEDED",
            "result_id": result2_id,
            "primary_artifact_id": primary_artifact_id,
            "primary_hash": primary_hash,
            "manifest": manifest,
        }

        # --- independent verification: real golden-verifier subprocess
        verifier_outcome = self._verify_workspace(run_id, manifest)
        self.records["verifier_outcome"] = verifier_outcome
        if verifier_outcome["verdict"] != "PASS":
            raise TrialError(
                "independent verification failed: " + str(verifier_outcome["finding_codes"])
            )
        task_version = self._task_version(task_id, project_id)
        verifier_run_id = "run-verifier-golden-" + run_id
        self.control_plane.admit_agent_run(AdmitAgentRun(
            self._envelope("agent_run.admit", "key-verifier-golden-" + run_id,
                           task_version, self.control, project_id,
                           "admit golden verifier run"),
            AgentRun(
                run_id=verifier_run_id,
                project_id=project_id,
                task_id=task_id,
                run_kind=AgentRunKind.VERIFIER,
                agent_identity=VERIFIER_IDENTITY,
                context_identity="verifier-context-golden",
                status=AgentRunStatus.ADMITTED,
                created_by=self.control,
            ),
        ))
        golden_verification_id = "verification-golden-" + run_id
        evidence_id = "evidence-golden-" + run_id
        self.control_plane.record_verification_result(RecordVerificationResult(
            self._envelope("verification.record_result", "key-verif-golden-" + run_id,
                           task_version, self.verifier, project_id,
                           "independent pytest verification of golden project"),
            VerificationResult(
                verification_id=golden_verification_id,
                plan_id=plan_id,
                plan_version=1,
                task_id=task_id,
                project_id=project_id,
                artifact_id=primary_artifact_id,
                artifact_hash=primary_hash,
                verifier_identity=self.verifier,
                verifier_run_id=verifier_run_id,
                verdict=Verdict.PASS,
                check_results=(VerificationCheckResult(
                    check_id="pytest", status=Verdict.PASS,
                    finding_codes=(), evidence_refs=(evidence_id,),
                    started_at=_now(), completed_at=_now(),
                ),),
                evidence=(Evidence(
                    evidence_id, primary_artifact_id, primary_hash,
                    VERIFIER_IDENTITY, True,
                ),),
                started_at=_now(), completed_at=_now(),
                correlation_id="corr-" + run_id,
            ),
        ))
        apply_receipt = self.control_plane.apply_verified_task_transition(
            ApplyVerifiedTaskTransition(
                self._envelope("task.apply_verified_transition", "key-apply-pass-" + run_id,
                               task_version, self.control, project_id,
                               "apply golden PASS"),
                task_id,
                golden_verification_id,
            )
        )
        self.records["task_pass"] = {
            "state": "PASSED",
            "verification_id": golden_verification_id,
            "receipt": apply_receipt.__dict__,
        }

        # --- complete the recovery attempt (real controller)
        completion = self.recovery.complete_recovery_attempt(CompleteRecoveryAttempt(
            command_id=_uuid("cmd-complete-recovery"),
            idempotency_key=_uuid("key-complete-recovery"),
            project_id=project_id,
            attempt_id=attempt["attempt_id"],
            outcome="SUCCEEDED",
            linked_execution_request_id=prepared_repair["execution_request_id"],
            linked_result_id=result2_id,
            linked_verification_id=golden_verification_id,
        ))
        self.records["recovery_complete"] = {
            "result_code": completion["result_code"],
        }

        # --- project delivery: guard facts + transitions to ACCEPTED
        self.records["delivery"] = self._advance_project_to_accepted(
            project_id, run_id, account_id,
        )

        # --- evidence snapshot
        self.records["events"] = self._collect_events(project_id)
        self.records["artifacts"] = {
            "primary_artifact_id": primary_artifact_id,
            "primary_hash": primary_hash,
            "manifest": manifest,
        }
        return self.records

    def _scenario_project(self, run_id: str, summary: str, task_id: str):
        """Shared intake for scenario runs: project + task graph + readiness."""
        project_id = "project-" + run_id
        self._project_id = project_id
        self.workspace = self.workspace_root / run_id
        self.workspace.mkdir(parents=True, exist_ok=True)
        self._ensure_verifier(VERIFIER_IDENTITY)
        self.control_plane.create_project(CreateProject(
            self._envelope("project.create", "key-create-" + run_id, 0,
                           self.control, project_id, "autonomous software request"),
            summary,
            self.user,
        ))
        patch_receipt = self.control_plane.apply_work_graph_patch(ApplyWorkGraphPatch(
            self._envelope("work_graph.apply_patch", "key-graph-" + run_id, 0,
                           self.control, project_id, "create golden todo task"),
            GraphPatch(
                base_graph_version=0,
                decision_id="decision-graph-" + run_id,
                operations=(CreateTask(GraphTask(task_id, "implement", summary)),),
            ),
        ))
        self._scenario_patch_event_ids[run_id] = patch_receipt.event_ids[0]
        return project_id, patch_receipt

    def _scenario_verification_plan(self, project_id: str, task_id: str, run_id: str) -> str:
        plan_id = "plan-" + run_id
        task_version = self._task_version(task_id, project_id)
        self.control_plane.create_verification_plan(CreateVerificationPlan(
            self._envelope("verification_plan.create", "key-plan-verif-" + run_id,
                           task_version, self.control, project_id,
                           "create pytest verification plan"),
            VerificationPlan(
                verification_plan_id=plan_id,
                task_id=task_id,
                project_id=project_id,
                version=1,
                status="ACTIVE",
                artifact_selectors=("workspace",),
                aggregation_rule="all_required_pass",
                independence="worker_context_excluded",
                created_by=self.control,
                checks=(VerificationPlanCheck(
                    check_id="pytest", check_type="integration_test",
                    runner_profile="pytest", required=True, timeout_seconds=300,
                    pass_condition="exit_code == 0", evidence_level="E2", ordinal=0,
                ),),
            ),
        ))
        return plan_id

    # ------------------------------------------------------------------ delivery

    def _advance_project_to_accepted(
        self, project_id: str, run_id: str, account_id: str,
    ) -> Dict[str, Any]:
        mainline = (
            ProjectState.CREATED, ProjectState.INTAKE, ProjectState.DISCOVERY,
            ProjectState.PLANNING, ProjectState.DESIGNING, ProjectState.IMPLEMENTING,
            ProjectState.VERIFYING, ProjectState.HARDENING, ProjectState.PACKAGING,
            ProjectState.DELIVERING, ProjectState.ACCEPTED,
        )
        steps = []
        project = self.project_store.read_project(project_id)
        while project.state is not ProjectState.ACCEPTED:
            target = mainline[mainline.index(project.state) + 1]
            version = project.version
            evidence_fact_id = "evidence-" + run_id + "-" + str(version)
            policy_fact_id = "policy-" + run_id + "-" + str(version)
            budget_fact_id = "budget-" + run_id + "-" + str(version)
            self.guard_facts.record_evidence_fact(RecordProjectEvidenceFact(
                self._envelope(
                    "project.record_evidence_fact",
                    "key-ev-" + run_id + "-" + str(version),
                    version, self.control, project_id,
                    "verification evidence for transition",
                ),
                evidence_fact_id=evidence_fact_id,
                project_version=version,
                from_state=project.state.value,
                to_state=target.value,
                subject_ref="verification-golden-" + run_id,
            ))
            self.guard_facts.record_policy_fact(RecordProjectPolicyFact(
                self._envelope(
                    "project.record_policy_fact",
                    "key-pol-" + run_id + "-" + str(version),
                    version, self.control, project_id,
                    "policy decision for transition",
                ),
                policy_decision_id=policy_fact_id,
                project_version=version,
                from_state=project.state.value,
                to_state=target.value,
                result="ALLOW",
                policy_bundle_version=POLICY_BUNDLE_VERSION,
                input_hash="sha256:" + uuid.uuid4().hex,
            ))
            account_version = self._account_version(account_id)
            self.accounting.issue_budget_fact(IssueProjectBudgetFact(
                self._envelope(
                    "resource.budget_fact.issue",
                    "key-budget-" + run_id + "-" + str(version),
                    account_version, self.control, project_id,
                    "budget fact for transition",
                ),
                budget_fact_id=budget_fact_id,
                account_id=account_id,
                project_version=version,
                from_state=project.state.value,
                to_state=target.value,
            ))
            receipt = self.control_plane.request_project_transition(
                RequestProjectTransition(
                    self._envelope(
                        "project.request_transition",
                        "key-trans-" + run_id + "-" + str(version),
                        version, self.control, project_id,
                        "advance to " + target.value,
                    ),
                    target,
                    self.control,
                    (evidence_fact_id, policy_fact_id, budget_fact_id),
                )
            )
            steps.append({
                "from": project.state.value, "to": target.value,
                "version": version, "receipt": receipt.__dict__,
            })
            project = self.project_store.read_project(project_id)
        return {"final_state": project.state.value, "steps": steps}

    def _collect_events(self, project_id: str) -> List[Dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT event_id, event_type, sequence, payload
                   FROM event_log WHERE project_id=%s ORDER BY sequence""",
                (project_id,),
            ).fetchall()
            return [{"event_id": r[0], "event_type": r[1], "sequence": r[2],
                     "payload": r[3]} for r in rows]
