import os
import hashlib
import threading
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
from hermes_runtime.application.human_gates import (
    ApplyHumanGateDecision,
    CancelHumanGateRequest,
    EnterProjectWaitingForGate,
    ExpireHumanGateRequest,
    HumanGateAuthority,
    RequestHumanGate,
    SubmitHumanGateDecision,
    SupersedeHumanGateRequest,
)
from hermes_runtime.domain.models import Actor, ActorType
from hermes_runtime.infrastructure.postgres_human_gate import PostgresHumanGateStore


DATABASE_URL = os.environ.get("HERMES_TEST_DATABASE_URL")


@unittest.skipUnless(
    DATABASE_URL and psycopg,
    "requires psycopg and explicit HERMES_TEST_DATABASE_URL pointing to PostgreSQL 14+",
)
class HumanGatePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = PostgresHumanGateStore(DATABASE_URL)
        cls.store.check_server_version(140000)
        for migration in sorted((Path(__file__).parents[1] / "migrations").glob("*.sql")):
            cls.store.apply_migration(migration)

    def setUp(self):
        self.store.reset_for_test()
        self.authority = HumanGateAuthority(self.store)
        self.main = Actor(ActorType.MAIN_HERMES, "main-hermes")
        self.user = Actor(ActorType.USER, "human-approver")

    def _admin_connection(self):
        return psycopg.connect(DATABASE_URL)

    def _seed_project(self, project_id="project-1", state="IMPLEMENTING", version=7):
        command_id = "seed-project-" + uuid.uuid4().hex
        payload = {"project_version": version, "new_state": state}
        with self._admin_connection() as connection:
            connection.execute(
                """
                INSERT INTO public.command_receipts(
                    command_id, project_id, command_type, idempotency_key,
                    request_hash, status, result, completed_at
                ) VALUES (%s,%s,'project.create',%s,'seed','APPLIED','{}',clock_timestamp())
                """,
                (command_id, project_id, command_id),
            )
            connection.execute(
                """
                INSERT INTO public.projects(project_id,title,state,version,last_command_id)
                VALUES (%s,'Human Gate Project',%s,%s,%s)
                """,
                (project_id, state, version, command_id),
            )
            connection.execute(
                "INSERT INTO public.project_graph_versions(project_id, graph_version) VALUES (%s, 0)",
                (project_id,),
            )
            row = connection.execute(
                """
                INSERT INTO public.event_log(
                    event_id,event_type,schema_version,producer_type,producer_id,
                    project_id,partition_key,command_id,correlation_id,payload
                ) VALUES (%s,'project.created','1.0','control_plane','seed',
                         %s,%s,%s,%s,%s::jsonb)
                RETURNING sequence
                """,
                (
                    "evt-" + command_id,
                    project_id,
                    project_id,
                    command_id,
                    command_id,
                    Jsonb(payload),
                ),
            ).fetchone()
            connection.execute(
                """
                INSERT INTO public.outbox_messages(message_id,event_id,topic,partition_key,sequence,payload)
                VALUES (%s,%s,'hermes.runtime.events',%s,%s,%s::jsonb)
                """,
                (
                    "msg-" + command_id,
                    "evt-" + command_id,
                    project_id,
                    row[0],
                    Jsonb(payload),
                ),
            )

    def _seed_policy_require_human(self, project_id, project_version, policy_id="policy-require-human"):
        with self._admin_connection() as connection:
            connection.execute(
                """
                INSERT INTO public.project_policy_decision_facts(
                    policy_decision_id,project_id,project_version,from_state,to_state,
                    result,authority,policy_bundle_version,input_hash
                ) VALUES (%s,%s,%s,'IMPLEMENTING','WAITING_FOR_HUMAN',
                         'REQUIRE_HUMAN','policy_engine','policy-test',%s)
                """,
                (policy_id, project_id, project_version, "sha256:" + uuid.uuid4().hex),
            )
        return policy_id

    def _seed_resume_guard(self, project_id="project-1", project_version=8, target_state="IMPLEMENTING"):
        suffix = uuid.uuid4().hex
        with self._admin_connection() as connection:
            connection.execute(
                """
                INSERT INTO public.project_evidence_facts(
                    evidence_fact_id,project_id,project_version,from_state,to_state,
                    result,authority,subject_ref
                ) VALUES (%s,%s,%s,'WAITING_FOR_HUMAN',%s,'VALID','verification_engine',%s)
                """,
                ("evidence-" + suffix, project_id, project_version, target_state, "subject-" + suffix),
            )
            connection.execute(
                """
                INSERT INTO public.project_policy_decision_facts(
                    policy_decision_id,project_id,project_version,from_state,to_state,
                    result,authority,policy_bundle_version,input_hash
                ) VALUES (%s,%s,%s,'WAITING_FOR_HUMAN',%s,'ALLOW','policy_engine','policy-test',%s)
                """,
                ("policy-" + suffix, project_id, project_version, target_state, "sha256:" + suffix),
            )
            connection.execute(
                """
                INSERT INTO public.project_budget_facts(
                    budget_fact_id,project_id,project_version,from_state,to_state,
                    status,authority,budget_scope_id,version
                ) VALUES (%s,%s,%s,'WAITING_FOR_HUMAN',%s,'OK','budget_engine',%s,1)
                """,
                ("budget-" + suffix, project_id, project_version, target_state, "budget-" + project_id),
            )

    def _request(self, gate_request_id="gate-1", project_id="project-1", policy_id="policy-require-human",
                 request_type="approval", expires_at="2099-01-01T00:00:00+00:00", expected_version=7,
                 attempt_ledger=(), remaining_options=(), recommended_option="",
                 idempotency_key=None):
        context_hash = "sha256:" + hashlib.sha256(
            "{}:{}:{}".format(project_id, gate_request_id, expected_version).encode("utf-8")
        ).hexdigest()
        context = {
            "context_id": "ctx-" + gate_request_id,
            "project_before_state": "IMPLEMENTING",
            "project_before_version": expected_version,
            "original_command_type": "execution.admit",
            "requester": {"type": "main_hermes", "id": "main-hermes"},
            "policy_decision_id": policy_id,
            "evidence_refs": ["evidence:" + gate_request_id],
            "supporting_refs": ["action:" + gate_request_id],
            "expected_task_versions": {},
            "context_hash": context_hash,
        }
        return self.authority.request_gate(
            RequestHumanGate(
                command_id="cmd-request-" + gate_request_id,
                idempotency_key=idempotency_key or "idem-request-" + gate_request_id,
                project_id=project_id,
                gate_request_id=gate_request_id,
                action_scope="project:resume",
                requester=self.main,
                expected_project_version=expected_version,
                resume_context=context,
                reason="policy requires human approval",
                request_type=request_type,
                policy_decision_id=policy_id,
                expires_at=expires_at,
                attempt_ledger=attempt_ledger,
                remaining_options=remaining_options,
                recommended_option=recommended_option,
            )
        )

    def _enter_waiting(self, gate_request_id="gate-1", expected_version=7):
        return self.authority.enter_project_waiting(
            EnterProjectWaitingForGate(
                command_id="cmd-wait-" + gate_request_id,
                idempotency_key="idem-wait-" + gate_request_id,
                project_id="project-1",
                waiting_record_id="wait-" + gate_request_id,
                gate_request_id=gate_request_id,
                resume_context_id="ctx-" + gate_request_id,
                expected_project_version=expected_version,
                blocking_reason="blocked by human approval",
            )
        )

    def _approve(self, gate_request_id="gate-1", decision_id="decision-1", approver=None,
                 expires_at="2099-01-01T00:00:00+00:00", command_id=None, key=None):
        approver = approver or self.user
        self.store.seed_human_authorization(
            "assert-" + decision_id,
            approver.actor_id,
            "project-1",
            gate_request_id,
            "project:resume",
        )
        return self.authority.submit_decision(
            SubmitHumanGateDecision(
                command_id=command_id or "cmd-decision-" + decision_id,
                idempotency_key=key or "idem-decision-" + decision_id,
                project_id="project-1",
                gate_decision_id=decision_id,
                gate_request_id=gate_request_id,
                decision="APPROVE",
                approver=approver,
                authorization_ref="test-authz:" + decision_id,
                assertion_id="assert-" + decision_id,
                assertion_hash="sha256:test-assertion",
                reason="approved by authorized human",
                expires_at=expires_at,
                actor_type=approver.actor_type.value,
                actor_id=approver.actor_id,
            )
        )

    def _apply(self, gate_request_id="gate-1", decision_id="decision-1", project_version=8,
               gate_version=2, waiting_version=1, decision_version=1):
        return self.authority.apply_decision(
            ApplyHumanGateDecision(
                command_id="cmd-apply-" + decision_id,
                idempotency_key="idem-apply-" + decision_id,
                project_id="project-1",
                gate_request_id=gate_request_id,
                gate_decision_id=decision_id,
                waiting_record_id="wait-" + gate_request_id,
                expected_project_version=project_version,
                expected_waiting_version=waiting_version,
                expected_gate_version=gate_version,
                expected_decision_version=decision_version,
                resume_context_hash=self._resume_context_hash(gate_request_id),
                target_state="IMPLEMENTING",
            )
        )

    def _resume_context_hash(self, gate_request_id):
        with self._admin_connection() as connection:
            return connection.execute(
                "SELECT resume_context_hash FROM public.human_gate_requests WHERE gate_request_id=%s",
                (gate_request_id,),
            ).fetchone()[0]

    def test_request_wait_approve_apply_resume_commits_event_outbox_receipt(self):
        self._seed_project()
        self._seed_policy_require_human("project-1", 7)
        requested = self._request()
        waiting = self._enter_waiting()
        approved = self._approve()
        self._seed_resume_guard()
        applied = self._apply()

        self.assertEqual("HUMAN_GATE_REQUESTED", requested["result_code"])
        self.assertEqual("PROJECT_WAITING_ENTERED", waiting["result_code"])
        self.assertEqual("HUMAN_GATE_APPROVED", approved["result_code"])
        self.assertEqual("HUMAN_GATE_DECISION_APPLIED", applied["result_code"])
        with self._admin_connection() as connection:
            project = connection.execute(
                "SELECT state, resume_state, version FROM public.projects WHERE project_id='project-1'"
            ).fetchone()
            waiting_row = connection.execute(
                "SELECT waiting_state, version FROM public.project_waiting_records WHERE waiting_record_id='wait-gate-1'"
            ).fetchone()
            app_count = connection.execute("SELECT count(*) FROM public.human_gate_decision_applications").fetchone()[0]
            events = connection.execute(
                "SELECT event_type FROM public.event_log WHERE project_id='project-1' ORDER BY sequence"
            ).fetchall()
            outbox_count = connection.execute("SELECT count(*) FROM public.outbox_messages").fetchone()[0]
        self.assertEqual(("IMPLEMENTING", None, 9), project)
        self.assertEqual(("RESOLVED", 2), waiting_row)
        self.assertEqual(1, app_count)
        self.assertIn(("human_gate.requested",), events)
        self.assertIn(("project.waiting_entered",), events)
        self.assertIn(("human_gate.approved",), events)
        self.assertIn(("human_gate.decision_applied",), events)
        self.assertIn(("project.resumed",), events)
        self.assertEqual(len(events), outbox_count)

    def test_ct_009_requires_valid_resume_context_before_waiting(self):
        self._seed_project()
        self._seed_policy_require_human("project-1", 7)
        with self.assertRaisesRegex(CommandRejected, "GATE_RESUME_GUARD_FAILED"):
            self.authority.request_gate(
                RequestHumanGate(
                    command_id="cmd-request-invalid-context",
                    idempotency_key="idem-request-invalid-context",
                    project_id="project-1",
                    gate_request_id="gate-invalid",
                    action_scope="project:resume",
                    requester=self.main,
                    expected_project_version=7,
                    resume_context={"context_id": "ctx-invalid"},
                    reason="missing immutable context hash",
                    policy_decision_id="policy-require-human",
                    expires_at="2099-01-01T00:00:00+00:00",
                )
            )
        with self.assertRaisesRegex(CommandRejected, "GATE_REQUEST_NOT_FOUND"):
            self.authority.enter_project_waiting(
                EnterProjectWaitingForGate(
                    command_id="cmd-wait-missing",
                    idempotency_key="idem-wait-missing",
                    project_id="project-1",
                    waiting_record_id="wait-missing",
                    gate_request_id="gate-missing",
                    resume_context_id="ctx-missing",
                    expected_project_version=7,
                    blocking_reason="missing request",
                )
            )

    def test_ct_010_exhaustion_gate_requires_attempt_ledger_options_and_recommendation(self):
        self._seed_project()
        with self.assertRaisesRegex(CommandRejected, "GATE_RESUME_GUARD_FAILED"):
            self._request("gate-exhaustion-bad", policy_id=None, request_type="exhaustion")
        result = self._request(
            "gate-exhaustion-good",
            policy_id=None,
            request_type="exhaustion",
            attempt_ledger=({"attempt": 1, "result": "FAIL"},),
            remaining_options=({"option": "ask-human"},),
            recommended_option="ask-human",
        )
        self.assertEqual("HUMAN_GATE_REQUESTED", result["result_code"])

    def test_worker_or_main_hermes_cannot_self_approve(self):
        self._seed_project()
        self._seed_policy_require_human("project-1", 7)
        self._request()
        self.store.seed_human_authorization(
            "assert-main", "main-hermes", "project-1", "gate-1", "project:resume"
        )
        with self.assertRaisesRegex(CommandRejected, "GATE_APPROVER_UNAUTHORIZED|GATE_SELF_APPROVAL_FORBIDDEN"):
            self.authority.submit_decision(
                SubmitHumanGateDecision(
                    command_id="cmd-main-approve",
                    idempotency_key="idem-main-approve",
                    project_id="project-1",
                    gate_decision_id="decision-main",
                    gate_request_id="gate-1",
                    decision="APPROVE",
                    approver=self.main,
                    authorization_ref="test-authz:main",
                    assertion_id="assert-main",
                    assertion_hash="sha256:test-assertion",
                    reason="main tries to approve",
                    expires_at="2099-01-01T00:00:00+00:00",
                    actor_type="main_hermes",
                    actor_id="main-hermes",
                )
            )

    def test_resume_rechecks_current_guard_and_rejects_stale_or_missing_facts(self):
        self._seed_project()
        self._seed_policy_require_human("project-1", 7)
        self._request()
        self._enter_waiting()
        self._approve()
        with self.assertRaisesRegex(CommandRejected, "GATE_EVIDENCE_INVALID"):
            self._apply()

    def test_idempotency_duplicate_and_payload_conflict_are_stable(self):
        self._seed_project()
        self._seed_policy_require_human("project-1", 7)
        first = self._request()
        second = self._request()
        self.assertEqual(first, second)
        with self.assertRaisesRegex(CommandRejected, "IDEMPOTENCY_PAYLOAD_CONFLICT"):
            self._request(gate_request_id="gate-2", idempotency_key="idem-request-gate-1")

    def test_reject_expire_cancel_and_supersede_are_terminal(self):
        self._seed_project()
        self._seed_policy_require_human("project-1", 7)
        self._request("gate-reject")
        self._enter_waiting("gate-reject")
        self.store.seed_human_authorization(
            "assert-reject", "human-approver", "project-1", "gate-reject", "project:resume"
        )
        rejected = self.authority.submit_decision(
            SubmitHumanGateDecision(
                command_id="cmd-reject",
                idempotency_key="idem-reject",
                project_id="project-1",
                gate_decision_id="decision-reject",
                gate_request_id="gate-reject",
                decision="REJECT",
                approver=self.user,
                authorization_ref="test-authz:reject",
                assertion_id="assert-reject",
                assertion_hash="sha256:test-assertion",
                reason="reject",
                expires_at="2099-01-01T00:00:00+00:00",
                actor_type=self.user.actor_type.value,
                actor_id=self.user.actor_id,
            )
        )
        self.assertEqual("HUMAN_GATE_REJECTED", rejected["result_code"])
        with self.assertRaisesRegex(CommandRejected, "GATE_DECISION_NOT_APPROVED"):
            self._apply("gate-reject", "decision-reject")

        self.store.reset_for_test()
        self._seed_project()
        self._seed_policy_require_human("project-1", 7)
        self._request("gate-expire")
        with self._admin_connection() as connection:
            connection.execute(
                """UPDATE public.human_gate_requests
                   SET created_at=clock_timestamp() - interval '2 seconds',
                       expires_at=clock_timestamp() - interval '1 second'
                   WHERE gate_request_id='gate-expire'"""
            )
        expired = self.authority.expire_request(
            ExpireHumanGateRequest(
                command_id="cmd-expire",
                idempotency_key="idem-expire",
                project_id="project-1",
                gate_request_id="gate-expire",
            )
        )
        self.assertEqual("HUMAN_GATE_EXPIRED", expired["result_code"])

        self.store.reset_for_test()
        self._seed_project()
        self._seed_policy_require_human("project-1", 7)
        self._request("gate-cancel")
        cancelled = self.authority.cancel_request(
            CancelHumanGateRequest(
                command_id="cmd-cancel",
                idempotency_key="idem-cancel",
                project_id="project-1",
                gate_request_id="gate-cancel",
                authorization_ref="operator-authz",
            )
        )
        self.assertEqual("HUMAN_GATE_CANCELLED", cancelled["result_code"])

        self.store.reset_for_test()
        self._seed_project()
        self._seed_policy_require_human("project-1", 7)
        self._request("gate-old")
        self._request("gate-new")
        superseded = self.authority.supersede_request(
            SupersedeHumanGateRequest(
                command_id="cmd-supersede",
                idempotency_key="idem-supersede",
                project_id="project-1",
                old_gate_request_id="gate-old",
                new_gate_request_id="gate-new",
            )
        )
        self.assertEqual("HUMAN_GATE_SUPERSEDED", superseded["result_code"])

    def test_concurrent_approve_reject_only_one_current_decision_wins(self):
        self._seed_project()
        self._seed_policy_require_human("project-1", 7)
        self._request()
        self.store.seed_human_authorization(
            "assert-approve", "human-approver", "project-1", "gate-1", "project:resume"
        )
        self.store.seed_human_authorization(
            "assert-reject", "operator-1", "project-1", "gate-1", "project:resume"
        )
        results = []

        def decide(decision, decision_id, actor, assertion_id):
            try:
                self.authority.submit_decision(
                    SubmitHumanGateDecision(
                        command_id="cmd-concurrent-" + decision_id,
                        idempotency_key="idem-concurrent-" + decision_id,
                        project_id="project-1",
                        gate_decision_id=decision_id,
                        gate_request_id="gate-1",
                        decision=decision,
                        approver=actor,
                        authorization_ref="test-authz:" + decision_id,
                        assertion_id=assertion_id,
                        assertion_hash="sha256:test-assertion",
                        reason=decision.lower(),
                        expires_at="2099-01-01T00:00:00+00:00",
                        actor_type=actor.actor_type.value,
                        actor_id=actor.actor_id,
                    )
                )
                results.append("ok")
            except CommandRejected as exc:
                results.append(str(exc))

        threads = (
            threading.Thread(target=decide, args=("APPROVE", "decision-approve", self.user, "assert-approve")),
            threading.Thread(
                target=decide,
                args=("REJECT", "decision-reject", Actor(ActorType.USER, "operator-1"), "assert-reject"),
            ),
        )
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        with self._admin_connection() as connection:
            current_count = connection.execute(
                "SELECT count(*) FROM public.human_gate_decisions WHERE gate_request_id='gate-1' AND decision_state='CURRENT'"
            ).fetchone()[0]
        self.assertEqual(1, current_count)
        self.assertEqual(1, results.count("ok"))

    def test_precommit_faults_rollback_without_orphan_state_and_retry_is_safe(self):
        self._seed_project()
        self._seed_policy_require_human("project-1", 7)
        self.store.fail_human_gate_once("after_request_before_event")
        with self.assertRaisesRegex(CommandRejected, "INJECTED_HUMAN_GATE_CRASH_AFTER_REQUEST"):
            self._request("gate-fault")
        with self._admin_connection() as connection:
            self.assertEqual(
                0,
                connection.execute("SELECT count(*) FROM public.human_gate_requests").fetchone()[0],
            )
        retried = self._request("gate-fault")
        self.assertEqual("HUMAN_GATE_REQUESTED", retried["result_code"])

        self.store.fail_human_gate_once("after_waiting_before_context")
        with self.assertRaisesRegex(CommandRejected, "INJECTED_HUMAN_GATE_CRASH_AFTER_WAITING"):
            self._enter_waiting("gate-fault")
        with self._admin_connection() as connection:
            project = connection.execute("SELECT state, version FROM public.projects WHERE project_id='project-1'").fetchone()
            waiting_count = connection.execute("SELECT count(*) FROM public.project_waiting_records").fetchone()[0]
        self.assertEqual(("IMPLEMENTING", 7), project)
        self.assertEqual(0, waiting_count)


if __name__ == "__main__":
    unittest.main()
