import unittest

from hermes_runtime.domain.models import Project, ProjectState
from hermes_runtime.domain.project_state_machine import (
    LEGAL_ADVANCES,
    AUTHORITY_BUDGET,
    AUTHORITY_EVIDENCE,
    AUTHORITY_GATE,
    AUTHORITY_POLICY,
    ProjectAction,
    ProjectGuardContext,
    ProjectGuardFactSummary,
    ProjectGuardRejected,
    evaluate_project_transition,
    project_transition_requirements,
)


class ProjectStateMachineTests(unittest.TestCase):
    def project(self, state, resume_state=None):
        return Project("project-1", state, 4, resume_state)

    def fact(self, kind, result, project_id="project-1", version=4, valid=True, current=True):
        authority = {
            "evidence": AUTHORITY_EVIDENCE,
            "policy": AUTHORITY_POLICY,
            "budget": AUTHORITY_BUDGET,
            "gate": AUTHORITY_GATE,
        }[kind]
        return ProjectGuardFactSummary(
            "{}-fact".format(kind),
            project_id,
            version,
            valid,
            current,
            authority,
            result,
            ("{}-fact".format(kind),),
        )

    def guard(self, **overrides):
        context = {
            "project_id": "project-1",
            "project_version": 4,
            "evidence": self.fact("evidence", "VALID"),
            "policy": self.fact("policy", "ALLOW"),
            "budget": self.fact("budget", "OK"),
            "gate": None,
            "requires_human_gate": False,
            "required_tasks_passed": True,
            "fact_refs": ("evidence-fact", "policy-fact", "budget-fact"),
        }
        context.update(overrides)
        return ProjectGuardContext(**context)

    def test_every_normative_mainline_transition(self):
        for source, target in LEGAL_ADVANCES:
            with self.subTest(source=source, target=target):
                decision = evaluate_project_transition(
                    self.project(source), ProjectAction.ADVANCE, target,
                    self.guard(project_version=4)
                )
                self.assertEqual(target, decision.target_state)

    def test_illegal_skip_and_same_state_have_stable_reason(self):
        scenarios = (
            (ProjectState.CREATED, ProjectState.PLANNING),
            (ProjectState.INTAKE, ProjectState.INTAKE),
            (ProjectState.IMPLEMENTING, ProjectState.DELIVERING),
        )
        for source, target in scenarios:
            with self.subTest(source=source, target=target):
                with self.assertRaisesRegex(
                    ProjectGuardRejected, "ILLEGAL_PROJECT_TRANSITION"
                ):
                    evaluate_project_transition(
                        self.project(source), ProjectAction.ADVANCE, target,
                        self.guard()
                    )

    def test_all_terminal_states_reject_exit(self):
        for state in (
            ProjectState.ACCEPTED,
            ProjectState.FAILED,
            ProjectState.CANCELLED,
        ):
            with self.subTest(state=state):
                with self.assertRaisesRegex(ProjectGuardRejected, "PROJECT_TERMINAL"):
                    evaluate_project_transition(
                        self.project(state), ProjectAction.ADVANCE, ProjectState.INTAKE,
                        self.guard()
                    )

    def test_pause_and_resume_preserve_exact_context(self):
        paused = evaluate_project_transition(
            self.project(ProjectState.IMPLEMENTING), ProjectAction.PAUSE,
            guard=self.guard()
        )
        self.assertEqual(ProjectState.PAUSED, paused.target_state)
        self.assertEqual(ProjectState.IMPLEMENTING, paused.resume_state)

        resumed = evaluate_project_transition(
            self.project(ProjectState.PAUSED, paused.resume_state),
            ProjectAction.RESUME,
            guard=self.guard(),
        )
        self.assertEqual(ProjectState.IMPLEMENTING, resumed.target_state)
        self.assertIsNone(resumed.resume_state)

    def test_resume_without_context_and_duplicate_pause_are_rejected(self):
        with self.assertRaisesRegex(
            ProjectGuardRejected, "PROJECT_RESUME_CONTEXT_MISSING"
        ):
            evaluate_project_transition(
                self.project(ProjectState.PAUSED), ProjectAction.RESUME,
                guard=self.guard()
            )
        with self.assertRaisesRegex(ProjectGuardRejected, "PROJECT_ALREADY_PAUSED"):
            evaluate_project_transition(
                self.project(ProjectState.PAUSED), ProjectAction.PAUSE,
                guard=self.guard()
            )

    def test_cancel_from_active_state_and_reject_terminal_cancel(self):
        decision = evaluate_project_transition(
            self.project(ProjectState.PLANNING), ProjectAction.CANCEL
        )
        self.assertEqual(ProjectState.CANCELLED, decision.target_state)
        with self.assertRaisesRegex(ProjectGuardRejected, "PROJECT_TERMINAL"):
            evaluate_project_transition(
                self.project(ProjectState.ACCEPTED), ProjectAction.CANCEL
            )

    def test_verifying_exit_requires_all_required_tasks_passed(self):
        with self.assertRaisesRegex(
            ProjectGuardRejected, "REQUIRED_TASKS_NOT_PASSED"
        ):
            evaluate_project_transition(
                self.project(ProjectState.VERIFYING),
                ProjectAction.ADVANCE,
                ProjectState.HARDENING,
                self.guard(required_tasks_passed=False),
            )

    def test_mainline_guard_fails_closed_without_authoritative_facts(self):
        scenarios = (
            (
                "missing guard",
                None,
                "PROJECT_GUARD_INPUT_INCOMPLETE",
            ),
            (
                "wrong guard version",
                self.guard(project_version=3),
                "PROJECT_GUARD_INPUT_INCOMPLETE",
            ),
            (
                "missing evidence",
                self.guard(evidence=None),
                "PROJECT_EVIDENCE_REQUIRED",
            ),
            (
                "invalid evidence",
                self.guard(evidence=self.fact("evidence", "INVALID", valid=False)),
                "PROJECT_EVIDENCE_INVALID",
            ),
            (
                "missing policy",
                self.guard(policy=None),
                "PROJECT_POLICY_DECISION_REQUIRED",
            ),
            (
                "policy denied",
                self.guard(policy=self.fact("policy", "DENY")),
                "PROJECT_POLICY_NOT_ALLOWED",
            ),
            (
                "missing budget",
                self.guard(budget=None),
                "PROJECT_BUDGET_FACT_REQUIRED",
            ),
            (
                "budget hard stop",
                self.guard(budget=self.fact("budget", "HARD_STOP")),
                "PROJECT_BUDGET_HARD_STOP",
            ),
            (
                "fact project mismatch",
                self.guard(evidence=self.fact("evidence", "VALID", project_id="other")),
                "PROJECT_GUARD_FACT_PROJECT_MISMATCH",
            ),
            (
                "stale fact",
                self.guard(policy=self.fact("policy", "ALLOW", current=False)),
                "PROJECT_GUARD_FACT_STALE",
            ),
        )
        for _, guard, reason in scenarios:
            with self.subTest(reason=reason):
                with self.assertRaisesRegex(ProjectGuardRejected, reason):
                    evaluate_project_transition(
                        self.project(ProjectState.CREATED),
                        ProjectAction.ADVANCE,
                        ProjectState.INTAKE,
                        guard,
                    )

    def test_require_human_policy_requires_applied_gate(self):
        base = self.guard(policy=self.fact("policy", "REQUIRE_HUMAN"))
        with self.assertRaisesRegex(
            ProjectGuardRejected, "PROJECT_GATE_DECISION_REQUIRED"
        ):
            evaluate_project_transition(
                self.project(ProjectState.PLANNING),
                ProjectAction.ADVANCE,
                ProjectState.DESIGNING,
                base,
            )
        with self.assertRaisesRegex(ProjectGuardRejected, "PROJECT_GATE_NOT_APPLIED"):
            evaluate_project_transition(
                self.project(ProjectState.PLANNING),
                ProjectAction.ADVANCE,
                ProjectState.DESIGNING,
                self.guard(
                    policy=self.fact("policy", "REQUIRE_HUMAN"),
                    gate=self.fact("gate", "ANSWERED_NOT_APPLIED"),
                ),
            )
        decision = evaluate_project_transition(
            self.project(ProjectState.PLANNING),
            ProjectAction.ADVANCE,
            ProjectState.DESIGNING,
            self.guard(
                policy=self.fact("policy", "REQUIRE_HUMAN"),
                gate=self.fact("gate", "ANSWERED_APPLIED"),
            ),
        )
        self.assertEqual(ProjectState.DESIGNING, decision.target_state)

    def test_guard_requirements_are_table_driven_and_deterministic(self):
        self.assertTrue(
            project_transition_requirements(
                ProjectState.CREATED, ProjectAction.ADVANCE, ProjectState.INTAKE
            ).evidence
        )
        self.assertFalse(
            project_transition_requirements(
                ProjectState.CREATED, ProjectAction.CANCEL, ProjectState.CANCELLED
            ).evidence
        )
        guard = self.guard()
        first = evaluate_project_transition(
            self.project(ProjectState.INTAKE),
            ProjectAction.ADVANCE,
            ProjectState.DISCOVERY,
            guard,
        )
        second = evaluate_project_transition(
            self.project(ProjectState.INTAKE),
            ProjectAction.ADVANCE,
            ProjectState.DISCOVERY,
            guard,
        )
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
