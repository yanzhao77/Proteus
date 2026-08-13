import hashlib
import json
from enum import Enum
from typing import Any, Mapping, Optional, Tuple

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from hermes_runtime.application.capabilities import (
    ChangeWorkerTemplateAvailability,
    CompileSandboxProfile,
    CreateContextBundle,
    CreateWorkerTemplateRevision,
    MatchCapabilityRequirements,
    RegisterCapabilitySchema,
)
from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.domain.capability import (
    AdmissionStatus,
    AuthorityRef,
    AvailabilityStatus,
    AvailableWorkerTemplate,
    CapabilityRejected,
    ContextSelector,
    SandboxCompileInput,
    WorkerTemplateRevision,
    build_context_bundle,
    compile_sandbox_profile,
    match_worker_template,
    normalize_capability_name,
    normalize_worker_template,
    worker_template_content_hash,
)
from hermes_runtime.infrastructure.postgres import PostgresRuntimeStore


class CapabilityFaultPoint(str, Enum):
    AFTER_RECEIPT_PLACEHOLDER = "after_receipt_placeholder"
    AFTER_AUTHORITY_BEFORE_EVENT = "after_authority_before_event"
    AFTER_EVENT_BEFORE_OUTBOX = "after_event_before_outbox"
    AFTER_OUTBOX_BEFORE_RECEIPT = "after_outbox_before_receipt"


