import os
import unittest
from pathlib import Path

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None

from hermes_runtime.domain.entry_proposal_master_plan import (
    EntryE3Rejected,
    build_edited_master_plan_content,
    canonical_content_hash,
    validate_editable_master_plan_fields,
    validate_editable_proposal_fields,
)
from hermes_runtime.domain.models import Actor, ActorType
from hermes_runtime.domain.product_api import ProductApiRejected, ProductApiRequest, ProductApiResponse
from hermes_runtime.application.product_api import ProductApiFacade
from hermes_runtime.infrastructure.postgres_entry_proposal_master_plan import PostgresEntryProposalMasterPlanStore
from hermes_runtime.infrastructure.postgres_project import PostgresProjectStore

DATABASE_URL = os.environ.get('HERMES_TEST_DATABASE_URL')

BASE_PROPOSAL = {
    'schema_version': 'e3-v1', 'compiler': 'proposal-compiler-v1',
    'source': {'draft_id': 'd', 'draft_revision_id': 'dr', 'understanding_id': 'u', 'understanding_revision_id': 'ur', 'clarification_ids': [], 'assumption_ids': []},
    'product_statement': 'x', 'target_outcome': 'y', 'scope_in': ['a'], 'scope_out': [],
    'requirements': [{'key': 'requirement-001', 'statement': 'do', 'source': 'entry_understanding'}],
    'assumptions': [], 'clarifications': [],
    'candidate_architecture': {'status': 'REVIEW_REQUIRED', 'reason': 'r'},
    'proposed_phases': ['review'], 'workforce_intent': {'status': 'ADVISORY_ONLY', 'allocated_workers': []},
    'verification_strategy': {'status': 'REVIEW_REQUIRED', 'requirement_keys': ['requirement-001']},
    'delivery_strategy': {'status': 'REVIEW_REQUIRED', 'method': 'x'},
    'complexity_band': 'LOW', 'known_risks': [], 'unresolved_items': [], 'constraints': [],
}
BASE_PLAN = {
    'schema_version': 'e3-v1', 'compiler': 'master-plan-compiler-v1',
    'proposal': {'proposal_revision_id': 'pr', 'proposal_content_hash': 'ph'},
    'source': {'draft_id': 'd', 'draft_revision_id': 'dr', 'understanding_id': 'u', 'understanding_revision_id': 'ur'},
    'goal': 'g', 'requirements': [{'key': 'r1', 'statement': 'S', 'source': 'entry_understanding'}],
    'constraints': [], 'architecture': {'status': 'REVIEW_REQUIRED', 'reason': 'n'}, 'phases': ['delivery-planning'],
    'nodes': [{'node_key': 'plan-node-001', 'phase': 'delivery-planning', 'title': 'S', 'requirement_refs': ['r1'], 'verification_refs': ['verify-r1']}],
    'dependencies': [], 'risks': [],
    'verification_intent': {'status': 'REVIEW_REQUIRED', 'requirement_keys': ['r1']},
    'delivery_intent': {'status': 'REVIEW_REQUIRED', 'method': 'n'},
    'workforce_intent': {'status': 'ADVISORY_ONLY', 'allocated_workers': []}, 'pre_approval_only': True,
}
GOOD_PROPOSAL_EDIT = {
    'product_statement': 'A', 'target_outcome': 'B', 'scope_in': ['s1'], 'scope_out': ['s2'],
    'requirements': [{'key': 'r1', 'statement': 'S', 'source': 'entry_understanding'}],
    'assumptions': [{'assumption_id': 'a1', 'statement': 'SA', 'basis': 'b', 'status': 'UNCONFIRMED_SOURCE_ASSUMPTION'}],
    'unresolved_items': ['u1', 'u2'], 'complexity_band': 'MEDIUM',
    'candidate_architecture': {'status': 'REVIEW_REQUIRED', 'reason': 'rr'},
}
GOOD_PLAN_EDIT = {
    'goal': 'G', 'requirements': [{'key': 'r1', 'statement': 'S', 'source': 'entry_understanding'}],
    'constraints': ['c1'], 'phases': ['p1'],
    'nodes': [{'node_key': 'plan-node-001', 'phase': 'p1', 'title': 'T', 'requirement_refs': ['r1'], 'verification_refs': ['verify-r1']}],
    'dependencies': [], 'verification_intent': {'status': 'REVIEW_REQUIRED', 'requirement_keys': ['r1']}, 'risks': ['risk1'],
}


