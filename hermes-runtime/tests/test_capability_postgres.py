import os
import threading
import unittest
from pathlib import Path

try:
    import psycopg
    from psycopg.types.json import Jsonb
except ImportError:
    psycopg = None
    Jsonb = None

from hermes_runtime.application.capabilities import (
    ChangeWorkerTemplateAvailability,
    CompileSandboxProfile,
    CreateContextBundle,
    CreateWorkerTemplateRevision,
    ExecutionPreparationAuthority,
    MatchCapabilityRequirements,
    RegisterCapabilitySchema,
)
from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.domain.capability import (
    AuthorityRef,
    CapabilityRequirement,
    ContextSelector,
    SandboxCompileInput,
    WorkerTemplateRevision,
)
from hermes_runtime.infrastructure.postgres_capability import (
    CapabilityFaultPoint,
    PostgresCapabilityStore,
)


DATABASE_URL = os.environ.get("HERMES_TEST_DATABASE_URL")


@unittest.skipUnless(DATABASE_URL and psycopg, "requires real PostgreSQL 14+")
class CapabilityPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = PostgresCapabilityStore(DATABASE_URL)
        for migration in sorted((Path(__file__).parents[1] / "migrations").glob("*.sql")):
            cls.store.apply_migration(migration)

    def setUp(self):
        self.store.reset_for_test()
        self.authority = ExecutionPreparationAuthority(PostgresCapabilityStore(DATABASE_URL))
        self.seed_selection_fixture()

    def seed_selection_fixture(self, suffix="p2"):
        with psycopg.connect(DATABASE_URL) as connection:
            for command_id, command_type in (
                ("cmd-create-project-" + suffix, "project.create"),
                ("cmd-trigger-" + suffix, "test.trigger"),
                ("cmd-plan-" + suffix, "planner.plan_candidates"),
                ("cmd-policy-" + suffix, "policy.evaluate"),
                ("cmd-risk-" + suffix, "risk.assess"),
                ("cmd-select-" + suffix, "selection.select_actions"),
                ("cmd-reserve-" + suffix, "accounting.reserve"),
                ("cmd-verification-plan-" + suffix, "verification_plan.create"),
            ):
                connection.execute(
                    """INSERT INTO command_receipts(
                       command_id,project_id,command_type,idempotency_key,
                       request_hash,status,result,completed_at)
                       VALUES (%s,'project-1',%s,%s,'fixture',
                               'APPLIED','{}',now())""",
                    (command_id, command_type, command_id),
                )
            project_sequence = connection.execute(
                """INSERT INTO event_log(
                   event_id,event_type,schema_version,producer_type,producer_id,
                   project_id,partition_key,command_id,correlation_id,payload)
                   VALUES ('evt-project-p2','project.created','1.0',
                           'control_plane','fixture','project-1','project-1',
                           %s,'fixture',
                           '{"project_id":"project-1","new_state":"CREATED","project_version":0}')
                   RETURNING sequence""",
                ("cmd-create-project-" + suffix,),
            ).fetchone()[0]
            connection.execute(
                """INSERT INTO outbox_messages(
                   message_id,event_id,topic,partition_key,sequence,payload)
                   VALUES ('msg-project-p2','evt-project-p2','hermes.runtime.events',
                           'project-1',%s,
                           '{"project_id":"project-1","new_state":"CREATED","project_version":0}')""",
                (project_sequence,),
            )
            connection.execute(
                """INSERT INTO projects(project_id,title,state,version,last_command_id)
                   VALUES ('project-1','P2 fixture','CREATED',0,%s)""",
                ("cmd-create-project-" + suffix,),
            )
            connection.execute(
                """INSERT INTO tasks(task_id,project_id,state,version)
                   VALUES ('task-1','project-1','READY',1)"""
            )
            connection.execute(
                """INSERT INTO event_log(
                   event_id,event_type,schema_version,producer_type,producer_id,
                   project_id,partition_key,command_id,correlation_id,payload)
                   VALUES ('evt-trigger-p2','task.readiness_recomputed','1.0',
                           'control_plane','fixture','project-1','project-1',
                           %s,'fixture','{"task_id":"task-1"}')""",
                ("cmd-trigger-" + suffix,),
            )
            connection.execute(
                """INSERT INTO analysis_contexts(
                   analysis_context_id,project_id,trigger_event_id,partition_key,
                   observed_at_sequence,trigger_event_type,trigger_event_schema_version,
                   trigger_event_hash,task_id,task_version_ref,rule_set_version,
                   context_hash)
                   VALUES ('ctx-analysis-1','project-1','evt-trigger-p2','project-1',
                           1,'task.readiness_recomputed','1.0','sha256:trigger',
                           'task-1','1','situation-rules/1.0','sha256:analysis')"""
            )
            connection.execute(
                """INSERT INTO situations(
                   situation_id,project_id,task_id,type,status,trigger_event_id,
                   analysis_context_id,severity,fingerprint,observed_at_sequence,
                   rule_set_version,canonicalization_version,confidence_basis_points,
                   version)
                   VALUES ('situation-1','project-1','task-1','work_available',
                           'OPEN','evt-trigger-p2','ctx-analysis-1','MEDIUM',
                           'sha256:situation',1,'situation-rules/1.0',
                           'situation-fingerprint/1.0',8000,1)"""
            )
            connection.execute(
                """INSERT INTO planning_runs(
                   planning_run_id,project_id,situation_id,situation_version,
                   analysis_context_id,analysis_context_hash,registry_version,
                   planner_rule_version,resource_estimator_version,input_hash,
                   candidate_count,created_by,command_id)
                   VALUES ('plan-run-1','project-1','situation-1',1,
                           'ctx-analysis-1','sha256:analysis','action-registry/1.0',
                           'planner-rules/1.0','resource-estimator/1.0',
                           'sha256:plan-input',1,'fixture',%s)""",
                ("cmd-plan-" + suffix,),
            )
            connection.execute(
                """INSERT INTO current_planning_runs(
                   situation_id,planning_run_id,situation_version,
                   analysis_context_hash,registry_version,planner_rule_version,
                   input_hash)
                   VALUES ('situation-1','plan-run-1',1,'sha256:analysis',
                           'action-registry/1.0','planner-rules/1.0',
                           'sha256:plan-input')"""
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
                   VALUES ('action-1','plan-run-1','project-1','situation-1',
                           1,'ctx-analysis-1','sha256:analysis','repair',
                           'fixture',ARRAY['task:task-1'],ARRAY['repair.code'],
                           '{"target_environment":"dev"}',
                           '{"execution_time_ms":500,"cpu_time_ms":100,"storage_bytes":100}',
                           8000,7000,3000,9000,'action-registry/1.0',
                           'planner-rules/1.0',0,'sha256:action')"""
            )
            connection.execute(
                """INSERT INTO policy_evaluation_contexts(
                   evaluation_context_id,project_id,planning_run_id,action_id,
                   action_content_hash,situation_id,situation_version,
                   analysis_context_hash,planner_input_hash,candidate_registry_version,
                   policy_bundle_version,target_environment,resource_estimate_hash,
                   context_hash)
                   VALUES ('evalctx-policy-1','project-1','plan-run-1','action-1',
                           'sha256:action','situation-1',1,'sha256:analysis',
                           'sha256:plan-input','action-registry/1.0',
                           'policy-bundle/1.0','dev','sha256:resource',
                           'sha256:policy-context')"""
            )
            connection.execute(
                """INSERT INTO policy_decisions(
                   policy_decision_id,evaluation_context_id,project_id,
                   planning_run_id,action_id,action_content_hash,result,
                   constraints,policy_bundle_version,policy_rule_version,
                   policy_input_hash,command_id)
                   VALUES ('policy-1','evalctx-policy-1','project-1',
                           'plan-run-1','action-1','sha256:action','ALLOW',
                           '{"network_access":"disabled","filesystem_write":"none","secret_access":"denied","production_access":"denied","allowed_tools":["pytest"],"max_external_api_calls":0}',
                           'policy-bundle/1.0','policy-rules/1.0',
                           'sha256:policy-input',%s)""",
                ("cmd-policy-" + suffix,),
            )
            connection.execute(
                """INSERT INTO current_policy_decisions(
                   action_id,policy_decision_id,planning_run_id,
                   action_content_hash,policy_bundle_version,policy_input_hash)
                   VALUES ('action-1','policy-1','plan-run-1','sha256:action',
                           'policy-bundle/1.0','sha256:policy-input')"""
            )
            connection.execute(
                """INSERT INTO risk_assessments(
                   risk_assessment_id,evaluation_context_id,project_id,
                   planning_run_id,action_id,action_content_hash,
                   risk_score_basis_points,risk_level,factors,required_mitigations,
                   available_mitigations,residual_risk_basis_points,
                   risk_model_version,risk_rule_version,risk_input_hash,command_id)
                   VALUES ('risk-1','evalctx-policy-1','project-1','plan-run-1',
                           'action-1','sha256:action',2000,'LOW','{}',
                           ARRAY['verification-before-apply'],
                           ARRAY['verification-before-apply'],1500,
                           'risk-model/1.0','risk-rules/1.0',
                           'sha256:risk-input',%s)""",
                ("cmd-risk-" + suffix,),
            )
            connection.execute(
                """INSERT INTO current_risk_assessments(
                   action_id,risk_assessment_id,planning_run_id,
                   action_content_hash,risk_model_version,risk_input_hash)
                   VALUES ('action-1','risk-1','plan-run-1','sha256:action',
                           'risk-model/1.0','sha256:risk-input')"""
            )
            connection.execute(
                """INSERT INTO resource_accounts(
                   account_id,project_id,scope_type,scope_id,version)
                   VALUES ('account-1','project-1','project','project-1',1)"""
            )
            connection.execute(
                """INSERT INTO resource_reservations(
                   reservation_id,account_id,project_id,owner_type,owner_id,
                   status,account_version,command_id)
                   VALUES ('reservation-1','account-1','project-1','decision',
                           'decision-1','ACTIVE',1,%s)""",
                ("cmd-reserve-" + suffix,),
            )
            connection.execute(
                """INSERT INTO verification_plans(
                   verification_plan_id,task_id,project_id,version,status,
                   artifact_selectors,aggregation_rule,independence,created_by,
                   command_id)
                   VALUES ('verification-plan-1','task-1','project-1',1,'ACTIVE',
                           '[]','all_required_pass','worker_context_excluded',
                           'fixture',%s)""",
                ("cmd-verification-plan-" + suffix,),
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
                   VALUES ('decision-1','project-1','situation-1',1,
                           'ctx-analysis-1','sha256:analysis',1,'plan-run-1',
                           'sha256:plan-input',1,'sha256:selection-input',
                           '[{"action_id":"action-1","content_hash":"sha256:action"}]',
                           ARRAY['action-1'],ARRAY['action-1'],
                           '[{"policy_decision_id":"policy-1"}]',
                           '[{"risk_assessment_id":"risk-1"}]',
                           '[]','[]','[{"reservation_id":"reservation-1"}]',
                           'selection-weight-profile/1.0',
                           'selection-normalizer/1.0',
                           'selection-conflict-rules/1.0',2,%s,
                           'action_selection','fixture')""",
                ("cmd-select-" + suffix,),
            )
            connection.execute(
                """INSERT INTO selected_action_refs(
                   decision_id,action_id,selection_rank,selected_intent)
                   VALUES ('decision-1','action-1',0,
                           '{"action_id":"action-1","type":"repair"}')"""
            )
            connection.execute(
                """INSERT INTO decision_reservation_mappings(
                   decision_id,action_id,reservation_id,account_id,
                   resource_amounts,account_version)
                   VALUES ('decision-1','action-1','reservation-1','account-1',
                           '{"execution_time_ms":500}',1)"""
            )

    def register_and_activate_template(self):
        self.authority.register_capability_schema(RegisterCapabilitySchema(
            "cmd-cap-schema", "key-cap-schema", "project-1",
            "repair.code", "capability-schema/1.0", "repair code capability",
        ))
        template = WorkerTemplateRevision(
            "template-1", 1, None, "python-process", ("repair.code",),
            "STANDARD", ("pytest",), (
                "network_access", "filesystem_write", "secret_access",
                "production_access", "allowed_tools", "forbidden_paths",
                "max_external_api_calls", "required_mitigations", "lock_scopes",
                "execution_time_ms", "cpu_time_ms", "storage_bytes", "process_count",
            ),
            {"execution_time_ms": 1000, "cpu_time_ms": 1000, "storage_bytes": 1000},
            {
                "network_access": "disabled",
                "filesystem_write": "none",
                "secret_access": "denied",
                "production_access": "denied",
                "allowed_tools": ["pytest"],
                "max_external_api_calls": 0,
            },
            1,
        )
        created = self.authority.create_worker_template_revision(
            CreateWorkerTemplateRevision(
                "cmd-template-1", "key-template-1", "project-1", template, 0,
            )
        )
        activated = self.authority.change_worker_template_availability(
            ChangeWorkerTemplateAvailability(
                "cmd-template-avail-1", "key-template-avail-1", "project-1",
                "template-1", 1, "AVAILABLE", "ADMISSIBLE", 1,
            )
        )
        return template, created, activated

    def match_command(self, suffix="1"):
        return MatchCapabilityRequirements(
            "cmd-match-" + suffix, "key-match-" + suffix, "project-1",
            CapabilityRequirement(
                "project-1", "task-1", "decision-1", "action-1", "repair",
                "sha256:action", ("repair.code",), ("pytest",), "STANDARD",
                {"network_access": "disabled", "filesystem_write": "none"},
                {"execution_time_ms": 500}, ("task:task-1",),
                ("network_access", "filesystem_write"),
            ),
            0,
        )

    def context_command(self, suffix="1"):
        return CreateContextBundle(
            "cmd-context-" + suffix, "key-context-" + suffix, "project-1",
            "task-1", "decision-1", "action-1", "template-1", 1,
            (
                ContextSelector("project", "project-1"),
                ContextSelector("task", "task-1"),
                ContextSelector("selected_action", "action-1"),
                ContextSelector("policy_decision", "policy-1"),
                ContextSelector("risk_assessment", "risk-1"),
                ContextSelector("resource_reservation", "reservation-1"),
                ContextSelector("verification_plan", "verification-plan-1"),
            ),
            (
                AuthorityRef("project", "project-1", "project-1", None, 1, "sha256:project", {}),
                AuthorityRef("task", "task-1", "project-1", "task-1", 1, "sha256:task", {}),
                AuthorityRef("selected_action", "action-1", "project-1", "task-1", 1, "sha256:action", {}),
                AuthorityRef("policy_decision", "policy-1", "project-1", "task-1", 1, "sha256:policy-input", {}),
                AuthorityRef("risk_assessment", "risk-1", "project-1", "task-1", 1, "sha256:risk-input", {}),
                AuthorityRef("resource_reservation", "reservation-1", "project-1", "task-1", 1, "sha256:reservation", {}),
                AuthorityRef("verification_plan", "verification-plan-1", "project-1", "task-1", 1, "sha256:verification-plan", {}),
            ),
        )

    def sandbox_command(self, template, context_hash, suffix="1"):
        return CompileSandboxProfile(
            "cmd-sandbox-" + suffix, "key-sandbox-" + suffix, "project-1",
            SandboxCompileInput(
                "project-1", "task-1", "action-1", "sha256:action",
                {
                    "network_access": "disabled",
                    "filesystem_write": "none",
                    "secret_access": "denied",
                    "production_access": "denied",
                    "allowed_tools": ["pytest"],
                    "max_external_api_calls": 0,
                },
                ("verification-before-apply",), ("verification-before-apply",),
                {"execution_time_ms": 500}, template, context_hash,
                ("task:task-1",),
            ),
        )

    def test_template_revision_availability_match_bundle_profile_event_outbox_receipt(self):
        template, _, activated = self.register_and_activate_template()
        self.assertEqual("AVAILABLE", activated["availability_status"])
        match = self.authority.match_capability_requirements(self.match_command())
        self.assertEqual("MATCHED", match["reason_code"])
        self.assertEqual("template-1", match["template_id"])
        bundle = self.authority.create_context_bundle(self.context_command())
        self.assertTrue(bundle["manifest_hash"].startswith("sha256:"))
        profile = self.authority.compile_sandbox_profile(
            self.sandbox_command(template, bundle["manifest_hash"])
        )
        self.assertTrue(profile["profile_hash"].startswith("sha256:"))
        with psycopg.connect(DATABASE_URL) as connection:
            self.assertEqual(1, connection.execute(
                "SELECT count(*) FROM worker_template_revisions WHERE template_id='template-1'"
            ).fetchone()[0])
            self.assertEqual(1, connection.execute(
                "SELECT count(*) FROM capability_match_records WHERE status='MATCHED'"
            ).fetchone()[0])
            self.assertEqual(1, connection.execute(
                "SELECT count(*) FROM context_bundles WHERE manifest_hash=%s",
                (bundle["manifest_hash"],),
            ).fetchone()[0])
            self.assertEqual(1, connection.execute(
                "SELECT count(*) FROM sandbox_profiles WHERE profile_hash=%s",
                (profile["profile_hash"],),
            ).fetchone()[0])
            self.assertEqual(6, connection.execute(
                """SELECT count(*) FROM event_log
                   WHERE event_type IN (
                     'capability.schema_registered','worker_template.revision_created',
                     'worker_template.availability_changed','capability.match_recorded',
                     'context.bundle_created','sandbox.profile_compiled')"""
            ).fetchone()[0])
            self.assertEqual(0, connection.execute(
                """SELECT count(*) FROM event_log
                   WHERE event_type IN ('execution.queued','execution.requested')"""
            ).fetchone()[0])
            self.assertEqual(0, connection.execute(
                "SELECT count(*) FROM execution_requests"
            ).fetchone()[0])
            self.assertEqual(0, connection.execute(
                "SELECT count(*) FROM execution_queue_items"
            ).fetchone()[0])

    def test_immutable_revision_and_context_profile_rows_are_db_enforced(self):
        template, _, _ = self.register_and_activate_template()
        bundle = self.authority.create_context_bundle(self.context_command())
        self.authority.compile_sandbox_profile(self.sandbox_command(template, bundle["manifest_hash"]))
        for statement in (
            "UPDATE worker_template_revisions SET trust_level='PRIVILEGED'",
            "DELETE FROM context_bundles",
            "UPDATE sandbox_profiles SET target='docker'",
        ):
            with self.subTest(statement=statement):
                with self.assertRaisesRegex(psycopg.errors.RaiseException, "append-only/immutable"):
                    with psycopg.connect(DATABASE_URL) as connection:
                        connection.execute(statement)

    def test_idempotency_conflict_expected_version_and_concurrent_activation(self):
        template, first, _ = self.register_and_activate_template()
        duplicate = self.authority.create_worker_template_revision(
            CreateWorkerTemplateRevision("cmd-template-1", "key-template-1", "project-1", template, 0)
        )
        self.assertEqual(first["content_hash"], duplicate["content_hash"])
        changed = WorkerTemplateRevision(
            "template-1", 1, None, "python-process", ("repair.code",),
            "ELEVATED", ("pytest",), template.supported_sandbox_features,
            template.resource_envelope, template.constraint_ranges, 1,
        )
        with self.assertRaisesRegex(CommandRejected, "CAPABILITY_IDEMPOTENCY_CONFLICT"):
            self.authority.create_worker_template_revision(
                CreateWorkerTemplateRevision("cmd-template-conflict", "key-template-1", "project-1", changed, 0)
            )
        with self.assertRaisesRegex(CommandRejected, "WORKER_TEMPLATE_AVAILABILITY_VERSION_CONFLICT"):
            self.authority.change_worker_template_availability(ChangeWorkerTemplateAvailability(
                "cmd-avail-stale", "key-avail-stale", "project-1",
                "template-1", 1, "DISABLED", "NOT_ADMISSIBLE", 1,
            ))

        results = []
        def run(index):
            try:
                result = ExecutionPreparationAuthority(PostgresCapabilityStore(DATABASE_URL)).change_worker_template_availability(
                    ChangeWorkerTemplateAvailability(
                        "cmd-avail-race-" + str(index), "key-avail-race-" + str(index),
                        "project-1", "template-1", 1, "AVAILABLE", "ADMISSIBLE", 2,
                    )
                )
                results.append(result["availability_version"])
            except Exception as exc:
                results.append(type(exc).__name__ + ":" + str(exc))
        threads = [threading.Thread(target=run, args=(idx,)) for idx in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(1, sum(item == 3 for item in results))

    def test_hash_mismatch_secret_and_compile_failure_leave_no_authority_rows(self):
        template, _, _ = self.register_and_activate_template()
        with self.assertRaisesRegex(CommandRejected, "SECRET_VALUE_FORBIDDEN"):
            self.authority.create_context_bundle(CreateContextBundle(
                "cmd-context-secret", "key-context-secret", "project-1",
                "task-1", "decision-1", "action-1", "template-1", 1,
                (ContextSelector("evidence", "evidence-1"),),
                (AuthorityRef("evidence", "evidence-1", "project-1", "task-1", 1, "sha256:e", {"password": "password=clear"}),),
            ))
        with self.assertRaisesRegex(CommandRejected, "SANDBOX_REQUIRED_MITIGATION_UNAVAILABLE"):
            self.authority.compile_sandbox_profile(CompileSandboxProfile(
                "cmd-sandbox-fail", "key-sandbox-fail", "project-1",
                SandboxCompileInput(
                    "project-1", "task-1", "action-1", "sha256:action", {},
                    ("missing",), (), {}, template, "sha256:missing", (),
                ),
            ))
        with psycopg.connect(DATABASE_URL) as connection:
            self.assertEqual(0, connection.execute("SELECT count(*) FROM context_bundles").fetchone()[0])
            self.assertEqual(0, connection.execute("SELECT count(*) FROM sandbox_profiles").fetchone()[0])
            texts = [
                str(row[0]) for row in connection.execute(
                    "SELECT result FROM command_receipts WHERE status='REJECTED'"
                ).fetchall()
            ]
        self.assertFalse(any("password=clear" in text for text in texts))

    def test_fault_injection_rolls_back_authority_event_outbox(self):
        self.authority.register_capability_schema(RegisterCapabilitySchema(
            "cmd-cap-schema", "key-cap-schema", "project-1",
            "repair.code", "capability-schema/1.0", "repair code capability",
        ))
        faulted_store = PostgresCapabilityStore(DATABASE_URL)
        faulted_store.fail_capability_once(CapabilityFaultPoint.AFTER_AUTHORITY_BEFORE_EVENT)
        faulted = ExecutionPreparationAuthority(faulted_store)
        with self.assertRaisesRegex(RuntimeError, "injected capability crash"):
            faulted.create_worker_template_revision(CreateWorkerTemplateRevision(
                "cmd-template-fault", "key-template-fault", "project-1",
                WorkerTemplateRevision(
                    "template-fault", 1, None, "python-process", ("repair.code",),
                    "STANDARD", ("pytest",), ("network_access",),
                    {}, {"network_access": "disabled"}, 1,
                ),
                0,
            ))
        with psycopg.connect(DATABASE_URL) as connection:
            self.assertEqual(0, connection.execute(
                "SELECT count(*) FROM worker_template_revisions WHERE template_id='template-fault'"
            ).fetchone()[0])
            self.assertEqual(0, connection.execute(
                "SELECT count(*) FROM event_log WHERE command_id='cmd-template-fault'"
            ).fetchone()[0])
            self.assertEqual(0, connection.execute(
                "SELECT count(*) FROM outbox_messages WHERE event_id IN (SELECT event_id FROM event_log WHERE command_id='cmd-template-fault')"
            ).fetchone()[0])


if __name__ == "__main__":
    unittest.main()
