import hashlib
import json
from enum import Enum
from typing import Any, Mapping, Optional

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.application.selections import SelectActions
from hermes_runtime.domain.selection import (
    CONFLICT_RULE_VERSION,
    NORMALIZER_VERSION,
    WEIGHTS,
    AccountSnapshot,
    CandidateInput,
    SelectionRejected,
    select_actions,
)
from hermes_runtime.infrastructure.postgres import PostgresRuntimeStore


class SelectionFaultPoint(str, Enum):
    AFTER_RECEIPT_PLACEHOLDER = "after_receipt_placeholder"
    AFTER_SCORE_DISPOSITION = "after_score_disposition"
    AFTER_FIRST_RESERVATION_BEFORE_SECOND = "after_first_reservation_before_second"
    AFTER_ALL_RESERVATIONS_BEFORE_DECISION = "after_all_reservations_before_decision"
    AFTER_DECISION_BEFORE_EVENT = "after_decision_before_event"
    AFTER_EVENT_BEFORE_OUTBOX = "after_event_before_outbox"
    AFTER_OUTBOX_BEFORE_RECEIPT = "after_outbox_before_receipt"


class PostgresSelectionStore(PostgresRuntimeStore):
    def __init__(self, dsn: str) -> None:
        super().__init__(dsn)
        self._selection_fault: Optional[SelectionFaultPoint] = None

    def fail_selection_once(self, point: SelectionFaultPoint) -> None:
        self._selection_fault = point

    def reset_for_test(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """TRUNCATE decision_reservation_mappings, selected_action_refs,
                   action_score_dimensions, action_scores,
                   decision_candidate_dispositions, decision_records,
                   selection_heads, current_risk_assessments, risk_mitigations,
                   risk_factors, risk_assessments, current_policy_decisions,
                   policy_constraints, policy_decision_rules, policy_decisions,
                   policy_evaluation_contexts, current_planning_runs,
                   candidate_action_resource_estimates,
                   candidate_action_expected_outputs,
                   candidate_action_preconditions,
                   candidate_action_capabilities,
                   candidate_action_targets, candidate_actions, planning_runs,
                   current_diagnoses, diagnosis_evidence_requests,
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

    def select_actions(self, command: SelectActions) -> Mapping[str, Any]:
        request_hash = self._request_hash(command)
        try:
            with self._connect(row_factory=dict_row) as connection:
                existing = self._begin_command(connection, command, request_hash)
                if existing is not None:
                    return existing
                converged = self._try_return_active_equivalent(
                    connection, command, request_hash
                )
                if converged is not None:
                    return converged
                run_row = self._load_planning_run(connection, command)
                candidates = self._load_candidates(connection, command)
                result = select_actions(
                    project_id=command.project_id,
                    situation_id=run_row["situation_id"],
                    situation_version=int(run_row["situation_version"]),
                    planning_run_id=command.planning_run_id,
                    planner_input_hash=run_row["input_hash"],
                    selection_version=command.expected_selection_version + 1,
                    expected_selection_version=command.expected_selection_version,
                    candidates=candidates,
                    weight_profile_id=command.weight_profile_id,
                )
                payloads = self._payloads(result, candidates, run_row, command)
                fault = self._selection_fault
                self._selection_fault = None
                applied = connection.execute(
                    """SELECT public.hermes_apply_selection_decision(
                       %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                       ) AS result""",
                    (
                        Jsonb(payloads["decision"]),
                        Jsonb(payloads["dispositions"]),
                        Jsonb(payloads["scores"]),
                        Jsonb(payloads["score_dimensions"]),
                        Jsonb(payloads["selected_refs"]),
                        Jsonb(payloads["reservation_mappings"]),
                        Jsonb(payloads["account_snapshots"]),
                        command.project_id,
                        command.planning_run_id,
                        command.expected_situation_version,
                        command.expected_selection_version,
                        command.weight_profile_id,
                        command.command_id,
                        command.actor_type,
                        command.actor_id,
                        fault.value if fault else None,
                    ),
                ).fetchone()["result"]
                response = {
                    "decision_id": applied["decision_id"],
                    "selection_version": applied["selection_version"],
                    "input_snapshot_hash": applied["input_snapshot_hash"],
                    "selected_action_ids": list(result.selected_action_ids),
                    "eligible_action_ids": list(result.eligible_action_ids),
                    "decision_reason_codes": list(result.decision_reason_codes),
                    "reservation_ids": [
                        item["reservation_id"] for item in payloads["reservation_mappings"]
                    ],
                    "event_id": applied.get("event_id"),
                    "deduplicated": applied.get("deduplicated", False),
                }
                receipt = {
                    "command_id": command.command_id,
                    "status": "APPLIED",
                    "result_code": "ACTIONS_SELECTED",
                    "target_version": response["selection_version"],
                    "event_ids": [applied["event_id"]] if applied.get("event_id") else [],
                    "response": response,
                }
                connection.execute(
                    """UPDATE command_receipts SET status='APPLIED',
                       result=%s, completed_at=now()
                       WHERE command_id=%s AND status='PROCESSING'""",
                    (Jsonb(receipt), command.command_id),
                )
                return response
        except SelectionRejected as exc:
            rejected = CommandRejected(str(exc))
            self._persist_rejection(command, request_hash, rejected.code, rejected.detail)
            raise rejected
        except CommandRejected as exc:
            self._persist_rejection(command, request_hash, exc.code, exc.detail)
            raise
        except psycopg.errors.RaiseException as exc:
            code = exc.diag.message_primary
            if code.startswith("INJECTED_SELECTION_CRASH_"):
                raise RuntimeError("injected selection crash: " + code)
            rejected = CommandRejected(code)
            self._persist_rejection(command, request_hash, rejected.code, rejected.detail)
            raise rejected

    def _begin_command(self, connection, command, request_hash):
        inserted = connection.execute(
            """INSERT INTO command_receipts(
               command_id, project_id, command_type, idempotency_key,
               request_hash, status, result)
               VALUES (%s,%s,'selection.select_actions',%s,%s,'PROCESSING','{}'::jsonb)
               ON CONFLICT DO NOTHING RETURNING command_id""",
            (command.command_id, command.project_id, command.idempotency_key, request_hash),
        ).fetchone()
        if inserted:
            return None
        row = connection.execute(
            """SELECT request_hash,status,result FROM command_receipts
               WHERE project_id=%s AND command_type='selection.select_actions'
                 AND idempotency_key=%s FOR UPDATE""",
            (command.project_id, command.idempotency_key),
        ).fetchone()
        if not row or row["request_hash"] != request_hash:
            raise CommandRejected("SELECTION_IDEMPOTENCY_CONFLICT")
        if row["status"] == "APPLIED":
            return dict(row["result"]["response"])
        raise CommandRejected("COMMAND_IN_PROGRESS")

    def _load_planning_run(self, connection, command):
        row = connection.execute(
            """SELECT pr.* FROM planning_runs pr
               JOIN current_planning_runs cpr
                 ON cpr.planning_run_id = pr.planning_run_id
              WHERE pr.planning_run_id=%s AND pr.project_id=%s""",
            (command.planning_run_id, command.project_id),
        ).fetchone()
        if not row:
            raise CommandRejected("SELECTION_PLANNING_RUN_NOT_CURRENT")
        if int(row["situation_version"]) != command.expected_situation_version:
            raise CommandRejected("SELECTION_CONTEXT_STALE")
        return row

    @staticmethod
    def _current_selection_version(connection, planning_run_id):
        row = connection.execute(
            "SELECT selection_version FROM selection_heads WHERE planning_run_id=%s",
            (planning_run_id,),
        ).fetchone()
        return int(row["selection_version"]) if row else 0

    def _try_return_active_equivalent(self, connection, command, request_hash):
        head = connection.execute(
            """SELECT current_decision_id,selection_version,active_reservation_count
               FROM selection_heads WHERE planning_run_id=%s""",
            (command.planning_run_id,),
        ).fetchone()
        if not head or not head["current_decision_id"]:
            return None
        if int(head["selection_version"]) <= command.expected_selection_version:
            return None
        if int(head["active_reservation_count"]) <= 0:
            return None
        bindings = {
            item.action_id: (item.account_id, item.expected_account_version)
            for item in command.candidate_account_bindings
        }
        rows = connection.execute(
            """SELECT d.action_id,d.resource_account_id,m.account_id,
                      r.command_id, cr.result
                 FROM decision_candidate_dispositions d
            LEFT JOIN decision_reservation_mappings m
                   ON m.decision_id=d.decision_id AND m.action_id=d.action_id
            LEFT JOIN resource_reservations r
                   ON r.reservation_id=m.reservation_id
            LEFT JOIN command_receipts cr ON cr.command_id=r.command_id
                WHERE d.decision_id=%s""",
            (head["current_decision_id"],),
        ).fetchall()
        for row in rows:
            if row["resource_account_id"] is None:
                continue
            expected = bindings.get(row["action_id"])
            if expected is None or expected[0] != row["resource_account_id"]:
                return None
        decision = connection.execute(
            """SELECT decision_id,selection_version,input_snapshot_hash,
                      eligible_action_ids,selected_action_ids,decision_reason_codes
                 FROM decision_records WHERE decision_id=%s""",
            (head["current_decision_id"],),
        ).fetchone()
        reservation_ids = [
            row["reservation_id"] for row in connection.execute(
                """SELECT reservation_id FROM decision_reservation_mappings
                   WHERE decision_id=%s ORDER BY action_id""",
                (head["current_decision_id"],),
            ).fetchall()
        ]
        event = connection.execute(
            """SELECT event_id FROM event_log
               WHERE command_id=%s AND event_type='decision.recorded'
               ORDER BY sequence DESC LIMIT 1""",
            (command.command_id,),
        ).fetchone()
        response = {
            "decision_id": decision["decision_id"],
            "selection_version": int(decision["selection_version"]),
            "input_snapshot_hash": decision["input_snapshot_hash"],
            "selected_action_ids": list(decision["selected_action_ids"]),
            "eligible_action_ids": list(decision["eligible_action_ids"]),
            "decision_reason_codes": list(decision["decision_reason_codes"]),
            "reservation_ids": reservation_ids,
            "event_id": event["event_id"] if event else None,
            "deduplicated": True,
        }
        receipt = {
            "command_id": command.command_id,
            "status": "APPLIED",
            "result_code": "ACTIONS_SELECTED",
            "target_version": response["selection_version"],
            "event_ids": [],
            "response": response,
        }
        connection.execute(
            """UPDATE command_receipts SET status='APPLIED',
               result=%s, completed_at=now()
               WHERE command_id=%s AND request_hash=%s AND status='PROCESSING'""",
            (Jsonb(receipt), command.command_id, request_hash),
        )
        return response

    def _load_candidates(self, connection, command):
        bindings = {item.action_id: item for item in command.candidate_account_bindings}
        rows = connection.execute(
            """SELECT ca.*,
                      pd.policy_decision_id, pd.result AS policy_result,
                      pd.constraints AS policy_constraints,
                      pd.policy_input_hash, pd.policy_bundle_version,
                      pd.policy_rule_version,
                      ra.risk_assessment_id, ra.risk_level,
                      ra.residual_risk_basis_points,
                      ra.required_mitigations AS risk_required_mitigations,
                      ra.available_mitigations AS risk_available_mitigations,
                      ra.risk_input_hash, ra.risk_model_version, ra.risk_rule_version
                 FROM candidate_actions ca
            LEFT JOIN current_policy_decisions cpd
                   ON cpd.action_id = ca.action_id
            LEFT JOIN policy_decisions pd
                   ON pd.policy_decision_id = cpd.policy_decision_id
            LEFT JOIN current_risk_assessments cra
                   ON cra.action_id = ca.action_id
            LEFT JOIN risk_assessments ra
                   ON ra.risk_assessment_id = cra.risk_assessment_id
                WHERE ca.planning_run_id=%s AND ca.project_id=%s
             ORDER BY ca.action_id""",
            (command.planning_run_id, command.project_id),
        ).fetchall()
        candidates = []
        for row in rows:
            binding = bindings.get(row["action_id"])
            account = None
            if binding:
                account = self._load_account(connection, binding.account_id)
            candidates.append(CandidateInput(
                row["action_id"], row["planning_run_id"], row["project_id"],
                row["situation_id"], int(row["situation_version"]),
                row["analysis_context_hash"], row["diagnosis_id"],
                row["diagnosis_input_hash"], row["type"],
                tuple(row["target_refs"] or ()),
                tuple(row["required_capabilities"] or ()),
                dict(row["parameters"]), dict(row["estimated_resources"]),
                int(row["planner_confidence_basis_points"]),
                int(row["expected_progress_basis_points"]),
                int(row["evidence_gain_basis_points"]),
                int(row["reversibility_basis_points"]),
                row["registry_version"], row["planner_rule_version"],
                int(row["ordinal"]), row["content_hash"],
                row["policy_decision_id"], row["policy_result"],
                dict(row["policy_constraints"] or {}),
                row["policy_input_hash"], row["policy_bundle_version"],
                row["policy_rule_version"], row["risk_assessment_id"],
                row["risk_level"], row["residual_risk_basis_points"],
                tuple(row["risk_required_mitigations"] or ()),
                tuple(row["risk_available_mitigations"] or ()),
                row["risk_input_hash"], row["risk_model_version"],
                row["risk_rule_version"], binding.account_id if binding else None,
                account, binding.expected_account_version if binding else None,
            ))
        return tuple(candidates)

    @staticmethod
    def _load_account(connection, account_id):
        row = connection.execute(
            """SELECT account_id,project_id,scope_type,scope_id,currency,version,threshold_status
               FROM resource_accounts WHERE account_id=%s""",
            (account_id,),
        ).fetchone()
        if not row:
            return None
        balances = {
            item["dimension"]: (
                int(item["limit_amount"]),
                int(item["consumed_amount"]),
                int(item["reserved_amount"]),
            )
            for item in connection.execute(
                """SELECT dimension,limit_amount,consumed_amount,reserved_amount
                   FROM resource_balances WHERE account_id=%s""",
                (account_id,),
            ).fetchall()
        }
        return AccountSnapshot(
            row["account_id"], row["project_id"], row["scope_type"],
            row["scope_id"], row["currency"], int(row["version"]),
            row["threshold_status"], balances,
        )

    def _payloads(self, result, candidates, run_row, command):
        by_id = {item.action_id: item for item in candidates}
        candidate_refs = []
        policy_refs = []
        risk_refs = []
        score_refs = []
        account_snapshots = []
        seen_accounts = set()
        dispositions = []
        scores = []
        score_dimensions = []
        selected_refs = []
        reservation_mappings = []
        rejection_summary = {}
        for decision in result.candidate_decisions:
            candidate = by_id[decision.action_id]
            candidate_refs.append({
                "action_id": candidate.action_id,
                "content_hash": candidate.content_hash,
                "type": candidate.action_type,
            })
            if candidate.policy_decision_id:
                policy_refs.append({
                    "action_id": candidate.action_id,
                    "policy_decision_id": candidate.policy_decision_id,
                    "result": candidate.policy_result,
                    "input_hash": candidate.policy_input_hash,
                    "version": candidate.policy_bundle_version,
                })
            if candidate.risk_assessment_id:
                risk_refs.append({
                    "action_id": candidate.action_id,
                    "risk_assessment_id": candidate.risk_assessment_id,
                    "level": candidate.risk_level,
                    "residual_risk_basis_points": candidate.residual_risk_basis_points,
                    "input_hash": candidate.risk_input_hash,
                    "version": candidate.risk_model_version,
                })
            if candidate.account and candidate.account.account_id not in seen_accounts:
                seen_accounts.add(candidate.account.account_id)
                account_snapshots.append({
                    "account_id": candidate.account.account_id,
                    "expected_account_version": candidate.expected_account_version,
                    "version": candidate.account.version,
                    "currency": candidate.account.currency,
                    "scope_type": candidate.account.scope_type,
                    "scope_id": candidate.account.scope_id,
                    "threshold_status": candidate.account.threshold_status,
                    "balances": _canonical(candidate.account.balances),
                })
            dispositions.append({
                "action_id": decision.action_id,
                "action_content_hash": candidate.content_hash,
                "disposition": decision.disposition.value,
                "reason_codes": list(decision.reason_codes),
                "policy_decision_id": candidate.policy_decision_id,
                "risk_assessment_id": candidate.risk_assessment_id,
                "resource_account_id": decision.account_id,
                "reservation_required": decision.reservation_required,
                "reservation_id": decision.reservation_id,
                "derived_read_write": dict(decision.derived_read_write),
                "ordinal": candidate.ordinal,
            })
            rejection_summary[decision.action_id] = list(decision.reason_codes)
            if decision.score:
                score_refs.append({"action_id": decision.action_id, "score_id": decision.score.score_id})
                scores.append({
                    "score_id": decision.score.score_id,
                    "action_id": decision.action_id,
                    "action_content_hash": candidate.content_hash,
                    "final_score_basis_points": decision.score.final_score_basis_points,
                    "normalizer_version": decision.score.normalizer_version,
                    "score_input_hash": decision.score.score_input_hash,
                    "reason_codes": list(decision.score.reason_codes),
                    "default_sources": dict(decision.score.default_sources),
                    "weights": WEIGHTS,
                    "contributions": dict(decision.score.contributions),
                })
                for name, value in decision.score.dimensions.items():
                    score_dimensions.append({
                        "score_id": decision.score.score_id,
                        "dimension_name": name,
                        "raw_basis_points": decision.score.raw_dimensions[name],
                        "normalized_basis_points": value,
                        "contribution_basis_points": decision.score.contributions[name],
                        "default_source": decision.score.default_sources.get(name),
                    })
            if decision.disposition.value == "SELECTED":
                selected_refs.append({
                    "action_id": decision.action_id,
                    "selection_rank": len(selected_refs),
                    "selected_intent": {
                        "action_id": decision.action_id,
                        "planning_run_id": command.planning_run_id,
                        "decision_id": result.decision_id,
                        "type": candidate.action_type,
                        "parameters": dict(candidate.parameters),
                        "target_refs": list(candidate.target_refs),
                    },
                })
                if decision.reservation_required:
                    reservation_mappings.append({
                        "action_id": decision.action_id,
                        "reservation_id": decision.reservation_id,
                        "account_id": decision.account_id,
                        "resource_amounts": dict(decision.resource_amounts),
                        "expected_account_version": candidate.expected_account_version,
                        "account_version": int(candidate.expected_account_version) + 1,
                        "currency": candidate.estimated_resources.get("currency") or "",
                    })
        payload = {
            "decision": {
                "decision_id": result.decision_id,
                "project_id": command.project_id,
                "situation_id": run_row["situation_id"],
                "situation_version": run_row["situation_version"],
                "planning_run_id": command.planning_run_id,
                "planning_input_hash": run_row["input_hash"],
                "selection_version": result.selection_version,
                "input_snapshot_hash": result.input_snapshot_hash,
                "candidate_refs": candidate_refs,
                "eligible_action_ids": list(result.eligible_action_ids),
                "selected_action_ids": list(result.selected_action_ids),
                "policy_refs": policy_refs,
                "risk_refs": risk_refs,
                "score_refs": score_refs,
                "reservation_refs": [
                    {"action_id": item["action_id"], "reservation_id": item["reservation_id"]}
                    for item in reservation_mappings
                ],
                "rejection_summary": rejection_summary,
                "decision_reason_codes": list(result.decision_reason_codes),
                "normalizer_version": NORMALIZER_VERSION,
                "conflict_rule_version": CONFLICT_RULE_VERSION,
                "max_parallel_selected_actions": result.max_parallel,
            },
            "dispositions": dispositions,
            "scores": scores,
            "score_dimensions": score_dimensions,
            "selected_refs": selected_refs,
            "reservation_mappings": reservation_mappings,
            "account_snapshots": account_snapshots,
        }
        return payload

    def _persist_rejection(self, command, request_hash, code, detail):
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO command_receipts(
                   command_id,project_id,command_type,idempotency_key,
                   request_hash,status,result,completed_at)
                   VALUES (%s,%s,'selection.select_actions',%s,%s,'REJECTED',%s,now())
                   ON CONFLICT DO NOTHING""",
                (command.command_id, command.project_id, command.idempotency_key,
                 request_hash, Jsonb({"result_code": code, "detail": detail})),
            )

    @staticmethod
    def _request_hash(command: SelectActions) -> str:
        return _hash_json({
            "command_type": "selection.select_actions",
            "project_id": command.project_id,
            "planning_run_id": command.planning_run_id,
            "expected_situation_version": command.expected_situation_version,
            "expected_selection_version": command.expected_selection_version,
            "weight_profile_id": command.weight_profile_id,
            "candidate_account_bindings": [
                {
                    "action_id": item.action_id,
                    "account_id": item.account_id,
                    "expected_account_version": item.expected_account_version,
                }
                for item in sorted(command.candidate_account_bindings, key=lambda item: item.action_id)
            ],
            "actor_type": command.actor_type,
            "actor_id": command.actor_id,
            "reason": command.reason,
        })


def _canonical(value) -> Any:
    return json.loads(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True))


def _hash_json(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()