class PostgresCapabilityStore(PostgresRuntimeStore):
    def __init__(self, dsn: str) -> None:
        super().__init__(dsn)
        self._fault: Optional[CapabilityFaultPoint] = None

    def fail_capability_once(self, point: CapabilityFaultPoint) -> None:
        self._fault = point

    def reset_for_test(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """TRUNCATE sandbox_profiles, context_bundle_items, context_bundles,
                   capability_match_records, worker_template_availability,
                   worker_template_capabilities, worker_template_revisions,
                   capability_schemas, decision_reservation_mappings,
                   selected_action_refs, action_score_dimensions, action_scores,
                   decision_candidate_dispositions, decision_records, selection_heads,
                   current_risk_assessments, risk_mitigations, risk_factors,
                   risk_assessments, current_policy_decisions, policy_constraints,
                   policy_decision_rules, policy_decisions, policy_evaluation_contexts,
                   current_planning_runs, candidate_action_resource_estimates,
                   candidate_action_expected_outputs, candidate_action_preconditions,
                   candidate_action_capabilities, candidate_action_targets,
                   candidate_actions, planning_runs, current_diagnoses,
                   diagnosis_evidence_requests, diagnosis_hypotheses,
                   diagnosis_evidence, diagnosis_findings, diagnoses,
                   situation_versions, situations, analysis_contexts,
                   delivery_operational_alerts, delivery_metric_counters,
                   local_transport_publications, consumer_quarantine,
                   consumer_pending_gaps, outbox_redrive_records,
                   outbox_delivery_dlq, outbox_delivery_attempts,
                   consumer_checkpoints, consumer_effects, consumer_inbox,
                   audit_records, outbox_messages, event_log,
                   event_partition_sequences, command_receipts,
                   resource_reconcile_records, resource_settlement_usage,
                   resource_settlements, resource_usage_amounts,
                   resource_usage_records, resource_reservation_amounts,
                   resource_reservations, resource_preparations,
                   resource_balances, resource_accounts, project_budget_facts,
                   project_policy_decision_facts, project_evidence_facts,
                   project_gate_decision_facts, project_transition_records,
                   feedback_records, task_dependencies, work_graph_edges,
                   project_graph_versions, verification_check_results,
                   verification_evidence, verification_results, evidence,
                   completion_claims, artifacts, verification_plan_checks,
                   verification_plans, agent_runs, verifier_identities, tasks,
                   projects RESTART IDENTITY CASCADE"""
            )

    def register_capability_schema(self, command: RegisterCapabilitySchema) -> Mapping[str, Any]:
        request_hash = self._request_hash("capability.register_schema", command)
        try:
            with self._connect(row_factory=dict_row) as connection:
                existing = self._begin_command(connection, command, request_hash, "capability.register_schema")
                if existing is not None:
                    return existing
                capability_name = normalize_capability_name(command.capability_name)
                content_hash = _hash_json({
                    "capability_name": capability_name,
                    "schema_version": command.schema_version,
                    "description": command.description,
                })
                result = self._apply(
                    connection,
                    "capability_schema",
                    {
                        "capability_name": capability_name,
                        "schema_version": command.schema_version,
                        "description": command.description,
                        "content_hash": content_hash,
                    },
                    command,
                    request_hash,
                    "capability.register_schema",
                )
                return self._complete(
                    connection, command, "CAPABILITY_SCHEMA_REGISTERED", result,
                    {
                        "capability_name": capability_name,
                        "schema_version": command.schema_version,
                        "content_hash": content_hash,
                    },
                )
        except CapabilityRejected as exc:
            self._reject(command, request_hash, "CAPABILITY_SCHEMA_REJECTED", str(exc), "capability.register_schema")
            raise CommandRejected(str(exc))
        except CommandRejected as exc:
            self._reject(command, request_hash, exc.code, exc.detail, "capability.register_schema")
            raise
        except psycopg.errors.RaiseException as exc:
            code = exc.diag.message_primary
            if code.startswith("INJECTED_CAPABILITY_CRASH_"):
                raise RuntimeError("injected capability crash: " + code)
            rejected = CommandRejected(code)
            self._reject(command, request_hash, rejected.code, rejected.detail, "capability.register_schema")
            raise rejected

    def create_worker_template_revision(self, command: CreateWorkerTemplateRevision) -> Mapping[str, Any]:
        request_hash = self._request_hash("capability.create_worker_template_revision", command)
        try:
            with self._connect(row_factory=dict_row) as connection:
                existing = self._begin_command(connection, command, request_hash, "capability.create_worker_template_revision")
                if existing is not None:
                    return existing
                normalized = normalize_worker_template(command.template)
                content_hash = worker_template_content_hash(command.template)
                result = self._apply(
                    connection,
                    "worker_template_revision",
                    {"template": normalized, "content_hash": content_hash},
                    command,
                    request_hash,
                    "capability.create_worker_template_revision",
                )
                return self._complete(
                    connection, command, "WORKER_TEMPLATE_REVISION_CREATED", result,
                    {
                        "template_id": command.template.template_id,
                        "revision": command.template.revision,
                        "content_hash": content_hash,
                        "availability_version": result["target_version"],
                    },
                )
        except CapabilityRejected as exc:
            self._reject(command, request_hash, str(exc), "", "capability.create_worker_template_revision")
            raise CommandRejected(str(exc))
        except CommandRejected as exc:
            self._reject(command, request_hash, exc.code, exc.detail, "capability.create_worker_template_revision")
            raise
        except psycopg.errors.RaiseException as exc:
            code = exc.diag.message_primary
            if code.startswith("INJECTED_CAPABILITY_CRASH_"):
                raise RuntimeError("injected capability crash: " + code)
            rejected = CommandRejected(code)
            self._reject(command, request_hash, rejected.code, rejected.detail, "capability.create_worker_template_revision")
            raise rejected

    def change_worker_template_availability(self, command: ChangeWorkerTemplateAvailability) -> Mapping[str, Any]:
        request_hash = self._request_hash("capability.change_worker_template_availability", command)
        try:
            AvailabilityStatus(command.availability_status)
            AdmissionStatus(command.admission_status)
            with self._connect(row_factory=dict_row) as connection:
                existing = self._begin_command(connection, command, request_hash, "capability.change_worker_template_availability")
                if existing is not None:
                    return existing
                result = self._apply(
                    connection,
                    "worker_template_availability",
                    {
                        "template_id": command.template_id,
                        "revision": command.revision,
                        "availability_status": command.availability_status,
                        "admission_status": command.admission_status,
                    },
                    command,
                    request_hash,
                    "capability.change_worker_template_availability",
                )
                return self._complete(
                    connection, command, "WORKER_TEMPLATE_AVAILABILITY_CHANGED", result,
                    {
                        "template_id": command.template_id,
                        "revision": command.revision,
                        "availability_status": command.availability_status,
                        "admission_status": command.admission_status,
                        "availability_version": result["target_version"],
                    },
                )
        except ValueError:
            self._reject(command, request_hash, "WORKER_TEMPLATE_AVAILABILITY_INVALID", "", "capability.change_worker_template_availability")
            raise CommandRejected("WORKER_TEMPLATE_AVAILABILITY_INVALID")
        except CommandRejected as exc:
            self._reject(command, request_hash, exc.code, exc.detail, "capability.change_worker_template_availability")
            raise
        except psycopg.errors.RaiseException as exc:
            code = exc.diag.message_primary
            if code.startswith("INJECTED_CAPABILITY_CRASH_"):
                raise RuntimeError("injected capability crash: " + code)
            rejected = CommandRejected(code)
            self._reject(command, request_hash, rejected.code, rejected.detail, "capability.change_worker_template_availability")
            raise rejected

    def match_capability_requirements(self, command: MatchCapabilityRequirements) -> Mapping[str, Any]:
        request_hash = self._request_hash("capability.match_requirements", command)
        try:
            with self._connect(row_factory=dict_row) as connection:
                existing = self._begin_command(connection, command, request_hash, "capability.match_requirements")
                if existing is not None:
                    return existing
                templates = self._load_templates(connection, command.project_id)
                known = tuple(row["capability_name"] for row in connection.execute(
                    "SELECT capability_name FROM public.capability_schemas"
                ).fetchall())
                result = match_worker_template(command.requirement, templates, known_capabilities=known)
                applied = self._apply(
                    connection,
                    "capability_match",
                    {
                        "match": result.__dict__,
                        "requirement": _canonical(command.requirement.__dict__),
                    },
                    command,
                    request_hash,
                    "capability.match_requirements",
                )
                return self._complete(
                    connection, command, "CAPABILITY_MATCH_RECORDED", applied,
                    dict(result.__dict__),
                )
        except CapabilityRejected as exc:
            self._reject(command, request_hash, str(exc), "", "capability.match_requirements")
            raise CommandRejected(str(exc))
        except CommandRejected as exc:
            self._reject(command, request_hash, exc.code, exc.detail, "capability.match_requirements")
            raise
        except psycopg.errors.RaiseException as exc:
            code = exc.diag.message_primary
            if code.startswith("INJECTED_CAPABILITY_CRASH_"):
                raise RuntimeError("injected capability crash: " + code)
            rejected = CommandRejected(code)
            self._reject(command, request_hash, rejected.code, rejected.detail, "capability.match_requirements")
            raise rejected

    def create_context_bundle(self, command: CreateContextBundle) -> Mapping[str, Any]:
        request_hash = self._request_hash("context.create_bundle", command)
        try:
            bundle = build_context_bundle(
                project_id=command.project_id,
                task_id=command.task_id,
                decision_id=command.decision_id,
                action_id=command.action_id,
                template_id=command.template_id,
                template_revision=command.template_revision,
                selectors=command.selectors,
                resolved_refs=command.resolved_refs,
                selector_schema_version=command.selector_schema_version,
                builder_version=command.builder_version,
            )
            with self._connect(row_factory=dict_row) as connection:
                existing = self._begin_command(connection, command, request_hash, "context.create_bundle")
                if existing is not None:
                    return existing
                applied = self._apply(
                    connection,
                    "context_bundle",
                    {
                        "bundle": {
                            "bundle_id": bundle.bundle_id,
                            "project_id": bundle.project_id,
                            "task_id": bundle.task_id,
                            "decision_id": bundle.decision_id,
                            "action_id": bundle.action_id,
                            "template_id": bundle.template_id,
                            "template_revision": bundle.template_revision,
                            "selector_schema_version": bundle.selector_schema_version,
                            "builder_version": bundle.builder_version,
                            "manifest": bundle.manifest,
                            "manifest_hash": bundle.manifest_hash,
                        },
                        "items": list(bundle.manifest["items"]),
                    },
                    command,
                    request_hash,
                    "context.create_bundle",
                )
                return self._complete(
                    connection, command, "CONTEXT_BUNDLE_CREATED", applied,
                    {
                        "bundle_id": bundle.bundle_id,
                        "manifest_hash": bundle.manifest_hash,
                        "selector_schema_version": bundle.selector_schema_version,
                        "builder_version": bundle.builder_version,
                    },
                )
        except CapabilityRejected as exc:
            self._reject(command, request_hash, str(exc), "", "context.create_bundle")
            raise CommandRejected(str(exc))
        except CommandRejected as exc:
            self._reject(command, request_hash, exc.code, exc.detail, "context.create_bundle")
            raise
        except psycopg.errors.RaiseException as exc:
            code = exc.diag.message_primary
            if code.startswith("INJECTED_CAPABILITY_CRASH_"):
                raise RuntimeError("injected capability crash: " + code)
            rejected = CommandRejected(code)
            self._reject(command, request_hash, rejected.code, rejected.detail, "context.create_bundle")
            raise rejected

    def compile_sandbox_profile(self, command: CompileSandboxProfile) -> Mapping[str, Any]:
        request_hash = self._request_hash("sandbox.compile_profile", command)
        try:
            profile = compile_sandbox_profile(command.compile_input)
            with self._connect(row_factory=dict_row) as connection:
                existing = self._begin_command(connection, command, request_hash, "sandbox.compile_profile")
                if existing is not None:
                    return existing
                applied = self._apply(
                    connection,
                    "sandbox_profile",
                    {
                        "profile": {
                            "profile_id": profile.profile_id,
                            "project_id": profile.project_id,
                            "task_id": profile.task_id,
                            "action_id": profile.action_id,
                            "template_id": profile.template_id,
                            "template_revision": profile.template_revision,
                            "context_bundle_hash": profile.context_bundle_hash,
                            "compiler_version": profile.compiler_version,
                            "target": profile.target,
                            "profile": profile.profile,
                            "profile_hash": profile.profile_hash,
                            "constraints_hash": profile.constraints_hash,
                        }
                    },
                    command,
                    request_hash,
                    "sandbox.compile_profile",
                )
                return self._complete(
                    connection, command, "SANDBOX_PROFILE_COMPILED", applied,
                    {
                        "profile_id": profile.profile_id,
                        "profile_hash": profile.profile_hash,
                        "constraints_hash": profile.constraints_hash,
                        "compiler_version": profile.compiler_version,
                        "target": profile.target,
                    },
                )
        except CapabilityRejected as exc:
            self._reject(command, request_hash, str(exc), "", "sandbox.compile_profile")
            raise CommandRejected(str(exc))
        except CommandRejected as exc:
            self._reject(command, request_hash, exc.code, exc.detail, "sandbox.compile_profile")
            raise
        except psycopg.errors.RaiseException as exc:
            code = exc.diag.message_primary
            if code.startswith("INJECTED_CAPABILITY_CRASH_"):
                raise RuntimeError("injected capability crash: " + code)
            rejected = CommandRejected(code)
            self._reject(command, request_hash, rejected.code, rejected.detail, "sandbox.compile_profile")
            raise rejected

    def _apply(self, connection, fact_type, payload, command, request_hash, command_type):
        fault = self._fault
        self._fault = None
        function_name = {
            "capability_schema": "hermes_register_capability_schema",
            "worker_template_revision": "hermes_create_worker_template_revision",
            "worker_template_availability": "hermes_change_worker_template_availability",
            "capability_match": "hermes_record_capability_match",
            "context_bundle": "hermes_create_context_bundle",
            "sandbox_profile": "hermes_compile_sandbox_profile",
        }[fact_type]
        return connection.execute(
            """SELECT public.{}(
               %s,%s,%s,%s,%s,%s,%s,%s,%s,%s
               ) AS result""".format(function_name),
            (
                Jsonb(payload),
                command.project_id,
                getattr(command, "expected_version", 0),
                command.command_id,
                command.idempotency_key,
                request_hash,
                command_type,
                command.actor_type,
                command.actor_id,
                fault.value if fault else None,
            ),
        ).fetchone()["result"]

    def _complete(self, connection, command, result_code, applied, response):
        final_response = dict(response)
        final_response["event_id"] = applied.get("event_id")
        final_response["deduplicated"] = applied.get("deduplicated", False)
        receipt = {
            "command_id": command.command_id,
            "status": "APPLIED",
            "result_code": result_code,
            "target_version": applied.get("target_version"),
            "event_ids": [applied["event_id"]] if applied.get("event_id") else [],
            "response": final_response,
        }
        connection.execute(
            """UPDATE command_receipts SET status='APPLIED',
               result=%s, completed_at=now()
               WHERE command_id=%s AND status='PROCESSING'""",
            (Jsonb(receipt), command.command_id),
        )
        return final_response

    def _begin_command(self, connection, command, request_hash, command_type):
        inserted = connection.execute(
            """INSERT INTO command_receipts(
               command_id, project_id, command_type, idempotency_key,
               request_hash, status, result)
               VALUES (%s,%s,%s,%s,%s,'PROCESSING','{}'::jsonb)
               ON CONFLICT DO NOTHING RETURNING command_id""",
            (command.command_id, command.project_id, command_type, command.idempotency_key, request_hash),
        ).fetchone()
        if inserted:
            return None
        row = connection.execute(
            """SELECT request_hash,status,result FROM command_receipts
               WHERE project_id=%s AND command_type=%s AND idempotency_key=%s
               FOR UPDATE""",
            (command.project_id, command_type, command.idempotency_key),
        ).fetchone()
        if not row or row["request_hash"] != request_hash:
            raise CommandRejected("CAPABILITY_IDEMPOTENCY_CONFLICT")
        if row["status"] == "APPLIED":
            return dict(row["result"]["response"])
        if row["status"] == "REJECTED":
            raise CommandRejected(row["result"]["result_code"], row["result"].get("detail", ""))
        raise CommandRejected("COMMAND_IN_PROGRESS")

    def _reject(self, command, request_hash, code, detail, command_type):
        sanitized = _sanitize_detail(detail)
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO command_receipts(
                   command_id,project_id,command_type,idempotency_key,
                   request_hash,status,result,completed_at)
                   VALUES (%s,%s,%s,%s,%s,'REJECTED',%s,now())
                   ON CONFLICT DO NOTHING""",
                (
                    command.command_id, command.project_id, command_type,
                    command.idempotency_key, request_hash,
                    Jsonb({"result_code": code, "detail": sanitized}),
                ),
            )

    def _load_templates(self, connection, project_id: str) -> Tuple[AvailableWorkerTemplate, ...]:
        rows = connection.execute(
            """SELECT w.*, a.availability_status, a.admission_status,
                     a.availability_version
                 FROM public.worker_template_revisions w
                 JOIN public.worker_template_availability a
                   ON a.template_id=w.template_id AND a.revision=w.revision
                WHERE w.project_id IS NULL OR w.project_id=%s
             ORDER BY w.template_id,w.revision""",
            (project_id,),
        ).fetchall()
        templates = []
        for row in rows:
            templates.append(AvailableWorkerTemplate(
                WorkerTemplateRevision(
                    template_id=row["template_id"],
                    revision=int(row["revision"]),
                    project_id=row["project_id"],
                    runtime_kind=row["runtime_kind"],
                    capabilities=tuple(row["capabilities"] or ()),
                    trust_level=row["trust_level"],
                    allowed_tools=tuple(row["allowed_tools"] or ()),
                    supported_sandbox_features=tuple(row["supported_sandbox_features"] or ()),
                    resource_envelope=dict(row["resource_envelope"] or {}),
                    constraint_ranges=dict(row["constraint_ranges"] or {}),
                    concurrency_capacity=int(row["concurrency_capacity"]),
                    content_hash=row["content_hash"],
                ),
                availability_status=row["availability_status"],
                admission_status=row["admission_status"],
                availability_version=int(row["availability_version"]),
            ))
        return tuple(templates)

    @staticmethod
    def _request_hash(command_type: str, command) -> str:
        value = dict(command.__dict__)
        for key, item in list(value.items()):
            if hasattr(item, "__dict__"):
                value[key] = _canonical(item.__dict__)
            elif isinstance(item, tuple):
                value[key] = [
                    _canonical(child.__dict__) if hasattr(child, "__dict__") else child
                    for child in item
                ]
        value["command_type"] = command_type
        return _hash_json(value)


def _hash_json(value) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(_canonical(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def _canonical(value) -> Any:
    return json.loads(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str))


def _sanitize_detail(value: str) -> str:
    text = str(value or "")
    if any(marker in text.lower() for marker in ("secret", "token", "password", "credential", "private key", "sk-")):
        return "<redacted>"
    return text