class E13EditorDomainTests(unittest.TestCase):
    def test_proposal_edit_strict_schema_rejects_unknown_and_bad(self):
        with self.assertRaises(EntryE3Rejected):
            validate_editable_proposal_fields({'product_statement': 'x'})  # missing required
        with self.assertRaises(EntryE3Rejected):
            validate_editable_proposal_fields({**GOOD_PROPOSAL_EDIT, 'extra': 1})
        with self.assertRaises(EntryE3Rejected):
            validate_editable_proposal_fields({**GOOD_PROPOSAL_EDIT, 'complexity_band': 'NOPE'})
        with self.assertRaises(EntryE3Rejected):
            validate_editable_proposal_fields({**GOOD_PROPOSAL_EDIT, 'requirements': [{'key': 'k', 'statement': ''}]})

    def test_plan_edit_dag_and_forbidden_keys(self):
        fields = validate_editable_master_plan_fields(GOOD_PLAN_EDIT)
        self.assertEqual('G', fields['goal'])
        dup = dict(GOOD_PLAN_EDIT)
        dup['nodes'] = [
            {'node_key': 'n1', 'phase': 'p', 'title': 't', 'requirement_refs': [], 'verification_refs': []},
            {'node_key': 'n1', 'phase': 'p', 'title': 't', 'requirement_refs': [], 'verification_refs': []},
        ]
        with self.assertRaises(EntryE3Rejected):
            validate_editable_master_plan_fields(dup)
        with self.assertRaises(EntryE3Rejected):
            validate_editable_master_plan_fields({**GOOD_PLAN_EDIT, 'goal': ''})

        def build(fields):
            return build_edited_master_plan_content(BASE_PLAN, fields, 'pr', 'ph', BASE_PLAN['source'])

        cyclic = dict(GOOD_PLAN_EDIT)
        cyclic['nodes'] = [
            {'node_key': 'n1', 'phase': 'p', 'title': 't', 'requirement_refs': [], 'verification_refs': []},
            {'node_key': 'n2', 'phase': 'p', 'title': 't', 'requirement_refs': [], 'verification_refs': []},
        ]
        cyclic['dependencies'] = [{'source': 'n1', 'target': 'n2'}, {'source': 'n2', 'target': 'n1'}]
        with self.assertRaises(EntryE3Rejected):
            build(validate_editable_master_plan_fields(cyclic))
        leak = dict(GOOD_PLAN_EDIT, **{'nodes': [{'node_key': 'n1', 'phase': 'p', 'title': 't', 'requirement_refs': [], 'verification_refs': [], 'project_id': 'x'}]})
        with self.assertRaises(EntryE3Rejected):
            build(validate_editable_master_plan_fields(leak))

    def test_deterministic_hash(self):
        from hermes_runtime.domain.entry_proposal_master_plan import build_edited_proposal_content, build_edited_master_plan_content
        a = build_edited_proposal_content(BASE_PROPOSAL, validate_editable_proposal_fields(GOOD_PROPOSAL_EDIT))
        b = build_edited_proposal_content(BASE_PROPOSAL, validate_editable_proposal_fields(GOOD_PROPOSAL_EDIT))
        self.assertEqual(a.content_hash, b.content_hash)
        self.assertNotEqual(a.content['compiler'], 'proposal-compiler-v1')
        m = build_edited_master_plan_content(BASE_PLAN, validate_editable_master_plan_fields(GOOD_PLAN_EDIT), 'pr', 'ph', BASE_PLAN['source'])
        self.assertTrue(m.content['pre_approval_only'])


