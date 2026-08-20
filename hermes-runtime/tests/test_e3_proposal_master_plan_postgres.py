import os
import unittest
from pathlib import Path

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None

from hermes_runtime.domain.entry_proposal_master_plan import EntryE3Rejected
from hermes_runtime.infrastructure.postgres_entry_proposal_master_plan import PostgresEntryProposalMasterPlanStore
from hermes_runtime.infrastructure.postgres_project import PostgresProjectStore

DATABASE_URL = os.environ.get('HERMES_TEST_DATABASE_URL')


@unittest.skipUnless(DATABASE_URL and psycopg, 'requires psycopg and HERMES_TEST_DATABASE_URL')
class E3ProposalMasterPlanPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        bootstrap = PostgresProjectStore(DATABASE_URL)
        for migration in sorted((Path(__file__).parents[1] / 'migrations').glob('*.sql')):
            bootstrap.apply_migration(migration)

    def setUp(self):
        self.alice = 'e3-postgres-alice'
        self.bob = 'e3-postgres-bob'
        self.draft_id = 'ed-e3-postgres'
        with psycopg.connect(DATABASE_URL) as c:
            c.execute('TRUNCATE TABLE public.entry_proposal_plan_command_receipts, public.entry_master_plan_revisions, public.entry_master_plans, public.entry_proposal_revisions, public.entry_proposals, public.entry_understanding_provenance, public.entry_clarification_answers, public.entry_understanding_assumptions, public.entry_understanding_transition_records, public.entry_understanding_revisions, public.entry_understandings, public.entry_draft_transition_records, public.entry_draft_revisions, public.entry_drafts CASCADE')
            c.execute("INSERT INTO public.entry_drafts(draft_id,creator_subject,title,raw_input,state,version,latest_revision_number,last_command_id) VALUES(%s,%s,%s,%s,'SUBMITTED',1,1,%s)", (self.draft_id, self.alice, 'E3 PostgreSQL', 'Build reviewable tracker', 'cmd-e3-draft'))
            c.execute("INSERT INTO public.entry_draft_revisions(revision_id,draft_id,revision_number,title,raw_input,created_by_subject,draft_version) VALUES(%s,%s,1,%s,%s,%s,1)", ('edr-e3-postgres-1', self.draft_id, 'E3 PostgreSQL', 'Build reviewable tracker', self.alice))
            c.execute("INSERT INTO public.entry_understandings(understanding_id,draft_id,creator_subject,state,version,latest_revision_number) VALUES(%s,%s,%s,'READY',1,1)", ('eu-e3-postgres', self.draft_id, self.alice))
            c.execute("INSERT INTO public.entry_understanding_revisions(understanding_revision_id,understanding_id,revision_number,source_draft_id,source_draft_revision_number,source_raw_input,interpreted_intent,objective,user_constraints,explicit_requirements,ambiguities,open_questions) VALUES(%s,%s,1,%s,1,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb)", ('eur-e3-postgres-1', 'eu-e3-postgres', self.draft_id, 'Build reviewable tracker', 'Build reviewable tracker', 'Deliver a reviewable tracker', '["web"]', '["Create issues","List issues"]', '[]', '[]'))
        self.store = PostgresEntryProposalMasterPlanStore(DATABASE_URL)

    def _counts(self):
        names = ('projects', 'tasks', 'execution_requests', 'planning_runs', 'candidate_actions', 'human_gate_requests')
        with psycopg.connect(DATABASE_URL, row_factory=dict_row) as c:
            return {name: c.execute(f'SELECT count(*) AS n FROM public.{name}').fetchone()['n'] for name in names}

    def test_happy_path_replay_and_no_authority_side_effect(self):
        before = self._counts()
        proposal = self.store.generate_proposal(self.alice, self.draft_id, 0, 'proposal-happy', 'Compile proposal')
        replay = self.store.generate_proposal(self.alice, self.draft_id, 0, 'proposal-happy', 'Compile proposal')
        self.assertEqual(proposal['proposal_id'], replay['proposal_id'])
        self.assertEqual(1, len(replay['revisions']))
        self.assertEqual('proposal-compiler-v1', proposal['current']['compiler'])
        self.assertEqual('e3-v1', proposal['current']['schema_version'])
        self.assertEqual(64, len(proposal['current']['content_hash']))
        plan = self.store.generate_master_plan(self.alice, self.draft_id, 0, 'plan-happy', 'Compile plan')
        plan_replay = self.store.generate_master_plan(self.alice, self.draft_id, 0, 'plan-happy', 'Compile plan')
        self.assertEqual(plan['master_plan_id'], plan_replay['master_plan_id'])
        self.assertEqual(1, len(plan_replay['revisions']))
        self.assertTrue(plan['current']['content']['pre_approval_only'])
        self.assertEqual(before, self._counts())

    def test_idempotency_conflict_and_expected_version_reject_without_revision(self):
        proposal = self.store.generate_proposal(self.alice, self.draft_id, 0, 'proposal-conflict', 'first')
        with self.assertRaisesRegex(EntryE3Rejected, 'ENTRY_PROPOSAL_IDEMPOTENCY_CONFLICT'):
            self.store.generate_proposal(self.alice, self.draft_id, 0, 'proposal-conflict', 'changed fingerprint')
        with self.assertRaisesRegex(EntryE3Rejected, 'ENTRY_PROPOSAL_VERSION_CONFLICT'):
            self.store.generate_proposal(self.alice, self.draft_id, 9, 'proposal-stale-version', 'stale')
        current = self.store.get_proposal(self.alice, self.draft_id)['item']
        self.assertEqual(proposal['current']['proposal_revision_id'], current['current']['proposal_revision_id'])
        self.assertEqual(1, len(current['revisions']))

    def test_creator_isolation_is_no_leak(self):
        self.store.generate_proposal(self.alice, self.draft_id, 0, 'proposal-private', 'private')
        hidden = self.store.get_proposal(self.bob, self.draft_id)
        self.assertEqual('NOT_AVAILABLE', hidden['availability'])
        self.assertIsNone(hidden['item'])
        hidden_plan = self.store.get_master_plan(self.bob, self.draft_id)
        self.assertEqual('NOT_AVAILABLE', hidden_plan['availability'])
        self.assertIsNone(hidden_plan['item'])

    def test_source_freshness_blocks_plan_and_current_pointer_stays_stable(self):
        proposal = self.store.generate_proposal(self.alice, self.draft_id, 0, 'proposal-source', 'source')
        with psycopg.connect(DATABASE_URL) as c:
            c.execute("UPDATE public.entry_understandings SET latest_revision_number=2, version=2 WHERE understanding_id='eu-e3-postgres'")
        with self.assertRaisesRegex(EntryE3Rejected, 'ENTRY_PLAN_SOURCE_STALE'):
            self.store.generate_master_plan(self.alice, self.draft_id, 0, 'plan-stale', 'stale source')
        current = self.store.get_proposal(self.alice, self.draft_id)['item']
        self.assertEqual(proposal['current']['proposal_revision_id'], current['current']['proposal_revision_id'])
        self.assertEqual(1, len(current['revisions']))

    def test_database_immutable_revision_update_and_delete_are_rejected(self):
        proposal = self.store.generate_proposal(self.alice, self.draft_id, 0, 'proposal-immutable', 'immutable')
        revision_id = proposal['current']['proposal_revision_id']
        original_hash = proposal['current']['content_hash']
        with psycopg.connect(DATABASE_URL, row_factory=dict_row) as c:
            with self.assertRaises(psycopg.Error):
                c.execute("UPDATE public.entry_proposal_revisions SET compiler_name='tampered' WHERE proposal_revision_id=%s", (revision_id,))
            c.rollback()
            with self.assertRaises(psycopg.Error):
                c.execute('DELETE FROM public.entry_proposal_revisions WHERE proposal_revision_id=%s', (revision_id,))
            c.rollback()
        current = self.store.get_proposal(self.alice, self.draft_id)['item']
        self.assertEqual(revision_id, current['current']['proposal_revision_id'])
        self.assertEqual(original_hash, current['current']['content_hash'])

    def test_schema_triggers_receipts_and_runtime_grants_are_minimal(self):
        with psycopg.connect(DATABASE_URL, row_factory=dict_row) as c:
            tables = {row['relname'] for row in c.execute("SELECT relname FROM pg_class WHERE relnamespace='public'::regnamespace AND relname LIKE 'entry_%plan%' OR relname IN ('entry_proposals','entry_proposal_revisions','entry_master_plans','entry_master_plan_revisions')")}
            self.assertTrue({'entry_proposals','entry_proposal_revisions','entry_master_plans','entry_master_plan_revisions','entry_proposal_plan_command_receipts'}.issubset(tables))
            triggers = {row['tgname'] for row in c.execute("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgname IN ('hermes_e3_proposal_revision_immutable','hermes_e3_master_plan_revision_immutable')")}
            self.assertEqual({'hermes_e3_proposal_revision_immutable','hermes_e3_master_plan_revision_immutable'}, triggers)
            grants = c.execute("SELECT count(*) AS n FROM information_schema.role_table_grants WHERE grantee='hermes_control_plane_runtime' AND privilege_type IN ('INSERT','UPDATE','DELETE') AND table_name IN ('projects','tasks','execution_requests','planning_runs','candidate_actions','human_gate_requests')").fetchone()['n']
            self.assertEqual(0, grants)

if __name__ == '__main__':
    unittest.main()
