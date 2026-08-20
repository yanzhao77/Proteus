import { afterEach, describe, expect, it, vi } from 'vitest';
import { productApiAdapters } from './productApiAdapters';

afterEach(() => vi.unstubAllGlobals());
const envelope = (data: unknown) => ({ ok: true, json: async () => ({ data, error: null, request_id: 'req-e3' }) });
const proposal = {
  proposal_id: 'ep-1', draft_id: 'ed-1', version: 1, latest_revision_number: 1, pre_approval_only: true,
  current: { proposal_revision_id: 'epr-1', revision_number: 1, content_hash: 'a'.repeat(64), compiler: 'proposal-compiler-v1', schema_version: 'e3-v1', created_at: '2026-08-20T00:00:00Z', source_draft_revision_id: 'edr-1', source_understanding_revision_id: 'eur-1', content: { source: { draft_revision_id: 'edr-1', understanding_revision_id: 'eur-1' }, product_statement: 'Build issue tracker', target_outcome: 'Review scope', scope_in: ['Create issues'], scope_out: [], requirements: [{ key: 'requirement-001', statement: 'Create issues', source: 'entry_understanding' }], assumptions: [{ assumption_id: 'a-1', statement: 'Browser exists', basis: 'source', status: 'UNCONFIRMED_SOURCE_ASSUMPTION' }], unresolved_items: [], complexity_band: 'LOW', candidate_architecture: { status: 'REVIEW_REQUIRED' } } }, revisions: [],
};

describe('E3 product API adapter', () => {
  it('uses the governed Proposal mutation shape and maps source/hash metadata', async () => {
    const fetchMock = vi.fn().mockResolvedValue(envelope({ availability: 'CURRENT', item: proposal }));
    vi.stubGlobal('fetch', fetchMock);
    const result = await productApiAdapters().draft.generateProposal('ed-1', { actor: 'ignored', reason: 'review', idempotencyKey: 'idem-e3', expectedVersion: 0 });
    expect(result).toMatchObject({ kind: 'data' });
    if (result.kind === 'data') {
      expect(result.value.current.contentHash).toBe('a'.repeat(64));
      expect(result.value.current.content.sourceDraftRevisionId).toBe('edr-1');
      expect(result.value.current.content.sourceUnderstandingRevisionId).toBe('eur-1');
    }
    expect(fetchMock).toHaveBeenCalledWith('/production-drafts/ed-1/proposal', expect.objectContaining({ method: 'POST', body: JSON.stringify({ reason: 'review', idempotency_key: 'idem-e3', expected_version: 0 }) }));
  });
  it('uses the governed Master Plan route and never exposes an approval mutation', async () => {
    const fetchMock = vi.fn().mockResolvedValue(envelope({ availability: 'NOT_AVAILABLE', reason: 'ENTRY_PLAN_NOT_AVAILABLE', item: null }));
    vi.stubGlobal('fetch', fetchMock);
    const result = await productApiAdapters().draft.generateMasterPlan('ed-1', { actor: 'ignored', reason: 'review', idempotencyKey: 'idem-plan', expectedVersion: 0 });
    expect(result).toMatchObject({ kind: 'not_implemented', message: 'ENTRY_PLAN_NOT_AVAILABLE' });
    expect(fetchMock.mock.calls[0][0]).toBe('/production-drafts/ed-1/proposal/master-plan');
    expect(Object.keys(productApiAdapters().draft)).not.toContain('approve');
  });
});
