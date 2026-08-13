import os
import threading
import unittest
from pathlib import Path

try:
    import psycopg
except ImportError:
    psycopg = None

from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.application.executions import ExecutionPreparation
from hermes_runtime.application.scheduling import (
    AcquireExecutionLease,
    ExecutionScheduler,
    RegisterScheduler,
    RelinquishExecutionLease,
    RenewExecutionLease,
)
from hermes_runtime.domain.execution import LockIntent
from hermes_runtime.infrastructure.postgres_execution import PostgresExecutionStore
from hermes_runtime.infrastructure.postgres_scheduler import (
    PostgresSchedulerStore,
    SchedulerFaultPoint,
)
import test_execution_postgres as execution_fixtures


DATABASE_URL = os.environ.get("HERMES_TEST_DATABASE_URL")


class _ExecutionFixture:
    seed_fixture = execution_fixtures.ExecutionPostgresTests.seed_fixture
    command = execution_fixtures.ExecutionPostgresTests.command


@unittest.skipUnless(DATABASE_URL and psycopg, "requires real PostgreSQL 14+")
class SchedulerPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = PostgresSchedulerStore(DATABASE_URL)
        for migration in sorted((Path(__file__).parents[1] / "migrations").glob("*.sql")):
            cls.store.apply_migration(migration)

    def setUp(self):
        self.store.reset_for_test()
        self.execution = ExecutionPreparation(PostgresExecutionStore(DATABASE_URL))
        self.scheduler = ExecutionScheduler(PostgresSchedulerStore(DATABASE_URL))
        self.fixture = _ExecutionFixture()
        self.fixture.store = self.store
        self.fixture.seed_fixture()

    def prepare(self, suffix="1", **overrides):
        return self.execution.prepare(self.fixture.command(suffix, **overrides))

    def register(self, scheduler_id="sched-1", session_id="session-1"):
        return self.scheduler.register(RegisterScheduler(
            command_id="cmd-register-" + scheduler_id + "-" + session_id,
            idempotency_key="key-register-" + scheduler_id + "-" + session_id,
            project_id="project-1",
            scheduler_id=scheduler_id,
            scheduler_session_id=session_id,
            actor_id=scheduler_id,
        ))

    def seed_second_fixture(self):
        with psycopg.connect(DATABASE_URL) as connection:
            for command_id, command_type in (
                ("cmd-trigger-second", "test.trigger"),
                ("cmd-policy-second", "policy.evaluate"),
                ("cmd-risk-second", "risk.assess"),
                ("cmd-select-second", "selection.select_actions"),
                ("cmd-reserve-second", "accounting.reserve"),
                ("cmd-verification-plan-second", "verification_plan.create"),
                ("cmd-match-second", "capability.match_requirements"),
                ("cmd-context-second", "context.create_bundle"),
                ("cmd-sandbox-second", "sandbox.compile_profile"),
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
                """INSERT INTO tasks(
                   task_id,project_id,state,version,current_verification_plan_id,
                   current_verification_plan_version)
                   VALUES ('task-2','project-1','READY',1,'verification-plan-2',1)"""
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
                           'fixture',ARRAY['task:task-2'],ARRAY['repair.code'],
                           '{"target_environment":"dev"}',
                           '{"execution_time_ms":500}',
                           8000,7000,3000,9000,'action-registry/1.0',
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
                           'policy-bundle/1.0','dev','sha256:resource',
                           'sha256:policy-context-2')"""
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
                           'sha256:policy-input','cmd-policy-second')"""
            )
            connection.execute(
                """INSERT INTO current_policy_decisions(
                   action_id,policy_decision_id,planning_run_id,
                   action_content_hash,policy_bundle_version,policy_input_hash)
                   VALUES ('action-2','policy-2','plan-run-1','sha256:action2',
                           'policy-bundle/1.0','sha256:policy-input')"""
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
                           'sha256:risk-input','cmd-risk-second')"""
            )
            connection.execute(
                """INSERT INTO current_risk_assessments(
                   action_id,risk_assessment_id,planning_run_id,
                   action_content_hash,risk_model_version,risk_input_hash)
                   VALUES ('action-2','risk-2','plan-run-1','sha256:action2',
                           'risk-model/1.0','sha256:risk-input')"""
            )
            connection.execute(
                """INSERT INTO resource_reservations(
                   reservation_id,account_id,project_id,owner_type,owner_id,
                   status,account_version,command_id)
                   VALUES ('reservation-2','account-1','project-1','decision',
                           'decision-2','ACTIVE',1,'cmd-reserve-second')"""
            )
            connection.execute(
                """INSERT INTO resource_reservation_amounts(
                   reservation_id,dimension,amount)
                   VALUES ('reservation-2','execution_time_ms',500)"""
            )
            connection.execute(
                """INSERT INTO verification_plans(
                   verification_plan_id,task_id,project_id,version,status,
                   artifact_selectors,aggregation_rule,independence,created_by,
                   command_id)
                   VALUES ('verification-plan-2','task-2','project-1',1,'ACTIVE',
                           '[]','all_required_pass','worker_context_excluded',
                           'fixture','cmd-verification-plan-second')"""
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
                           'selection-conflict-rules/1.0',2,'cmd-select-second',
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
                           '{"execution_time_ms":500}',1)"""
            )
            connection.execute(
                """INSERT INTO capability_match_records(
                   match_id,project_id,task_id,decision_id,action_id,status,
                   reason_code,requirements_hash,matcher_version,template_id,
                   template_revision,availability_version,template_content_hash,
                   requirement,command_id,actor_type,actor_id)
                   VALUES ('capmatch-2','project-1','task-2','decision-2',
                           'action-2','MATCHED','MATCHED','sha256:requirements2',
                           'capability-matcher/1.0','template-1',1,2,
                           'sha256:template',
                           '{"project_id":"project-1","task_id":"task-2","decision_id":"decision-2","action_id":"action-2","action_content_hash":"sha256:action2"}',
                           'cmd-match-second','capability_registry','fixture')"""
            )
            connection.execute(
                """INSERT INTO context_bundles(
                   bundle_id,project_id,task_id,decision_id,action_id,template_id,
                   template_revision,selector_schema_version,builder_version,
                   manifest,manifest_hash,command_id,actor_type,actor_id)
                   VALUES ('ctx-2','project-1','task-2','decision-2','action-2',
                           'template-1',1,'context-selector/1.0',
                           'context-builder/1.0',
                           '{"items":[],"selectors":[]}',
                           'sha256:context2','cmd-context-second',
                           'context_builder','fixture')"""
            )
            connection.execute(
                """INSERT INTO sandbox_profiles(
                   profile_id,project_id,task_id,action_id,template_id,
                   template_revision,context_bundle_hash,compiler_version,
                   target,profile,profile_hash,constraints_hash,command_id,
                   actor_type,actor_id)
                   VALUES ('sbx-2','project-1','task-2','action-2','template-1',
                           1,'sha256:context2','sandbox-compiler/1.0',
                           'contract-only/1.0',
                           '{"bindings":{"project_id":"project-1"},"secrets":{"mode":"denied"}}',
                           'sha256:sandbox2','sha256:constraints',
                           'cmd-sandbox-second','sandbox_compiler','fixture')"""
            )

    def second_command_overrides(self):
        return dict(
            task_id="task-2",
            decision_id="decision-2",
            decision_version=2,
            decision_hash="sha256:selection-input2",
            action_id="action-2",
            action_content_hash="sha256:action2",
            policy_decision_id="policy-2",
            risk_assessment_id="risk-2",
            reservation_id="reservation-2",
            capability_match_id="capmatch-2",
            capability_requirements_hash="sha256:requirements2",
            context_bundle_id="ctx-2",
            context_manifest_hash="sha256:context2",
            sandbox_profile_id="sbx-2",
            sandbox_profile_hash="sha256:sandbox2",
            verification_plan_id="verification-plan-2",
            input_artifacts=(),
        )

    def acquire_command(self, suffix="1", scheduler_id="sched-1", session_id="session-1"):
        return AcquireExecutionLease(
            command_id="cmd-acquire-" + suffix,
            idempotency_key="key-acquire-" + suffix,
            project_id="project-1",
            scheduler_id=scheduler_id,
            scheduler_session_id=session_id,
            actor_id=scheduler_id,
        )

    def test_acquire_success_is_atomic_request_queue_lease_locks_event_outbox_receipt(self):
        request = self.prepare()
        self.register()
        lease = self.scheduler.acquire(self.acquire_command())
        self.assertEqual(request["execution_request_id"], lease["execution_request_id"])
        self.assertEqual("LEASED", lease["request_state"])
        self.assertEqual(1, lease["fencing_token"])
        self.assertEqual(2, lease["request_version"])
        with psycopg.connect(DATABASE_URL) as connection:
            self.assertEqual(1, connection.execute(
                "SELECT count(*) FROM execution_leases WHERE lease_state='ACTIVE'"
            ).fetchone()[0])
            self.assertEqual(2, connection.execute(
                "SELECT count(*) FROM execution_lock_ownerships WHERE lock_state='ACTIVE'"
            ).fetchone()[0])
            self.assertEqual(1, connection.execute(
                "SELECT count(*) FROM event_log WHERE event_type='execution.lease_acquired'"
            ).fetchone()[0])
            self.assertEqual(1, connection.execute(
                """SELECT count(*) FROM outbox_messages
                   WHERE event_id IN (
                     SELECT event_id FROM event_log
                     WHERE event_type='execution.lease_acquired')"""
            ).fetchone()[0])
            self.assertEqual(500, connection.execute(
                """SELECT reserved_amount FROM resource_balances
                   WHERE account_id='account-1' AND dimension='execution_time_ms'"""
            ).fetchone()[0])
            self.assertEqual("QUEUED", connection.execute(
                "SELECT request_state FROM execution_requests WHERE execution_request_id=%s",
                (request["execution_request_id"],),
            ).fetchone()[0])

    def test_ct_002_two_schedulers_compete_only_one_gets_current_lease(self):
        self.prepare()
        self.register("sched-a", "session-a")
        self.register("sched-b", "session-b")
        barrier = threading.Barrier(2)
        results = []

        def run(scheduler_id, session_id):
            barrier.wait(timeout=5)
            result = ExecutionScheduler(PostgresSchedulerStore(DATABASE_URL)).acquire(
                self.acquire_command(scheduler_id, scheduler_id, session_id)
            )
            results.append(result)

        threads = [
            threading.Thread(target=run, args=("sched-a", "session-a")),
            threading.Thread(target=run, args=("sched-b", "session-b")),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        winners = [item for item in results if item["result_code"] == "EXECUTION_LEASE_ACQUIRED"]
        self.assertEqual(1, len(winners), results)
        self.assertEqual(1, winners[0]["fencing_token"])
        with psycopg.connect(DATABASE_URL) as connection:
            self.assertEqual(1, connection.execute(
                "SELECT count(*) FROM execution_leases WHERE lease_state='ACTIVE'"
            ).fetchone()[0])
            self.assertEqual(1, connection.execute(
                "SELECT count(DISTINCT current_lease_id) FROM execution_request_current_states WHERE request_state='LEASED'"
            ).fetchone()[0])

    def test_conflicting_lock_scope_allows_only_one_lease(self):
        self.prepare("one")
        self.seed_second_fixture()
        self.prepare("two", **self.second_command_overrides(), lock_intents=(LockIntent("repository:repo-main"),))
        self.register("sched-a", "session-a")
        self.register("sched-b", "session-b")
        first = self.scheduler.acquire(self.acquire_command("one", "sched-a", "session-a"))
        second = self.scheduler.acquire(self.acquire_command("two", "sched-b", "session-b"))
        self.assertEqual("EXECUTION_LEASE_ACQUIRED", first["result_code"])
        self.assertEqual("NO_ELIGIBLE_EXECUTION", second["result_code"])
        with psycopg.connect(DATABASE_URL) as connection:
            self.assertEqual(1, connection.execute(
                "SELECT count(*) FROM execution_lock_ownerships WHERE lock_state='ACTIVE' AND lock_scope='repository:repo-main'"
            ).fetchone()[0])

    def test_non_conflicting_requests_can_be_leased_independently(self):
        self.prepare("one")
        self.seed_second_fixture()
        self.prepare(
            "two",
            **self.second_command_overrides(),
            lock_intents=(LockIntent("repository:repo-other"), LockIntent("workspace:project-1:other")),
        )
        self.register("sched-a", "session-a")
        self.register("sched-b", "session-b")
        first = self.scheduler.acquire(self.acquire_command("one", "sched-a", "session-a"))
        second = self.scheduler.acquire(self.acquire_command("two", "sched-b", "session-b"))
        self.assertEqual("EXECUTION_LEASE_ACQUIRED", first["result_code"])
        self.assertEqual("EXECUTION_LEASE_ACQUIRED", second["result_code"])
        self.assertNotEqual(first["lease_id"], second["lease_id"])

    def test_renew_keeps_token_and_uses_db_clock_expiry(self):
        self.prepare()
        self.register()
        lease = self.scheduler.acquire(self.acquire_command())
        renewed = self.scheduler.renew(RenewExecutionLease(
            command_id="cmd-renew-1",
            idempotency_key="key-renew-1",
            project_id="project-1",
            execution_request_id=lease["execution_request_id"],
            lease_id=lease["lease_id"],
            scheduler_id="sched-1",
            scheduler_session_id="session-1",
            fencing_token=lease["fencing_token"],
            expected_lease_version=lease["lease_version"],
            actor_id="sched-1",
        ))
        self.assertEqual(lease["fencing_token"], renewed["fencing_token"])
        self.assertEqual(2, renewed["lease_version"])
        stale = self.scheduler.validate_current_lease(
            execution_request_id=lease["execution_request_id"],
            lease_id=lease["lease_id"],
            scheduler_id="sched-1",
            scheduler_session_id="session-1",
            fencing_token=0,
            observed_request_version=lease["request_version"],
        )
        self.assertFalse(stale["valid"])
        self.assertEqual("FENCING_TOKEN_STALE", stale["reason_code"])

    def test_expired_lease_takeover_increments_token_and_old_holder_cannot_renew(self):
        self.prepare()
        self.register("sched-old", "session-old")
        self.register("sched-new", "session-new")
        old = self.scheduler.acquire(self.acquire_command("old", "sched-old", "session-old"))
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute(
                """UPDATE execution_leases
                   SET expires_at=clock_timestamp() - interval '1 millisecond'
                   WHERE lease_id=%s""",
                (old["lease_id"],),
            )
            connection.execute(
                """UPDATE execution_lock_ownerships
                   SET expires_at=clock_timestamp() - interval '1 millisecond'
                   WHERE lease_id=%s""",
                (old["lease_id"],),
            )
        new = self.scheduler.acquire(self.acquire_command("new", "sched-new", "session-new"))
        self.assertEqual("EXECUTION_LEASE_TAKEN_OVER", new["result_code"])
        self.assertGreater(new["fencing_token"], old["fencing_token"])
        with self.assertRaisesRegex(CommandRejected, "LEASE_NOT_ACTIVE|LEASE_EXPIRED"):
            self.scheduler.renew(RenewExecutionLease(
                command_id="cmd-renew-old",
                idempotency_key="key-renew-old",
                project_id="project-1",
                execution_request_id=old["execution_request_id"],
                lease_id=old["lease_id"],
                scheduler_id="sched-old",
                scheduler_session_id="session-old",
                fencing_token=old["fencing_token"],
                expected_lease_version=old["lease_version"],
                actor_id="sched-old",
            ))

    def test_relinquish_requeues_without_releasing_reservation_and_next_token_increases(self):
        self.prepare()
        self.register()
        first = self.scheduler.acquire(self.acquire_command("first"))
        released = self.scheduler.relinquish(RelinquishExecutionLease(
            command_id="cmd-release-1",
            idempotency_key="key-release-1",
            project_id="project-1",
            execution_request_id=first["execution_request_id"],
            lease_id=first["lease_id"],
            scheduler_id="sched-1",
            scheduler_session_id="session-1",
            fencing_token=first["fencing_token"],
            expected_lease_version=first["lease_version"],
            actor_id="sched-1",
        ))
        self.assertEqual("QUEUED", released["request_state"])
        second = self.scheduler.acquire(self.acquire_command("second"))
        self.assertGreater(second["fencing_token"], first["fencing_token"])
        with psycopg.connect(DATABASE_URL) as connection:
            self.assertEqual("ACTIVE", connection.execute(
                "SELECT status FROM resource_reservations WHERE reservation_id='reservation-1'"
            ).fetchone()[0])
            self.assertEqual(500, connection.execute(
                """SELECT reserved_amount FROM resource_balances
                   WHERE account_id='account-1' AND dimension='execution_time_ms'"""
            ).fetchone()[0])

    def test_duplicate_acquire_same_command_returns_original_and_payload_conflict_rejects(self):
        self.prepare()
        self.register()
        first = self.scheduler.acquire(self.acquire_command("idem"))
        second = self.scheduler.acquire(self.acquire_command("idem"))
        self.assertEqual(first["lease_id"], second["lease_id"])
        with self.assertRaisesRegex(CommandRejected, "SCHEDULER_IDEMPOTENCY_CONFLICT"):
            self.scheduler.acquire(AcquireExecutionLease(
                command_id="cmd-acquire-idem-conflict",
                idempotency_key="key-acquire-idem",
                project_id="project-1",
                scheduler_id="sched-1",
                scheduler_session_id="session-1",
                actor_id="sched-1",
                reason="different payload",
            ))

    def test_fault_injection_rolls_back_precommit_scheduler_points(self):
        points = (
            SchedulerFaultPoint.AFTER_RECEIPT_PLACEHOLDER,
            SchedulerFaultPoint.AFTER_AUTHORITY_VALIDATION,
            SchedulerFaultPoint.AFTER_QUEUE_CANDIDATE_LOCKED,
            SchedulerFaultPoint.AFTER_LOCK_SCOPES_PREPARED,
            SchedulerFaultPoint.AFTER_FENCING_TOKEN_ALLOCATED,
            SchedulerFaultPoint.AFTER_LEASE_WRITTEN,
            SchedulerFaultPoint.AFTER_LOCKS_WRITTEN,
            SchedulerFaultPoint.AFTER_REQUEST_LEASED,
            SchedulerFaultPoint.AFTER_QUEUE_CLAIMED,
            SchedulerFaultPoint.AFTER_EVENT_BEFORE_OUTBOX,
            SchedulerFaultPoint.AFTER_OUTBOX_BEFORE_RECEIPT,
            SchedulerFaultPoint.AFTER_RECEIPT_BEFORE_COMMIT,
        )
        for point in points:
            with self.subTest(point=point.value):
                self.store.reset_for_test()
                self.fixture.seed_fixture()
                self.prepare(point.value)
                self.register()
                faulted = PostgresSchedulerStore(DATABASE_URL)
                faulted.fail_scheduler_once(point)
                with self.assertRaisesRegex(CommandRejected, "injected scheduler crash"):
                    ExecutionScheduler(faulted).acquire(self.acquire_command(point.value))
                with psycopg.connect(DATABASE_URL) as connection:
                    self.assertEqual(0, connection.execute("SELECT count(*) FROM execution_leases").fetchone()[0])
                    self.assertEqual(0, connection.execute("SELECT count(*) FROM execution_lock_ownerships").fetchone()[0])
                    self.assertEqual("QUEUED", connection.execute(
                        "SELECT request_state FROM execution_request_current_states"
                    ).fetchone()[0])
                    self.assertEqual("PENDING", connection.execute(
                        "SELECT queue_state FROM execution_queue_current_states"
                    ).fetchone()[0])
                    self.assertEqual(0, connection.execute(
                        "SELECT count(*) FROM event_log WHERE event_type LIKE 'execution.lease%'"
                    ).fetchone()[0])


if __name__ == "__main__":
    unittest.main()
