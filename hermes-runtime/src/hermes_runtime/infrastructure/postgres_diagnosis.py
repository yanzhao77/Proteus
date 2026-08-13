import hashlib
import json
from enum import Enum
from typing import Any, Mapping, Optional, Tuple

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from hermes_runtime.application.diagnoses import RunDiagnosis
from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.domain.diagnosis import (
    RULE_SET_VERSION,
    CanonicalFinding,
    DiagnosisInput,
    EvidenceRelation,
    EvidenceSummary,
    diagnosis_id_for,
    diagnose,
)
from hermes_runtime.infrastructure.postgres import PostgresRuntimeStore


class DiagnosisFaultPoint(str, Enum):
    AFTER_DIAGNOSIS_BEFORE_EVIDENCE = "after_diagnosis_before_evidence"
    AFTER_EVIDENCE_BEFORE_HYPOTHESIS = "after_evidence_before_hypothesis"
    AFTER_HYPOTHESIS_BEFORE_EVIDENCE_REQUEST = "after_hypothesis_before_evidence_request"
    AFTER_EVIDENCE_REQUEST_BEFORE_EVENT = "after_evidence_request_before_event"
    AFTER_CURRENT_BEFORE_EVENT = "after_current_before_event"
    AFTER_EVENT_BEFORE_OUTBOX = "after_event_before_outbox"
    AFTER_OUTBOX_BEFORE_RECEIPT = "after_outbox_before_receipt"


