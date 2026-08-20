import unittest

from hermes_runtime.domain.entry_approval_bridge import (
    ApproveEntryPlan,
    ApprovalSource,
    EntryE4Rejected,
    preview_approval,
    validate_approval,
)


class E4DomainTests(unittest.TestCase):
    def source(self, **overrides):
        plan = {
            "schema_version": "v1",
            "compiler": "e3-master-plan-v1",
            "pre_approval_only": True,
            "nodes": [
                {"node_key": "a", "title": "First", "requirement_refs": ["r1"]},
                {"node_key": "b", "title": "Second", "requirement_refs": ["r2"]},
            ],
            "dependencies": [{"source": "a", "target": "b"}],
            "assumptions": [{"key": "a1", "status": "UNCONFIRMED_SOURCE_ASSUMPTION"}],
            "architecture": {"status": "REVIEW_REQUIRED"},
            "verification_intent": {"status": "REVIEW_REQUIRED"},
            "delivery_intent": {"status": "REVIEW_REQUIRED"},
        }
        source = ApprovalSource("creator", "ed", 4, "edr", "eur", "epr", "proposal-hash", "emp", 5, "empr", "plan-hash", plan)
        return source.__class__(**{**source.__dict__, **overrides})

    def request(self, source, preview, acknowledgements):
        return ApproveEntryPlan("creator", "explicit approval", "key", source.draft_version, source.plan_id, source.plan_version, source.plan_revision_id, source.plan_content_hash, source.proposal_revision_id, source.proposal_content_hash, preview.compiled_blueprint_hash, acknowledgements, "corr")

    def test_preview_is_stable_and_has_no_runtime_identity(self):
        first = preview_approval(self.source())
        second = preview_approval(self.source())
        self.assertEqual(first.blueprint, second.blueprint)
        self.assertEqual(first.compiled_blueprint_hash, second.compiled_blueprint_hash)
        tasks = {task["node_key"]: task for task in first.blueprint["tasks"]}
        dependency = first.blueprint["dependencies"][0]
        self.assertEqual(dependency["task_id"], tasks["b"]["task_id"])
        self.assertEqual(dependency["depends_on_task_id"], tasks["a"]["task_id"])
        self.assertNotIn("execution", str(first.blueprint).lower())
        self.assertNotIn("worker", str(first.blueprint).lower())

    def test_acknowledgements_are_exact_and_server_computed(self):
        source = self.source()
        preview = preview_approval(source)
        self.assertEqual(preview.required_acknowledgements, ("assumption:a1", "review:architecture", "review:delivery_intent", "review:verification_intent"))
        with self.assertRaisesRegex(EntryE4Rejected, "ENTRY_APPROVAL_ACKNOWLEDGEMENT_REQUIRED"):
            validate_approval(source, self.request(source, preview, ()), preview)
        validate_approval(source, self.request(source, preview, preview.required_acknowledgements), preview)

    def test_stale_hash_subject_and_blueprint_fail_closed(self):
        source = self.source()
        preview = preview_approval(source)
        request = self.request(source, preview, preview.required_acknowledgements)
        with self.assertRaisesRegex(EntryE4Rejected, "ENTRY_APPROVAL_UNAUTHORIZED"):
            validate_approval(source, request.__class__(**{**request.__dict__, "verified_subject": "foreign"}), preview)
        with self.assertRaisesRegex(EntryE4Rejected, "ENTRY_APPROVAL_BLUEPRINT_MISMATCH"):
            validate_approval(source, request.__class__(**{**request.__dict__, "compiled_blueprint_hash": "wrong"}), preview)
        with self.assertRaisesRegex(EntryE4Rejected, "ENTRY_APPROVAL_SOURCE_STALE"):
            validate_approval(source, request.__class__(**{**request.__dict__, "plan_revision_id": "other"}), preview)

    def test_invalid_plan_dag_reference_fails_closed(self):
        source = self.source()
        source.plan_content["dependencies"] = [{"source": "a", "target": "missing"}]
        with self.assertRaisesRegex(EntryE4Rejected, "ENTRY_APPROVAL_PLAN_INVALID"):
            preview_approval(source)
