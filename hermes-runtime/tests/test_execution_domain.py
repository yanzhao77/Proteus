import unittest

from hermes_runtime.domain.execution import (
    ArtifactInputRef,
    ExecutionAdmissionSnapshot,
    ExecutionRejected,
    LockIntent,
    VersionedRef,
    normalize_lock_intents,
    normalize_priority,
    prepare_execution_request_snapshot,
    route_action_type,
)


class ExecutionDomainTests(unittest.TestCase):
    def snapshot(self, **overrides):
        base = dict(
            project_id="project-1",
            task_id="task-1",
            project_version=1,
            task_version=1,
            decision=VersionedRef("decision-1", 1, "sha256:decision"),
            action=VersionedRef("action-1", 1, "sha256:action"),
            action_type="repair",
            action_requirements_hash="sha256:requirements",
            policy=VersionedRef("policy-1", 1, "sha256:policy"),
            risk=VersionedRef("risk-1", 1, "sha256:risk"),
            mandatory_mitigations_hash="sha256:mitigations",
            resource_reservation=VersionedRef("reservation-1", 1, "sha256:reservation"),
            capability_match=VersionedRef("capmatch-1", 1, "sha256:requirements"),
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
            verification_plan=VersionedRef("verification-plan-1", 1, "sha256:plan"),
            input_artifacts=(ArtifactInputRef("artifact-1", "task-1", "sha256:artifact"),),
            lock_intents=(
                LockIntent("workspace:project-1:default"),
                LockIntent("repository:repo-main"),
                LockIntent("workspace:project-1:default"),
            ),
            priority=10,
        )
        base.update(overrides)
        return ExecutionAdmissionSnapshot(**base)

    def test_action_routing_fail_closed(self):
        self.assertEqual("WORKER", route_action_type("repair").value)
        self.assertEqual("CONTROL_PLANE", route_action_type("pause").value)
        self.assertEqual("HUMAN_GATE", route_action_type("request_resource").value)
        self.assertEqual("RECOVERY", route_action_type("reconcile").value)
        self.assertEqual("UNSUPPORTED", route_action_type("launch_nukes").value)
        with self.assertRaisesRegex(ExecutionRejected, "EXEC_ADMISSION_ACTION_ROUTE_UNSUPPORTED"):
            prepare_execution_request_snapshot(
                self.snapshot(action_type="pause"),
                idempotency_key="key-1",
            )

    def test_lock_scope_normalization_deduplicates_stable_order(self):
        normalized = normalize_lock_intents((
            LockIntent("deployment_target:prod:svc"),
            LockIntent("repository:repo-main"),
            LockIntent("workspace:Project-1:Default"),
            LockIntent("repository:repo-main"),
        ))
        self.assertEqual((
            "repository:repo-main",
            "workspace:project-1:default",
            "deployment_target:prod:svc",
        ), tuple(item.scope for item in normalized))
        with self.assertRaisesRegex(ExecutionRejected, "EXEC_ADMISSION_LOCK_CONFLICT"):
            normalize_lock_intents((LockIntent("unknown:thing"),))

    def test_priority_boundaries(self):
        self.assertEqual(-1000, normalize_priority(-1000))
        self.assertEqual(1000, normalize_priority(1000))
        with self.assertRaisesRegex(ExecutionRejected, "EXEC_ADMISSION_INCOMPLETE"):
            normalize_priority(1001)

    def test_canonical_payload_and_ids_are_deterministic(self):
        first = prepare_execution_request_snapshot(self.snapshot(), idempotency_key="key-1")
        second = prepare_execution_request_snapshot(self.snapshot(), idempotency_key="key-1")
        self.assertEqual(first.payload_hash, second.payload_hash)
        self.assertEqual(first.execution_request_id, second.execution_request_id)
        self.assertEqual(first.queue_item_id, second.queue_item_id)
        self.assertEqual("QUEUED", "QUEUED")
        self.assertEqual(
            ["repository:repo-main", "workspace:project-1:default"],
            [item["scope"] for item in first.request_snapshot["lock_intents"]],
        )

    def test_snapshot_requires_versions_hashes_and_attempt_baseline(self):
        with self.assertRaisesRegex(ExecutionRejected, "EXEC_ADMISSION_VERSION_CONFLICT"):
            prepare_execution_request_snapshot(
                self.snapshot(decision=VersionedRef("decision-1", 0, "sha256:decision")),
                idempotency_key="key-1",
            )
        with self.assertRaisesRegex(ExecutionRejected, "EXEC_ADMISSION_INCOMPLETE"):
            prepare_execution_request_snapshot(
                self.snapshot(policy=VersionedRef("policy-1", 1, "not-a-hash")),
                idempotency_key="key-1",
            )
        with self.assertRaisesRegex(ExecutionRejected, "EXEC_ADMISSION_INCOMPLETE"):
            prepare_execution_request_snapshot(
                self.snapshot(attempt_baseline=1),
                idempotency_key="key-1",
            )


if __name__ == "__main__":
    unittest.main()