class PostgresDiagnosisStore(PostgresRuntimeStore):
    def __init__(self, dsn: str) -> None:
        super().__init__(dsn)
        self._diagnosis_fault: Optional[DiagnosisFaultPoint] = None

    def fail_diagnosis_once(self, point: DiagnosisFaultPoint) -> None:
        self._diagnosis_fault = point

    def reset_for_test(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """TRUNCATE current_diagnoses, diagnosis_evidence_requests,
                   diagnosis_hypotheses, diagnosis_evidence, diagnosis_findings,
                   diagnoses, situation_versions, situations, analysis_contexts,
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
                   resource_balances, resource_accounts,
                   project_budget_facts, project_policy_decision_facts,
                   project_evidence_facts, project_gate_decision_facts,
                   project_transition_records, feedback_records,
                   task_dependencies, work_graph_edges, project_graph_versions,
                   verification_check_results, verification_evidence,
                   verification_results, evidence, completion_claims, artifacts,
                   verification_plan_checks, verification_plans, agent_runs,
                   verifier_identities, tasks, projects
                   RESTART IDENTITY CASCADE"""
            )

    def run_diagnosis(self, command: RunDiagnosis) -> Mapping[str, Any]:
        request_hash = self._request_hash(command)
        try:
            with self._connect(row_factory=dict_row) as connection:
                existing = self._begin_diagnosis_command(
                    connection, command, request_hash
                )
                if existing is not None:
                    return existing
                inputs = self._load_inputs(connection, command)
                result = diagnose(inputs)
                diagnosis_id = diagnosis_id_for(inputs, result)
                fault = self._diagnosis_fault
                self._diagnosis_fault = None
                payload = self._apply(
                    connection,
                    command,
                    inputs,
                    result,
                    diagnosis_id,
                    fault.value if fault else None,
                )
                receipt = {
                    "command_id": command.command_id,
                    "status": "APPLIED",
                    "result_code": "DIAGNOSIS_COMPLETED",
                    "target_version": command.situation_version,
                    "event_ids": [payload["event_id"]] if payload.get("event_id") else [],
                    "response": payload,
                }
                connection.execute(
                    """UPDATE command_receipts SET status='APPLIED',
                       result=%s, completed_at=now()
                       WHERE command_id=%s AND status='PROCESSING'""",
                    (Jsonb(receipt), command.command_id),
                )
                return payload
        except CommandRejected as exc:
            self._persist_rejection(command, request_hash, exc.code, exc.detail)
            raise
        except psycopg.errors.RaiseException as exc:
            code = exc.diag.message_primary
            if code.startswith("INJECTED_DIAGNOSIS_CRASH_"):
                raise RuntimeError("injected diagnosis crash: " + code)
            rejected = CommandRejected(code)
            self._persist_rejection(command, request_hash, rejected.code, rejected.detail)
            raise rejected

    def _begin_diagnosis_command(self, connection, command, request_hash):
        inserted = connection.execute(
            """INSERT INTO command_receipts(
               command_id, project_id, command_type, idempotency_key,
               request_hash, status, result)
               VALUES (%s,%s,'diagnosis.run',%s,%s,'PROCESSING','{}'::jsonb)
               ON CONFLICT DO NOTHING RETURNING command_id""",
            (command.command_id, command.project_id, command.idempotency_key,
             request_hash),
        ).fetchone()
        if inserted:
            return None
        row = connection.execute(
            """SELECT request_hash,status,result FROM command_receipts
               WHERE project_id=%s AND command_type='diagnosis.run'
                 AND idempotency_key=%s FOR UPDATE""",
            (command.project_id, command.idempotency_key),
        ).fetchone()
        if not row:
            raise CommandRejected("DIAGNOSIS_IDEMPOTENCY_CONFLICT")
        if row["request_hash"] != request_hash:
            raise CommandRejected("DIAGNOSIS_IDEMPOTENCY_CONFLICT")
        if row["status"] == "APPLIED":
            return dict(row["result"]["response"])
        if row["status"] == "REJECTED":
            result = row["result"]
            raise CommandRejected(result["result_code"], result.get("detail", ""))
        raise CommandRejected("COMMAND_IN_PROGRESS")

    def _load_inputs(self, connection, command: RunDiagnosis) -> DiagnosisInput:
        situation = connection.execute(
            """SELECT * FROM situations
               WHERE situation_id=%s AND project_id=%s""",
            (command.situation_id, command.project_id),
        ).fetchone()
        if not situation:
            raise CommandRejected("DIAGNOSIS_SITUATION_NOT_FOUND")
        if situation["status"] != "OPEN":
            raise CommandRejected("DIAGNOSIS_SITUATION_NOT_OPEN")
        if int(situation["version"]) != command.situation_version:
            raise CommandRejected("DIAGNOSIS_SITUATION_VERSION_CONFLICT")
        if situation["analysis_context_id"] != command.analysis_context_id:
            raise CommandRejected("DIAGNOSIS_CONTEXT_NOT_FOUND")

        context = connection.execute(
            """SELECT * FROM analysis_contexts
               WHERE analysis_context_id=%s AND project_id=%s""",
            (command.analysis_context_id, command.project_id),
        ).fetchone()
        if not context:
            raise CommandRejected("DIAGNOSIS_CONTEXT_NOT_FOUND")
        if context["context_hash"] != command.analysis_context_hash:
            raise CommandRejected("DIAGNOSIS_CONTEXT_HASH_MISMATCH")
        if int(context["observed_at_sequence"]) != int(situation["observed_at_sequence"]):
            raise CommandRejected("DIAGNOSIS_INPUT_STALE")

        verification_ids = tuple(context["verification_refs"] or ())
        findings = self._load_findings(connection, context, situation, verification_ids)
        evidence = self._load_evidence(connection, context, situation, findings)
        history_refs = self._load_history_refs(connection, situation, findings)
        return DiagnosisInput(
            command.project_id,
            command.situation_id,
            command.situation_version,
            command.analysis_context_id,
            command.analysis_context_hash,
            int(context["observed_at_sequence"]),
            situation["failure_type"],
            tuple(situation["affected_components"] or ()),
            findings,
            evidence,
            history_refs,
            command.rule_set_version,
        )

    def _load_findings(self, connection, context, situation, verification_ids):
        rows = []
        if verification_ids:
            rows = connection.execute(
                """SELECT v.verification_id, v.task_id, v.artifact_id,
                          v.artifact_hash, v.correlation_id, c.check_id,
                          c.status, c.finding_codes, c.evidence_refs
                   FROM verification_results v
                   JOIN verification_check_results c
                     ON c.verification_id = v.verification_id
                   JOIN event_log e ON e.command_id = v.command_id
                   WHERE v.verification_id = ANY(%s)
                     AND v.project_id = %s
                     AND e.sequence <= %s
                   ORDER BY v.verification_id, c.check_id""",
                (list(verification_ids), context["project_id"],
                 context["observed_at_sequence"]),
            ).fetchall()
        findings = []
        for row in rows:
            if row["task_id"] != situation["task_id"]:
                raise CommandRejected("DIAGNOSIS_EVIDENCE_TASK_MISMATCH")
            for code in row["finding_codes"] or ():
                findings.append(CanonicalFinding(
                    str(code),
                    "verification_check",
                    "HIGH" if row["status"] == "FAIL" else "MEDIUM",
                    row["task_id"],
                    row["artifact_id"],
                    row["artifact_hash"],
                    _first(situation["affected_components"]),
                    row["verification_id"],
                    row["check_id"],
                    tuple(str(item) for item in (row["evidence_refs"] or ())),
                    row["correlation_id"],
                ))
        if findings:
            return tuple(findings)
        if situation["failure_type"]:
            return (CanonicalFinding(
                str(situation["failure_type"]),
                "situation_failure_type",
                situation["severity"],
                situation["task_id"],
                _first(situation["affected_artifact_refs"]),
                None,
                _first(situation["affected_components"]),
                _first(verification_ids),
                None,
                tuple(context["evidence_refs"] or ()),
                None,
            ),)
        return ()

    def _load_evidence(self, connection, context, situation, findings):
        refs = sorted({
            ref
            for finding in findings
            for ref in finding.evidence_refs
        } | set(context["evidence_refs"] or ()))
        if not refs:
            return ()
        rows = connection.execute(
            """SELECT e.evidence_id, e.artifact_id, e.artifact_hash,
                      e.producer_identity, e.valid, e.observed_at_sequence,
                      e.invalidated_at, a.task_id, t.project_id,
                      bool_or(ve.verification_id = ANY(%s)) AS in_context_verification
               FROM evidence e
               JOIN artifacts a ON a.artifact_id = e.artifact_id
               JOIN tasks t ON t.task_id = a.task_id
               LEFT JOIN verification_evidence ve ON ve.evidence_id = e.evidence_id
               WHERE e.evidence_id = ANY(%s)
               GROUP BY e.evidence_id, e.artifact_id, e.artifact_hash,
                        e.producer_identity, e.valid, e.observed_at_sequence,
                        e.invalidated_at, a.task_id, t.project_id
               ORDER BY e.evidence_id""",
            (list(context["verification_refs"] or ()), refs),
        ).fetchall()
        found = {row["evidence_id"]: row for row in rows}
        for ref in refs:
            if ref not in found:
                if ref in set(context["verification_refs"] or ()):
                    continue
                raise CommandRejected("DIAGNOSIS_EVIDENCE_NOT_FOUND")
        evidence = []
        expected_artifacts = {
            item for item in (situation["affected_artifact_refs"] or ()) if item
        }
        for row in rows:
            if row["project_id"] != context["project_id"]:
                raise CommandRejected("DIAGNOSIS_EVIDENCE_PROJECT_MISMATCH")
            if situation["task_id"] and row["task_id"] != situation["task_id"]:
                raise CommandRejected("DIAGNOSIS_EVIDENCE_TASK_MISMATCH")
            if int(row["observed_at_sequence"] or 0) > int(context["observed_at_sequence"]):
                raise CommandRejected("DIAGNOSIS_CONTEXT_FUTURE_FACT")
            if row["invalidated_at"] is not None or not bool(row["valid"]):
                raise CommandRejected("DIAGNOSIS_EVIDENCE_INVALID")
            if not row["in_context_verification"]:
                raise CommandRejected("DIAGNOSIS_EVIDENCE_INVALID")
            if _looks_like_worker(row["producer_identity"]):
                raise CommandRejected("DIAGNOSIS_EVIDENCE_INVALID")
            if expected_artifacts and row["artifact_id"] not in expected_artifacts:
                raise CommandRejected("DIAGNOSIS_EVIDENCE_ARTIFACT_MISMATCH")
            finding_hashes = {
                item.artifact_hash for item in findings
                if item.artifact_hash and row["evidence_id"] in item.evidence_refs
            }
            if finding_hashes and row["artifact_hash"] not in finding_hashes:
                raise CommandRejected("DIAGNOSIS_EVIDENCE_ARTIFACT_MISMATCH")
            relation = EvidenceRelation.CONTRADICTING if (
                str(row["evidence_id"]).endswith("-contradict")
                or str(row["evidence_id"]).endswith("-contradicting")
            ) else EvidenceRelation.SUPPORTING
            evidence.append(EvidenceSummary(
                row["evidence_id"],
                row["artifact_id"],
                row["artifact_hash"],
                row["producer_identity"],
                bool(row["valid"]),
                relation,
                "CONTRADICTS_FINDING" if relation is EvidenceRelation.CONTRADICTING
                else "DIRECT_VERIFICATION_EVIDENCE",
            ))
        return tuple(evidence)

    def _load_history_refs(self, connection, situation, findings):
        codes = sorted({item.finding_code for item in findings})
        if not codes:
            return ()
        rows = connection.execute(
            """SELECT d.diagnosis_id
               FROM diagnoses d
               JOIN diagnosis_findings f ON f.diagnosis_id = d.diagnosis_id
               WHERE d.project_id = %s
                 AND d.situation_id <> %s
                 AND f.finding_code = ANY(%s)
                 AND d.observed_at_sequence <= %s
               ORDER BY d.created_at DESC, d.diagnosis_id
               LIMIT 10""",
            (situation["project_id"], situation["situation_id"], codes,
             situation["observed_at_sequence"]),
        ).fetchall()
        return tuple(row["diagnosis_id"] for row in rows)

    def _apply(self, connection, command, inputs, result, diagnosis_id, fault):
        row = connection.execute(
            """SELECT public.hermes_apply_diagnosis(
               %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
               %s,%s,%s,%s,%s,%s,%s,%s) AS result""",
            (
                diagnosis_id,
                inputs.project_id,
                inputs.situation_id,
                inputs.situation_version,
                inputs.analysis_context_id,
                inputs.analysis_context_hash,
                inputs.rule_set_version,
                result.input_hash,
                result.root_cause_status.value,
                result.root_cause,
                result.confidence_basis_points,
                result.diagnostic_method,
                list(result.matched_rule_ids),
                Jsonb(self._findings_payload(result.findings)),
                Jsonb(self._evidence_payload(result.evidence)),
                Jsonb(self._hypotheses_payload(result.hypotheses)),
                Jsonb(self._evidence_requests_payload(result.evidence_requests)),
                command.command_id,
                command.actor_type,
                command.actor_id,
                fault,
            ),
        ).fetchone()
        return dict(row["result"])

    @staticmethod
    def _findings_payload(findings):
        return [
            {
                "finding_code": item.finding_code,
                "finding_type": item.finding_type,
                "severity": item.severity,
                "task_id": item.task_id,
                "artifact_id": item.artifact_id,
                "artifact_hash": item.artifact_hash,
                "component": item.component,
                "source_verification_id": item.source_verification_id,
                "source_check_id": item.source_check_id,
                "evidence_refs": list(item.evidence_refs),
                "trace_id": item.trace_id,
                "ordinal": ordinal,
            }
            for ordinal, item in enumerate(findings)
        ]

    @staticmethod
    def _evidence_payload(evidence):
        return [
            {
                "evidence_id": item.evidence_id,
                "relation": item.relation.value,
                "reason_code": item.reason_code,
            }
            for item in evidence
        ]

    @staticmethod
    def _hypotheses_payload(hypotheses):
        return [
            {
                "description_code": item.description_code,
                "confidence_basis_points": item.confidence_basis_points,
                "test_action_hint": item.test_action_hint,
                "ordinal": item.ordinal,
            }
            for item in hypotheses
        ]

    @staticmethod
    def _evidence_requests_payload(requests):
        return [
            {
                "request_code": item.request_code,
                "evidence_kind": item.evidence_kind,
                "target_ref": item.target_ref,
                "reason_code": item.reason_code,
                "priority": item.priority,
            }
            for item in requests
        ]

    def _persist_rejection(self, command, request_hash: str, code: str, detail: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO command_receipts(
                   command_id,project_id,command_type,idempotency_key,
                   request_hash,status,result,completed_at)
                   VALUES (%s,%s,'diagnosis.run',%s,%s,'REJECTED',%s,now())
                   ON CONFLICT DO NOTHING""",
                (command.command_id, command.project_id, command.idempotency_key,
                 request_hash, Jsonb({"result_code": code, "detail": detail})),
            )
            try:
                connection.execute(
                    """INSERT INTO audit_records(
                       audit_id, project_id, source_command_id, actor_type, actor_id,
                       action, outcome, reason_code, detail)
                       VALUES (%s,%s,%s,%s,%s,'diagnosis.run','REJECTED',%s,%s)
                       ON CONFLICT (source_command_id, reason_code) DO NOTHING""",
                    ("audit-" + _hash_value({
                        "command_id": command.command_id, "code": code
                    })[:32], command.project_id, command.command_id,
                     command.actor_type, command.actor_id, code, detail),
                )
            except psycopg.errors.InsufficientPrivilege:
                # Low-privilege runtime roles may record their CommandReceipt but
                # cannot write audit_records directly. Preserve the original
                # stable rejection code instead of masking it with a permission
                # error; DB authority functions still enforce the hard boundary.
                pass

    @staticmethod
    def _request_hash(command: RunDiagnosis) -> str:
        return _hash_value({
            "command_type": "diagnosis.run",
            "project_id": command.project_id,
            "situation_id": command.situation_id,
            "situation_version": command.situation_version,
            "analysis_context_id": command.analysis_context_id,
            "analysis_context_hash": command.analysis_context_hash,
            "rule_set_version": command.rule_set_version,
            "actor_type": command.actor_type,
            "actor_id": command.actor_id,
        })


def _first(values) -> Optional[str]:
    if not values:
        return None
    return sorted(str(item) for item in values if item)[0]


def _looks_like_worker(value: str) -> bool:
    lowered = str(value).lower()
    return lowered == "worker" or lowered.startswith("worker-")


def _hash_value(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=True).encode("utf-8")
    ).hexdigest()
