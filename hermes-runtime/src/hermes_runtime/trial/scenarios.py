"""P6 autonomous trial scenarios: real failure injection and recovery (B-E).

Each scenario drives the REAL authority chain through the AutonomousRunDriver
and returns a machine-readable result. Failure injection is real: real pytest
failures, real SIGKILL, real artifact mutation, real human-gate pause/resume.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Mapping

from hermes_runtime.application.commands import (
    AdmitAgentRun,
    ApplyVerifiedTaskTransition,
    CreateResourceAccount,
    RecordVerificationResult,
)
from hermes_runtime.application.executions import PrepareExecutionRequest
from hermes_runtime.application.planning import PlanCandidates
from hermes_runtime.application.scheduling import (
    AcquireExecutionLease,
    RelinquishExecutionLease,
)
from hermes_runtime.application.workers import (
    RecordArtifactCandidate,
    RecordUsageSample,
    StartWorkerRun,
    SubmitExecutionResult,
)
from hermes_runtime.application.human_gates import (
    ApplyHumanGateDecision,
    EnterProjectWaitingForGate,
    HumanGateAuthority,
    RequestHumanGate,
    SubmitHumanGateDecision,
)
from hermes_runtime.domain.models import (
    AgentRun,
    AgentRunKind,
    AgentRunStatus,
    Actor,
    ActorType,
    Evidence,
    VerificationCheckResult,
    VerificationResult,
    Verdict,
)
from hermes_runtime.domain.execution import ArtifactInputRef, LockIntent
from hermes_runtime.domain.worker_execution import (
    ArtifactCandidateSubmission,
    ExecutionOutcome,
    ExecutionResultSubmission,
    UsageSampleSubmission,
    WorkerFrozenContext,
    WorkerLeaseBinding,
)
from hermes_runtime.infrastructure.postgres_human_gate import PostgresHumanGateStore
from hermes_runtime.trial.driver import (
    AutonomousRunDriver,
    TrialError,
    WORKER_IDENTITY,
    _now,
    _uuid,
)
from hermes_runtime.trial.golden_worker import WorkerFaultMode


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run_verification_failure_scenario(
    driver: AutonomousRunDriver, request: Mapping[str, Any], run_id: str,
) -> Dict[str, Any]:
    """Scenario A: a different real defect (missing feature) is verified,
    diagnosed and repaired through the real loop."""
    records = driver.run_happy_path(
        dict(request), run_id, first_fault=WorkerFaultMode.MISSING_FEATURE
    )
    _assert(records["delivery"]["final_state"] == "ACCEPTED", "delivery not ACCEPTED")
    _assert(records["task_pass"]["state"] == "PASSED", "task not PASSED")
    _assert(records["recovery"]["failure_type"] == "test_assertion_failure", "wrong failure")
    _assert(records["diagnosis"]["root_cause"] == "test_assertion_failure", "wrong root cause")
    records["scenario"] = {"id": "A-verification-failure", "result": "PASS"}
    return records


def run_duplicate_execution_scenario(
    driver: AutonomousRunDriver, request: Mapping[str, Any], run_id: str,
) -> Dict[str, Any]:
    """Scenario C: the SAME semantic command resubmitted with the SAME
    idempotency key deduplicates to the identical receipt (no double write)."""
    project_id = "project-" + run_id
    driver._project_id = project_id
    summary = "Duplicate execution deduplication trial"
    from hermes_runtime.application.commands import CreateProject
    first_command = CreateProject(
        driver._envelope("project.create", "key-dedup-" + run_id, 0,
                         driver.control, project_id, "dedup trial"),
        summary, driver.user,
    )
    first = driver.control_plane.create_project(first_command)
    second = driver.control_plane.create_project(first_command)
    _assert(first.command_id == second.command_id, "command ids differ")
    _assert(first.status == "APPLIED" and second.status == "APPLIED", "receipts not APPLIED")
    _assert(first.result_code == second.result_code, "result codes differ")
    with driver._connect() as connection:
        count = connection.execute(
            "SELECT count(*) FROM projects WHERE project_id=%s", (project_id,)
        ).fetchone()[0]
        receipts = connection.execute(
            "SELECT count(*) FROM command_receipts WHERE project_id=%s AND command_type='project.create'",
            (project_id,),
        ).fetchone()[0]
    _assert(count == 1, "duplicate project rows written")
    _assert(receipts == 1, "duplicate command receipts written")
    return {
        "scenario": {"id": "C-duplicate-execution", "result": "PASS"},
        "project_id": project_id,
        "receipt": first.__dict__,
        "deduplicated_receipt": second.__dict__,
        "project_rows": count,
        "receipt_rows": receipts,
    }


def _freeze_and_start(
    driver: AutonomousRunDriver, run_id: str, task_id: str, project_id: str,
    plan_id: str, tag: str, account_id: str,
):
    """Run a full implement freeze chain and return the pieces needed to drive
    the worker: template, prepared, lease, binding."""
    patch_event_id = driver._scenario_patch_event_ids[run_id]
    work_available = driver._situation_for_event(patch_event_id)
    if work_available.get("classification") not in {"CREATED", "UPDATED"}:
        raise TrialError("work_available situation not created")
    ctx = driver._situation_context(work_available["analysis_context_id"])
    plan = driver.planner.plan(PlanCandidates(
        command_id=_uuid("cmd-plan"),
        idempotency_key=_uuid("key-plan-" + tag),
        project_id=project_id,
        situation_id=work_available["situation_id"],
        expected_situation_version=work_available["version"],
        analysis_context_id=ctx["analysis_context_id"],
        analysis_context_hash=ctx["context_hash"],
        registry_version="action-registry/1.1",
    ))
    action = driver._read_candidate(plan["planning_run_id"], "implement")
    driver.accounting.create_account(CreateResourceAccount(
        driver._envelope("resource_account.create", "key-account-" + run_id, 0,
                         driver.control, project_id, "create scenario account"),
        account_id=account_id, scope_type="project", scope_id=project_id,
        limits={"execution_time_ms": 3600000, "cpu_time_ms": 3600000,
                "docker_runtime_ms": 3600000, "storage_bytes": 10000000,
                "agent_runs": 20},
    ))
    template = driver._seed_worker_template(project_id)
    policy, risk = driver._evaluate_action(
        plan["planning_run_id"], action, work_available["version"], tag,
    )
    selection, reservation_id = driver._select_action(
        plan["planning_run_id"], action, work_available["version"], account_id, tag,
    )
    match, context, sandbox = driver._capability_freeze(
        task_id, selection["decision_id"], action, policy, risk,
        reservation_id, plan_id, template, tag,
    )
    prepared = driver.execution.prepare(driver._prepare_command(
        run_id, task_id, selection, action, policy, risk, reservation_id,
        match, template, context, sandbox, plan_id, tag,
    ))
    lease, binding = driver._lease_and_start(
        run_id, prepared["execution_request_id"], reservation_id,
        template, context, sandbox, tag,
    )
    return {
        "work_available": work_available, "plan": plan, "action": action,
        "template": template, "policy": policy, "risk": risk,
        "selection": selection, "reservation_id": reservation_id,
        "match": match, "context": context, "sandbox": sandbox,
        "prepared": prepared, "lease": lease, "binding": binding,
        "planning_run_id": plan["planning_run_id"],
        "account_id": account_id,
    }


def run_tamper_scenario(
    driver: AutonomousRunDriver, request: Mapping[str, Any], run_id: str,
) -> Dict[str, Any]:
    """Scenario D: the produced artifact is tampered (real file mutation) and
    the independent verifier fails it closed (ARTIFACT_HASH_MISMATCH)."""
    project_id = "project-" + run_id
    task_id = "task-" + run_id
    plan_id = "plan-" + run_id
    driver._scenario_project(run_id, "Tamper fail-closed trial", task_id)
    driver._scenario_verification_plan(project_id, task_id, run_id)
    account_id = "account-" + run_id
    freeze = _freeze_and_start(
        driver, run_id, task_id, project_id, plan_id, "tamper", account_id,
    )
    worker = driver._run_golden_worker(
        task_id, freeze["prepared"]["execution_request_id"], run_id,
        "Tamper fail-closed trial", WorkerFaultMode.NONE, prepare_venv=True,
        tag="tamper",
        renewal={
            "execution_request_id": freeze["prepared"]["execution_request_id"],
            "lease_id": freeze["lease"]["lease_id"],
            "scheduler_id": freeze["lease"]["scheduler_id"],
            "session": freeze["lease"]["scheduler_session_id"],
            "fencing_token": freeze["lease"]["fencing_token"],
        },
    )
    _assert(worker["pytest"]["passed"], "baseline worker should pass pytest")
    manifest = worker["manifest"]

    # record candidates + usage + SUCCEEDED result (task -> COMPLETION_CLAIMED)
    freeze["binding"] = driver._refresh_binding(freeze["binding"])
    candidate_ids = []
    for item in manifest:
        candidate_id = _uuid("artifact-cand")
        driver.worker.record_artifact_candidate(RecordArtifactCandidate(
            command_id=_uuid("cmd-artifact"),
            idempotency_key=_uuid("key-artifact-" + candidate_id),
            binding=freeze["binding"],
            candidate=ArtifactCandidateSubmission(
                candidate_id=candidate_id, artifact_kind="source_tree",
                content_hash=item["content_hash"],
                storage_ref="object://artifacts/" + run_id + "/" + item["path"],
                size_bytes=item["size_bytes"], media_type="text/plain",
            ),
            actor_id=WORKER_IDENTITY,
        ))
        candidate_ids.append(candidate_id)
    primary = candidate_ids[0]
    usage_id = _uuid("usage")
    usage_sample_id = "sample-" + run_id
    driver.worker.record_usage_sample(RecordUsageSample(
        command_id=_uuid("cmd-usage"),
        idempotency_key=_uuid("key-usage-" + usage_id),
        binding=freeze["binding"],
        sample=UsageSampleSubmission(
            usage_id=usage_id, sample_id=usage_sample_id,
            reservation_id=freeze["reservation_id"],
            amounts={"execution_time_ms": 5000},
            interval_start=_now(), interval_end=_now(),
        ),
        actor_id=WORKER_IDENTITY,
    ))
    account_version = driver._account_version(account_id)
    result_id = "result-" + run_id + "-tamper"
    driver.worker.submit_result(SubmitExecutionResult(
        command_id=_uuid("cmd-result"),
        idempotency_key=_uuid("key-result-tamper"),
        binding=freeze["binding"],
        result=ExecutionResultSubmission(
            result_id=result_id, outcome=ExecutionOutcome.SUCCEEDED,
            error_classification="", artifact_candidate_refs=tuple(candidate_ids),
            evidence_candidate_refs=(), usage_sample_refs=(usage_sample_id,),
            started_at=_now(), finished_at=_now(),
            adapter_identity="golden-builder", adapter_version="1.0",
            primary_artifact_candidate_id=primary,
            completion_claim_id="claim-golden-" + run_id,
        ),
        expected_account_version=account_version, actor_id=WORKER_IDENTITY,
    ))

    # REAL artifact tampering: mutate a produced file on disk
    tampered = driver.workspace / "app" / "main.py"
    original = tampered.read_bytes()
    tampered.write_bytes(original + b"\n# P6 tamper injection\n")
    tampered_hash = "sha256:" + __import__("hashlib").sha256(tampered.read_bytes()).hexdigest()
    recorded_hash = manifest[0]["content_hash"]

    # independent verifier: re-hashes -> mismatch -> FAIL
    outcome = driver._verify_workspace(run_id, manifest)
    _assert(outcome["verdict"] == "FAIL", "verifier did not fail the tampered artifact")
    _assert("ARTIFACT_HASH_MISMATCH" in outcome["finding_codes"], "wrong finding code")
    _assert(tampered_hash != recorded_hash, "tamper did not change the hash")

    # record the FAIL verdict through the real authority -> task FAILED
    task_version = driver._task_version(task_id, project_id)
    verifier_run_id = "run-verifier-tamper-" + run_id
    driver.control_plane.admit_agent_run(AdmitAgentRun(
        driver._envelope("agent_run.admit", "key-verifier-tamper-" + run_id,
                         task_version, driver.control, project_id,
                         "admit tamper verifier run"),
        AgentRun(
            run_id=verifier_run_id, project_id=project_id, task_id=task_id,
            run_kind=AgentRunKind.VERIFIER, agent_identity="verifier-golden",
            context_identity="verifier-context-tamper",
            status=AgentRunStatus.ADMITTED, created_by=driver.control,
        ),
    ))
    verification_id = "verification-tamper-" + run_id
    evidence_id = "evidence-tamper-" + run_id
    driver.control_plane.record_verification_result(RecordVerificationResult(
        driver._envelope("verification.record_result", "key-verif-tamper-" + run_id,
                         task_version, driver.verifier, project_id,
                         "independent verification detects tampering"),
        VerificationResult(
            verification_id=verification_id, plan_id=plan_id, plan_version=1,
            task_id=task_id, project_id=project_id,
            artifact_id="artifact-" + primary,
            artifact_hash=recorded_hash,
            verifier_identity=driver.verifier, verifier_run_id=verifier_run_id,
            verdict=Verdict.FAIL,
            check_results=(VerificationCheckResult(
                check_id="pytest", status=Verdict.FAIL,
                finding_codes=("ARTIFACT_HASH_MISMATCH",),
                evidence_refs=(evidence_id,), started_at=_now(), completed_at=_now(),
            ),),
            evidence=(Evidence(evidence_id, "artifact-" + primary, recorded_hash,
                               "verifier-golden", True),),
            started_at=_now(), completed_at=_now(),
            correlation_id="corr-" + run_id,
        ),
    ))
    driver.control_plane.apply_verified_task_transition(ApplyVerifiedTaskTransition(
        driver._envelope("task.apply_verified_transition", "key-apply-tamper-" + run_id,
                         task_version, driver.control, project_id,
                         "apply tamper FAIL"),
        task_id, verification_id,
    ))
    _assert(driver._task_version(task_id, project_id) > 0, "task missing")
    with driver._connect() as connection:
        state = connection.execute(
            "SELECT state FROM tasks WHERE task_id=%s", (task_id,)
        ).fetchone()[0]
        finding = connection.execute(
            """SELECT finding_codes FROM verification_check_results
               WHERE verification_id=%s""", (verification_id,)
        ).fetchone()[0]
    _assert(state == "FAILED", "task not FAILED after tamper detection")
    _assert("ARTIFACT_HASH_MISMATCH" in finding, "finding not recorded")
    return {
        "scenario": {"id": "D-artifact-tampering", "result": "PASS"},
        "task_state": state,
        "verification_id": verification_id,
        "recorded_hash": recorded_hash,
        "tampered_hash": tampered_hash,
        "verifier": {k: outcome[k] for k in ("verdict", "finding_codes", "hash_mismatches")},
    }


def run_worker_crash_scenario(
    driver: AutonomousRunDriver, request: Mapping[str, Any], run_id: str,
) -> Dict[str, Any]:
    """Scenario B: the worker subprocess is SIGKILLed mid-run; the scheduler
    lease is relinquished, the request requeues, is re-acquired and re-run
    (attempt 2) through the real authority, then verified independently."""
    project_id = "project-" + run_id
    task_id = "task-" + run_id
    plan_id = "plan-" + run_id
    driver._scenario_project(run_id, "Worker crash recovery trial", task_id)
    driver._scenario_verification_plan(project_id, task_id, run_id)
    account_id = "account-" + run_id
    freeze = _freeze_and_start(
        driver, run_id, task_id, project_id, plan_id, "crash", account_id,
    )
    execution_request_id = freeze["prepared"]["execution_request_id"]

    # launch the real golden worker subprocess and SIGKILL it mid-run
    workspace = driver.workspace
    context_path = workspace / "worker-context-crash.json"
    result_path = workspace / "worker-result-crash.json"
    context = {
        "workspace": str(workspace),
        "project_id": project_id, "task_id": task_id,
        "execution_request_id": execution_request_id,
        "request_summary": "Worker crash recovery trial",
        "fault_mode": WorkerFaultMode.NONE,
        "prepare_venv": True,
        "test_database_url": driver.test_database_url,
        "result_path": str(result_path),
    }
    context_path.write_text(__import__("json").dumps(context, sort_keys=True))
    proc = subprocess.Popen(
        [sys.executable, "-m", "hermes_runtime.trial.golden_worker", str(context_path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    time.sleep(2.0)
    proc.send_signal(signal.SIGKILL)
    proc.wait(timeout=30)
    _assert(not result_path.exists(), "killed worker still produced a result")

    # real recovery: relinquish the lease (request requeues), re-acquire, rerun
    scheduler = "scheduler-crash"
    session = "session-crash"
    driver.scheduler.relinquish(RelinquishExecutionLease(
        command_id=_uuid("cmd-relinquish"),
        idempotency_key=_uuid("key-relinquish-" + run_id),
        project_id=project_id,
        execution_request_id=execution_request_id,
        lease_id=freeze["lease"]["lease_id"],
        scheduler_id=scheduler, scheduler_session_id=session,
        fencing_token=freeze["lease"]["fencing_token"],
        expected_lease_version=freeze["lease"]["lease_version"],
        actor_id=scheduler,
    ))
    lease2 = driver.scheduler.acquire(AcquireExecutionLease(
        command_id=_uuid("cmd-acquire2"),
        idempotency_key=_uuid("key-acquire2-" + run_id),
        project_id=project_id,
        scheduler_id=scheduler, scheduler_session_id=session,
        actor_id=scheduler,
    ))
    _assert(lease2["execution_request_id"] == execution_request_id, "requeued request not re-acquired")
    binding2 = WorkerLeaseBinding(
        project_id=project_id,
        execution_request_id=execution_request_id,
        execution_attempt=2,
        run_id="run-crash-2",
        lease_id=lease2["lease_id"],
        lease_version=lease2["lease_version"],
        fencing_token=lease2["fencing_token"],
        scheduler_id=scheduler,
        scheduler_session_id=session,
        worker_agent_identity=WORKER_IDENTITY,
        context_identity="worker-context-crash2",
        observed_request_version=lease2["request_version"],
    )
    driver.worker.start_run(StartWorkerRun(
        command_id=_uuid("cmd-start2"),
        idempotency_key=_uuid("key-start2-" + run_id),
        binding=binding2,
        frozen_context=WorkerFrozenContext(
            worker_template_id="template-golden",
            worker_template_revision=1,
            worker_template_content_hash=freeze["template"]["content_hash"],
            context_bundle_id=freeze["context"]["bundle_id"],
            context_manifest_hash=freeze["context"]["manifest_hash"],
            sandbox_profile_id=freeze["sandbox"]["profile_id"],
            sandbox_profile_hash=freeze["sandbox"]["profile_hash"],
            reservation_id=freeze["reservation_id"],
        ),
        actor_id=WORKER_IDENTITY,
    ))
    request_version = driver._request_version(execution_request_id)
    binding2 = WorkerLeaseBinding(
        project_id=binding2.project_id,
        execution_request_id=binding2.execution_request_id,
        execution_attempt=2,
        run_id=binding2.run_id,
        lease_id=binding2.lease_id,
        lease_version=binding2.lease_version,
        fencing_token=binding2.fencing_token,
        scheduler_id=binding2.scheduler_id,
        scheduler_session_id=binding2.scheduler_session_id,
        worker_agent_identity=binding2.worker_agent_identity,
        context_identity=binding2.context_identity,
        observed_request_version=request_version,
    )
    # The SIGKILL may have interrupted the venv build; the re-run repairs the
    # workspace by preparing a fresh venv (a real worker behavior).
    worker2 = driver._run_golden_worker(
        task_id, execution_request_id, run_id, "Worker crash recovery trial",
        WorkerFaultMode.NONE, prepare_venv=True, tag="crash2",
        renewal={
            "execution_request_id": execution_request_id,
            "lease_id": lease2["lease_id"],
            "scheduler_id": scheduler,
            "session": session,
            "fencing_token": lease2["fencing_token"],
        },
    )
    _assert(worker2["pytest"]["passed"], "re-run worker should pass pytest")
    manifest = worker2["manifest"]
    binding2 = driver._refresh_binding(binding2)
    candidate_ids = []
    for item in manifest:
        candidate_id = _uuid("artifact-cand")
        driver.worker.record_artifact_candidate(RecordArtifactCandidate(
            command_id=_uuid("cmd-artifact"),
            idempotency_key=_uuid("key-artifact-" + candidate_id),
            binding=binding2,
            candidate=ArtifactCandidateSubmission(
                candidate_id=candidate_id, artifact_kind="source_tree",
                content_hash=item["content_hash"],
                storage_ref="object://artifacts/" + run_id + "/" + item["path"],
                size_bytes=item["size_bytes"], media_type="text/plain",
            ),
            actor_id=WORKER_IDENTITY,
        ))
        candidate_ids.append(candidate_id)
    primary = candidate_ids[0]
    usage_id = _uuid("usage")
    usage_sample_id = "sample-" + run_id
    driver.worker.record_usage_sample(RecordUsageSample(
        command_id=_uuid("cmd-usage"),
        idempotency_key=_uuid("key-usage-" + usage_id),
        binding=binding2,
        sample=UsageSampleSubmission(
            usage_id=usage_id, sample_id=usage_sample_id,
            reservation_id=freeze["reservation_id"],
            amounts={"execution_time_ms": 5000},
            interval_start=_now(), interval_end=_now(),
        ),
        actor_id=WORKER_IDENTITY,
    ))
    result2_id = "result-" + run_id + "-crash2"
    driver.worker.submit_result(SubmitExecutionResult(
        command_id=_uuid("cmd-result"),
        idempotency_key=_uuid("key-result-crash2"),
        binding=binding2,
        result=ExecutionResultSubmission(
            result_id=result2_id, outcome=ExecutionOutcome.SUCCEEDED,
            error_classification="", artifact_candidate_refs=tuple(candidate_ids),
            evidence_candidate_refs=(), usage_sample_refs=(usage_sample_id,),
            started_at=_now(), finished_at=_now(),
            adapter_identity="golden-builder", adapter_version="1.0",
            primary_artifact_candidate_id=primary,
            completion_claim_id="claim-golden-" + run_id,
        ),
        expected_account_version=driver._account_version(account_id),
        actor_id=WORKER_IDENTITY,
    ))

    # independent verification PASS
    task_version = driver._task_version(task_id, project_id)
    verifier_run_id = "run-verifier-crash-" + run_id
    driver.control_plane.admit_agent_run(AdmitAgentRun(
        driver._envelope("agent_run.admit", "key-verifier-crash-" + run_id,
                         task_version, driver.control, project_id,
                         "admit crash-recovery verifier run"),
        AgentRun(
            run_id=verifier_run_id, project_id=project_id, task_id=task_id,
            run_kind=AgentRunKind.VERIFIER, agent_identity="verifier-golden",
            context_identity="verifier-context-crash",
            status=AgentRunStatus.ADMITTED, created_by=driver.control,
        ),
    ))
    outcome = driver._verify_workspace(run_id, manifest)
    _assert(outcome["verdict"] == "PASS", "independent verification did not pass")
    verification_id = "verification-crash-" + run_id
    evidence_id = "evidence-crash-" + run_id
    driver.control_plane.record_verification_result(RecordVerificationResult(
        driver._envelope("verification.record_result", "key-verif-crash-" + run_id,
                         task_version, driver.verifier, project_id,
                         "independent verification after worker crash recovery"),
        VerificationResult(
            verification_id=verification_id, plan_id=plan_id, plan_version=1,
            task_id=task_id, project_id=project_id,
            artifact_id="artifact-" + primary,
            artifact_hash=manifest[0]["content_hash"],
            verifier_identity=driver.verifier, verifier_run_id=verifier_run_id,
            verdict=Verdict.PASS,
            check_results=(VerificationCheckResult(
                check_id="pytest", status=Verdict.PASS, finding_codes=(),
                evidence_refs=(evidence_id,), started_at=_now(), completed_at=_now(),
            ),),
            evidence=(Evidence(evidence_id, "artifact-" + primary,
                               manifest[0]["content_hash"], "verifier-golden", True),),
            started_at=_now(), completed_at=_now(),
            correlation_id="corr-" + run_id,
        ),
    ))
    driver.control_plane.apply_verified_task_transition(ApplyVerifiedTaskTransition(
        driver._envelope("task.apply_verified_transition", "key-apply-crash-" + run_id,
                         task_version, driver.control, project_id,
                         "apply crash-recovery PASS"),
        task_id, verification_id,
    ))
    _assert(driver._task_version(task_id, project_id) > 0, "task missing")
    with driver._connect() as connection:
        state = connection.execute(
            "SELECT state FROM tasks WHERE task_id=%s", (task_id,)
        ).fetchone()[0]
    _assert(state == "PASSED", "task not PASSED after crash recovery")
    return {
        "scenario": {"id": "B-worker-crash", "result": "PASS"},
        "task_state": state,
        "execution_request_id": execution_request_id,
        "relinquished_then_reacquired": True,
        "verification_id": verification_id,
        "signal": "SIGKILL",
    }


def run_human_gate_scenario(
    driver: AutonomousRunDriver, request: Mapping[str, Any], run_id: str,
) -> Dict[str, Any]:
    """Scenario E: a policy-required human gate pauses the project
    (WAITING_FOR_HUMAN) and the authorized human decision resumes it through
    the real HumanGateAuthority."""
    project_id = "project-" + run_id
    driver._project_id = project_id
    from hermes_runtime.application.commands import (
        CreateProject,
        RecordProjectPolicyFact,
    )
    driver.control_plane.create_project(CreateProject(
        driver._envelope("project.create", "key-create-" + run_id, 0,
                         driver.control, project_id, "human gate trial"),
        "Human gate pause/resume trial", driver.user,
    ))
    # The gate requires a REAL REQUIRE_HUMAN policy fact at the current
    # project version (produced through the P6 guard-fact authority command).
    policy_fact_id = "policy-require-human-" + run_id
    driver.guard_facts.record_policy_fact(RecordProjectPolicyFact(
        driver._envelope("project.record_policy_fact",
                         "key-gate-policy-" + run_id, 0,
                         driver.control, project_id,
                         "record REQUIRE_HUMAN policy fact for gate"),
        policy_decision_id=policy_fact_id,
        project_version=0,
        from_state="CREATED",
        to_state="CREATED",
        result="REQUIRE_HUMAN",
        policy_bundle_version="policy-bundle/1.0",
        input_hash="sha256:" + uuid.uuid4().hex,
    ))
    authority = HumanGateAuthority(PostgresHumanGateStore(driver.database_url))
    main = Actor(ActorType.MAIN_HERMES, "main-hermes")
    user = Actor(ActorType.USER, "human-approver")
    gate_request_id = "gate-" + run_id
    context_hash = "sha256:" + __import__("hashlib").sha256(
        (project_id + ":" + gate_request_id).encode()
    ).hexdigest()
    resume_context = {
        "context_id": "ctx-" + gate_request_id,
        "project_before_state": "CREATED",
        "project_before_version": 0,
        "original_command_type": "project.request_transition",
        "requester": {"type": "main_hermes", "id": "main-hermes"},
        "policy_decision_id": policy_fact_id,
        "evidence_refs": [],
        "supporting_refs": [],
        "expected_task_versions": {},
        "context_hash": context_hash,
    }
    requested = authority.request_gate(RequestHumanGate(
        command_id=_uuid("cmd-gate-request"),
        idempotency_key=_uuid("key-gate-request"),
        project_id=project_id,
        gate_request_id=gate_request_id,
        action_scope="project:resume",
        requester=main,
        expected_project_version=0,
        resume_context=resume_context,
        reason="policy requires human approval",
        request_type="approval",
        policy_decision_id=policy_fact_id,
        expires_at="2099-01-01T00:00:00+00:00",
    ))
    _assert(requested["result_code"] == "HUMAN_GATE_REQUESTED", "gate request failed")
    waiting = authority.enter_project_waiting(EnterProjectWaitingForGate(
        command_id=_uuid("cmd-gate-wait"),
        idempotency_key=_uuid("key-gate-wait"),
        project_id=project_id,
        waiting_record_id="wait-" + run_id,
        gate_request_id=gate_request_id,
        resume_context_id="ctx-" + gate_request_id,
        expected_project_version=0,
        blocking_reason="blocked by human approval",
    ))
    _assert(waiting["result_code"] == "PROJECT_WAITING_ENTERED", "enter waiting failed")
    with driver._connect() as connection:
        paused_state = connection.execute(
            "SELECT state FROM projects WHERE project_id=%s", (project_id,)
        ).fetchone()[0]
    _assert(paused_state == "WAITING_FOR_HUMAN", "project not paused for human gate")

    # authorized human approves (authorization assertion is a config-table seed)
    PostgresHumanGateStore(driver.database_url).seed_human_authorization(
        "assert-" + run_id, user.actor_id, project_id, gate_request_id,
        "project:resume",
    )
    submitted = authority.submit_decision(SubmitHumanGateDecision(
        command_id=_uuid("cmd-gate-decision"),
        idempotency_key=_uuid("key-gate-decision"),
        project_id=project_id,
        gate_decision_id="decision-" + run_id,
        gate_request_id=gate_request_id,
        decision="APPROVE",
        approver=user,
        authorization_ref="authz:" + run_id,
        assertion_id="assert-" + run_id,
        assertion_hash="sha256:test-assertion",
        reason="approved by authorized human",
        expires_at="2099-01-01T00:00:00+00:00",
        actor_type=user.actor_type.value,
        actor_id=user.actor_id,
    ))
    _assert(submitted["result_code"] == "HUMAN_GATE_APPROVED", "decision submit failed")

    # The resume guard requires current evidence/policy/budget facts for the
    # WAITING_FOR_HUMAN -> CREATED transition at the CURRENT project version.
    from hermes_runtime.application.commands import (
        CreateResourceAccount,
        IssueProjectBudgetFact,
        RecordProjectEvidenceFact,
    )
    account_id = "account-gate-" + run_id
    driver.accounting.create_account(CreateResourceAccount(
        driver._envelope("resource_account.create", "key-gate-account-" + run_id, 0,
                         driver.control, project_id, "create gate account"),
        account_id=account_id, scope_type="project", scope_id=project_id,
        limits={"execution_time_ms": 3600000, "storage_bytes": 10000000},
    ))
    with driver._connect() as connection:
        row = connection.execute(
            """SELECT p.version,
                      (SELECT version FROM human_gate_requests WHERE gate_request_id=%s),
                      (SELECT version FROM project_waiting_records WHERE waiting_record_id=%s),
                      (SELECT version FROM human_gate_decisions WHERE gate_decision_id=%s)
               FROM projects p WHERE p.project_id=%s""",
            (gate_request_id, "wait-" + run_id, "decision-" + run_id, project_id),
        ).fetchone()
    project_version, gate_version, waiting_version, decision_version = (int(x) for x in row)
    driver.guard_facts.record_evidence_fact(RecordProjectEvidenceFact(
        driver._envelope("project.record_evidence_fact", "key-gate-ev-" + run_id,
                         project_version, driver.control, project_id,
                         "gate resume evidence fact"),
        evidence_fact_id="evidence-gate-" + run_id,
        project_version=project_version,
        from_state="WAITING_FOR_HUMAN",
        to_state="CREATED",
        subject_ref="human-gate-" + run_id,
    ))
    driver.guard_facts.record_policy_fact(RecordProjectPolicyFact(
        driver._envelope("project.record_policy_fact", "key-gate-pol-" + run_id,
                         project_version, driver.control, project_id,
                         "gate resume policy fact"),
        policy_decision_id="policy-gate-" + run_id,
        project_version=project_version,
        from_state="WAITING_FOR_HUMAN",
        to_state="CREATED",
        result="ALLOW",
        policy_bundle_version="policy-bundle/1.0",
        input_hash="sha256:" + uuid.uuid4().hex,
    ))
    account_version = driver._account_version(account_id)
    driver.accounting.issue_budget_fact(IssueProjectBudgetFact(
        driver._envelope("resource.budget_fact.issue", "key-gate-budget-" + run_id,
                         account_version, driver.control, project_id,
                         "gate resume budget fact"),
        budget_fact_id="budget-gate-" + run_id,
        account_id=account_id,
        project_version=project_version,
        from_state="WAITING_FOR_HUMAN",
        to_state="CREATED",
    ))
    applied = authority.apply_decision(ApplyHumanGateDecision(
        command_id=_uuid("cmd-gate-apply"),
        idempotency_key=_uuid("key-gate-apply"),
        project_id=project_id,
        gate_request_id=gate_request_id,
        gate_decision_id="decision-" + run_id,
        waiting_record_id="wait-" + run_id,
        expected_project_version=project_version,
        expected_waiting_version=waiting_version,
        expected_gate_version=gate_version,
        expected_decision_version=decision_version,
        resume_context_hash=context_hash,
        target_state="CREATED",
    ))
    _assert(applied["result_code"] == "HUMAN_GATE_DECISION_APPLIED", "gate apply failed")
    with driver._connect() as connection:
        resumed_state = connection.execute(
            "SELECT state FROM projects WHERE project_id=%s", (project_id,)
        ).fetchone()[0]
    _assert(resumed_state == "CREATED", "project not resumed after human gate")
    return {
        "scenario": {"id": "E-human-gate", "result": "PASS"},
        "paused_state": paused_state,
        "resumed_state": resumed_state,
        "gate_request_id": gate_request_id,
        "result_codes": [requested["result_code"], waiting["result_code"],
                         submitted["result_code"], applied["result_code"]],
    }
