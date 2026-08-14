import os
import unittest
from pathlib import Path

try:
    import psycopg
    from psycopg.types.json import Jsonb
except ImportError:
    psycopg = None
    Jsonb = None

from hermes_runtime.application.commands import (
    AdmitAgentRun,
    ApplyVerifiedTaskTransition,
    RecordVerificationResult,
)
from hermes_runtime.application.diagnoses import DiagnosisEngine, RunDiagnosis
from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.application.executions import ExecutionPreparation
from hermes_runtime.application.handlers import ControlPlane
from hermes_runtime.application.planning import ActionPlanner, PlanCandidates
from hermes_runtime.application.recovery import (
    CompleteRecoveryAttempt,
    EmitExecutionFeedback,
    PlanRecoveryAttempt,
    RecoveryController,
)
from hermes_runtime.application.scheduling import (
    AcquireExecutionLease,
    ExecutionScheduler,
    RegisterScheduler,
)
from hermes_runtime.application.situations import SituationAnalyzer
from hermes_runtime.application.workers import (
    RecordArtifactCandidate,
    RecordUsageSample,
    StartWorkerRun,
    SubmitExecutionResult,
    WorkerExecution,
)
from hermes_runtime.domain.execution import ArtifactInputRef, LockIntent
from hermes_runtime.domain.models import (
    Actor,
    ActorType,
    AgentRun,
    AgentRunKind,
    AgentRunStatus,
    CommandEnvelope,
    Evidence,
    VerificationCheckResult,
    VerificationResult,
    Verdict,
)
from hermes_runtime.domain.worker_execution import (
    ArtifactCandidateSubmission,
    ExecutionOutcome,
    ExecutionResultSubmission,
    UsageSampleSubmission,
    WorkerFrozenContext,
    WorkerLeaseBinding,
)
from hermes_runtime.infrastructure.postgres import PostgresRuntimeStore
from hermes_runtime.infrastructure.postgres_diagnosis import PostgresDiagnosisStore
from hermes_runtime.infrastructure.postgres_execution import PostgresExecutionStore
from hermes_runtime.infrastructure.postgres_planner import PostgresPlannerStore
from hermes_runtime.infrastructure.postgres_recovery import (
    PostgresRecoveryStore,
    RecoveryFaultPoint,
)
from hermes_runtime.infrastructure.postgres_scheduler import PostgresSchedulerStore
from hermes_runtime.infrastructure.postgres_situation import PostgresSituationStore
from hermes_runtime.infrastructure.postgres_worker_execution import PostgresWorkerExecutionStore

try:
    from . import test_execution_postgres as execution_fixtures
except ImportError:
    import test_execution_postgres as execution_fixtures


DATABASE_URL = os.environ.get("HERMES_TEST_DATABASE_URL")


class _ExecutionFixture:
    seed_fixture = execution_fixtures.ExecutionPostgresTests.seed_fixture
    command = execution_fixtures.ExecutionPostgresTests.command


