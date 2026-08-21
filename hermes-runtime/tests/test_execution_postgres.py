import json
import os
import uuid
import threading
import unittest
from pathlib import Path

try:
    import psycopg
except ImportError:
    psycopg = None

from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.application.executions import ExecutionPreparation, PrepareExecutionRequest
from hermes_runtime.domain.entry_approval_bridge import stable_id
from hermes_runtime.domain.execution import ArtifactInputRef, LockIntent
from hermes_runtime.infrastructure.postgres_execution import (
    ExecutionFaultPoint,
    PostgresExecutionStore,
)


DATABASE_URL = os.environ.get("HERMES_TEST_DATABASE_URL")


@unittest.skipUnless(DATABASE_URL and psycopg, "requires real PostgreSQL 14+")
class ExecutionPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = PostgresExecutionStore(DATABASE_URL)
        for migration in sorted((Path(__file__).parents[1] / "migrations").glob("*.sql")):
            cls.store.apply_migration(migration)

    def setUp(self):
        self.store.reset_for_test()
        self.execution = ExecutionPreparation(PostgresExecutionStore(DATABASE_URL))
        self.seed_fixture()

    def seed_fixture(self, suffix="p2"):
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
                ("cmd-cap-schema-" + suffix, "capability.register_schema"),
                ("cmd-template-" + suffix, "capability.create_worker_template_revision"),
                ("cmd-template-avail-" + suffix, "capability.change_worker_template_availability"),
                ("cmd-match-" + suffix, "capability.match_requirements"),
                ("cmd-context-" + suffix, "context.create_bundle"),
                ("cmd-sandbox-" + suffix, "sandbox.compile_profile"),
                ("cmd-artifact-" + suffix, "test.artifact"),
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
                """UPDATE command_receipts
                   SET status='PROCESSING',completed_at=NULL
                   WHERE command_id=%s""",
                ("cmd-create-project-" + suffix,),
            )
            connection.execute(
                """SELECT public.hermes_create_project_authority(
                   'project-1','P2 execution fixture',%s,'control_plane',
                   'fixture','user','fixture','create')""",
                ("cmd-create-project-" + suffix,),
            )
            seq = connection.execute(
                """INSERT INTO event_log(
                   event_id,event_type,schema_version,producer_type,producer_id,
                   project_id,partition_key,command_id,correlation_id,payload)
                   VALUES ('evt-project-exec','project.created','1.0',
                           'control_plane','fixture','project-1','project-1',
                           %s,'fixture',
                           '{"project_id":"project-1","project_version":0,"new_state":"CREATED"}')
                   RETURNING sequence""",
                ("cmd-create-project-" + suffix,),
            ).fetchone()[0]
            connection.execute(
                """INSERT INTO outbox_messages(
                   message_id,event_id,topic,partition_key,sequence,payload)
                   VALUES ('msg-project-exec','evt-project-exec','hermes.runtime.events',
                           'project-1',%s,
                           '{"project_id":"project-1","project_version":0,"new_state":"CREATED"}')""",
                (seq,),
            )
            connection.execute(
                """UPDATE command_receipts
                   SET status='APPLIED',
                       result='{"result_code":"PROJECT_CREATED"}',
                       completed_at=now()
                   WHERE command_id=%s""",
                ("cmd-create-project-" + suffix,),
            )
            connection.execute(
                """INSERT INTO tasks(
                   task_id,project_id,state,version,current_verification_plan_id,
                   current_verification_plan_version)
                   VALUES ('task-1','project-1','READY',1,
                           'verification-plan-1',1)"""
            )
            connection.execute(
                """INSERT INTO event_log(
                   event_id,event_type,schema_version,producer_type,producer_id,
                   project_id,partition_key,command_id,correlation_id,payload)
                   VALUES ('evt-trigger-exec','task.readiness_recomputed','1.0',
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
                   VALUES ('ctx-analysis-1','project-1','evt-trigger-exec',
                           'project-1',1,'task.readiness_recomputed','1.0',
                           'sha256:trigger','task-1','1','situation-rules/1.0',
                           'sha256:analysis')"""
            )
            connection.execute(
                """INSERT INTO situations(
                   situation_id,project_id,task_id,type,status,trigger_event_id,
                   analysis_context_id,severity,fingerprint,observed_at_sequence,
                   rule_set_version,canonicalization_version,confidence_basis_points,
                   version)
                   VALUES ('situation-1','project-1','task-1','work_available',
                           'OPEN','evt-trigger-exec','ctx-analysis-1','MEDIUM',
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
                """INSERT INTO resource_balances(account_id,dimension,limit_amount,reserved_amount)
                   VALUES ('account-1','execution_time_ms',1000,500)"""
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
                """INSERT INTO resource_reservation_amounts(
                   reservation_id,dimension,amount)
                   VALUES ('reservation-1','execution_time_ms',500)"""
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
                """INSERT INTO artifacts(
                   artifact_id,task_id,content_hash,media_type,produced_by)
                   VALUES ('artifact-1','task-1','sha256:artifact','text/plain',
                           'fixture')"""
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
            connection.execute(
                """INSERT INTO capability_schemas(
                   capability_name,schema_version,description,content_hash,
                   command_id,actor_type,actor_id)
                   VALUES ('repair.code','capability-schema/1.0','repair',
                           'sha256:cap-schema',%s,'capability_registry','fixture')""",
                ("cmd-cap-schema-" + suffix,),
            )
            connection.execute(
                """INSERT INTO worker_template_revisions(
                   template_id,revision,project_id,runtime_kind,capabilities,
                   trust_level,allowed_tools,supported_sandbox_features,
                   resource_envelope,constraint_ranges,concurrency_capacity,
                   schema_version,content_hash,command_id,actor_type,actor_id)
                   VALUES ('template-1',1,NULL,'python-process',ARRAY['repair.code'],
                           'STANDARD',ARRAY['pytest'],
                           ARRAY['network_access','filesystem_write','secret_access',
                                 'production_access','allowed_tools',
                                 'max_external_api_calls','required_mitigations',
                                 'lock_scopes','execution_time_ms'],
                           '{"execution_time_ms":1000}',
                           '{"network_access":"disabled","filesystem_write":"none","secret_access":"denied","production_access":"denied","allowed_tools":["pytest"],"max_external_api_calls":0}',
                           1,'worker-template-schema/1.0','sha256:template',
                           %s,'capability_registry','fixture')""",
                ("cmd-template-" + suffix,),
            )
            connection.execute(
                """INSERT INTO worker_template_capabilities(
                   template_id,revision,capability_name,schema_version)
                   VALUES ('template-1',1,'repair.code','capability-schema/1.0')"""
            )
            connection.execute(
                """INSERT INTO worker_template_availability(
                   template_id,revision,availability_status,admission_status,
                   availability_version,reason,command_id,actor_type,actor_id)
                   VALUES ('template-1',1,'AVAILABLE','ADMISSIBLE',2,'fixture',
                           %s,'capability_registry','fixture')""",
                ("cmd-template-avail-" + suffix,),
            )
            connection.execute(
                """INSERT INTO capability_match_records(
                   match_id,project_id,task_id,decision_id,action_id,status,
                   reason_code,requirements_hash,matcher_version,template_id,
                   template_revision,availability_version,template_content_hash,
                   requirement,command_id,actor_type,actor_id)
                   VALUES ('capmatch-1','project-1','task-1','decision-1',
                           'action-1','MATCHED','MATCHED','sha256:requirements',
                           'capability-matcher/1.0','template-1',1,2,
                           'sha256:template',
                           '{"project_id":"project-1","task_id":"task-1","decision_id":"decision-1","action_id":"action-1","action_content_hash":"sha256:action"}',
                           %s,'capability_registry','fixture')""",
                ("cmd-match-" + suffix,),
            )
            connection.execute(
                """INSERT INTO context_bundles(
                   bundle_id,project_id,task_id,decision_id,action_id,template_id,
                   template_revision,selector_schema_version,builder_version,
                   manifest,manifest_hash,command_id,actor_type,actor_id)
                   VALUES ('ctx-1','project-1','task-1','decision-1','action-1',
                           'template-1',1,'context-selector/1.0',
                           'context-builder/1.0',
                           '{"items":[],"selectors":[]}',
                           'sha256:context',%s,'context_builder','fixture')""",
                ("cmd-context-" + suffix,),
            )
            connection.execute(
                """INSERT INTO sandbox_profiles(
                   profile_id,project_id,task_id,action_id,template_id,
                   template_revision,context_bundle_hash,compiler_version,
                   target,profile,profile_hash,constraints_hash,command_id,
                   actor_type,actor_id)
                   VALUES ('sbx-1','project-1','task-1','action-1','template-1',
                           1,'sha256:context','sandbox-compiler/1.0',
                           'contract-only/1.0',
                           '{"bindings":{"project_id":"project-1"},"secrets":{"mode":"denied"}}',
                           'sha256:sandbox','sha256:constraints',%s,
                           'sandbox_compiler','fixture')""",
                ("cmd-sandbox-" + suffix,),
            )

    def command(self, suffix="1", **overrides):
        base = dict(
            command_id="cmd-exec-" + suffix,
            idempotency_key="key-exec-" + suffix,
            project_id="project-1",
            task_id="task-1",
            expected_project_version=0,
            expected_task_version=1,
            decision_id="decision-1",
            decision_version=1,
            decision_hash="sha256:selection-input",
            action_id="action-1",
            action_version=1,
            action_content_hash="sha256:action",
            action_type="repair",
            action_requirements_hash="sha256:requirements",
            policy_decision_id="policy-1",
            policy_version=1,
            policy_hash="sha256:policy-input",
            risk_assessment_id="risk-1",
            risk_version=1,
            risk_hash="sha256:risk-input",
            mandatory_mitigations_hash="sha256:mitigations",
            reservation_id="reservation-1",
            reservation_version=1,
            reservation_hash="sha256:reservation",
            capability_match_id="capmatch-1",
            capability_match_version=1,
            capability_requirements_hash="sha256:requirements",
            worker_template_id="template-1",
            worker_template_revision=1,
            worker_template_content_hash="sha256:template",
            worker_template_availability_version=2,
            context_bundle_id="ctx-1",
            context_manifest_hash="sha256:context",
            sandbox_profile_id="sbx-1",
            sandbox_profile_hash="sha256:sandbox",
            sandbox_compiler_version="sandbox-compiler/1.0",
            sandbox_compiler_target="contract-only/1.0",
            verification_plan_id="verification-plan-1",
            verification_plan_version=1,
            verification_plan_hash="sha256:verification-plan",
            input_artifacts=(ArtifactInputRef("artifact-1", "task-1", "sha256:artifact"),),
            lock_intents=(LockIntent("repository:repo-main"), LockIntent("workspace:project-1:default")),
            priority=10,
        )
        base.update(overrides)
        return PrepareExecutionRequest(**base)

    def counts(self):
        with psycopg.connect(DATABASE_URL) as connection:
            return {
                table: connection.execute("SELECT count(*) FROM " + table).fetchone()[0]
                for table in (
                    "execution_requests",
                    "execution_reservation_bindings",
                    "execution_queue_items",
                    "event_log",
                    "outbox_messages",
                    "command_receipts",
                )
            }


    def _guard_result(self, payload):
        with psycopg.connect(DATABASE_URL) as connection:
            return bool(connection.execute(
                "SELECT public.hermes_execution_has_secret_value(%s::jsonb)",
                (json.dumps(payload),),
            ).fetchone()[0])

    def test_structured_secret_guard_rejects_canaries_and_preserves_identity_references(self):
        canary = "s" + "k-" + uuid.uuid4().hex
        private_marker = "-----BEGIN " + "PRIVATE KEY-----"
        rejected = (
            {"note": canary},
            {"note": "header Bearer " + canary},
            {"note": "equal=" + canary},
            {"note": "colon:" + canary},
            {"note": "space " + canary},
            {"note": "slash/" + canary},
            {"nested": {"items": [canary]}},
            {"password": "runtime-value"},
            {"api_key": canary},
            {"access_token": canary},
            {"authorization": "Bearer " + canary},
            {"client_secret": canary},
            {"private_key": private_marker},
            {"note": private_marker},
            {"secret_ref": "not-an-opaque-reference"},
            {"credential_ref": canary},
        )
        for payload in rejected:
            with self.subTest(payload_shape=sorted(payload)):
                self.assertTrue(self._guard_result(payload))

        e4_task_id = stable_id("task", "bridge-canary", "node-canary")
        accepted = (
            {"task_id": e4_task_id},
            {"risk": {"ref_id": "risk-" + e4_task_id}},
            {"project_id": "project-" + uuid.uuid4().hex},
            {"execution_request_id": "exec-" + uuid.uuid4().hex},
            {"verification_plan_id": "verification-" + uuid.uuid4().hex},
            {"receipt_id": "receipt-" + uuid.uuid4().hex},
            {"token_count": 7, "secret_ref": "secret-ref-vault-abcdef"},
            {"credential_ref": "credential-opaque-vault-abcdef", "handle": "handle-ref-vault-abcdef"},
        )
        for payload in accepted:
            with self.subTest(payload_shape=sorted(payload)):
                self.assertFalse(self._guard_result(payload))

    def test_runtime_canary_rejection_has_no_persisted_secret_material(self):
        canary = "s" + "k-" + uuid.uuid4().hex
        command = self.command("runtime-canary", task_id=canary)
        with self.assertRaisesRegex(CommandRejected, "SECRET_VALUE_FORBIDDEN"):
            self.execution.prepare(command)
        with psycopg.connect(DATABASE_URL) as connection:
            for table in (
                "execution_requests", "execution_reservation_bindings",
                "execution_queue_items", "command_receipts", "event_log",
                "outbox_messages", "audit_records",
            ):
                found = connection.execute(
                    "SELECT EXISTS (SELECT 1 FROM " + table + " WHERE to_jsonb(" + table + ")::text LIKE %s)",
                    ("%" + canary + "%",),
                ).fetchone()[0]
                self.assertFalse(found, table + " persisted the runtime canary")

    def test_e4_derived_snapshot_passes_guard_and_real_execution_admission_continues(self):
        task_id = stable_id("task", "bridge-stage-a", "node-stage-a")
        risk_ref_id = "risk-" + task_id
        admission_snapshot = {
            "task_id": task_id,
            "risk": {"ref_id": risk_ref_id},
            "project_id": "project-" + uuid.uuid4().hex,
            "execution_request_id": "execution-" + uuid.uuid4().hex,
            "verification_plan_id": "verification-" + uuid.uuid4().hex,
        }
        self.assertFalse(self._guard_result(admission_snapshot))
        result = self.execution.prepare(self.command("e4-derived-guard"))
        self.assertEqual("QUEUED", result["request_state"])

    def test_success_prepares_request_binds_reservation_queues_event_outbox_receipt(self):
        result = self.execution.prepare(self.command())
        self.assertEqual("QUEUED", result["request_state"])
        self.assertEqual(1, result["request_version"])
        with psycopg.connect(DATABASE_URL) as connection:
            self.assertEqual(1, connection.execute("SELECT count(*) FROM execution_requests").fetchone()[0])
            self.assertEqual(1, connection.execute("SELECT count(*) FROM execution_reservation_bindings").fetchone()[0])
            self.assertEqual(1, connection.execute("SELECT count(*) FROM execution_queue_items").fetchone()[0])
            self.assertEqual(1, connection.execute(
                "SELECT count(*) FROM event_log WHERE event_type='execution.request_prepared'"
            ).fetchone()[0])
            self.assertEqual(1, connection.execute(
                "SELECT count(*) FROM event_log WHERE event_type='execution.queued'"
            ).fetchone()[0])
            self.assertEqual(2, connection.execute(
                """SELECT count(*) FROM outbox_messages
                   WHERE event_id IN (
                     SELECT event_id FROM event_log
                     WHERE event_type IN ('execution.request_prepared','execution.queued'))"""
            ).fetchone()[0])
            self.assertEqual(500, connection.execute(
                """SELECT reserved_amount FROM resource_balances
                   WHERE account_id='account-1' AND dimension='execution_time_ms'"""
            ).fetchone()[0])
            receipt = connection.execute(
                "SELECT status,result FROM command_receipts WHERE command_id='cmd-exec-1'"
            ).fetchone()
            self.assertEqual("APPLIED", receipt[0])
            self.assertEqual("EXECUTION_REQUEST_QUEUED", receipt[1]["result_code"])
        pending = self.execution.pending("project-1")
        self.assertEqual(1, len(pending))
        self.assertEqual(result["queue_item_id"], pending[0]["queue_item_id"])

    def test_idempotency_same_payload_returns_original_and_conflict_rejects(self):
        first = self.execution.prepare(self.command("idem"))
        second = self.execution.prepare(self.command("idem"))
        self.assertEqual(first["execution_request_id"], second["execution_request_id"])
        self.assertTrue(second["deduplicated"])
        with self.assertRaisesRegex(CommandRejected, "EXEC_ADMISSION_IDEMPOTENCY_CONFLICT"):
            self.execution.prepare(self.command(
                "idem-conflict",
                idempotency_key="key-exec-idem",
                priority=20,
            ))

    def test_fail_closed_rejections_do_not_create_request_or_queue(self):
        cases = (
            ("control", {"action_type": "pause"}, "EXEC_ADMISSION_ACTION_ROUTE_UNSUPPORTED"),
            ("task", {"expected_task_version": 9}, "EXEC_ADMISSION_VERSION_CONFLICT"),
            ("policy", {"policy_decision_id": "missing"}, "EXEC_ADMISSION_POLICY_NOT_ALLOW"),
            ("artifact", {"input_artifacts": (ArtifactInputRef("artifact-1", "task-1", "sha256:wrong"),)}, "EXEC_ADMISSION_ARTIFACT_MISMATCH"),
            ("context", {"context_manifest_hash": "sha256:wrong"}, "EXEC_ADMISSION_CONTEXT_FREEZE_FAILED"),
            ("sandbox", {"sandbox_profile_hash": "sha256:wrong"}, "EXEC_ADMISSION_SANDBOX_COMPILE_FAILED"),
            ("lock", {"lock_intents": (LockIntent("unknown:thing"),)}, "EXEC_ADMISSION_LOCK_CONFLICT"),
        )
        for suffix, overrides, code in cases:
            with self.subTest(suffix=suffix):
                self.store.reset_for_test()
                self.seed_fixture()
                with self.assertRaisesRegex(CommandRejected, code):
                    self.execution.prepare(self.command(suffix, **overrides))
                with psycopg.connect(DATABASE_URL) as connection:
                    self.assertEqual(0, connection.execute("SELECT count(*) FROM execution_requests").fetchone()[0])
                    self.assertEqual(0, connection.execute("SELECT count(*) FROM execution_queue_items").fetchone()[0])
                    self.assertEqual(0, connection.execute(
                        "SELECT count(*) FROM event_log WHERE event_type='execution.queued'"
                    ).fetchone()[0])

    def test_concurrent_prepare_same_reservation_only_one_success(self):
        results = []

        def run(index):
            try:
                result = ExecutionPreparation(PostgresExecutionStore(DATABASE_URL)).prepare(
                    self.command("race-" + str(index), idempotency_key="key-race-" + str(index))
                )
                results.append(("ok", result["execution_request_id"]))
            except Exception as exc:
                results.append(("err", str(exc)))

        threads = [threading.Thread(target=run, args=(idx,)) for idx in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(1, sum(item[0] == "ok" for item in results))
        with psycopg.connect(DATABASE_URL) as connection:
            self.assertEqual(1, connection.execute("SELECT count(*) FROM execution_requests").fetchone()[0])
            self.assertEqual(1, connection.execute("SELECT count(*) FROM execution_queue_items").fetchone()[0])

    def test_fault_injection_rolls_back_every_precommit_point_and_retry_succeeds(self):
        points = (
            ExecutionFaultPoint.AFTER_RECEIPT_PLACEHOLDER,
            ExecutionFaultPoint.AFTER_AUTHORITY_VALIDATION,
            ExecutionFaultPoint.AFTER_RESERVATION_BINDING,
            ExecutionFaultPoint.AFTER_REQUEST_WRITE,
            ExecutionFaultPoint.AFTER_QUEUE_ITEM,
            ExecutionFaultPoint.AFTER_EVENT_BEFORE_OUTBOX,
            ExecutionFaultPoint.AFTER_OUTBOX_BEFORE_RECEIPT,
            ExecutionFaultPoint.AFTER_RECEIPT_BEFORE_COMMIT,
        )
        for point in points:
            with self.subTest(point=point.value):
                self.store.reset_for_test()
                self.seed_fixture()
                faulted_store = PostgresExecutionStore(DATABASE_URL)
                faulted_store.fail_execution_once(point)
                with self.assertRaisesRegex(RuntimeError, "injected execution crash"):
                    ExecutionPreparation(faulted_store).prepare(self.command(point.value))
                with psycopg.connect(DATABASE_URL) as connection:
                    self.assertEqual(0, connection.execute("SELECT count(*) FROM execution_requests").fetchone()[0])
                    self.assertEqual(0, connection.execute("SELECT count(*) FROM execution_reservation_bindings").fetchone()[0])
                    self.assertEqual(0, connection.execute("SELECT count(*) FROM execution_queue_items").fetchone()[0])
                    self.assertEqual(0, connection.execute(
                        "SELECT count(*) FROM event_log WHERE command_id=%s",
                        ("cmd-exec-" + point.value,),
                    ).fetchone()[0])
                    self.assertEqual(500, connection.execute(
                        """SELECT reserved_amount FROM resource_balances
                           WHERE account_id='account-1' AND dimension='execution_time_ms'"""
                    ).fetchone()[0])
                retry = self.execution.prepare(self.command("retry-" + point.value))
                self.assertEqual("QUEUED", retry["request_state"])

    def test_queue_read_order_is_deterministic_without_claiming(self):
        first = self.execution.prepare(self.command("order1", priority=1))
        self.store.reset_for_test()
        self.seed_fixture("p2b")
        second = self.execution.prepare(self.command("order2", priority=50))
        pending = self.execution.pending("project-1")
        self.assertEqual([second["queue_item_id"]], [item["queue_item_id"] for item in pending])
        self.assertNotEqual(first["queue_item_id"], second["queue_item_id"])


if __name__ == "__main__":
    unittest.main()