@unittest.skipUnless(DATABASE_URL and psycopg, 'requires psycopg and HERMES_TEST_DATABASE_URL')
class E13EditorPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        bootstrap = PostgresProjectStore(DATABASE_URL)
        for migration in sorted((Path(__file__).parents[1] / 'migrations').glob('*.sql')):
            bootstrap.apply_migration(migration)

    def setUp(self):
        self.alice = 'e13-postgres-alice'
        self.bob = 'e13-postgres-bob'
        self.draft_id = 'ed-e13-postgres'
        with psycopg.connect(DATABASE_URL) as c:
            c.execute('TRUNCATE TABLE public.entry_proposal_plan_command_receipts, public.entry_master_plan_revisions, public.entry_master_plans, public.entry_proposal_revisions, public.entry_proposals, public.entry_understanding_provenance, public.entry_clarification_answers, public.entry_understanding_assumptions, public.entry_understanding_transition_records, public.entry_understanding_revisions, public.entry_understandings, public.entry_draft_transition_records, public.entry_draft_revisions, public.entry_drafts CASCADE')
            c.execute("INSERT INTO public.entry_drafts(draft_id,creator_subject,title,raw_input,state,version,latest_revision_number,last_command_id) VALUES(%s,%s,%s,%s,'SUBMITTED',1,1,%s)", (self.draft_id, self.alice, 'E13 PostgreSQL', 'Build editor', 'cmd-e13-draft'))
            c.execute("INSERT INTO public.entry_draft_revisions(revision_id,draft_id,revision_number,title,raw_input,created_by_subject,draft_version) VALUES(%s,%s,1,%s,%s,%s,1)", ('edr-e13-postgres-1', self.draft_id, 'E13 PostgreSQL', 'Build editor', self.alice))
            c.execute("INSERT INTO public.entry_understandings(understanding_id,draft_id,creator_subject,state,version,latest_revision_number) VALUES(%s,%s,%s,'READY',1,1)", ('eu-e13-postgres', self.draft_id, self.alice))
            c.execute("INSERT INTO public.entry_understanding_revisions(understanding_revision_id,understanding_id,revision_number,source_draft_id,source_draft_revision_number,source_raw_input,interpreted_intent,objective,user_constraints,explicit_requirements,ambiguities,open_questions) VALUES(%s,%s,1,%s,1,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb)", ('eur-e13-postgres-1', 'eu-e13-postgres', self.draft_id, 'Build editor', 'Build editor', 'Deliver editor', '["web"]', '["Create issues","List issues"]', '[]', '[]'))
        self.store = PostgresEntryProposalMasterPlanStore(DATABASE_URL)

    def _seed(self):
        proposal = self.store.generate_proposal(self.alice, self.draft_id, 0, 'seed-proposal', 'seed')
        plan = self.store.generate_master_plan(self.alice, self.draft_id, 0, 'seed-plan', 'seed')
        return proposal, plan

    def _counts(self):
        names = ('projects', 'tasks', 'execution_requests', 'planning_runs', 'candidate_actions', 'human_gate_requests')
        with psycopg.connect(DATABASE_URL, row_factory=dict_row) as c:
            return {name: c.execute(f'SELECT count(*) AS n FROM public.{name}').fetchone()['n'] for name in names}

    def test_save_proposal_revision_creates_new_immutable_revision(self):
        before = self._counts()
        proposal, _ = self._seed()
        result = self.store.save_proposal_revision(self.alice, self.draft_id, 1, 'edit-proposal-1', 'edit', GOOD_PROPOSAL_EDIT)
        self.assertEqual(2, result['version'])
        self.assertEqual(2, len(result['revisions']))
        self.assertEqual('proposal-editor-v1', result['current']['compiler'])
        self.assertEqual(GOOD_PROPOSAL_EDIT['product_statement'], result['current']['content']['product_statement'])
        # immutable revisions never share an id
        self.assertNotEqual(result['revisions'][0]['proposal_revision_id'], result['revisions'][1]['proposal_revision_id'])
        self.assertEqual(result['revisions'][1]['proposal_revision_id'], result['current']['proposal_revision_id'])
        self.assertEqual(before, self._counts())

    def test_save_plan_revision_preserves_source_lineage_and_version(self):
        proposal, plan = self._seed()
        result = self.store.save_master_plan_revision(self.alice, self.draft_id, 1, 'edit-plan-1', 'edit', GOOD_PLAN_EDIT)
        self.assertEqual(2, result['version'])
        self.assertEqual(2, len(result['revisions']))
        self.assertEqual('master-plan-editor-v1', result['current']['compiler'])
        self.assertEqual(GOOD_PLAN_EDIT['goal'], result['current']['content']['goal'])
        # source lineage preserved
        self.assertEqual(plan['current']['proposal_revision_id'], result['current']['proposal_revision_id'])
        self.assertEqual(plan['current']['proposal_content_hash'], result['current']['proposal_content_hash'])
        self.assertEqual(plan['current']['source_draft_revision_id'], result['current']['source_draft_revision_id'])
        self.assertEqual(plan['current']['source_understanding_revision_id'], result['current']['source_understanding_revision_id'])

    def test_creator_isolation(self):
        self._seed()
        hidden = self.store.get_proposal(self.bob, self.draft_id)
        self.assertEqual('NOT_AVAILABLE', hidden['availability'])
        with self.assertRaises(EntryE3Rejected):
            self.store.save_proposal_revision(self.bob, self.draft_id, 1, 'x', 'y', GOOD_PROPOSAL_EDIT)

    def test_expected_version_conflict(self):
        self._seed()
        with self.assertRaisesRegex(EntryE3Rejected, 'ENTRY_PROPOSAL_VERSION_CONFLICT'):
            self.store.save_proposal_revision(self.alice, self.draft_id, 9, 'bad-ver', 'edit', GOOD_PROPOSAL_EDIT)

    def test_idempotent_replay_same_key_same_payload(self):
        self._seed()
        first = self.store.save_proposal_revision(self.alice, self.draft_id, 1, 'replay-key', 'edit', GOOD_PROPOSAL_EDIT)
        second = self.store.save_proposal_revision(self.alice, self.draft_id, 1, 'replay-key', 'edit', GOOD_PROPOSAL_EDIT)
        self.assertEqual(first['current']['proposal_revision_id'], second['current']['proposal_revision_id'])
        self.assertEqual(2, second['version'])

    def test_idempotency_conflict_different_payload(self):
        self._seed()
        self.store.save_proposal_revision(self.alice, self.draft_id, 1, 'conflict-key', 'edit', GOOD_PROPOSAL_EDIT)
        with self.assertRaisesRegex(EntryE3Rejected, 'ENTRY_PROPOSAL_SAVE_IDEMPOTENCY_CONFLICT'):
            self.store.save_proposal_revision(self.alice, self.draft_id, 1, 'conflict-key', 'edit', {**GOOD_PROPOSAL_EDIT, 'product_statement': 'DIFFERENT'})

    def test_schema_validation_rejected(self):
        self._seed()
        with self.assertRaisesRegex(EntryE3Rejected, 'ENTRY_PROPOSAL_EDIT_SCHEMA_INVALID'):
            self.store.save_proposal_revision(self.alice, self.draft_id, 1, 'bad-schema', 'edit', {'product_statement': 'x'})
        with self.assertRaisesRegex(EntryE3Rejected, 'ENTRY_PLAN_EDIT_SCHEMA_INVALID'):
            self.store.save_master_plan_revision(self.alice, self.draft_id, 1, 'bad-plan', 'edit', {'goal': ''})

    def test_plan_dag_rejected_on_save(self):
        self._seed()
        cyclic = dict(GOOD_PLAN_EDIT)
        cyclic['nodes'] = [
            {'node_key': 'n1', 'phase': 'p', 'title': 't', 'requirement_refs': [], 'verification_refs': []},
            {'node_key': 'n2', 'phase': 'p', 'title': 't', 'requirement_refs': [], 'verification_refs': []},
        ]
        cyclic['dependencies'] = [{'source': 'n1', 'target': 'n2'}, {'source': 'n2', 'target': 'n1'}]
        with self.assertRaises(EntryE3Rejected):
            self.store.save_master_plan_revision(self.alice, self.draft_id, 1, 'cyclic', 'edit', cyclic)

    def test_downstream_plan_becomes_stale_when_proposal_changes(self):
        self._seed()
        self.store.save_master_plan_revision(self.alice, self.draft_id, 1, 'plan-edit', 'edit', GOOD_PLAN_EDIT)
        fresh = self.store.get_master_plan(self.alice, self.draft_id)['item']
        self.assertEqual('CURRENT', fresh['proposal_revision_status'])
        self.store.save_proposal_revision(self.alice, self.draft_id, 1, 'proposal-edit', 'edit', GOOD_PROPOSAL_EDIT)
        stale = self.store.get_master_plan(self.alice, self.draft_id)['item']
        self.assertEqual('STALE', stale['proposal_revision_status'])

    def test_immutable_revision_history_cannot_be_mutated(self):
        proposal, _ = self._seed()
        rid = proposal['current']['proposal_revision_id']
        with psycopg.connect(DATABASE_URL, row_factory=dict_row) as c:
            with self.assertRaises(psycopg.Error):
                c.execute("UPDATE public.entry_proposal_revisions SET compiler_name='tampered' WHERE proposal_revision_id=%s", (rid,))
            c.rollback()
            with self.assertRaises(psycopg.Error):
                c.execute('DELETE FROM public.entry_proposal_revisions WHERE proposal_revision_id=%s', (rid,))
            c.rollback()

    def test_materialized_plan_protection(self):
        self._seed()
        guarded = PostgresEntryProposalMasterPlanStore(DATABASE_URL, plan_materialization_guard=lambda plan_id: True)
        with self.assertRaisesRegex(EntryE3Rejected, 'ENTRY_PLAN_MATERIALIZED_PROTECTED'):
            guarded.save_master_plan_revision(self.alice, self.draft_id, 1, 'guard-key', 'edit', GOOD_PLAN_EDIT)