@unittest.skipUnless(DATABASE_URL and psycopg, "requires real PostgreSQL 14+")
class RecoveryPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = PostgresRecoveryStore(DATABASE_URL)
        for migration in sorted((Path(__file__).parents[1] / "migrations").glob("*.sql")):
            cls.store.apply_migration(migration)

    def setUp(self):
        self.store.reset_for_test()
        self.execution = ExecutionPreparation(PostgresExecutionStore(DATABASE_URL))
        self.scheduler = ExecutionScheduler(PostgresSchedulerStore(DATABASE_URL))
        self.worker = WorkerExecution(PostgresWorkerExecutionStore(DATABASE_URL))
        self.recovery = RecoveryController(PostgresRecoveryStore(DATABASE_URL))
        self.fixture = _ExecutionFixture()
        self.fixture.store = self.store
        self.fixture.seed_fixture("p2-5")

    def prepare_leased(self, suffix):
        prepared = self.execution.prepare(self.fixture.command(suffix))
        self.scheduler.register(RegisterScheduler(
            "cmd-register-" + suffix,
            "key-register-" + suffix,
            "project-1",
            "sched-" + suffix,
            "session-" + suffix,
            actor_id="sched-" + suffix,
        ))
        lease = self.scheduler.acquire(AcquireExecutionLease(
            "cmd-acquire-" + suffix,
            "key-acquire-" + suffix,
            "project-1",
            "sched-" + suffix,
            "session-" + suffix,
            actor_id="sched-" + suffix,
        ))
        self.assertEqual(prepared["execution_request_id"], lease["execution_request_id"])
        return prepared, lease

    def binding(self, lease, suffix, **overrides):
        values = dict(
            project_id="project-1",
            execution_request_id=lease["execution_request_id"],
            execution_attempt=1,
            run_id="worker-run-" + suffix,
            lease_id=lease["lease_id"],
            lease_version=lease["lease_version"],
            fencing_token=lease["fencing_token"],
            scheduler_id="sched-" + suffix,
            scheduler_session_id="session-" + suffix,
            worker_agent_identity="worker-" + suffix,
            context_identity="worker-context-" + suffix,
            observed_request_version=lease["request_version"],
        )
        values.update(overrides)
        return WorkerLeaseBinding(**values)

    def frozen(self, suffix, reservation_id="reservation-1"):
        context_bundle_id = "ctx-1" if reservation_id == "reservation-1" else "ctx-" + suffix
        sandbox_profile_id = "sbx-1" if reservation_id == "reservation-1" else "sbx-" + suffix
        return WorkerFrozenContext(
            "template-1",
            1,
            "sha256:template",
            context_bundle_id,
            "sha256:context" if reservation_id == "reservation-1" else "sha256:context2",
            sandbox_profile_id,
            "sha256:sandbox" if reservation_id == "reservation-1" else "sha256:sandbox2",
            reservation_id,
        )

    def start(self, lease, suffix, reservation_id="reservation-1"):
        binding = self.binding(lease, suffix)
        return self.worker.start_run(StartWorkerRun(
            "cmd-start-" + suffix,
            "key-start-" + suffix,
            binding,
            self.frozen(suffix, reservation_id),
            actor_id=binding.worker_agent_identity,
        ))

    def current_binding(self, lease, suffix):
        version = self.store.scalar(
            "SELECT request_version FROM execution_request_current_states "
            "WHERE execution_request_id='{}'".format(lease["execution_request_id"])
        )
        return self.binding(lease, suffix, observed_request_version=version)

    def submit_failed_execution_result(self, suffix="fail"):
        _, lease = self.prepare_leased(suffix)
        self.start(lease, suffix, "reservation-1")
        binding = self.current_binding(lease, suffix)
        result = self.worker.submit_result(SubmitExecutionResult(
            "cmd-result-" + suffix,
            "key-result-" + suffix,
            binding,
            ExecutionResultSubmission(
                "result-" + suffix,
                ExecutionOutcome.FAILED_PERMANENT,
                "test_assertion_failure",
                (),
                (),
                (),
                "2026-08-13T00:00:00Z",
                "2026-08-13T00:00:01Z",
                "test-adapter",
                "1.0",
            ),
            1,
            actor_id=binding.worker_agent_identity,
        ))
        self.assertEqual("FAILED", result["request_state"])
        return result

    def plan_feedback_chain(self, failed_result_id="result-fail"):
        feedback = self.recovery.emit_execution_feedback(EmitExecutionFeedback(
            "cmd-feedback-1",
            "key-feedback-1",
            "project-1",
            failed_result_id,
            "feedback-1",
            "repair-task-1",
            max_attempts=2,
        ))
        self.assertEqual("RECOVERY_FEEDBACK_EMITTED", feedback["result_code"])

        situation = self._analyze_through_event(feedback["event_ids"][0])
        with psycopg.connect(DATABASE_URL) as connection:
            situation_row = connection.execute(
                """SELECT s.situation_id,s.version,s.analysis_context_id,c.context_hash
                   FROM situations s JOIN analysis_contexts c
                     ON c.analysis_context_id=s.analysis_context_id
                   WHERE s.trigger_event_id=%s""",
                (feedback["event_ids"][0],),
            ).fetchone()
        self.assertIsNotNone(situation_row, situation)
        diagnosis = DiagnosisEngine(PostgresDiagnosisStore(DATABASE_URL)).run(
            RunDiagnosis(
                "cmd-diagnosis-feedback",
                "key-diagnosis-feedback",
                "project-1",
                situation_row[0],
                situation_row[1],
                situation_row[2],
                situation_row[3],
            )
        )
        self.assertIn(diagnosis["root_cause_status"], {"PROBABLE", "CONFIRMED"})
        plan = ActionPlanner(PostgresPlannerStore(DATABASE_URL)).plan(PlanCandidates(
            "cmd-planner-feedback",
            "key-planner-feedback",
            "project-1",
            situation_row[0],
            situation_row[1],
            situation_row[2],
            situation_row[3],
            expected_diagnosis_id=diagnosis["diagnosis_id"],
            expected_diagnosis_input_hash=diagnosis["input_hash"],
        ))
        with psycopg.connect(DATABASE_URL) as connection:
            action_types = {row[0] for row in connection.execute(
                "SELECT type FROM candidate_actions WHERE planning_run_id=%s",
                (plan["planning_run_id"],),
            ).fetchall()}
        self.assertIn("repair", action_types)
        attempt = self.recovery.plan_recovery_attempt(PlanRecoveryAttempt(
            "cmd-recovery-attempt-1",
            "key-recovery-attempt-1",
            "project-1",
            feedback["cycle_id"],
            "attempt-1",
        ))
        self.assertEqual("RECOVERY_ATTEMPT_PLANNED", attempt["result_code"])
        self.assertEqual("repair", attempt["action_type"])
        return feedback, diagnosis, plan, attempt

    def _analyze_through_event(self, target_event_id):
        store = PostgresSituationStore(DATABASE_URL)
        result = None
        with psycopg.connect(DATABASE_URL) as connection:
            rows = connection.execute(
                """SELECT event_id FROM event_log
                   WHERE project_id='project-1'
                   ORDER BY sequence"""
            ).fetchall()
        for (event_id,) in rows:
            result = store.analyze_logged_event(event_id)
            if event_id == target_event_id:
                return result
        self.fail("target feedback event was not found: " + target_event_id)

    def seed_second_execution_freeze(self):
        with psycopg.connect(DATABASE_URL) as connection:
            task_version = connection.execute(
                """UPDATE tasks SET state='READY', version=version+1
                   WHERE task_id='task-1' AND project_id='project-1'
                   RETURNING version"""
            ).fetchone()[0]
            account_version = connection.execute(
                "SELECT version FROM resource_accounts WHERE account_id='account-1'"
            ).fetchone()[0]
            for command_id, command_type in (
                ("cmd-action-recovery", "planner.plan_candidates"),
                ("cmd-policy-recovery", "policy.evaluate"),
                ("cmd-risk-recovery", "risk.assess"),
                ("cmd-reserve-recovery", "accounting.reserve"),
                ("cmd-select-recovery", "selection.select_actions"),
                ("cmd-match-recovery", "capability.match_requirements"),
                ("cmd-context-recovery", "context.create_bundle"),
                ("cmd-sandbox-recovery", "sandbox.compile_profile"),
            ):
                connection.execute(
                    """INSERT INTO command_receipts(
                       command_id,project_id,command_type,idempotency_key,
                       request_hash,status,result,completed_at)
                       VALUES (%s,'project-1',%s,%s,'fixture',
                               'APPLIED','{}',now())""",
                    (command_id, command_type, command_id),
                )
            connection.execute(
                """INSERT INTO candidate_actions(
                   action_id,planning_run_id,project_id,situation_id,
                   situation_version,analysis_context_id,analysis_context_hash,
                   type,reason_code,target_refs,required_capabilities,
                   parameters,estimated_resources,planner_confidence_basis_points,
                   expected_progress_basis_points,evidence_gain_basis_points,
                   reversibility_basis_points,registry_version,planner_rule_version,
                   ordinal,content_hash)
                   VALUES ('action-2','plan-run-1','project-1','situation-1',
                           1,'ctx-analysis-1','sha256:analysis','repair',
                           'recovery_repair_attempt',ARRAY['task:task-1'],
                           ARRAY['repair.code'],
                           '{"target_environment":"dev"}',
                           '{"execution_time_ms":400,"cpu_time_ms":100,"storage_bytes":100}',
                           8500,8000,1500,9000,'action-registry/1.0',
                           'planner-rules/1.0',1,'sha256:action2')"""
            )
            connection.execute(
                """INSERT INTO policy_evaluation_contexts(
                   evaluation_context_id,project_id,planning_run_id,action_id,
                   action_content_hash,situation_id,situation_version,
                   analysis_context_hash,planner_input_hash,candidate_registry_version,
                   policy_bundle_version,target_environment,resource_estimate_hash,
                   context_hash)
                   VALUES ('evalctx-policy-2','project-1','plan-run-1','action-2',
                           'sha256:action2','situation-1',1,'sha256:analysis',
                           'sha256:plan-input','action-registry/1.0',
                           'policy-bundle/1.0','dev','sha256:resource2',
                           'sha256:policy-context2')"""
            )
            connection.execute(
                """INSERT INTO policy_decisions(
                   policy_decision_id,evaluation_context_id,project_id,
                   planning_run_id,action_id,action_content_hash,result,
                   constraints,policy_bundle_version,policy_rule_version,
                   policy_input_hash,command_id)
                   VALUES ('policy-2','evalctx-policy-2','project-1',
                           'plan-run-1','action-2','sha256:action2','ALLOW',
                           '{"network_access":"disabled","filesystem_write":"none","secret_access":"denied","production_access":"denied","allowed_tools":["pytest"],"max_external_api_calls":0}',
                           'policy-bundle/1.0','policy-rules/1.0',
                           'sha256:policy-input2','cmd-policy-recovery')"""
            )
            connection.execute(
                """INSERT INTO current_policy_decisions(
                   action_id,policy_decision_id,planning_run_id,
                   action_content_hash,policy_bundle_version,policy_input_hash)
                   VALUES ('action-2','policy-2','plan-run-1','sha256:action2',
                           'policy-bundle/1.0','sha256:policy-input2')"""
            )
            connection.execute(
                """INSERT INTO risk_assessments(
                   risk_assessment_id,evaluation_context_id,project_id,
                   planning_run_id,action_id,action_content_hash,
                   risk_score_basis_points,risk_level,factors,required_mitigations,
                   available_mitigations,residual_risk_basis_points,
                   risk_model_version,risk_rule_version,risk_input_hash,command_id)
                   VALUES ('risk-2','evalctx-policy-2','project-1','plan-run-1',
                           'action-2','sha256:action2',2000,'LOW','{}',
                           ARRAY['verification-before-apply'],
                           ARRAY['verification-before-apply'],1500,
                           'risk-model/1.0','risk-rules/1.0',
                           'sha256:risk-input2','cmd-risk-recovery')"""
            )
            connection.execute(
                """INSERT INTO current_risk_assessments(
                   action_id,risk_assessment_id,planning_run_id,
                   action_content_hash,risk_model_version,risk_input_hash)
                   VALUES ('action-2','risk-2','plan-run-1','sha256:action2',
                           'risk-model/1.0','sha256:risk-input2')"""
            )
            connection.execute(
                """INSERT INTO resource_reservations(
                   reservation_id,account_id,project_id,owner_type,owner_id,
                   status,account_version,command_id)
                   VALUES ('reservation-2','account-1','project-1','decision',
                           'decision-2','ACTIVE',%s,'cmd-reserve-recovery')""",
                (account_version,),
            )
            connection.execute(
                """INSERT INTO resource_reservation_amounts(
                   reservation_id,dimension,amount)
                   VALUES ('reservation-2','execution_time_ms',400)"""
            )
            connection.execute(
                """UPDATE resource_balances
                   SET reserved_amount=reserved_amount+400
                   WHERE account_id='account-1' AND dimension='execution_time_ms'"""
            )
            connection.execute(
                """INSERT INTO decision_records(
                   decision_id,project_id,situation_id,situation_version,
                   analysis_context_id,analysis_context_hash,input_observed_at_sequence,
                   planning_run_id,planning_input_hash,selection_version,
                   input_snapshot_hash,candidate_refs,eligible_action_ids,
                   selected_action_ids,policy_refs,risk_refs,
                   resource_account_snapshots,score_refs,reservation_refs,
                   weight_profile_id,normalizer_version,conflict_rule_version,
                   max_parallel_selected_actions,command_id,actor_type,actor_id)
                   VALUES ('decision-2','project-1','situation-1',1,
                           'ctx-analysis-1','sha256:analysis',1,'plan-run-1',
                           'sha256:plan-input',2,'sha256:selection-input2',
                           '[{"action_id":"action-2","content_hash":"sha256:action2"}]',
                           ARRAY['action-2'],ARRAY['action-2'],
                           '[{"policy_decision_id":"policy-2"}]',
                           '[{"risk_assessment_id":"risk-2"}]',
                           '[]','[]','[{"reservation_id":"reservation-2"}]',
                           'selection-weight-profile/1.0',
                           'selection-normalizer/1.0',
                           'selection-conflict-rules/1.0',2,'cmd-select-recovery',
                           'action_selection','fixture')"""
            )
            connection.execute(
                """INSERT INTO selected_action_refs(
                   decision_id,action_id,selection_rank,selected_intent)
                   VALUES ('decision-2','action-2',0,
                           '{"action_id":"action-2","type":"repair"}')"""
            )
            connection.execute(
                """INSERT INTO decision_reservation_mappings(
                   decision_id,action_id,reservation_id,account_id,
                   resource_amounts,account_version)
                   VALUES ('decision-2','action-2','reservation-2','account-1',
                           '{"execution_time_ms":400}',%s)""",
                (account_version,),
            )
            connection.execute(
                """INSERT INTO capability_match_records(
                   match_id,project_id,task_id,decision_id,action_id,status,
                   reason_code,requirements_hash,matcher_version,template_id,
                   template_revision,availability_version,template_content_hash,
                   requirement,command_id,actor_type,actor_id)
                   VALUES ('capmatch-2','project-1','task-1','decision-2',
                           'action-2','MATCHED','MATCHED','sha256:requirements2',
                           'capability-matcher/1.0','template-1',1,2,
                           'sha256:template',
                           '{"project_id":"project-1","task_id":"task-1","decision_id":"decision-2","action_id":"action-2","action_content_hash":"sha256:action2"}',
                           'cmd-match-recovery','capability_registry','fixture')"""
            )
            connection.execute(
                """INSERT INTO context_bundles(
                   bundle_id,project_id,task_id,decision_id,action_id,template_id,
                   template_revision,selector_schema_version,builder_version,
                   manifest,manifest_hash,command_id,actor_type,actor_id)
                   VALUES ('ctx-recovery','project-1','task-1','decision-2','action-2',
                           'template-1',1,'context-selector/1.0',
                           'context-builder/1.0',
                           '{"items":[],"selectors":[]}',
                           'sha256:context2','cmd-context-recovery',
                           'context_builder','fixture')"""
            )
            connection.execute(
                """INSERT INTO sandbox_profiles(
                   profile_id,project_id,task_id,action_id,template_id,
                   template_revision,context_bundle_hash,compiler_version,
                   target,profile,profile_hash,constraints_hash,command_id,
                   actor_type,actor_id)
                   VALUES ('sbx-recovery','project-1','task-1','action-2',
                           'template-1',1,'sha256:context2',
                           'sandbox-compiler/1.0','contract-only/1.0',
                           '{"bindings":{"project_id":"project-1"},"secrets":{"mode":"denied"}}',
                           'sha256:sandbox2','sha256:constraints2',
                           'cmd-sandbox-recovery','sandbox_compiler','fixture')"""
            )
        return task_version, account_version

    def recovery_prepare_command(self, expected_task_version):
        return self.fixture.command(
            "recovery",
            command_id="cmd-exec-recovery",
            idempotency_key="key-exec-recovery",
            expected_task_version=expected_task_version,
            decision_id="decision-2",
            decision_version=2,
            decision_hash="sha256:selection-input2",
            action_id="action-2",
            action_content_hash="sha256:action2",
            action_requirements_hash="sha256:requirements2",
            policy_decision_id="policy-2",
            policy_hash="sha256:policy-input2",
            risk_assessment_id="risk-2",
            risk_hash="sha256:risk-input2",
            reservation_id="reservation-2",
            reservation_hash="sha256:reservation2",
            capability_match_id="capmatch-2",
            capability_requirements_hash="sha256:requirements2",
            context_bundle_id="ctx-recovery",
            context_manifest_hash="sha256:context2",
            sandbox_profile_id="sbx-recovery",
            sandbox_profile_hash="sha256:sandbox2",
            input_artifacts=(ArtifactInputRef("artifact-1", "task-1", "sha256:artifact"),),
            lock_intents=(LockIntent("repository:repo-main:recovery"),),
            priority=20,
        )

    def execute_successful_recovery_attempt(self, expected_task_version, account_version):
        prepared = self.execution.prepare(self.recovery_prepare_command(expected_task_version))
        self.scheduler.register(RegisterScheduler(
            "cmd-register-recovery",
            "key-register-recovery",
            "project-1",
            "sched-recovery",
            "session-recovery",
            actor_id="sched-recovery",
        ))
        lease = self.scheduler.acquire(AcquireExecutionLease(
            "cmd-acquire-recovery",
            "key-acquire-recovery",
            "project-1",
            "sched-recovery",
            "session-recovery",
            actor_id="sched-recovery",
        ))
        self.assertEqual(prepared["execution_request_id"], lease["execution_request_id"])
        binding = self.binding(
            lease,
            "recovery",
            run_id="worker-run-recovery",
            scheduler_id="sched-recovery",
            scheduler_session_id="session-recovery",
            worker_agent_identity="worker-recovery",
            context_identity="worker-context-recovery",
        )
        self.worker.start_run(StartWorkerRun(
            "cmd-start-recovery",
            "key-start-recovery",
            binding,
            self.frozen("recovery", "reservation-2"),
            actor_id="worker-recovery",
        ))
        version = self.store.scalar(
            "SELECT request_version FROM execution_request_current_states "
            "WHERE execution_request_id='{}'".format(lease["execution_request_id"])
        )
        binding = self.binding(
            lease,
            "recovery",
            run_id="worker-run-recovery",
            scheduler_id="sched-recovery",
            scheduler_session_id="session-recovery",
            worker_agent_identity="worker-recovery",
            context_identity="worker-context-recovery",
            observed_request_version=version,
        )
        self.worker.record_artifact_candidate(RecordArtifactCandidate(
            "cmd-art-recovery",
            "key-art-recovery",
            binding,
            ArtifactCandidateSubmission(
                "artifact-candidate-recovery",
                "patch",
                "sha256:artifactrecovery",
                "object://artifact/recovery",
                10,
                "text/plain",
            ),
            actor_id="worker-recovery",
        ))
        self.worker.record_usage_sample(RecordUsageSample(
            "cmd-usage-recovery",
            "key-usage-recovery",
            binding,
            UsageSampleSubmission(
                "usage-recovery",
                "sample-recovery",
                "reservation-2",
                {"execution_time_ms": 300},
                interval_start="2026-08-13T00:00:00Z",
                interval_end="2026-08-13T00:00:01Z",
            ),
            actor_id="worker-recovery",
        ))
        result = self.worker.submit_result(SubmitExecutionResult(
            "cmd-result-recovery",
            "key-result-recovery",
            binding,
            ExecutionResultSubmission(
                "result-recovery",
                ExecutionOutcome.SUCCEEDED,
                "",
                ("artifact-candidate-recovery",),
                (),
                ("sample-recovery",),
                "2026-08-13T00:00:00Z",
                "2026-08-13T00:00:01Z",
                "test-adapter",
                "1.0",
                primary_artifact_candidate_id="artifact-candidate-recovery",
                completion_claim_id="claim-recovery",
            ),
            account_version,
            actor_id="worker-recovery",
        ))
        self.assertEqual("SUCCEEDED", result["request_state"])
        return prepared, result

    def verify_recovered_artifact_passes(self):
        runtime_store = PostgresRuntimeStore(DATABASE_URL)
        plane = ControlPlane(runtime_store)
        control = Actor(ActorType.CONTROL_PLANE, "control")
        verifier = Actor(ActorType.VERIFIER, "verifier-1")
        runtime_store.seed_verifier("verifier-1")
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute(
                """INSERT INTO verification_plan_checks(
                   verification_plan_id,plan_version,check_id,type,runner_profile,
                   required,timeout_seconds,pass_condition,evidence_level,ordinal)
                   VALUES ('verification-plan-1',1,'required','integration_test',
                           'runner',true,60,'exit_code == 0','E2',0)
                   ON CONFLICT DO NOTHING"""
            )
            task_version = connection.execute(
                "SELECT version FROM tasks WHERE task_id='task-1'"
            ).fetchone()[0]
        plane.admit_agent_run(AdmitAgentRun(
            CommandEnvelope(
                "cmd-verifier-run-recovery",
                "agent_run.admit",
                "key-verifier-run-recovery",
                task_version,
                control,
                "independent verification after recovery execution",
                "project-1",
            ),
            AgentRun(
                "verifier-run-recovery",
                "project-1",
                "task-1",
                AgentRunKind.VERIFIER,
                "verifier-1",
                "verifier-context-recovery",
                AgentRunStatus.ADMITTED,
                control,
            ),
        ))
        result = VerificationResult(
            "verification-recovery",
            "verification-plan-1",
            1,
            "task-1",
            "project-1",
            "artifact-artifact-candidate-recovery",
            "sha256:artifactrecovery",
            verifier,
            "verifier-run-recovery",
            Verdict.PASS,
            (VerificationCheckResult(
                "required",
                Verdict.PASS,
                (),
                ("evidence-recovery-pass",),
                "2026-08-13T00:00:00Z",
                "2026-08-13T00:00:01Z",
            ),),
            (Evidence(
                "evidence-recovery-pass",
                "artifact-artifact-candidate-recovery",
                "sha256:artifactrecovery",
                "verifier-1",
                True,
            ),),
            "2026-08-13T00:00:00Z",
            "2026-08-13T00:00:01Z",
            "corr-recovery-pass",
        )
        plane.record_verification_result(RecordVerificationResult(
            CommandEnvelope(
                "cmd-verification-recovery",
                "verification.record_result",
                "key-verification-recovery",
                task_version,
                verifier,
                "independent verifier verdict",
                "project-1",
            ),
            result,
        ))
        with psycopg.connect(DATABASE_URL) as connection:
            self.assertEqual("COMPLETION_CLAIMED", connection.execute(
                "SELECT state FROM tasks WHERE task_id='task-1'"
            ).fetchone()[0])
        receipt = plane.apply_verified_task_transition(ApplyVerifiedTaskTransition(
            CommandEnvelope(
                "cmd-apply-pass-recovery",
                "task.apply_verified_transition",
                "key-apply-pass-recovery",
                task_version,
                control,
                "apply independent PASS verdict",
                "project-1",
            ),
            "task-1",
            "verification-recovery",
        ))
        self.assertEqual("TASK_TRANSITIONED", receipt.result_code)
        return "verification-recovery"

    def test_feedback_diagnosis_planning_recovery_attempt_and_independent_pass(self):
        failed = self.submit_failed_execution_result()
        self.assertEqual("result-fail", failed["result_id"])
        with psycopg.connect(DATABASE_URL) as connection:
            self.assertEqual(("RUNNING", 0, 0), connection.execute(
                """SELECT t.state,
                          (SELECT count(*) FROM verification_results),
                          (SELECT count(*) FROM completion_claims)
                   FROM tasks t WHERE t.task_id='task-1'"""
            ).fetchone())

        feedback, _, _, attempt = self.plan_feedback_chain()
        task_version, account_version = self.seed_second_execution_freeze()
        prepared, result = self.execute_successful_recovery_attempt(
            task_version, account_version
        )
        with psycopg.connect(DATABASE_URL) as connection:
            self.assertEqual("COMPLETION_CLAIMED", connection.execute(
                "SELECT state FROM tasks WHERE task_id='task-1'"
            ).fetchone()[0])
            self.assertEqual(0, connection.execute(
                "SELECT count(*) FROM verification_results"
            ).fetchone()[0])
        verification_id = self.verify_recovered_artifact_passes()
        completion = self.recovery.complete_recovery_attempt(CompleteRecoveryAttempt(
            "cmd-complete-recovery",
            "key-complete-recovery",
            "project-1",
            attempt["attempt_id"],
            "SUCCEEDED",
            linked_execution_request_id=prepared["execution_request_id"],
            linked_result_id=result["result_id"],
            linked_verification_id=verification_id,
        ))
        self.assertEqual("RECOVERY_ATTEMPT_COMPLETED", completion["result_code"])
        with psycopg.connect(DATABASE_URL) as connection:
            row = connection.execute(
                """SELECT c.cycle_state,a.attempt_state,a.execution_request_id,
                          a.result_id,a.verification_id,t.state
                   FROM recovery_cycles c
                   JOIN recovery_attempts a ON a.cycle_id=c.cycle_id
                   JOIN tasks t ON t.task_id=c.task_id
                   WHERE c.cycle_id=%s""",
                (feedback["cycle_id"],),
            ).fetchone()
        self.assertEqual(("COMPLETED", "SUCCEEDED", prepared["execution_request_id"],
                          result["result_id"], verification_id, "PASSED"), row)

    def test_duplicate_feedback_and_bounded_retry_exhaustion_are_stable(self):
        self.submit_failed_execution_result()
        first = self.recovery.emit_execution_feedback(EmitExecutionFeedback(
            "cmd-feedback-idem",
            "key-feedback-idem",
            "project-1",
            "result-fail",
            "feedback-idem",
            "repair-task-idem",
            max_attempts=1,
        ))
        second = self.recovery.emit_execution_feedback(EmitExecutionFeedback(
            "cmd-feedback-idem",
            "key-feedback-idem",
            "project-1",
            "result-fail",
            "feedback-idem",
            "repair-task-idem",
            max_attempts=1,
        ))
        self.assertEqual(first, second)
        planned = self.recovery.plan_recovery_attempt(PlanRecoveryAttempt(
            "cmd-attempt-idem-1",
            "key-attempt-idem-1",
            "project-1",
            first["cycle_id"],
            "attempt-idem-1",
        ))
        exhausted = self.recovery.plan_recovery_attempt(PlanRecoveryAttempt(
            "cmd-attempt-idem-2",
            "key-attempt-idem-2",
            "project-1",
            first["cycle_id"],
            "attempt-idem-2",
        ))
        self.assertEqual("RECOVERY_ATTEMPT_PLANNED", planned["result_code"])
        self.assertEqual("RECOVERY_EXHAUSTED", exhausted["result_code"])
        self.assertEqual("human_gate", exhausted["action_type"])
        with psycopg.connect(DATABASE_URL) as connection:
            self.assertEqual(("EXHAUSTED", 1), connection.execute(
                "SELECT cycle_state,attempt_count FROM recovery_cycles WHERE cycle_id=%s",
                (first["cycle_id"],),
            ).fetchone())
            self.assertEqual(("BLOCKED", "RECOVERY_EXHAUSTED"), connection.execute(
                """SELECT attempt_state,reason_code FROM recovery_attempts
                   WHERE attempt_id='attempt-idem-2'"""
            ).fetchone())

    def test_recovery_fault_injection_rolls_back_precommit_writes(self):
        for point in RecoveryFaultPoint:
            with self.subTest(point=point.value):
                self.setUp()
                self.submit_failed_execution_result(point.value[:8])
                before = self._recovery_counts()
                faulted = PostgresRecoveryStore(DATABASE_URL)
                faulted.fail_recovery_once(point.value)
                with self.assertRaises(CommandRejected):
                    RecoveryController(faulted).emit_execution_feedback(EmitExecutionFeedback(
                        "cmd-feedback-fault-" + point.value,
                        "key-feedback-fault-" + point.value,
                        "project-1",
                        "result-" + point.value[:8],
                        "feedback-fault-" + point.value[:8],
                        "repair-task-fault",
                    ))
                self.assertEqual(before, self._recovery_counts())

    def _recovery_counts(self):
        with psycopg.connect(DATABASE_URL) as connection:
            return tuple(connection.execute(
                "SELECT count(*) FROM " + table
            ).fetchone()[0] for table in (
                "execution_feedback_records",
                "recovery_cycles",
                "recovery_attempts",
                "recovery_collaboration_requests",
                "feedback_records",
                "event_log",
                "outbox_messages",
                "command_receipts",
            ))


if __name__ == "__main__":
    unittest.main()
