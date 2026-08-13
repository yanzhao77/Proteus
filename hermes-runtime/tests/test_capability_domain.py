import unittest

from hermes_runtime.domain.capability import (
    AuthorityRef,
    AvailableWorkerTemplate,
    CapabilityRejected,
    CapabilityRequirement,
    ContextSelector,
    SandboxCompileInput,
    WorkerTemplateRevision,
    build_context_bundle,
    compile_sandbox_profile,
    match_worker_template,
    normalize_capability_name,
    profile_conforms,
    worker_template_content_hash,
)


class CapabilityDomainTests(unittest.TestCase):
    def template(self, template_id="tpl-a", trust="STANDARD", tools=("pytest", "git"),
                 features=None, resources=None, constraints=None, available=True):
        features = features or (
            "network_access", "filesystem_write", "secret_access",
            "production_access", "allowed_tools", "forbidden_paths",
            "max_external_api_calls", "required_mitigations", "lock_scopes",
            "execution_time_ms", "cpu_time_ms", "storage_bytes", "process_count",
            "output_bytes",
        )
        resources = resources or {
            "execution_time_ms": 1000,
            "cpu_time_ms": 800,
            "storage_bytes": 2048,
            "external_api_calls": 0,
        }
        constraints = constraints or {
            "network_access": "disabled",
            "filesystem_write": "none",
            "secret_access": "denied",
            "production_access": "denied",
            "allowed_tools": list(tools),
            "max_external_api_calls": 0,
        }
        return AvailableWorkerTemplate(
            WorkerTemplateRevision(
                template_id, 1, None, "python-process", ("repair.code",),
                trust, tools, features, resources, constraints, 2,
            ),
            availability_status="AVAILABLE" if available else "DISABLED",
            admission_status="ADMISSIBLE" if available else "NOT_ADMISSIBLE",
            availability_version=1,
        )

    def requirement(self, **overrides):
        values = {
            "project_id": "project-1",
            "task_id": "task-1",
            "decision_id": "decision-1",
            "action_id": "action-1",
            "action_type": "repair",
            "action_content_hash": "sha256:action",
            "required_capabilities": ("repair.code",),
            "required_tools": ("pytest",),
            "minimum_trust": "STANDARD",
            "sandbox_requirements": {"network_access": "disabled", "filesystem_write": "none"},
            "resource_envelope": {"execution_time_ms": 500},
            "lock_scopes": ("task:task-1",),
            "mandatory_constraints": ("network_access", "filesystem_write"),
        }
        values.update(overrides)
        return CapabilityRequirement(**values)

    def test_capability_requirement_normalization_matching_and_tie_breaker(self):
        self.assertEqual("repair.code", normalize_capability_name(" Repair.Code "))
        templates = (
            self.template("tpl-b", trust="ELEVATED"),
            self.template("tpl-a", trust="STANDARD"),
        )
        result = match_worker_template(
            self.requirement(), templates, known_capabilities=("repair.code",)
        )
        self.assertEqual("MATCHED", result.reason_code)
        self.assertEqual("tpl-a", result.template_id)
        self.assertTrue(result.requirements_hash.startswith("sha256:"))

    def test_match_fail_closed_reasons_are_distinct(self):
        cases = (
            ("UNAVAILABLE", (self.template(available=False),), {}),
            ("TRUST_INSUFFICIENT", (self.template(trust="UNTRUSTED"),), {}),
            ("TOOL_UNSUPPORTED", (self.template(tools=("git",)),), {}),
            ("SANDBOX_UNSUPPORTED", (self.template(features=("network_access",)),), {}),
            ("RESOURCE_ENVELOPE_UNSUPPORTED", (self.template(resources={"execution_time_ms": 1}),), {}),
            ("UNKNOWN_REQUIREMENT", (self.template(),), {"known_capabilities": ("other",)}),
        )
        for expected, templates, kwargs in cases:
            with self.subTest(expected=expected):
                result = match_worker_template(self.requirement(), templates, **kwargs)
                self.assertEqual(expected, result.reason_code)
                self.assertEqual("NOT_ADMISSIBLE", result.status)

    def test_unknown_trust_and_unknown_mandatory_constraint_reject(self):
        with self.assertRaisesRegex(CapabilityRejected, "CAPABILITY_TRUST_UNKNOWN"):
            match_worker_template(
                self.requirement(minimum_trust="root"), (self.template(),),
                known_capabilities=("repair.code",),
            )
        with self.assertRaisesRegex(CapabilityRejected, "SANDBOX_UNKNOWN_MANDATORY_CONSTRAINT"):
            match_worker_template(
                self.requirement(sandbox_requirements={"unknown_constraint": True}),
                (self.template(),),
                known_capabilities=("repair.code",),
            )

    def test_context_bundle_is_canonical_bounded_scope_and_secret_safe(self):
        selectors = (
            ContextSelector("task", "task-1"),
            ContextSelector("artifact", "artifact-1"),
        )
        refs = (
            AuthorityRef("artifact", "artifact-1", "project-1", "task-1", 1, "sha256:artifact", {}),
            AuthorityRef("task", "task-1", "project-1", "task-1", 7, "sha256:task", {}),
        )
        first = build_context_bundle(
            project_id="project-1", task_id="task-1", decision_id="decision-1",
            action_id="action-1", template_id="tpl-a", template_revision=1,
            selectors=selectors, resolved_refs=refs,
        )
        second = build_context_bundle(
            project_id="project-1", task_id="task-1", decision_id="decision-1",
            action_id="action-1", template_id="tpl-a", template_revision=1,
            selectors=tuple(reversed(selectors)), resolved_refs=tuple(reversed(refs)),
        )
        self.assertEqual(first.manifest_hash, second.manifest_hash)
        with self.assertRaisesRegex(CapabilityRejected, "CONTEXT_REF_TASK_MISMATCH"):
            build_context_bundle(
                project_id="project-1", task_id="task-1", decision_id="decision-1",
                action_id="action-1", template_id="tpl-a", template_revision=1,
                selectors=selectors,
                resolved_refs=(AuthorityRef("task", "task-1", "project-1", "other", 1, "sha256:x", {}),),
            )
        with self.assertRaisesRegex(CapabilityRejected, "SECRET_VALUE_FORBIDDEN"):
            build_context_bundle(
                project_id="project-1", task_id="task-1", decision_id="decision-1",
                action_id="action-1", template_id="tpl-a", template_revision=1,
                selectors=(ContextSelector("evidence", "evidence-1"),),
                resolved_refs=(AuthorityRef("evidence", "evidence-1", "project-1", "task-1", 1, "sha256:e", {"api_token": "sk-123456789012"}),),
            )

    def test_sandbox_compiler_merges_by_tightening_and_conformance_detects_weakening(self):
        template = self.template().template
        context_hash = "sha256:context"
        profile = compile_sandbox_profile(SandboxCompileInput(
            project_id="project-1",
            task_id="task-1",
            action_id="action-1",
            action_content_hash="sha256:action",
            policy_constraints={
                "network_access": {"allowlist": ["api.internal", "metrics.internal"]},
                "filesystem_write": "workspace_only",
                "allowed_tools": ["pytest", "git"],
                "forbidden_paths": ["/etc"],
                "max_external_api_calls": 3,
            },
            risk_required_mitigations=("verification_before_apply",),
            risk_available_mitigations=("verification_before_apply",),
            action_constraints={
                "network_access": {"allowlist": ["api.internal"]},
                "filesystem_write": "none",
                "allowed_tools": ["pytest"],
                "max_external_api_calls": 0,
                "execution_time_ms": 500,
            },
            template=template,
            context_bundle_hash=context_hash,
            lock_scopes=("task:task-1", "artifact:artifact-1"),
        ))
        self.assertEqual("none", profile.profile["filesystem"]["write"])
        self.assertEqual(["pytest"], profile.profile["process"]["allowed_tools"])
        self.assertEqual(0, profile.profile["limits"]["max_external_api_calls"])
        self.assertIn("verification-before-apply", profile.profile["audit"]["required_mitigations"])
        conforms, reasons = profile_conforms(profile.profile, [
            {"filesystem_write": "workspace_only", "max_external_api_calls": 3},
            {"filesystem_write": "none", "max_external_api_calls": 0},
        ])
        self.assertTrue(conforms, reasons)
        weak = dict(profile.profile)
        weak["filesystem"] = dict(weak["filesystem"], write="workspace_only")
        self.assertFalse(profile_conforms(weak, [{"filesystem_write": "none"}])[0])

    def test_sandbox_rejects_unknown_unsupported_missing_mitigation_and_is_deterministic(self):
        template = self.template().template
        base = SandboxCompileInput(
            "project-1", "task-1", "action-1", "sha256:action",
            {"network_access": "disabled"}, ("m1",), ("m1",),
            {"execution_time_ms": 100}, template, "sha256:context", ("task:task-1",),
        )
        first = compile_sandbox_profile(base)
        second = compile_sandbox_profile(base)
        self.assertEqual(first.profile_hash, second.profile_hash)
        self.assertEqual(worker_template_content_hash(template), worker_template_content_hash(template))
        with self.assertRaisesRegex(CapabilityRejected, "SANDBOX_UNKNOWN_MANDATORY_CONSTRAINT"):
            compile_sandbox_profile(SandboxCompileInput(
                "project-1", "task-1", "action-1", "sha256:action",
                {"unknown": True}, (), (), {}, template, "sha256:context", (),
            ))
        limited = self.template(features=("network_access",)).template
        with self.assertRaisesRegex(CapabilityRejected, "SANDBOX_TEMPLATE_UNSUPPORTED_CONSTRAINT"):
            compile_sandbox_profile(SandboxCompileInput(
                "project-1", "task-1", "action-1", "sha256:action",
                {"filesystem_write": "none"}, (), (), {}, limited, "sha256:context", (),
            ))
        with self.assertRaisesRegex(CapabilityRejected, "SANDBOX_REQUIRED_MITIGATION_UNAVAILABLE"):
            compile_sandbox_profile(SandboxCompileInput(
                "project-1", "task-1", "action-1", "sha256:action",
                {}, ("m1",), (), {}, template, "sha256:context", (),
            ))


if __name__ == "__main__":
    unittest.main()
