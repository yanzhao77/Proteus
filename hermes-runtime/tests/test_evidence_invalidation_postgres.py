import os
import unittest
import uuid
from pathlib import Path

try:
    import psycopg
    from psycopg.types.json import Jsonb
except ImportError:
    psycopg = None
    Jsonb = None

from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.application.evidence_invalidation import (
    EvidenceInvalidationAuthority,
    InvalidateEvidence,
)
from hermes_runtime.application.human_gates import (
    ApplyHumanGateDecision,
    EnterProjectWaitingForGate,
    HumanGateAuthority,
    RequestHumanGate,
    SubmitHumanGateDecision,
)
from hermes_runtime.domain.models import Actor, ActorType
from hermes_runtime.infrastructure.postgres_evidence_invalidation import (
    PostgresEvidenceInvalidationStore,
)


DATABASE_URL = os.environ.get("HERMES_TEST_DATABASE_URL")


@unittest.skipUnless(DATABASE_URL and psycopg, "requires real PostgreSQL 14+")
class EvidenceInvalidationPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = PostgresEvidenceInvalidationStore(DATABASE_URL)
        cls.store.check_server_version(140000)
        for migration in sorted((Path(__file__).parents[1] / "migrations").glob("*.sql")):
            cls.store.apply_migration(migration)

    def setUp(self):
        self.store.reset_for_test()
        self.authority = EvidenceInvalidationAuthority(self.store)
        self.gates = HumanGateAuthority(self.store)
        self.operator = Actor(ActorType.SYSTEM_OPERATOR, "operator-1")
        self.user = Actor(ActorType.USER, "human-1")

    def _admin_connection(self):
        return psycopg.connect(DATABASE_URL)

    def _seed_project_evidence_verification(self, passed=False):
        with self._admin_connection() as connection:
            connection.execute(
                """
                INSERT INTO public.command_receipts(
                    command_id,project_id,command_type,idempotency_key,
                    request_hash,status,result,completed_at
                ) VALUES
                ('cmd-seed-project','project-1','project.create','idem-seed-project',
                 'sha256:seed','APPLIED','{}',clock_timestamp()),
                ('cmd-seed-run','project-1','agent_run.admit','idem-seed-run',
                 'sha256:seed-run','APPLIED','{}',clock_timestamp()),
                ('cmd-seed-plan','project-1','verification_plan.create','idem-seed-plan',
                 'sha256:seed-plan','APPLIED','{}',clock_timestamp()),
                ('cmd-seed-verification','project-1','verification.record','idem-seed-verification',
                 'sha256:seed-verification','APPLIED','{}',clock_timestamp())
                """
            )
            connection.execute(
                """
                INSERT INTO public.projects(project_id,title,state,version,last_command_id)
                VALUES ('project-1','Evidence Project','IMPLEMENTING',7,'cmd-seed-project')
                """
            )
            connection.execute(
                "INSERT INTO public.project_graph_versions(project_id,graph_version) VALUES ('project-1',0)"
            )
            row = connection.execute(
                """
                INSERT INTO public.event_log(
                    event_id,event_type,schema_version,producer_type,producer_id,
                    project_id,partition_key,command_id,correlation_id,payload
                ) VALUES ('evt-seed-project','project.state_transition.applied','1.0',
                          'control_plane','seed','project-1','project-1',
                          'cmd-seed-project','cmd-seed-project',
                          %s::jsonb)
                RETURNING sequence
                """,
                (Jsonb({"project_version": 7, "new_state": "IMPLEMENTING"}),),
            ).fetchone()
            connection.execute(
                """
                INSERT INTO public.outbox_messages(
                    message_id,event_id,topic,partition_key,sequence,payload
                ) VALUES ('msg-seed-project','evt-seed-project','hermes.runtime.events',
                          'project-1',%s,%s::jsonb)
                """,
                (row[0], Jsonb({"project_version": 7, "new_state": "IMPLEMENTING"})),
            )
            connection.execute(
                """
                INSERT INTO public.tasks(task_id,project_id,state,version)
                VALUES ('task-1','project-1','VERIFYING',1)
                """
            )
            connection.execute(
                "INSERT INTO public.verifier_identities(verifier_id,active) VALUES ('verifier-1',true)"
            )
            connection.execute(
                """
                INSERT INTO public.agent_runs(
                    run_id,project_id,task_id,run_kind,agent_identity,context_identity,
                    status,created_by,command_id
                ) VALUES ('verifier-run-1','project-1','task-1','VERIFIER',
                          'verifier-1','verifier-context-1','ADMITTED',
                          'test-fixture','cmd-seed-run')
                """
            )
            connection.execute(
                """
                INSERT INTO public.verification_plans(
                    verification_plan_id,task_id,project_id,version,status,
                    artifact_selectors,aggregation_rule,independence,created_by,command_id
                ) VALUES ('plan-1','task-1','project-1',1,'ACTIVE','["artifact"]'::jsonb,
                          'all_required_pass','worker_context_excluded',
                          'test-fixture','cmd-seed-plan')
                """
            )
            connection.execute(
                """
                INSERT INTO public.verification_plan_checks(
                    verification_plan_id,plan_version,check_id,type,runner_profile,
                    required,timeout_seconds,pass_condition,evidence_level,ordinal
                ) VALUES ('plan-1',1,'check-1','integration_test','test-runner',
                          true,60,'exit_code == 0','E2',0)
                """
            )
            connection.execute(
                """
                INSERT INTO public.artifacts(
                    artifact_id,task_id,content_hash,media_type,produced_by
                ) VALUES ('artifact-1','task-1','sha256:artifact','text/plain','worker-1')
                """
            )
            connection.execute(
                """
                INSERT INTO public.evidence(
                    evidence_id,artifact_id,artifact_hash,producer_identity,valid
                ) VALUES ('evidence-1','artifact-1','sha256:artifact','verifier-1',true)
                """
            )
            connection.execute(
                """
                INSERT INTO public.verification_results(
                    verification_id,task_id,artifact_id,artifact_hash,
                    verifier_identity,criteria,verdict,correlation_id,occurred_at,
                    command_id,project_id,plan_id,plan_version,verifier_run_id,
                    authority_status,started_at,completed_at
                ) VALUES ('verification-1','task-1','artifact-1','sha256:artifact',
                          'verifier-1','criteria','PASS','corr-1',clock_timestamp(),
                          'cmd-seed-verification','project-1','plan-1',1,
                          'verifier-run-1','AUTHORITATIVE',clock_timestamp(),clock_timestamp())
                """
            )
            connection.execute(
                """
                INSERT INTO public.verification_evidence(verification_id,evidence_id)
                VALUES ('verification-1','evidence-1')
                """
            )
            connection.execute(
                """
                INSERT INTO public.verification_check_results(
                    verification_id,check_id,status,finding_codes,evidence_refs,
                    started_at,completed_at
                ) VALUES ('verification-1','check-1','PASS','[]'::jsonb,
                          '["evidence-1"]'::jsonb,clock_timestamp(),clock_timestamp())
                """
            )
            if passed:
                connection.execute(
                    """
                    UPDATE public.tasks
                    SET state='PASSED',
                        current_artifact_id='artifact-1',
                        current_artifact_hash='sha256:artifact',
                        current_verification_id='verification-1',
                        current_verification_plan_id='plan-1',
                        current_verification_plan_version=1
                    WHERE task_id='task-1'
                    """
                )

    def _invalidate(self, suffix="1", expected=0, scope="task"):
        return self.authority.invalidate(
            InvalidateEvidence(
                command_id="cmd-einv-" + suffix,
                idempotency_key="idem-einv-" + suffix,
                project_id="project-1",
                evidence_id="evidence-1",
                expected_version=expected,
                actor=self.operator,
                producer="verification_engine",
                reason_code="ARTIFACT_HASH_STALE",
                reason="artifact hash changed after verification",
                scope=scope,
                affected_refs={"verification_result_ids": ["verification-1"]},
                dependency_refs=["verification-1"],
                authorization_ref="authz:evidence",
            )
        )

    def test_invalidation_is_append_only_and_does_not_rewrite_evidence_or_verification(self):
        self._seed_project_evidence_verification(passed=True)
        result = self._invalidate()
        self.assertEqual("EVIDENCE_INVALIDATED", result["result_code"])
        with self._admin_connection() as connection:
            self.assertEqual(
                (True,),
                connection.execute("SELECT valid FROM public.evidence WHERE evidence_id='evidence-1'").fetchone(),
            )
            self.assertEqual(
                ("PASS",),
                connection.execute(
                    "SELECT verdict FROM public.verification_results WHERE verification_id='verification-1'"
                ).fetchone(),
            )
            self.assertEqual(
                ("PASSED",),
                connection.execute("SELECT state FROM public.tasks WHERE task_id='task-1'").fetchone(),
            )
            self.assertEqual(
                1,
                connection.execute(
                    "SELECT count(*) FROM public.evidence_dependency_stale_records WHERE required_action='REVERIFICATION_REQUIRED'"
                ).fetchone()[0],
            )
            self.assertEqual(
                1,
                connection.execute(
                    "SELECT count(*) FROM public.reverification_requirements WHERE requirement_state='OPEN'"
                ).fetchone()[0],
            )
            with self.assertRaises(psycopg.errors.RaiseException):
                connection.execute(
                    "UPDATE public.evidence_invalidation_records SET reason='patched'"
                )

    def test_idempotent_retry_payload_conflict_and_expected_version_conflict(self):
        self._seed_project_evidence_verification()
        first = self._invalidate()
        retry = self._invalidate()
        self.assertEqual(first["invalidation_id"], retry["invalidation_id"])
        with self.assertRaisesRegex(CommandRejected, "IDEMPOTENCY_PAYLOAD_CONFLICT"):
            self.authority.invalidate(
                InvalidateEvidence(
                    "cmd-einv-conflict",
                    "idem-einv-1",
                    "project-1",
                    "evidence-1",
                    0,
                    self.operator,
                    "verification_engine",
                    "DIFFERENT_REASON",
                    "different payload",
                    "task",
                    {},
                    [],
                    "authz:evidence",
                )
            )
        with self.assertRaisesRegex(CommandRejected, "EXPECTED_VERSION_CONFLICT"):
            self.authority.invalidate(
                InvalidateEvidence(
                    "cmd-einv-version",
                    "idem-einv-version",
                    "project-1",
                    "evidence-1",
                    0,
                    self.operator,
                    "verification_engine",
                    "ARTIFACT_HASH_STALE",
                    "stale expected version",
                    "task",
                    {},
                    [],
                    "authz:evidence",
                )
            )

    def test_unknown_scope_creates_reverification_required_fail_closed(self):
        self._seed_project_evidence_verification()
        result = self._invalidate(scope="UNKNOWN")
        self.assertEqual("REVERIFICATION_REQUIRED", result["required_action"])
        with self._admin_connection() as connection:
            self.assertEqual(
                1,
                connection.execute(
                    "SELECT count(*) FROM public.evidence_dependency_stale_records WHERE dependency_type='unknown_scope'"
                ).fetchone()[0],
            )

    def _seed_gate_with_evidence_ref(self):
        self._seed_project_evidence_verification()
        with self._admin_connection() as connection:
            connection.execute(
                """
                INSERT INTO public.project_policy_decision_facts(
                    policy_decision_id,project_id,project_version,from_state,to_state,
                    result,authority,policy_bundle_version,input_hash
                ) VALUES ('policy-require','project-1',7,'IMPLEMENTING','WAITING_FOR_HUMAN',
                          'REQUIRE_HUMAN','policy_engine','policy-test','sha256:policy')
                """
            )
            connection.execute(
                """
                INSERT INTO public.project_evidence_facts(
                    evidence_fact_id,project_id,project_version,from_state,to_state,
                    result,authority,subject_ref
                ) VALUES ('evidence-fact-resume','project-1',8,'WAITING_FOR_HUMAN',
                          'IMPLEMENTING','VALID','verification_engine','evidence-1')
                """
            )
            connection.execute(
                """
                INSERT INTO public.project_policy_decision_facts(
                    policy_decision_id,project_id,project_version,from_state,to_state,
                    result,authority,policy_bundle_version,input_hash
                ) VALUES ('policy-resume','project-1',8,'WAITING_FOR_HUMAN','IMPLEMENTING',
                          'ALLOW','policy_engine','policy-test','sha256:policy-resume')
                """
            )
            connection.execute(
                """
                INSERT INTO public.project_budget_facts(
                    budget_fact_id,project_id,project_version,from_state,to_state,
                    status,authority,budget_scope_id,version
                ) VALUES ('budget-resume','project-1',8,'WAITING_FOR_HUMAN','IMPLEMENTING',
                          'OK','budget_engine','budget-project-1',1)
                """
            )
        context_hash = "sha256:" + uuid.uuid4().hex
        self._last_resume_context_hash = context_hash
        self.gates.request_gate(
            RequestHumanGate(
                command_id="cmd-gate-request",
                idempotency_key="idem-gate-request",
                project_id="project-1",
                gate_request_id="gate-1",
                action_scope="project:resume",
                requester=Actor(ActorType.MAIN_HERMES, "main"),
                expected_project_version=7,
                resume_context={
                    "context_id": "ctx-gate-1",
                    "project_before_state": "IMPLEMENTING",
                    "project_before_version": 7,
                    "original_command_type": "execution.admit",
                    "requester": {"type": "main_hermes", "id": "main"},
                    "policy_decision_id": "policy-require",
                    "evidence_refs": ["evidence:evidence-1"],
                    "supporting_refs": [],
                    "expected_task_versions": {},
                    "context_hash": context_hash,
                },
                reason="needs human approval",
                policy_decision_id="policy-require",
                expires_at="2099-01-01T00:00:00+00:00",
            )
        )
        self.gates.enter_project_waiting(
            EnterProjectWaitingForGate(
                "cmd-gate-wait",
                "idem-gate-wait",
                "project-1",
                "wait-1",
                "gate-1",
                "ctx-gate-1",
                7,
                "blocked by human",
            )
        )
        self.store.seed_human_authorization(
            "assert-gate-1",
            "human-1",
            "project-1",
            "gate-1",
            "project:resume",
        )

    def test_invalid_evidence_blocks_new_gate_decision_and_existing_resume_application(self):
        self._seed_gate_with_evidence_ref()
        self.gates.submit_decision(
            SubmitHumanGateDecision(
                "cmd-gate-decision-current",
                "idem-gate-decision-current",
                "project-1",
                "decision-current",
                "gate-1",
                "APPROVE",
                self.user,
                "authz:human",
                "assert-gate-1",
                "sha256:test-assertion",
                "approve before invalidation",
                evidence_refs=("evidence:evidence-1",),
                expires_at="2099-01-01T00:00:00+00:00",
                actor_id="human-1",
            )
        )
        self._invalidate()
        with self.assertRaisesRegex(CommandRejected, "GATE_EVIDENCE_INVALID"):
            self.gates.apply_decision(
                ApplyHumanGateDecision(
                    "cmd-gate-apply-invalid",
                    "idem-gate-apply-invalid",
                    "project-1",
                    "gate-1",
                    "decision-current",
                    "wait-1",
                    8,
                    1,
                    2,
                    1,
                    self._last_resume_context_hash,
                    "IMPLEMENTING",
                )
            )
        with self._admin_connection() as connection:
            with self.assertRaises(psycopg.errors.RaiseException) as raised:
                connection.execute(
                    """
                    INSERT INTO public.human_gate_decisions(
                        gate_decision_id,gate_request_id,project_id,gate_request_version,
                        decision,approver_type,approver_id,authorization_ref,assertion_id,
                        assertion_hash,decision_reason,evidence_refs,constraints,expires_at,
                        decision_state,payload_hash,command_id
                    ) VALUES ('decision-invalid-trigger','gate-1','project-1',1,
                              'APPROVE','user','human-1','authz:human','assert-gate-1',
                              'sha256:test-assertion','invalid evidence direct insert',
                              '["evidence:evidence-1"]'::jsonb,'{}'::jsonb,
                              '2099-01-01T00:00:00+00:00','CURRENT',
                              'sha256:invalid-decision','cmd-gate-decision-current')
                    """
                )
            self.assertIn("GATE_EVIDENCE_INVALID", str(raised.exception))

    def test_fault_injection_rolls_back_event_outbox_receipt_and_state(self):
        self._seed_project_evidence_verification()
        self.store.fail_evidence_invalidation_once("after_event_before_state")
        with self.assertRaisesRegex(CommandRejected, "INJECTED_P3_EVIDENCE_CRASH_AFTER_EVENT"):
            self._invalidate(suffix="fault")
        with self._admin_connection() as connection:
            self.assertEqual(
                0,
                connection.execute(
                    "SELECT count(*) FROM public.evidence_invalidation_records WHERE evidence_id='evidence-1'"
                ).fetchone()[0],
            )
            self.assertEqual(
                0,
                connection.execute(
                    "SELECT count(*) FROM public.command_receipts WHERE command_id='cmd-einv-fault'"
                ).fetchone()[0],
            )


if __name__ == "__main__":
    unittest.main()
