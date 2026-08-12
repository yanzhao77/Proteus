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
    AdmitAgentRun,
    ApplyVerifiedTaskTransition,
    CreateVerificationPlan,
    InvalidateAgentRun,
    RecordVerificationResult,
    ReviseVerificationPlan,
    SubmitCompletionClaim,
)
from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.application.handlers import ControlPlane
from hermes_runtime.domain.models import (
    Actor,
    ActorType,
    AgentRun,
    AgentRunKind,
    AgentRunStatus,
    ArtifactCandidate,
    CommandEnvelope,
    CompletionClaim,
    Evidence,
    TaskState,
    VerificationCheckResult,
    VerificationPlan,
    VerificationPlanCheck,
    VerificationResult,
    Verdict,
)
from hermes_runtime.infrastructure.postgres import FaultPoint, PostgresRuntimeStore


DATABASE_URL = os.environ.get("HERMES_TEST_DATABASE_URL")


@unittest.skipUnless(DATABASE_URL and psycopg, "requires real PostgreSQL 14+")
class VerificationClosurePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = PostgresRuntimeStore(DATABASE_URL)
        for migration in sorted((Path(__file__).parents[1] / "migrations").glob("*.sql")):
            cls.store.apply_migration(migration)

    def setUp(self):
        self.store.reset_for_test()
        self.plane = ControlPlane(self.store)
        self.control = Actor(ActorType.CONTROL_PLANE, "control")
        self.worker = Actor(ActorType.WORKER, "worker")
        self.verifier = Actor(ActorType.VERIFIER, "verifier")
        self.store.seed_verifier("verifier")
        self.store.seed_task("task", TaskState.RUNNING, 1)

    def envelope(self, command_type, actor, version, key=None, project="project-1"):
        return CommandEnvelope(
            "cmd-" + str(uuid.uuid4()), command_type,
            key or command_type + "-key", version, actor,
            "P0 closure conformance", project,
        )

    def run_command(
        self, kind, run_id, version=1, identity=None, context=None,
        task="task", project="project-1", key=None,
    ):
        actor_identity = identity or ("worker" if kind is AgentRunKind.WORKER else "verifier")
        run = AgentRun(
            run_id, project, task, kind, actor_identity,
            context or kind.value.lower() + "-context", AgentRunStatus.ADMITTED,
            self.control, 1,
        )
        return AdmitAgentRun(
            self.envelope(
                "agent_run.admit", self.control, version,
                key or "agent-run-" + run_id, project,
            ),
            run,
        )

    def check(self, check_id="required", required=True, ordinal=0):
        return VerificationPlanCheck(
            check_id, "integration_test", "runner", required, 60,
            "exit_code == 0", "E2", ordinal,
        )

    def plan_command(
        self, version=1, task_version=1, checks=None, revise=False,
        aggregation="all_required_pass", independence="worker_context_excluded",
        key=None,
    ):
        plan = VerificationPlan(
            "plan", "task", "project-1", version, "ACTIVE", ("artifact",),
            aggregation, independence, self.control,
            tuple(checks or (self.check(), self.check("optional", False, 1))),
        )
        command = self.envelope(
            "verification_plan.revise" if revise else "verification_plan.create",
            self.control, task_version, key,
        )
        return ReviseVerificationPlan(command, plan) if revise else CreateVerificationPlan(command, plan)

    def claim_command(
        self, version=2, run_id="worker-run", worker=None,
        task="task", project="project-1", key=None,
    ):
        identity = worker or self.worker
        claim = CompletionClaim(
            "claim", task, run_id, identity,
            ArtifactCandidate("artifact", task, "sha256:aaa", "text/plain", identity.actor_id),
            "completed",
        )
        return SubmitCompletionClaim(
            self.envelope("task.submit_completion_claim", identity, version, key, project), claim
        )

    def result_command(
        self, verdict=Verdict.PASS, statuses=None, version=3,
        run_id="verifier-run", identity=None, context_evidence=True,
        plan_version=1, artifact_hash="sha256:aaa", task="task",
        project="project-1", key=None, duplicate=False, unknown=False,
    ):
        verifier = identity or self.verifier
        evidence = Evidence(
            "evidence", "artifact", artifact_hash, verifier.actor_id, context_evidence
        )
        values = statuses or {"required": verdict, "optional": Verdict.FAIL}
        checks = [
            VerificationCheckResult(
                check_id, status, (), ("evidence",),
                "2026-08-12T00:00:00Z", "2026-08-12T00:01:00Z",
            )
            for check_id, status in values.items()
        ]
        if duplicate:
            checks.append(checks[0])
        if unknown:
            checks.append(VerificationCheckResult(
                "unknown", Verdict.PASS, (), ("evidence",),
                "2026-08-12T00:00:00Z", "2026-08-12T00:01:00Z",
            ))
        result = VerificationResult(
            "verification", "plan", plan_version, task, project,
            "artifact", artifact_hash, verifier, run_id, verdict,
            tuple(checks), (evidence,), "2026-08-12T00:00:00Z",
            "2026-08-12T00:01:00Z", "correlation",
        )
        return RecordVerificationResult(
            self.envelope("verification.record_result", verifier, version, key, project), result
        )

    def prepare_claim(self):
        self.plane.admit_agent_run(self.run_command(AgentRunKind.WORKER, "worker-run"))
        self.plane.create_verification_plan(self.plan_command())
        return self.plane.submit_completion_claim(self.claim_command())

    def prepare_verification(self, **kwargs):
        self.prepare_claim()
        self.plane.admit_agent_run(
            self.run_command(AgentRunKind.VERIFIER, "verifier-run", version=3)
        )
        return self.plane.record_verification_result(self.result_command(**kwargs))

    def test_complete_authority_chain_is_idempotent_and_atomic(self):
        run = self.run_command(AgentRunKind.WORKER, "worker-run")
        self.assertEqual(self.plane.admit_agent_run(run), self.plane.admit_agent_run(run))
        plan = self.plan_command()
        self.assertEqual(self.plane.create_verification_plan(plan), self.plane.create_verification_plan(plan))
        claim = self.claim_command()
        self.assertEqual(self.plane.submit_completion_claim(claim), self.plane.submit_completion_claim(claim))
        verifier = self.run_command(AgentRunKind.VERIFIER, "verifier-run", version=3)
        self.plane.admit_agent_run(verifier)
        result = self.result_command()
        self.assertEqual(
            self.plane.record_verification_result(result),
            self.plane.record_verification_result(result),
        )
        receipt = self.plane.apply_verified_task_transition(
            ApplyVerifiedTaskTransition(
                self.envelope("task.apply_verified_transition", self.control, 3),
                "task", "verification",
            )
        )
        task = self.store.read_task("task")
        self.assertEqual((TaskState.PASSED, 4), (task.state, task.version))
        self.assertEqual("TASK_TRANSITIONED", receipt.result_code)
        self.assertEqual(6, self.store.count("event_log"))
        self.assertEqual(6, self.store.count("outbox_messages"))

    def test_plan_validation_revision_concurrency_and_payload_idempotency(self):
        for aggregation, independence, code in (
            ("any_pass", "worker_context_excluded", "UNSUPPORTED_AGGREGATION_RULE"),
            ("all_required_pass", "shared", "UNSUPPORTED_INDEPENDENCE_POLICY"),
        ):
            with self.subTest(code=code), self.assertRaisesRegex(CommandRejected, code):
                self.plane.create_verification_plan(
                    self.plan_command(aggregation=aggregation, independence=independence, key=code)
                )
        first = self.plan_command(key="plan-idempotency")
        self.plane.create_verification_plan(first)
        changed = self.plan_command(
            checks=(self.check("changed"),), key="plan-idempotency"
        )
        with self.assertRaisesRegex(CommandRejected, "IDEMPOTENCY_CONFLICT"):
            self.plane.create_verification_plan(changed)
        barrier = threading.Barrier(2)
        outcomes = []

        def revise(key):
            plane = ControlPlane(PostgresRuntimeStore(DATABASE_URL))
            barrier.wait()
            try:
                plane.revise_verification_plan(
                    self.plan_command(2, 2, revise=True, key=key)
                )
                outcomes.append("ok")
            except CommandRejected as exc:
                outcomes.append(exc.code)

        threads = [threading.Thread(target=revise, args=(key,)) for key in ("rev-a", "rev-b")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(1, outcomes.count("ok"))
        self.assertEqual(1, outcomes.count("VERSION_CONFLICT"))
        self.assertEqual(1, self.store.scalar("SELECT count(*) FROM verification_plans WHERE status='ACTIVE'"))

    def test_completion_claim_requires_matching_valid_worker_run_and_provenance(self):
        self.plane.create_verification_plan(self.plan_command())
        cases = (
            ("missing", {}, "WORKER_AGENT_RUN_NOT_FOUND"),
            ("verifier-kind", {"kind": AgentRunKind.VERIFIER}, "WORKER_AGENT_RUN_KIND_REQUIRED"),
            ("identity", {"identity": "other"}, "WORKER_AGENT_RUN_IDENTITY_MISMATCH"),
            ("task", {"task": "other"}, "WORKER_AGENT_RUN_TASK_MISMATCH"),
            ("project", {"project": "other"}, "WORKER_AGENT_RUN_PROJECT_MISMATCH"),
        )
        for label, options, code in cases:
            self.store.reset_for_test()
            self.store.seed_verifier("verifier")
            self.store.seed_task("task", TaskState.RUNNING, 1)
            self.plane.create_verification_plan(self.plan_command())
            if label != "missing":
                if label == "task":
                    with self.store._connect() as connection:
                        connection.execute(
                            "INSERT INTO tasks(task_id,project_id,state,version) VALUES ('other','project-1','RUNNING',1)"
                        )
                elif label == "project":
                    with self.store._connect() as connection:
                        connection.execute(
                            "INSERT INTO tasks(task_id,project_id,state,version) VALUES ('other','other','RUNNING',1)"
                        )
                    options["task"] = "other"
                self.plane.admit_agent_run(
                    self.run_command(
                        options.pop("kind", AgentRunKind.WORKER), "bad-run",
                        version=(1 if label in {"task", "project"} else 2),
                        **options
                    )
                )
            with self.subTest(label=label), self.assertRaisesRegex(CommandRejected, code):
                self.plane.submit_completion_claim(self.claim_command(run_id="bad-run"))
        self.store.reset_for_test()
        self.store.seed_verifier("verifier")
        self.store.seed_task("task", TaskState.RUNNING, 1)
        self.plane.admit_agent_run(self.run_command(AgentRunKind.WORKER, "worker-run"))
        self.plane.create_verification_plan(self.plan_command())
        self.plane.invalidate_agent_run(InvalidateAgentRun(
            self.envelope("agent_run.invalidate", self.control, 1), "worker-run"
        ))
        with self.assertRaisesRegex(CommandRejected, "WORKER_AGENT_RUN_NOT_ACTIVE"):
            self.plane.submit_completion_claim(self.claim_command())

    def test_verifier_run_identity_context_and_scope_are_enforced(self):
        self.prepare_claim()
        cases = (
            ("missing", {}, "VERIFIER_AGENT_RUN_NOT_FOUND"),
            ("worker-kind", {"kind": AgentRunKind.WORKER}, "VERIFIER_AGENT_RUN_KIND_REQUIRED"),
            ("identity", {"identity": "other"}, "VERIFIER_AGENT_RUN_IDENTITY_MISMATCH"),
            ("shared-context", {"context": "worker-context"}, "WORKER_VERIFIER_CONTEXT_NOT_INDEPENDENT"),
        )
        for index, (label, options, code) in enumerate(cases):
            run_id = "verifier-" + label
            if label != "missing":
                self.plane.admit_agent_run(self.run_command(
                    options.pop("kind", AgentRunKind.VERIFIER), run_id,
                    version=3, key="admit-" + label, **options
                ))
            with self.subTest(label=label), self.assertRaisesRegex(CommandRejected, code):
                self.plane.record_verification_result(
                    self.result_command(run_id=run_id, key="result-" + str(index))
                )
        with self.store._connect() as connection:
            connection.execute(
                "INSERT INTO tasks(task_id,project_id,state,version) VALUES ('other-task','project-1','RUNNING',1),('other-project-task','other','RUNNING',1)"
            )
        self.plane.admit_agent_run(self.run_command(
            AgentRunKind.VERIFIER, "verifier-other-task", version=1,
            task="other-task", key="verifier-other-task",
        ))
        with self.assertRaisesRegex(CommandRejected, "VERIFIER_AGENT_RUN_TASK_MISMATCH"):
            self.plane.record_verification_result(
                self.result_command(run_id="verifier-other-task", key="other-task-result")
            )
        self.plane.admit_agent_run(self.run_command(
            AgentRunKind.VERIFIER, "verifier-other-project", version=1,
            task="other-project-task", project="other", key="verifier-other-project",
        ))
        with self.assertRaisesRegex(CommandRejected, "VERIFIER_AGENT_RUN_PROJECT_MISMATCH"):
            self.plane.record_verification_result(
                self.result_command(run_id="verifier-other-project", key="other-project-result")
            )
        self.plane.admit_agent_run(self.run_command(
            AgentRunKind.VERIFIER, "verifier-invalidated", version=3,
            key="verifier-invalidated",
        ))
        self.plane.invalidate_agent_run(InvalidateAgentRun(
            self.envelope("agent_run.invalidate", self.control, 1, "invalidate-verifier"),
            "verifier-invalidated",
        ))
        with self.assertRaisesRegex(CommandRejected, "VERIFIER_AGENT_RUN_NOT_ACTIVE"):
            self.plane.record_verification_result(
                self.result_command(run_id="verifier-invalidated", key="invalidated-result")
            )

    def test_check_aggregation_missing_duplicate_unknown_and_evidence_fail_closed(self):
        self.prepare_claim()
        self.plane.admit_agent_run(self.run_command(AgentRunKind.VERIFIER, "verifier-run", version=3))
        cases = (
            ({"statuses": {"optional": Verdict.PASS}}, "REQUIRED_VERIFICATION_CHECK_RESULT_MISSING"),
            ({"duplicate": True}, "DUPLICATE_VERIFICATION_CHECK_RESULT"),
            ({"unknown": True}, "UNKNOWN_VERIFICATION_CHECK"),
            ({"context_evidence": False}, "CHECK_EVIDENCE_ARTIFACT_MISMATCH"),
            ({"verdict": Verdict.PASS, "statuses": {"required": Verdict.FAIL}}, "VERIFICATION_AGGREGATE_MISMATCH"),
        )
        for index, (kwargs, code) in enumerate(cases):
            with self.subTest(code=code), self.assertRaisesRegex(CommandRejected, code):
                self.plane.record_verification_result(
                    self.result_command(key="check-case-" + str(index), **kwargs)
                )
        for status in (Verdict.INCONCLUSIVE, Verdict.ERROR, Verdict.CANCELLED):
            command = self.result_command(
                verdict=status, statuses={"required": status, "optional": Verdict.PASS},
                key="non-pass-" + status.value,
            )
            command = RecordVerificationResult(
                command.envelope,
                VerificationResult(
                    "verification-" + status.value, command.result.plan_id,
                    command.result.plan_version, command.result.task_id,
                    command.result.project_id, command.result.artifact_id,
                    command.result.artifact_hash, command.result.verifier_identity,
                    command.result.verifier_run_id, command.result.verdict,
                    command.result.check_results, command.result.evidence,
                    command.result.started_at, command.result.completed_at,
                    command.result.correlation_id,
                ),
            )
            self.plane.record_verification_result(command)
            with self.assertRaisesRegex(CommandRejected, "FORMAL_PASS_OR_FAIL_REQUIRED"):
                self.plane.apply_verified_task_transition(ApplyVerifiedTaskTransition(
                    self.envelope("task.apply_verified_transition", self.control, 3,
                                  "transition-" + status.value),
                    "task", command.result.verification_id,
                ))

    def test_plan_revision_artifact_change_and_legacy_result_cannot_authorize_pass(self):
        self.prepare_verification()
        self.plane.revise_verification_plan(self.plan_command(2, 3, revise=True))
        with self.assertRaisesRegex(CommandRejected, "CURRENT_VERIFICATION_PLAN_REQUIRED"):
            self.plane.apply_verified_task_transition(ApplyVerifiedTaskTransition(
                self.envelope("task.apply_verified_transition", self.control, 4),
                "task", "verification",
            ))
        with self.store._connect() as connection:
            connection.execute(
                """INSERT INTO artifacts(
                   artifact_id,task_id,content_hash,media_type,produced_by,produced_by_run_id
                   ) VALUES ('artifact-new','task','sha256:changed','text/plain','worker','worker-run')"""
            )
            connection.execute(
                """UPDATE tasks SET current_artifact_id='artifact-new',
                   current_artifact_hash='sha256:changed' WHERE task_id='task'"""
            )
            with self.assertRaisesRegex(psycopg.errors.RaiseException, "TASK_PASS_VERIFICATION"):
                connection.execute("UPDATE tasks SET state='PASSED',current_verification_id='verification' WHERE task_id='task'")
                connection.execute("SET CONSTRAINTS ALL IMMEDIATE")

    def test_no_plan_and_legacy_result_fail_closed(self):
        with self.assertRaisesRegex(
            psycopg.errors.RaiseException,
            "TASK_PASS_VERIFICATION_AUTHORITY_INVARIANT_VIOLATION",
        ):
            with self.store._connect() as connection:
                connection.execute("UPDATE tasks SET state='PASSED' WHERE task_id='task'")
                connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        with self.store._connect() as connection:
            connection.execute(
                """INSERT INTO command_receipts(
                   command_id,project_id,command_type,idempotency_key,request_hash,
                   status,result,completed_at
                   ) VALUES ('legacy-command','project-1','test.legacy','legacy','x',
                             'APPLIED','{}',now())"""
            )
            connection.execute(
                """INSERT INTO artifacts(
                   artifact_id,task_id,content_hash,media_type,produced_by
                   ) VALUES ('legacy-artifact','task','sha256:legacy','text/plain','legacy')"""
            )
            connection.execute(
                """INSERT INTO verifier_identities(verifier_id,active)
                   VALUES ('legacy-verifier',true)"""
            )
            connection.execute(
                """INSERT INTO verification_results(
                   verification_id,task_id,artifact_id,artifact_hash,
                   verifier_identity,criteria,verdict,correlation_id,occurred_at,command_id
                   ) VALUES ('legacy-result','task','legacy-artifact','sha256:legacy',
                             'legacy-verifier','free text','PASS','legacy',now(),
                             'legacy-command')"""
            )
        with self.assertRaisesRegex(
            CommandRejected, "LEGACY_VERIFICATION_NOT_AUTHORITATIVE"
        ):
            self.plane.apply_verified_task_transition(ApplyVerifiedTaskTransition(
                self.envelope("task.apply_verified_transition", self.control, 1,
                              "legacy-transition"),
                "task", "legacy-result",
            ))

    def test_faults_roll_back_run_plan_checks_result_and_outbox(self):
        points = (
            (FaultPoint.AFTER_AGENT_RUN_BEFORE_EVENT, lambda: self.plane.admit_agent_run(self.run_command(AgentRunKind.WORKER, "worker-run")), "agent_runs"),
            (FaultPoint.AFTER_PLAN_BEFORE_CHECK, lambda: self.plane.create_verification_plan(self.plan_command()), "verification_plans"),
            (FaultPoint.AFTER_PLAN_CHECK_BEFORE_EVENT, lambda: self.plane.create_verification_plan(self.plan_command()), "verification_plan_checks"),
        )
        for point, action, table in points:
            self.store.reset_for_test()
            self.store.seed_verifier("verifier")
            self.store.seed_task("task", TaskState.RUNNING, 1)
            self.store.fail_once(point)
            with self.subTest(point=point), self.assertRaisesRegex(RuntimeError, "injected"):
                action()
            self.assertEqual(0, self.store.count(table))
            self.assertEqual(0, self.store.count("event_log"))
            self.assertEqual(0, self.store.count("outbox_messages"))
        for point in (
            FaultPoint.AFTER_VERIFICATION_RESULT_BEFORE_CHECK,
            FaultPoint.AFTER_VERIFICATION_CHECK_BEFORE_EVENT,
        ):
            self.store.reset_for_test()
            self.store.seed_verifier("verifier")
            self.store.seed_task("task", TaskState.RUNNING, 1)
            self.prepare_claim()
            self.plane.admit_agent_run(self.run_command(AgentRunKind.VERIFIER, "verifier-run", version=3))
            before = self.store.count("outbox_messages")
            self.store.fail_once(point)
            with self.subTest(point=point), self.assertRaisesRegex(RuntimeError, "injected"):
                self.plane.record_verification_result(self.result_command())
            self.assertEqual(0, self.store.count("verification_results"))
            self.assertEqual(0, self.store.count("verification_check_results"))
            self.assertEqual(before, self.store.count("outbox_messages"))


if __name__ == "__main__":
    unittest.main()
