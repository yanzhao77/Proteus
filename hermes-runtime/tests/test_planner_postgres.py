import threading
import unittest
from pathlib import Path

import os

try:
    import psycopg
    from psycopg.types.json import Jsonb
except ImportError:
    psycopg = None
    Jsonb = None

from hermes_runtime.application.diagnoses import DiagnosisEngine, RunDiagnosis
from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.application.handlers import ControlPlane
from hermes_runtime.application.commands import CreateProject
from hermes_runtime.application.planning import ActionPlanner, PlanCandidates
from hermes_runtime.domain.models import Actor, ActorType, CommandEnvelope
from hermes_runtime.infrastructure.postgres_diagnosis import PostgresDiagnosisStore
from hermes_runtime.infrastructure.postgres_planner import (
    PlannerFaultPoint,
    PostgresPlannerStore,
)
from hermes_runtime.infrastructure.postgres_project import PostgresProjectStore
from hermes_runtime.infrastructure.postgres_situation import PostgresSituationStore


DATABASE_URL = os.environ.get("HERMES_TEST_DATABASE_URL")


@unittest.skipUnless(DATABASE_URL and psycopg, "requires real PostgreSQL 14+")
class PlannerPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = PostgresPlannerStore(DATABASE_URL)
        for migration in sorted((Path(__file__).parents[1] / "migrations").glob("*.sql")):
            cls.store.apply_migration(migration)

    def setUp(self):
        self.store.reset_for_test()
        self.planner = ActionPlanner(self.store)

    def create_project(self, project_id="project-1"):
        receipt = ControlPlane(PostgresProjectStore(DATABASE_URL)).create_project(
            CreateProject(
                CommandEnvelope(
                    "cmd-create-" + project_id, "project.create",
                    "key-create-" + project_id, 0,
                    Actor(ActorType.CONTROL_PLANE, "project-manager"),
                    "planner fixture", project_id,
                ),
                "Planner test project", Actor(ActorType.USER, "user-1"),
            )
        )
        PostgresSituationStore(DATABASE_URL).analyze_logged_event(receipt.event_ids[0])

    def create_verification_failed(self, suffix="vf", finding_codes=("UNRECOGNIZED_FINDING",), evidence_refs=()):
        self.create_project("project-1")
        task_id = "task-" + suffix
        verifier_run_id = "verifier-run-" + suffix
        plan_id = "plan-" + suffix
        artifact_id = "artifact-" + suffix
        verification_id = "verification-" + suffix
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute(
                """INSERT INTO tasks(task_id,project_id,state,version)
                   VALUES (%s,'project-1','COMPLETION_CLAIMED',1)""",
                (task_id,),
            )
            connection.execute(
                """INSERT INTO verifier_identities(verifier_id,active)
                   VALUES ('verifier-1', true) ON CONFLICT DO NOTHING"""
            )
            for command_id, command_type in (
                ("cmd-run-" + suffix, "test.seed"),
                ("cmd-plan-" + suffix, "test.seed"),
                ("cmd-verification-" + suffix, "verification.record"),
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
                """INSERT INTO agent_runs(
                   run_id,project_id,task_id,run_kind,agent_identity,
                   context_identity,status,created_by,command_id)
                   VALUES (%s,'project-1',%s,'VERIFIER',
                           'verifier-1','verifier-context-1','ADMITTED',
                           'fixture',%s)""",
                (verifier_run_id, task_id, "cmd-run-" + suffix),
            )
            connection.execute(
                """INSERT INTO verification_plans(
                   verification_plan_id,task_id,project_id,version,status,
                   artifact_selectors,aggregation_rule,independence,created_by,
                   command_id)
                   VALUES (%s,%s,'project-1',1,'ACTIVE',
                           %s,'all_required_pass',
                           'worker_context_excluded','fixture',%s)""",
                (plan_id, task_id, Jsonb([artifact_id]), "cmd-plan-" + suffix),
            )
            connection.execute(
                """INSERT INTO artifacts(
                   artifact_id,task_id,content_hash,media_type,produced_by)
                   VALUES (%s,%s,'sha256:artifact',
                           'text/plain','worker-1')""",
                (artifact_id, task_id),
            )
            for evidence_id in evidence_refs:
                connection.execute(
                    """INSERT INTO evidence(
                       evidence_id,artifact_id,artifact_hash,producer_identity,
                       valid,observed_at_sequence)
                       VALUES (%s,%s,'sha256:artifact',
                               'verifier-1',true,0)""",
                    (evidence_id, artifact_id),
                )
            connection.execute(
                """INSERT INTO verification_results(
                   verification_id,task_id,artifact_id,artifact_hash,
                   verifier_identity,criteria,verdict,correlation_id,
                   occurred_at,command_id,authority_status,plan_id,
                   plan_version,project_id,verifier_run_id,started_at,completed_at)
                   VALUES (%s,%s,%s,'sha256:artifact',
                           'verifier-1',%s,'FAIL',%s,now(),%s,
                           'AUTHORITATIVE',%s,1,'project-1',
                           %s,now(),now())""",
                (verification_id, task_id, artifact_id, plan_id + ":1",
                 "corr-" + suffix, "cmd-verification-" + suffix, plan_id,
                 verifier_run_id),
            )
            connection.execute(
                """INSERT INTO verification_check_results(
                   verification_id,check_id,status,finding_codes,evidence_refs,
                   started_at,completed_at)
                   VALUES (%s,'check-1','FAIL',%s,%s,now(),now())""",
                (verification_id, Jsonb(list(finding_codes)), Jsonb(list(evidence_refs))),
            )
            for evidence_id in evidence_refs:
                connection.execute(
                    """INSERT INTO verification_evidence(verification_id,evidence_id)
                       VALUES (%s,%s)""",
                    (verification_id, evidence_id),
                )
            payload = {
                "verification_id": verification_id,
                "task_id": task_id,
                "artifact_id": artifact_id,
                "artifact_hash": "sha256:artifact",
                "artifact_refs": [artifact_id],
                "evidence_refs": list(evidence_refs),
                "verdict": "FAIL",
                "failure_type": finding_codes[0],
                "severity": "HIGH",
                "affected_components": ["component:test"],
            }
            connection.execute(
                """INSERT INTO event_log(
                   event_id,event_type,schema_version,producer_type,producer_id,
                   project_id,partition_key,command_id,correlation_id,task_id,payload)
                   VALUES (%s,'verification.recorded','1.0','verification_engine',
                           'verifier-1','project-1','project-1',%s,%s,%s,%s)""",
                ("evt-verification-" + suffix, "cmd-verification-" + suffix,
                 "corr-" + suffix, task_id, Jsonb(payload)),
            )
        situation_result = PostgresSituationStore(
            DATABASE_URL
        ).analyze_logged_event("evt-verification-" + suffix)
        situation = self._situation(situation_result["situation_id"])
        diagnosis = DiagnosisEngine(PostgresDiagnosisStore(DATABASE_URL)).run(
            RunDiagnosis(
                "cmd-diagnosis-" + suffix, "key-diagnosis-" + suffix,
                "project-1", situation["situation_id"], situation["version"],
                situation["analysis_context_id"], situation["context_hash"],
            )
        )
        return dict(situation, diagnosis_id=diagnosis["diagnosis_id"],
                    diagnosis_input_hash=diagnosis["input_hash"])

    def create_work_available(self, suffix="ready", task_state="READY"):
        self.create_project("project-1")
        task_id = "task-" + suffix
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute(
                """INSERT INTO tasks(task_id,project_id,state,version)
                   VALUES (%s,'project-1',%s,1)""",
                (task_id, task_state),
            )
            connection.execute(
                """INSERT INTO command_receipts(
                   command_id,project_id,command_type,idempotency_key,
                   request_hash,status,result,completed_at)
                   VALUES (%s,'project-1','task.recompute_readiness',%s,
                           'fixture','APPLIED','{}',now())""",
                ("cmd-ready-" + suffix, "cmd-ready-" + suffix),
            )
            payload = {
                "graph_version": 0,
                "ready_state_changes": [{
                    "task_id": task_id, "from_state": "NEW", "to_state": "READY"
                }],
            }
            connection.execute(
                """INSERT INTO event_log(
                   event_id,event_type,schema_version,producer_type,producer_id,
                   project_id,partition_key,command_id,correlation_id,task_id,payload)
                   VALUES (%s,'task.readiness_recomputed','1.0',
                           'control_plane','work-graph-authority',
                           'project-1','project-1',%s,%s,%s,%s)""",
                ("evt-ready-" + suffix, "cmd-ready-" + suffix,
                 "cmd-ready-" + suffix, task_id, Jsonb(payload)),
            )
        result = PostgresSituationStore(DATABASE_URL).analyze_logged_event(
            "evt-ready-" + suffix
        )
        if result.get("situation_id"):
            return self._situation(result["situation_id"])
        with psycopg.connect(DATABASE_URL) as connection:
            row = connection.execute(
                """SELECT situation_id FROM situations
                   WHERE project_id='project-1' AND task_id=%s
                     AND type='work_available' AND status='OPEN'""",
                (task_id,),
            ).fetchone()
        return self._situation(row[0])

    def create_budget_pressure(self, suffix="budget", status="HARD_STOP"):
        self.create_project("project-1")
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute(
                """INSERT INTO resource_accounts(
                   account_id,project_id,scope_type,scope_id,version,
                   threshold_status)
                   VALUES ('account-1','project-1','project','project-1',1,%s)""",
                (status,),
            )
            connection.execute(
                """INSERT INTO command_receipts(
                   command_id,project_id,command_type,idempotency_key,
                   request_hash,status,result,completed_at)
                   VALUES (%s,'project-1','resource.reserve',%s,
                           'fixture','APPLIED','{}',now())""",
                ("cmd-budget-" + suffix, "cmd-budget-" + suffix),
            )
            payload = {
                "account_id": "account-1",
                "entity_version": 1,
                "threshold_status": status,
            }
            connection.execute(
                """INSERT INTO event_log(
                   event_id,event_type,schema_version,producer_type,producer_id,
                   project_id,partition_key,command_id,correlation_id,payload)
                   VALUES (%s,'budget.reserved','1.0','accounting',
                           'resource-accounting','project-1','project-1',
                           %s,%s,%s)""",
                ("evt-budget-" + suffix, "cmd-budget-" + suffix,
                 "cmd-budget-" + suffix, Jsonb(payload)),
            )
        result = PostgresSituationStore(DATABASE_URL).analyze_logged_event(
            "evt-budget-" + suffix
        )
        return self._situation(result["situation_id"])

    def _situation(self, situation_id):
        with psycopg.connect(DATABASE_URL) as connection:
            row = connection.execute(
                """SELECT s.situation_id,s.version,s.analysis_context_id,
                          c.context_hash
                   FROM situations s JOIN analysis_contexts c
                     ON c.analysis_context_id=s.analysis_context_id
                   WHERE s.situation_id=%s""",
                (situation_id,),
            ).fetchone()
        return {
            "situation_id": row[0],
            "version": row[1],
            "analysis_context_id": row[2],
            "context_hash": row[3],
        }

    def command(self, fixture, suffix="1", **overrides):
        data = {
            "command_id": "cmd-planner-" + suffix,
            "idempotency_key": "key-planner-" + suffix,
            "project_id": "project-1",
            "situation_id": fixture["situation_id"],
            "expected_situation_version": fixture["version"],
            "analysis_context_id": fixture["analysis_context_id"],
            "analysis_context_hash": fixture["context_hash"],
            "expected_diagnosis_id": fixture.get("diagnosis_id"),
            "expected_diagnosis_input_hash": fixture.get("diagnosis_input_hash"),
        }
        data.update(overrides)
        return PlanCandidates(**data)

    def counts(self):
        with psycopg.connect(DATABASE_URL) as connection:
            return tuple(connection.execute(
                "SELECT count(*) FROM " + table
            ).fetchone()[0] for table in (
                "planning_runs", "candidate_actions",
                "candidate_action_targets", "candidate_action_capabilities",
                "candidate_action_preconditions",
                "candidate_action_expected_outputs",
                "candidate_action_resource_estimates",
                "current_planning_runs", "event_log", "outbox_messages",
                "command_receipts",
            ))

    def test_unknown_diagnosis_plans_diagnose_and_deeper_test_no_repair(self):
        fixture = self.create_verification_failed("unknown")
        result = self.planner.plan(self.command(fixture, "unknown"))
        with psycopg.connect(DATABASE_URL) as connection:
            types = [row[0] for row in connection.execute(
                """SELECT type FROM candidate_actions
                   WHERE planning_run_id=%s ORDER BY ordinal""",
                (result["planning_run_id"],),
            ).fetchall()]
            event_type = connection.execute(
                "SELECT event_type FROM event_log WHERE event_id=%s",
                (result["event_id"],),
            ).fetchone()[0]
        self.assertIn("run_deeper_test", types)
        self.assertIn("diagnose", types)
        self.assertNotIn("repair", types)
        self.assertEqual("action.candidates_planned", event_type)

    def test_confirmed_diagnosis_generates_mapped_repair_and_alternatives(self):
        fixture = self.create_verification_failed(
            "confirmed", ("TEST_ASSERTION_FAILURE",), ("evidence-confirmed",)
        )
        result = self.planner.plan(self.command(fixture, "confirmed"))
        with psycopg.connect(DATABASE_URL) as connection:
            types = {row[0] for row in connection.execute(
                "SELECT type FROM candidate_actions WHERE planning_run_id=%s",
                (result["planning_run_id"],),
            ).fetchall()}
        self.assertIn("repair", types)
        self.assertIn("retry", types)
        self.assertIn("run_deeper_test", types)

    def test_ready_task_plans_schedule_candidate_no_execution_request(self):
        fixture = self.create_work_available()
        result = self.planner.plan(self.command(fixture, "ready"))
        with psycopg.connect(DATABASE_URL) as connection:
            row = connection.execute(
                """SELECT type,parameters FROM candidate_actions
                   WHERE planning_run_id=%s""",
                (result["planning_run_id"],),
            ).fetchone()
        self.assertEqual("schedule_ready_task", row[0])
        self.assertFalse(row[1]["creates_execution_request"])
        self.assertEqual("ONLY_ONE_REGISTRY_CANDIDATE_VALID",
                         result["single_candidate_reason_code"])

    def test_budget_hard_stop_plans_request_resource_and_pause_without_budget_mutation(self):
        fixture = self.create_budget_pressure(status="HARD_STOP")
        with psycopg.connect(DATABASE_URL) as connection:
            before = connection.execute(
                "SELECT version,threshold_status FROM resource_accounts WHERE account_id='account-1'"
            ).fetchone()
        result = self.planner.plan(self.command(fixture, "budget"))
        with psycopg.connect(DATABASE_URL) as connection:
            after = connection.execute(
                "SELECT version,threshold_status FROM resource_accounts WHERE account_id='account-1'"
            ).fetchone()
            types = {row[0] for row in connection.execute(
                "SELECT type FROM candidate_actions WHERE planning_run_id=%s",
                (result["planning_run_id"],),
            ).fetchall()}
        self.assertEqual(before, after)
        self.assertEqual({"request_resource", "pause"}, types)

    def test_stale_context_version_and_diagnosis_rejections(self):
        fixture = self.create_verification_failed("stale")
        cases = (
            ("version", {"expected_situation_version": fixture["version"] + 1},
             "PLANNER_SITUATION_VERSION_CONFLICT"),
            ("hash", {"analysis_context_hash": "sha256:" + "0" * 64},
             "PLANNER_CONTEXT_HASH_MISMATCH"),
            ("diagnosis", {"expected_diagnosis_input_hash": "sha256:" + "1" * 64},
             "PLANNER_DIAGNOSIS_INPUT_MISMATCH"),
        )
        for label, overrides, code in cases:
            with self.subTest(label=label):
                with self.assertRaisesRegex(CommandRejected, code):
                    self.planner.plan(self.command(fixture, label, **overrides))

    def test_work_available_forbids_diagnosis_and_not_ready_is_stale(self):
        fixture = self.create_work_available("notready", task_state="RUNNING")
        with self.assertRaisesRegex(CommandRejected, "PLANNER_TARGET_STALE"):
            self.planner.plan(self.command(fixture, "notready"))
        self.store.reset_for_test()
        self.planner = ActionPlanner(self.store)
        fixture = self.create_work_available("diagforbidden")
        with self.assertRaisesRegex(CommandRejected, "PLANNER_DIAGNOSIS_NOT_ALLOWED"):
            self.planner.plan(self.command(
                fixture, "diagforbidden",
                expected_diagnosis_id="diag-forged",
                expected_diagnosis_input_hash="sha256:" + "2" * 64,
            ))

    def test_idempotent_retry_conflict_and_concurrent_equivalence(self):
        fixture = self.create_verification_failed("idem")
        first = self.planner.plan(self.command(fixture, "idem"))
        second = self.planner.plan(self.command(fixture, "idem"))
        self.assertEqual(first["planning_run_id"], second["planning_run_id"])
        with self.assertRaisesRegex(CommandRejected, "PLANNER_IDEMPOTENCY_CONFLICT"):
            self.planner.plan(self.command(
                fixture, "idem-conflict",
                command_id="cmd-planner-idem-other",
                idempotency_key="key-planner-idem",
                analysis_context_hash="sha256:" + "3" * 64,
            ))

        self.store.reset_for_test()
        self.planner = ActionPlanner(self.store)
        fixture = self.create_verification_failed("concurrent")
        barrier = threading.Barrier(2)
        results = []
        failures = []

        def plan(index):
            try:
                barrier.wait()
                results.append(ActionPlanner(PostgresPlannerStore(
                    DATABASE_URL
                )).plan(self.command(fixture, "concurrent-" + str(index))))
            except Exception as exc:
                failures.append(exc)

        threads = [threading.Thread(target=plan, args=(i,)) for i in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual([], failures)
        self.assertEqual(results[0]["planning_run_id"], results[1]["planning_run_id"])
        with psycopg.connect(DATABASE_URL) as connection:
            self.assertEqual(
                1, connection.execute("SELECT count(*) FROM planning_runs").fetchone()[0]
            )

    def test_fault_injection_rolls_back_everything_and_ack_retry_is_stable(self):
        for point in PlannerFaultPoint:
            with self.subTest(point=point.value):
                self.store.reset_for_test()
                self.planner = ActionPlanner(self.store)
                fixture = self.create_verification_failed("fault-" + point.value[:8])
                before = self.counts()
                self.store.fail_planner_once(point)
                with self.assertRaises(RuntimeError):
                    self.planner.plan(self.command(fixture, "fault-" + point.value[:8]))
                self.assertEqual(before, self.counts())
        self.store.reset_for_test()
        self.planner = ActionPlanner(self.store)
        fixture = self.create_verification_failed("ack")
        first = self.planner.plan(self.command(fixture, "ack"))
        second = self.planner.plan(self.command(fixture, "ack"))
        self.assertEqual(first["planning_run_id"], second["planning_run_id"])

    def test_planning_immutable_and_does_not_mutate_upstream(self):
        fixture = self.create_verification_failed("immutable")
        with psycopg.connect(DATABASE_URL) as connection:
            before = connection.execute(
                """SELECT s.version,s.status,t.state,t.version,d.input_hash
                   FROM situations s JOIN tasks t ON t.task_id=s.task_id
                   JOIN diagnoses d ON d.situation_id=s.situation_id
                   WHERE s.situation_id=%s""",
                (fixture["situation_id"],),
            ).fetchone()
        result = self.planner.plan(self.command(fixture, "immutable"))
        with psycopg.connect(DATABASE_URL) as connection:
            after = connection.execute(
                """SELECT s.version,s.status,t.state,t.version,d.input_hash
                   FROM situations s JOIN tasks t ON t.task_id=s.task_id
                   JOIN diagnoses d ON d.situation_id=s.situation_id
                   WHERE s.situation_id=%s""",
                (fixture["situation_id"],),
            ).fetchone()
            with self.assertRaises(psycopg.errors.RaiseException):
                connection.execute(
                    "UPDATE candidate_actions SET reason_code='mutated' WHERE planning_run_id=%s",
                    (result["planning_run_id"],),
                )
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
