import { afterEach, describe, expect, it, vi } from 'vitest';
import { productApiAdapters } from './productApiAdapters';

afterEach(() => vi.unstubAllGlobals());

const envelope = (data: unknown) => ({
  ok: true,
  json: async () => ({ data, error: null, request_id: 'req-1' }),
});

describe('FH-1 Product API read adapters', () => {
  it('parses a source-derived Portfolio while preserving null progress', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(envelope({
      availability: 'CURRENT',
      items: [{
        production_id: 'p-1', display_name: 'Real Project', display_state: 'IMPLEMENTING',
        phase: 'IMPLEMENTING', current_summary: null, progress: null,
        progress_basis: 'NOT_AVAILABLE', owner: null, gate_count: 1, plan_revision: null,
        last_updated: '2026-08-18T10:00:00Z', as_of: '2026-08-18T10:00:00Z',
        freshness: 'NOT_AVAILABLE', source: 'projects', source_version: 7,
      }],
    })));
    const result = await productApiAdapters().portfolio.listProductions();
    expect(result.kind).toBe('data');
    if (result.kind === 'data') {
      expect(result.value[0].productionId).toBe('p-1');
      expect(result.value[0].progress).toBeNull();
      expect(result.value[0].progressSource).toBeNull();
    }
  });

  it('parses source-derived Gate attention without inventing risk or evidence', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(envelope({
      availability: 'CURRENT',
      items: [{
        gate_id: 'g-1', production_name: 'Real Project', action_summary: 'database-migration',
        risk: null, reason: 'review', evidence_count: null, expires_at: null,
        freshness: 'NOT_AVAILABLE', source: 'human_gate_requests', as_of: '2026-08-18T10:00:00Z',
      }],
    })));
    const result = await productApiAdapters().gates.listGates();
    expect(result.kind).toBe('data');
    if (result.kind === 'data') {
      expect(result.value[0].risk).toBe('not_available');
      expect(result.value[0].evidenceCount).toBeNull();
    }
  });

  it('treats unavailable scope as unavailable, not as an empty portfolio', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(envelope({
      availability: 'NOT_AVAILABLE', reason: 'PORTFOLIO_READ_MODEL_NOT_CONFIGURED', items: [],
    })));
    const result = await productApiAdapters().portfolio.listProductions();
    expect(result).toMatchObject({ kind: 'not_implemented', message: 'PORTFOLIO_READ_MODEL_NOT_CONFIGURED' });
  });

  it('does not expose any mutation through the FH-1 read adapter', async () => {
    const result = await productApiAdapters().production.resume('p-1', {
      actor: 'a', reason: 'r', idempotencyKey: 'k', expectedVersion: 1,
    });
    expect(result.kind).toBe('not_implemented');
  });
  it('maps a source-derived Live Production snapshot without inventing progress or authority controls', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(envelope({ availability: 'CURRENT', freshness: 'CURRENT', projection_schema_version: 'e7-live-production-projection/1', snapshot_watermark: 9, item: { production_id: 'p-1', project: { project_id: 'p-1', title: 'Real Project', state: 'IMPLEMENTING', version: 3, updated_at: '2026-08-21T00:00:00Z' }, workflow: { nodes: [{ node_id: 'task-1', title: 'Build', state: 'RUNNING', version: 2, source_identity: 'task-1' }], edges: [] }, execution_requests: [], verification: { plans: [], results: [] }, evidence: { valid_count: 0, invalidated_count: 1, missing_count: 1, items: [] }, gates: [], recovery: [], recent_events: [] } })));
    const result = await productApiAdapters().production.getLiveSnapshot('p-1');
    expect(result.kind).toBe('data');
    if (result.kind === 'data') {
      expect(result.value.snapshotWatermark).toBe(9);
      expect(result.value.workflow.nodes[0].sourceIdentity).toBe('task-1');
      expect(result.value.evidence.invalidatedCount).toBe(1);
    }
  });
  it('preserves a stale cursor response for snapshot rehydration rather than treating it as a live event stream', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(envelope({ availability: 'STALE', reason: 'LIVE_PRODUCTION_CURSOR_AHEAD', items: [], snapshot_watermark: 9 })));
    const result = await productApiAdapters().production.getLiveEvents('p-1', 10, 50);
    expect(result.kind).toBe('data');
    if (result.kind === 'data') expect(result.value.availability).toBe('STALE');
  });

});