@unittest.skipUnless(DATABASE_URL and psycopg, 'requires psycopg and HERMES_TEST_DATABASE_URL')
class E13EditorProductApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        bootstrap = PostgresProjectStore(DATABASE_URL)
        for migration in sorted((Path(__file__).parents[1] / 'migrations').glob('*.sql')):
            bootstrap.apply_migration(migration)

    def setUp(self):
        self.alice = 'e13-api-alice'
        self.draft_id = 'ed-e13-api'
        with psycopg.connect(DATABASE_URL) as c:
            c.execute('TRUNCATE TABLE public.entry_proposal_plan_command_receipts, public.entry_master_plan_revisions, public.entry_master_plans, public.entry_proposal_revisions, public.entry_proposals, public.entry_understanding_provenance, public.entry_clarification_answers, public.entry_understanding_assumptions, public.entry_understanding_transition_records, public.entry_understanding_revisions, public.entry_understandings, public.entry_draft_transition_records, public.entry_draft_revisions, public.entry_drafts CASCADE')
            c.execute("INSERT INTO public.entry_drafts(draft_id,creator_subject,title,raw_input,state,version,latest_revision_number,last_command_id) VALUES(%s,%s,%s,%s,'SUBMITTED',1,1,%s)", (self.draft_id, self.alice, 'E13 API', 'Build editor', 'cmd-e13-api'))
            c.execute("INSERT INTO public.entry_draft_revisions(revision_id,draft_id,revision_number,title,raw_input,created_by_subject,draft_version) VALUES(%s,%s,1,%s,%s,%s,1)", ('edr-e13-api-1', self.draft_id, 'E13 API', 'Build editor', self.alice))
            c.execute("INSERT INTO public.entry_understandings(understanding_id,draft_id,creator_subject,state,version,latest_revision_number) VALUES(%s,%s,%s,'READY',1,1)", ('eu-e13-api', self.draft_id, self.alice))
            c.execute("INSERT INTO public.entry_understanding_revisions(understanding_revision_id,understanding_id,revision_number,source_draft_id,source_draft_revision_number,source_raw_input,interpreted_intent,objective,user_constraints,explicit_requirements,ambiguities,open_questions) VALUES(%s,%s,1,%s,1,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb)", ('eur-e13-api-1', 'eu-e13-api', self.draft_id, 'Build editor', 'Build editor', 'Deliver editor', '["web"]', '["Create issues","List issues"]', '[]', '[]'))
        self.store = PostgresEntryProposalMasterPlanStore(DATABASE_URL)
        self.facade = ProductApiFacade(None, None, entry_proposal_master_plan_api=self.store)

    def _handle(self, method, path, body):
        request = ProductApiRequest(
            method, path, {}, body,
            actor=Actor(ActorType.USER, self.alice), verified_identity_subject=self.alice,
        )
        return self.facade.handle(request)

    def test_facade_route_saves_proposal_revision(self):
        self._handle('POST', f'/production-drafts/{self.draft_id}/proposal', {'reason': 'seed', 'idempotency_key': 's1', 'expected_version': 0})
        response = self._handle('POST', f'/production-drafts/{self.draft_id}/proposal/revisions', {'reason': 'edit', 'idempotency_key': 'e1', 'expected_version': 1, 'content': GOOD_PROPOSAL_EDIT})
        self.assertEqual(201, response.status_code)
        self.assertEqual(2, response.body['item']['version'])

    def test_facade_route_rejects_unknown_fields(self):
        self._handle('POST', f'/production-drafts/{self.draft_id}/proposal', {'reason': 'seed', 'idempotency_key': 's1', 'expected_version': 0})
        with self.assertRaises(ProductApiRejected):
            self._handle('POST', f'/production-drafts/{self.draft_id}/proposal/revisions', {'reason': 'edit', 'idempotency_key': 'e1', 'expected_version': 1, 'content': GOOD_PROPOSAL_EDIT, 'actor': 'x'})

    def test_facade_route_saves_plan_revision(self):
        self._handle('POST', f'/production-drafts/{self.draft_id}/proposal', {'reason': 'seed', 'idempotency_key': 's1', 'expected_version': 0})
        self._handle('POST', f'/production-drafts/{self.draft_id}/proposal/master-plan', {'reason': 'seed', 'idempotency_key': 's2', 'expected_version': 0})
        response = self._handle('POST', f'/production-drafts/{self.draft_id}/proposal/master-plan/revisions', {'reason': 'edit', 'idempotency_key': 'e2', 'expected_version': 1, 'content': GOOD_PLAN_EDIT})
        self.assertEqual(201, response.status_code)
        self.assertEqual(2, response.body['item']['version'])


if __name__ == '__main__':
    unittest.main()
