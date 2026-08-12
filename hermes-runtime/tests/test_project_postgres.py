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
    CancelProject,
    CreateProject,
    PauseProject,
    RequestProjectTransition,
    ResumeProject,
)
from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.application.handlers import ControlPlane
from hermes_runtime.domain.models import Actor, ActorType, CommandEnvelope, ProjectState
from hermes_runtime.infrastructure.postgres import FaultPoint
from hermes_runtime.infrastructure.postgres_project import PostgresProjectStore


DATABASE_URL = os.environ.get("HERMES_TEST_DATABASE_URL")


def envelope(command_type, actor, expected_version, key, reason="project test"):
    return CommandEnvelope(
        command_id="cmd-" + str(uuid.uuid4()),
        command_type=command_type,
        idempotency_key=key,
        expected_version=expected_version,
        actor=actor,
        reason=reason,
        project_id="project-1",
    )


@unittest.skipUnless(
    DATABASE_URL and psycopg,
    "requires psycopg and explicit HERMES_TEST_DATABASE_URL pointing to PostgreSQL 14+",
)
class ProjectPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = PostgresProjectStore(DATABASE_URL)
        cls.store.check_server_version(140000)
        migrations = Path(__file__).parents[1] / "migrations"
        for migration in sorted(migrations.glob("*.sql")):
            cls.store.apply_migration(migration)

    def setUp(self):
        self.store.reset_for_test()
        self.plane = ControlPlane(self.store)
        self.control = Actor(ActorType.CONTROL_PLANE, "project-manager")
        self.user = Actor(ActorType.USER, "user-1")
        self.main = Actor(ActorType.MAIN_HERMES, "main-hermes-1")

    def create_command(self, key="create-project", actor=None, requester=None, reason="create"):
        return CreateProject(
            envelope("project.create", actor or self.control, 0, key, reason),
            "Hermes Project",
            requester or self.user,
        )

    def transition_command(
        self,
        target,
        version,
        key,
        actor=None,
        requester=None,
        supporting_refs=(),
        reason="advance",
    ):
        return RequestProjectTransition(
            envelope(
                "project.request_transition",
                actor or self.control,
                version,
                key,
                reason,
            ),
            target,
            requester or self.main,
            supporting_refs,
        )

    def create_project(self):
        return self.plane.create_project(self.create_command())

    def advance_to(self, target):
        mainline = (
            ProjectState.CREATED,
            ProjectState.INTAKE,
            ProjectState.DISCOVERY,
            ProjectState.PLANNING,
            ProjectState.DESIGNING,
            ProjectState.IMPLEMENTING,
            ProjectState.VERIFYING,
            ProjectState.HARDENING,
            ProjectState.PACKAGING,
            ProjectState.DELIVERING,
            ProjectState.ACCEPTED,
        )
        if self.store.count("projects") == 0:
            self.create_project()
        project = self.store.read_project("project-1")
        while project.state is not target:
            next_state = mainline[mainline.index(project.state) + 1]
            self.seed_guard_facts(project, next_state)
            self.plane.request_project_transition(
                self.transition_command(
                    next_state,
                    project.version,
                    "advance-{}".format(next_state.value.lower()),
                )
            )
            project = self.store.read_project("project-1")
        return project

    def seed_guard_facts(self, project, target, suffix="", policy_result="ALLOW",
                         budget_status="OK", evidence_result="VALID",
                         gate_status=None, project_id=None, version=None):
        project_id = project_id or project.project_id
        version = project.version if version is None else version
        suffix = suffix or "{}-{}-{}".format(project_id, version, target.value.lower())
        with self._admin_connection() as connection:
            connection.execute(
                """
                INSERT INTO project_evidence_facts
                  (evidence_fact_id, project_id, project_version, from_state, to_state,
                   result, authority, subject_ref)
                VALUES (%s, %s, %s, %s, %s, %s, 'verification_engine', %s)
                """,
                (
                    "evidence-" + suffix,
                    project_id,
                    version,
                    project.state.value,
                    target.value,
                    evidence_result,
                    "subject-" + suffix,
                ),
            )
            connection.execute(
                """
                INSERT INTO project_policy_decision_facts
                  (policy_decision_id, project_id, project_version, from_state,
                   to_state, result, authority, policy_bundle_version, input_hash)
                VALUES (%s, %s, %s, %s, %s, %s, 'policy_engine', 'policy-test', %s)
                """,
                (
                    "policy-" + suffix,
                    project_id,
                    version,
                    project.state.value,
                    target.value,
                    policy_result,
                    "sha256:" + uuid.uuid4().hex,
                ),
            )
            connection.execute(
                """
                INSERT INTO project_budget_facts
                  (budget_fact_id, project_id, project_version, from_state, to_state,
                   status, authority, budget_scope_id, version)
                VALUES (%s, %s, %s, %s, %s, %s, 'budget_engine', %s, 1)
                """,
                (
                    "budget-" + suffix,
                    project_id,
                    version,
                    project.state.value,
                    target.value,
                    budget_status,
                    "budget-" + project_id,
                ),
            )
            if gate_status:
                connection.execute(
                    """
                    INSERT INTO project_gate_decision_facts
                      (gate_decision_id, project_id, project_version, from_state,
                       to_state, status, authority, gate_id, decision_ref)
                    VALUES (%s, %s, %s, %s, %s, %s, 'human_gate', %s, %s)
                    """,
                    (
                        "gate-" + suffix,
                        project_id,
                        version,
                        project.state.value,
                        target.value,
                        gate_status,
                        "gate-" + suffix,
                        "decision-" + suffix,
                    ),
                )
        return (
            "evidence-" + suffix,
            "policy-" + suffix,
            "budget-" + suffix,
            "gate-" + suffix if gate_status else None,
        )

    def test_create_and_transition_commit_state_event_outbox_receipt(self):
        created = self.create_project()
        self.seed_guard_facts(self.store.read_project("project-1"), ProjectState.INTAKE)
        applied = self.plane.request_project_transition(
            self.transition_command(ProjectState.INTAKE, 0, "to-intake")
        )

        project = self.store.read_project("project-1")
        self.assertEqual("PROJECT_CREATED", created.result_code)
        self.assertEqual(ProjectState.INTAKE, project.state)
        self.assertEqual(1, project.version)
        self.assertEqual("PROJECT_TRANSITION_APPLIED", applied.result_code)
        self.assertEqual(2, self.store.count("event_log"))
        self.assertEqual(2, self.store.count("outbox_messages"))
        self.assertEqual(2, self.store.count("command_receipts"))
        self.assertEqual(2, self.store.count("project_transition_records"))

    def test_project_transition_fails_closed_without_authoritative_guard_facts(self):
        self.create_project()
        with self.assertRaisesRegex(CommandRejected, "PROJECT_EVIDENCE_REQUIRED"):
            self.plane.request_project_transition(
                self.transition_command(
                    ProjectState.INTAKE,
                    0,
                    "fake-supporting-refs",
                    supporting_refs=("policy_allowed=true", "budget_available=true"),
                )
            )
        self.assertEqual(ProjectState.CREATED, self.store.read_project("project-1").state)
        self.assertEqual(
            0,
            self.store.scalar(
                "SELECT count(*) FROM event_log WHERE event_type = 'project.state_transition.applied'"
            ),
        )

    def test_guard_facts_must_be_current_project_bound_and_allowed(self):
        self.create_project()
        project = self.store.read_project("project-1")
        scenarios = (
            (
                "invalid-evidence",
                {"evidence_result": "INVALID"},
                "PROJECT_EVIDENCE_INVALID",
            ),
            (
                "policy-deny",
                {"policy_result": "DENY"},
                "PROJECT_POLICY_NOT_ALLOWED",
            ),
            (
                "budget-hard-stop",
                {"budget_status": "HARD_STOP"},
                "PROJECT_BUDGET_HARD_STOP",
            ),
            (
                "gate-not-applied",
                {
                    "policy_result": "REQUIRE_HUMAN",
                    "gate_status": "ANSWERED_NOT_APPLIED",
                },
                "PROJECT_GATE_NOT_APPLIED",
            ),
        )
        for suffix, kwargs, reason in scenarios:
            with self.subTest(reason=reason):
                self.store.reset_for_test()
                self.create_project()
                project = self.store.read_project("project-1")
                self.seed_guard_facts(project, ProjectState.INTAKE, suffix, **kwargs)
                with self.assertRaisesRegex(CommandRejected, reason):
                    self.plane.request_project_transition(
                        self.transition_command(ProjectState.INTAKE, 0, suffix)
                    )
                self.assertEqual(
                    ProjectState.CREATED, self.store.read_project("project-1").state
                )

    def test_other_project_guard_fact_supporting_ref_is_rejected(self):
        self.create_project()
        project = self.store.read_project("project-1")
        with self._admin_connection() as connection:
            connection.execute(
                """
                INSERT INTO command_receipts
                  (command_id, project_id, command_type, idempotency_key,
                   request_hash, status, result, completed_at)
                VALUES ('other-project-command', 'other-project', 'project.create',
                        'other-project-command', 'hash', 'APPLIED', '{}'::jsonb, now());
                INSERT INTO projects
                  (project_id, title, state, version, last_command_id)
                VALUES ('other-project', 'Other', 'CREATED', 0, 'other-project-command');
                INSERT INTO project_graph_versions (project_id, graph_version)
                VALUES ('other-project', 0);
                INSERT INTO event_log
                  (event_id, event_type, schema_version, producer_type, producer_id,
                   project_id, partition_key, command_id, correlation_id, payload)
                VALUES ('other-project-event', 'project.created', '1.0',
                        'control_plane', 'seed', 'other-project', 'other-project',
                        'other-project-command', 'other-project-command',
                        '{"project_version": 0, "new_state": "CREATED"}'::jsonb);
                INSERT INTO outbox_messages
                  (message_id, event_id, topic, partition_key, sequence, payload)
                SELECT 'other-project-message', 'other-project-event',
                       'hermes.runtime.events', 'other-project', sequence,
                       '{"project_version": 0, "new_state": "CREATED"}'::jsonb
                FROM event_log WHERE event_id = 'other-project-event';
                """
            )
        refs = self.seed_guard_facts(
            project, ProjectState.INTAKE, "other-project-ref", project_id="other-project"
        )
        self.seed_guard_facts(project, ProjectState.INTAKE, "local-valid")
        with self.assertRaisesRegex(
            CommandRejected, "PROJECT_GUARD_FACT_PROJECT_MISMATCH"
        ):
            self.plane.request_project_transition(
                self.transition_command(
                    ProjectState.INTAKE,
                    0,
                    "wrong-project-fact",
                    supporting_refs=(refs[0],),
                )
            )

    def test_stale_invalidated_or_superseded_guard_facts_cannot_advance(self):
        cases = (
            (
                "old-version",
                "UPDATE project_evidence_facts SET project_version = 99 WHERE evidence_fact_id = %s",
                "PROJECT_GUARD_FACT_STALE",
            ),
            (
                "invalidated",
                "UPDATE project_evidence_facts SET valid = false, invalidated_at = now() WHERE evidence_fact_id = %s",
                "PROJECT_GUARD_FACT_STALE",
            ),
            (
                "superseded",
                "UPDATE project_evidence_facts SET superseded_by = evidence_fact_id WHERE evidence_fact_id = %s",
                "PROJECT_GUARD_FACT_STALE",
            ),
        )
        for suffix, mutation, reason in cases:
            with self.subTest(reason=reason):
                self.store.reset_for_test()
                self.create_project()
                project = self.store.read_project("project-1")
                refs = self.seed_guard_facts(project, ProjectState.INTAKE, suffix)
                with self._admin_connection() as connection:
                    connection.execute(mutation, (refs[0],))
                with self.assertRaisesRegex(CommandRejected, reason):
                    self.plane.request_project_transition(
                        self.transition_command(
                            ProjectState.INTAKE,
                            0,
                            suffix,
                            supporting_refs=(refs[0],),
                        )
                    )
                self.assertEqual(
                    ProjectState.CREATED, self.store.read_project("project-1").state
                )

    def test_concurrent_guard_fact_invalidation_is_rechecked_before_transition(self):
        self.create_project()
        project = self.store.read_project("project-1")
        refs = self.seed_guard_facts(project, ProjectState.INTAKE, "evidence-race")
        fact_locked = threading.Event()
        release_fact = threading.Event()
        outcome = []

        def invalidate_fact():
            with self._admin_connection() as connection:
                connection.execute(
                    """
                    UPDATE project_evidence_facts
                    SET valid = false, invalidated_at = now()
                    WHERE evidence_fact_id = %s
                    """,
                    (refs[0],),
                )
                fact_locked.set()
                release_fact.wait(timeout=5)

        thread = threading.Thread(target=invalidate_fact)
        thread.start()
        self.assertTrue(fact_locked.wait(timeout=5))

        def transition():
            plane = ControlPlane(PostgresProjectStore(DATABASE_URL))
            try:
                plane.request_project_transition(
                    self.transition_command(
                        ProjectState.INTAKE,
                        0,
                        "evidence-race",
                        supporting_refs=(refs[0], refs[1], refs[2]),
                    )
                )
                outcome.append("APPLIED")
            except CommandRejected as exc:
                outcome.append(exc.code)

        transition_thread = threading.Thread(target=transition)
        transition_thread.start()
        release_fact.set()
        thread.join()
        transition_thread.join()
        self.assertEqual(["PROJECT_GUARD_FACT_STALE"], outcome)
        self.assertEqual(ProjectState.CREATED, self.store.read_project("project-1").state)

    def test_concurrent_policy_supersede_is_rechecked_before_transition(self):
        self.create_project()
        project = self.store.read_project("project-1")
        refs = self.seed_guard_facts(project, ProjectState.INTAKE, "policy-race")
        fact_locked = threading.Event()
        release_fact = threading.Event()
        outcome = []

        def supersede_policy():
            with self._admin_connection() as connection:
                connection.execute(
                    """
                    UPDATE project_policy_decision_facts
                    SET superseded_by = policy_decision_id
                    WHERE policy_decision_id = %s
                    """,
                    (refs[1],),
                )
                fact_locked.set()
                release_fact.wait(timeout=5)

        thread = threading.Thread(target=supersede_policy)
        thread.start()
        self.assertTrue(fact_locked.wait(timeout=5))

        def transition():
            plane = ControlPlane(PostgresProjectStore(DATABASE_URL))
            try:
                plane.request_project_transition(
                    self.transition_command(
                        ProjectState.INTAKE,
                        0,
                        "policy-race",
                        supporting_refs=(refs[0], refs[1], refs[2]),
                    )
                )
                outcome.append("APPLIED")
            except CommandRejected as exc:
                outcome.append(exc.code)

        transition_thread = threading.Thread(target=transition)
        transition_thread.start()
        release_fact.set()
        thread.join()
        transition_thread.join()
        self.assertEqual(["PROJECT_GUARD_FACT_STALE"], outcome)
        self.assertEqual(ProjectState.CREATED, self.store.read_project("project-1").state)

    def test_require_human_policy_allows_transition_only_with_applied_gate(self):
        self.create_project()
        project = self.store.read_project("project-1")
        self.seed_guard_facts(
            project,
            ProjectState.INTAKE,
            "human-required",
            policy_result="REQUIRE_HUMAN",
            gate_status="ANSWERED_APPLIED",
        )
        receipt = self.plane.request_project_transition(
            self.transition_command(ProjectState.INTAKE, 0, "human-required")
        )
        self.assertEqual("PROJECT_TRANSITION_APPLIED", receipt.result_code)
        self.assertEqual(ProjectState.INTAKE, self.store.read_project("project-1").state)

    def test_pause_resume_and_cancel_use_semantic_targets(self):
        self.advance_to(ProjectState.IMPLEMENTING)
        project = self.store.read_project("project-1")
        self.seed_guard_facts(project, ProjectState.PAUSED, "pause")
        self.plane.pause_project(
            PauseProject(
                envelope("project.pause", self.control, project.version, "pause"),
                self.user,
                "auth-user-pause",
            )
        )
        paused = self.store.read_project("project-1")
        self.assertEqual(ProjectState.PAUSED, paused.state)
        self.assertEqual(ProjectState.IMPLEMENTING, paused.resume_state)

        self.seed_guard_facts(paused, ProjectState.IMPLEMENTING, "resume")
        self.plane.resume_project(
            ResumeProject(
                envelope("project.resume", self.control, paused.version, "resume"),
                self.user,
                "auth-user-resume",
            )
        )
        resumed = self.store.read_project("project-1")
        self.assertEqual(ProjectState.IMPLEMENTING, resumed.state)
        self.assertIsNone(resumed.resume_state)

        self.seed_guard_facts(resumed, ProjectState.PAUSED, "pause-again")
        self.plane.pause_project(
            PauseProject(
                envelope("project.pause", self.control, resumed.version, "pause-again"),
                self.user,
                "auth-user-pause-again",
            )
        )
        paused_again = self.store.read_project("project-1")
        self.plane.cancel_project(
            CancelProject(
                envelope(
                    "project.cancel", self.control, paused_again.version, "cancel"
                ),
                self.user,
                "auth-user-cancel",
            )
        )
        self.assertEqual(
            ProjectState.CANCELLED, self.store.read_project("project-1").state
        )
        self.assertEqual(
            2,
            self.store.scalar(
                "SELECT count(*) FROM event_log WHERE event_type = 'project.paused'"
            ),
        )
        self.assertEqual(
            1,
            self.store.scalar(
                "SELECT count(*) FROM event_log WHERE event_type = 'project.resumed'"
            ),
        )
        self.assertEqual(
            1,
            self.store.scalar(
                "SELECT count(*) FROM event_log WHERE event_type = 'project.cancelled'"
            ),
        )

    def test_illegal_terminal_and_duplicate_semantic_actions_are_audited(self):
        self.advance_to(ProjectState.IMPLEMENTING)
        project = self.store.read_project("project-1")
        self.seed_guard_facts(project, ProjectState.DELIVERING, "illegal-skip")
        with self.assertRaisesRegex(CommandRejected, "ILLEGAL_PROJECT_TRANSITION"):
            self.plane.request_project_transition(
                self.transition_command(
                    ProjectState.DELIVERING, project.version, "illegal-skip"
                )
            )
        self.seed_guard_facts(project, ProjectState.PAUSED, "pause")
        self.plane.pause_project(
            PauseProject(
                envelope("project.pause", self.control, project.version, "pause"),
                self.user,
            )
        )
        paused = self.store.read_project("project-1")
        with self.assertRaisesRegex(CommandRejected, "PROJECT_ALREADY_PAUSED"):
            self.plane.pause_project(
                PauseProject(
                    envelope("project.pause", self.control, paused.version, "pause-again"),
                    self.user,
                )
            )
        self.assertEqual(ProjectState.PAUSED, self.store.read_project("project-1").state)
        self.assertEqual(2, self.store.count("audit_records"))

    def test_actor_matrix_rejects_direct_state_submitters_and_requesters(self):
        self.create_project()
        self.seed_guard_facts(self.store.read_project("project-1"), ProjectState.INTAKE)
        direct_actors = (
            Actor(ActorType.USER, "user-direct"),
            Actor(ActorType.MAIN_HERMES, "main-direct"),
            Actor(ActorType.WORKER, "worker-direct"),
            Actor(ActorType.VERIFIER, "verifier-direct"),
            Actor(ActorType.SCHEDULER, "scheduler-direct"),
            Actor(ActorType.RECOVERY_CONTROLLER, "recovery-direct"),
        )
        for index, actor in enumerate(direct_actors):
            with self.subTest(actor=actor.actor_type):
                with self.assertRaisesRegex(
                    CommandRejected, "CONTROL_PLANE_AUTHORITY_REQUIRED"
                ):
                    self.plane.request_project_transition(
                        self.transition_command(
                            ProjectState.INTAKE,
                            0,
                            "direct-{}".format(index),
                            actor=actor,
                            requester=actor,
                        )
                    )
        for index, requester in enumerate(
            (
                Actor(ActorType.WORKER, "worker-request"),
                Actor(ActorType.VERIFIER, "verifier-request"),
                Actor(ActorType.SCHEDULER, "scheduler-request"),
            )
        ):
            with self.subTest(requester=requester.actor_type):
                with self.assertRaisesRegex(
                    CommandRejected, "PROJECT_REQUESTER_NOT_AUTHORIZED"
                ):
                    self.plane.request_project_transition(
                        self.transition_command(
                            ProjectState.INTAKE,
                            0,
                            "requester-{}".format(index),
                            requester=requester,
                        )
                    )
        project = self.store.read_project("project-1")
        self.assertEqual(ProjectState.CREATED, project.state)
        self.assertEqual(0, project.version)
        self.assertEqual(0, self.store.scalar(
            "SELECT count(*) FROM event_log WHERE event_type = 'project.state_transition.applied'"
        ))
        self.assertEqual(9, self.store.count("audit_records"))

    def test_missing_reason_and_cancel_authorization_are_rejected(self):
        self.create_project()
        missing_actor = self.transition_command(
            ProjectState.INTAKE, 0, "missing-actor"
        )
        missing_actor = RequestProjectTransition(
            CommandEnvelope(
                missing_actor.envelope.command_id,
                missing_actor.envelope.command_type,
                missing_actor.envelope.idempotency_key,
                missing_actor.envelope.expected_version,
                None,
                missing_actor.envelope.reason,
                missing_actor.envelope.project_id,
            ),
            missing_actor.target_state,
            missing_actor.requested_by,
        )
        with self.assertRaisesRegex(
            CommandRejected, "CONTROL_PLANE_AUTHORITY_REQUIRED"
        ):
            self.plane.request_project_transition(missing_actor)
        with self.assertRaisesRegex(CommandRejected, "COMMAND_REASON_REQUIRED"):
            self.plane.request_project_transition(
                self.transition_command(ProjectState.INTAKE, 0, "empty-reason", reason="")
            )
        with self.assertRaisesRegex(
            CommandRejected, "CANCELLATION_AUTHORIZATION_REQUIRED"
        ):
            self.plane.cancel_project(
                CancelProject(
                    envelope("project.cancel", self.control, 0, "no-auth"),
                    self.user,
                    "",
                )
            )
        self.assertEqual(ProjectState.CREATED, self.store.read_project("project-1").state)
        self.assertEqual(3, self.store.count("audit_records"))

    def test_command_type_must_match_semantic_handler(self):
        self.create_project()
        self.seed_guard_facts(self.store.read_project("project-1"), ProjectState.INTAKE)
        mismatched = self.transition_command(
            ProjectState.INTAKE, 0, "wrong-command-type"
        )
        mismatched = RequestProjectTransition(
            CommandEnvelope(
                mismatched.envelope.command_id,
                "project.cancel",
                mismatched.envelope.idempotency_key,
                mismatched.envelope.expected_version,
                mismatched.envelope.actor,
                mismatched.envelope.reason,
                mismatched.envelope.project_id,
            ),
            mismatched.target_state,
            mismatched.requested_by,
        )
        with self.assertRaisesRegex(
            CommandRejected, "PROJECT_COMMAND_SEMANTICS_MISMATCH"
        ):
            self.plane.request_project_transition(mismatched)
        self.assertEqual(ProjectState.CREATED, self.store.read_project("project-1").state)
        self.assertEqual(1, self.store.count("audit_records"))

    def test_idempotency_version_conflict_and_independent_connection_race(self):
        self.create_project()
        self.seed_guard_facts(self.store.read_project("project-1"), ProjectState.INTAKE)
        first_command = self.transition_command(ProjectState.INTAKE, 0, "same-key")
        first = self.plane.request_project_transition(first_command)
        retry = self.transition_command(ProjectState.INTAKE, 0, "same-key")
        second = self.plane.request_project_transition(retry)
        self.assertEqual(first, second)

        with self.assertRaisesRegex(CommandRejected, "IDEMPOTENCY_CONFLICT"):
            self.plane.request_project_transition(
                self.transition_command(ProjectState.DISCOVERY, 0, "same-key")
            )
        with self.assertRaisesRegex(CommandRejected, "VERSION_CONFLICT"):
            self.plane.request_project_transition(
                self.transition_command(ProjectState.DISCOVERY, 0, "stale-version")
            )

        self.seed_guard_facts(self.store.read_project("project-1"), ProjectState.DISCOVERY)

        barrier = threading.Barrier(2)
        outcomes = []

        def run(key):
            plane = ControlPlane(PostgresProjectStore(DATABASE_URL))
            command = self.transition_command(ProjectState.DISCOVERY, 1, key)
            barrier.wait()
            try:
                plane.request_project_transition(command)
                outcomes.append("APPLIED")
            except CommandRejected as exc:
                outcomes.append(exc.code)

        threads = [
            threading.Thread(target=run, args=("race-a",)),
            threading.Thread(target=run, args=("race-b",)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(1, outcomes.count("APPLIED"))
        self.assertEqual(1, outcomes.count("VERSION_CONFLICT"))
        project = self.store.read_project("project-1")
        self.assertEqual(ProjectState.DISCOVERY, project.state)
        self.assertEqual(2, project.version)
        self.assertEqual(3, self.store.count("outbox_messages"))

    def test_every_precommit_fault_rolls_back_project_event_outbox_and_receipt(self):
        points = (
            FaultPoint.BEFORE_PROJECT_UPDATE,
            FaultPoint.AFTER_PROJECT_UPDATE_BEFORE_EVENT,
            FaultPoint.AFTER_EVENT_BEFORE_OUTBOX,
            FaultPoint.AFTER_PROJECT_OUTBOX_BEFORE_RECEIPT,
            FaultPoint.BEFORE_PROJECT_COMMIT,
        )
        for index, point in enumerate(points):
            with self.subTest(point=point):
                self.store.reset_for_test()
                self.create_project()
                self.seed_guard_facts(
                    self.store.read_project("project-1"), ProjectState.INTAKE,
                    "fault-{}".format(index)
                )
                self.store.fail_once(point)
                with self.assertRaisesRegex(RuntimeError, "injected"):
                    self.plane.request_project_transition(
                        self.transition_command(
                            ProjectState.INTAKE, 0, "fault-{}".format(index)
                        )
                    )
                project = self.store.read_project("project-1")
                self.assertEqual(ProjectState.CREATED, project.state)
                self.assertEqual(0, project.version)
                self.assertEqual(1, self.store.count("event_log"))
                self.assertEqual(1, self.store.count("outbox_messages"))
                self.assertEqual(1, self.store.count("command_receipts"))
                self.assertEqual(1, self.store.count("project_transition_records"))

    def test_task_guard_requires_authoritative_pass_with_current_verification(self):
        self.advance_to(ProjectState.VERIFYING)
        with self._admin_connection() as connection:
            connection.execute(
                """
                INSERT INTO tasks
                  (task_id, project_id, state, version)
                VALUES ('required-task', 'project-1', 'COMPLETION_CLAIMED', 1),
                       ('unrelated-task', 'other-project', 'BLOCKED', 1)
                """
            )
        project = self.store.read_project("project-1")
        self.seed_guard_facts(project, ProjectState.HARDENING, "blocked-task")
        with self.assertRaisesRegex(CommandRejected, "REQUIRED_TASKS_NOT_PASSED"):
            self.plane.request_project_transition(
                self.transition_command(
                    ProjectState.HARDENING, project.version, "blocked-task"
                )
            )
        self.assertEqual(ProjectState.VERIFYING, self.store.read_project("project-1").state)

    def test_task_guard_accepts_only_current_hash_pass_and_ignores_other_project(self):
        self.advance_to(ProjectState.VERIFYING)
        self.store.seed_passed_task_authority("required-task", 3)
        with self._admin_connection() as connection:
            connection.execute(
                """
                INSERT INTO tasks
                  (task_id, project_id, state, version, current_artifact_id,
                   current_artifact_hash, current_verification_id)
                VALUES ('other-blocked', 'other-project', 'BLOCKED', 1,
                        NULL, NULL, NULL);
                SET CONSTRAINTS ALL IMMEDIATE;
                """
            )
        project = self.store.read_project("project-1")
        self.seed_guard_facts(project, ProjectState.HARDENING, "verified-tasks")
        self.plane.request_project_transition(
            self.transition_command(
                ProjectState.HARDENING,
                project.version,
                "verified-tasks-complete",
                supporting_refs=("verification-required-task",),
            )
        )
        self.assertEqual(
            ProjectState.HARDENING, self.store.read_project("project-1").state
        )

    def test_passed_label_with_stale_verification_hash_cannot_advance_project(self):
        self.advance_to(ProjectState.VERIFYING)
        with self.assertRaisesRegex(
            psycopg.errors.RaiseException,
            "TASK_PASS_VERIFICATION_AUTHORITY_INVARIANT_VIOLATION",
        ):
            with self._admin_connection() as connection:
                connection.execute(
                """
                INSERT INTO verifier_identities (verifier_id, active)
                VALUES ('verifier-stale', true);
                INSERT INTO command_receipts
                  (command_id, project_id, command_type, idempotency_key,
                   request_hash, status, result, completed_at)
                VALUES ('stale-fact-command', 'project-1', 'test.stale_fact',
                        'stale-fact', 'hash', 'APPLIED', '{}'::jsonb, now());
                INSERT INTO tasks
                  (task_id, project_id, state, version, current_artifact_id,
                   current_artifact_hash, current_verification_id)
                VALUES ('stale-task', 'project-1', 'PASSED', 3,
                        'stale-artifact', 'sha256:current',
                        'stale-verification');
                INSERT INTO artifacts
                  (artifact_id, task_id, content_hash, media_type, produced_by)
                VALUES ('stale-artifact', 'stale-task', 'sha256:current',
                        'text/plain', 'worker-stale');
                INSERT INTO verification_results
                  (verification_id, task_id, artifact_id, artifact_hash,
                   verifier_identity, criteria, verdict, correlation_id,
                   occurred_at, command_id)
                VALUES ('stale-verification', 'stale-task', 'stale-artifact',
                        'sha256:old', 'verifier-stale', 'stale-criteria', 'PASS',
                        'stale-correlation', now(), 'stale-fact-command');
                SET CONSTRAINTS ALL IMMEDIATE;
                """
                )
        self.assertEqual(ProjectState.VERIFYING, self.store.read_project("project-1").state)

    def test_concurrent_task_change_is_revalidated_before_project_transition(self):
        self.advance_to(ProjectState.VERIFYING)
        self.store.seed_passed_task_authority("required-task", 3)
        project = self.store.read_project("project-1")
        self.seed_guard_facts(project, ProjectState.HARDENING, "task-race")
        task_locked = threading.Event()
        release_task = threading.Event()
        outcome = []

        def invalidate_task():
            with self._admin_connection() as connection:
                connection.execute(
                    "UPDATE tasks SET state = 'BLOCKED' WHERE task_id = 'required-task'"
                )
                task_locked.set()
                release_task.wait(timeout=5)

        thread = threading.Thread(target=invalidate_task)
        thread.start()
        self.assertTrue(task_locked.wait(timeout=5))

        def transition():
            plane = ControlPlane(PostgresProjectStore(DATABASE_URL))
            try:
                plane.request_project_transition(
                    self.transition_command(
                        ProjectState.HARDENING,
                        project.version,
                        "task-race-revalidate",
                    )
                )
                outcome.append("APPLIED")
            except CommandRejected as exc:
                outcome.append(exc.code)

        transition_thread = threading.Thread(target=transition)
        transition_thread.start()
        release_task.set()
        thread.join()
        transition_thread.join()

        self.assertEqual(["REQUIRED_TASKS_NOT_PASSED"], outcome)
        self.assertEqual(ProjectState.VERIFYING, self.store.read_project("project-1").state)

    def _admin_connection(self):
        return psycopg.connect(DATABASE_URL)


if __name__ == "__main__":
    if not DATABASE_URL:
        raise SystemExit("HERMES_TEST_DATABASE_URL is required for integration tests")
    unittest.main()
