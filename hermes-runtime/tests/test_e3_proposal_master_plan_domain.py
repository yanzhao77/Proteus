from copy import deepcopy
import unittest

from hermes_runtime.domain.entry_proposal_master_plan import (
    EntryE3Rejected,
    ProposalSource,
    SourceAssumption,
    SourceClarification,
    canonical_content_hash,
    compile_master_plan,
    compile_proposal,
    validate_master_plan_content,
)


def ready_source(**overrides):
    source = ProposalSource(
        creator_subject="creator-1",
        draft_id="ed-1",
        draft_state="SUBMITTED",
        draft_revision_id="edr-1",
        draft_revision_number=1,
        understanding_id="eu-1",
        understanding_state="READY",
        understanding_revision_id="eur-1",
        understanding_revision_number=1,
        interpreted_intent="Build an issue tracker",
        objective="Deliver a reviewable issue tracker scope",
        user_constraints=("web",),
        explicit_requirements=("Create issues", "List issues"),
        ambiguities=(),
        open_questions=(),
        clarifications=(),
        assumptions=(SourceAssumption("assumption-1", "Users have browsers", "source"),),
    )
    return source.__class__(**{**source.__dict__, **overrides})


def proposal_with_revision():
    candidate = compile_proposal(ready_source())
    content = deepcopy(candidate.content)
    content["source"]["proposal_revision_id"] = "epr-1"
    return content, candidate.content_hash


class E3ProposalMasterPlanDomainTests(unittest.TestCase):
    def test_same_source_snapshot_has_byte_stable_proposal_hash(self):
        first = compile_proposal(ready_source())
        second = compile_proposal(ready_source(user_constraints=("web",)))
        self.assertEqual(first.content, second.content)
        self.assertEqual(first.content_hash, second.content_hash)
        self.assertEqual(
            canonical_content_hash({"b": [2, 1], "a": True}),
            canonical_content_hash({"a": True, "b": [2, 1]}),
        )

    def test_unconfirmed_assumption_is_never_promoted_to_accepted(self):
        proposal = compile_proposal(ready_source())
        self.assertEqual(proposal.content["assumptions"][0]["status"], "UNCONFIRMED_SOURCE_ASSUMPTION")
        self.assertNotIn("accepted", str(proposal.content).lower())

    def test_open_clarification_blocks_proposal(self):
        source = ready_source(clarifications=(SourceClarification("c-1", "Who?", "required", "OPEN", None),))
        with self.assertRaisesRegex(EntryE3Rejected, "ENTRY_PROPOSAL_SOURCE_NOT_READY"):
            compile_proposal(source)

    def test_plan_is_deterministic_and_source_attributed(self):
        proposal, proposal_hash = proposal_with_revision()
        first = compile_master_plan(proposal, proposal_hash)
        second = compile_master_plan(proposal, proposal_hash)
        self.assertEqual(first.content, second.content)
        self.assertEqual(first.content_hash, second.content_hash)
        self.assertEqual(first.content["source"]["draft_revision_id"], "edr-1")
        self.assertEqual(first.content["source"]["understanding_revision_id"], "eur-1")
        self.assertTrue(first.content["pre_approval_only"])

    def test_master_plan_validation_fails_closed(self):
        cases = (
            (lambda plan: plan.__setitem__("goal", ""), "ENTRY_PLAN_SCHEMA_INVALID"),
            (lambda plan: plan.__setitem__("nodes", plan["nodes"] + [deepcopy(plan["nodes"][0])]), "ENTRY_PLAN_DAG_INVALID"),
            (lambda plan: plan.__setitem__("dependencies", [{"source": "missing", "target": plan["nodes"][0]["node_key"]}]), "ENTRY_PLAN_DAG_INVALID"),
            (lambda plan: plan.__setitem__("dependencies", [{"source": plan["nodes"][0]["node_key"], "target": plan["nodes"][0]["node_key"]}]), "ENTRY_PLAN_DAG_INVALID"),
            (lambda plan: plan.__setitem__("dependencies", [{"source": plan["nodes"][0]["node_key"], "target": plan["nodes"][1]["node_key"]}, {"source": plan["nodes"][1]["node_key"], "target": plan["nodes"][0]["node_key"]}]), "ENTRY_PLAN_DAG_INVALID"),
            (lambda plan: plan["nodes"][0].__setitem__("requirement_refs", []), "ENTRY_PLAN_REQUIREMENT_COVERAGE_INVALID"),
        )
        for mutator, code in cases:
            with self.subTest(code=code):
                proposal, proposal_hash = proposal_with_revision()
                plan = deepcopy(compile_master_plan(proposal, proposal_hash).content)
                mutator(plan)
                with self.assertRaisesRegex(EntryE3Rejected, code):
                    validate_master_plan_content(plan)

    def test_unresolved_proposal_blocks_plan_and_output_cannot_have_runtime_identities(self):
        proposal, proposal_hash = proposal_with_revision()
        proposal["unresolved_items"] = ["answer scope"]
        with self.assertRaisesRegex(EntryE3Rejected, "ENTRY_PLAN_SOURCE_NOT_READY"):
            compile_master_plan(proposal, proposal_hash)
        proposal, proposal_hash = proposal_with_revision()
        plan = compile_master_plan(proposal, proposal_hash)
        content = str(plan.content)
        self.assertNotIn("project_id", content)
        self.assertNotIn("task_id", content)
        self.assertNotIn("execution_id", content)
