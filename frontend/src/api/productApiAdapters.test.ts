import { afterEach, describe, expect, it, vi } from 'vitest';
import { productApiAdapters } from './productApiAdapters';

afterEach(() => vi.unstubAllGlobals());

const envelope = (data: unknown) => ({
  ok: true,
  json: async () => ({ data, error: null, request_id: 'req-1' }),
});
const failure = (code: string) => ({
  ok: false,
  json: async () => ({ data: null, error: { code, message: `message-${code}` }, request_id: 'req-1' }),
});

describe('Product API read adapters, E11 transport, and E12 Human Gate decisions', () => {
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

  it('uses the verified E12 Gate Inbox and decision receipt transport without client authority fields', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(envelope({ availability: 'CURRENT', items: [{ gate_id: 'gate-1', project_id: 'project-1', production_name: 'Real Project', action: 'project:resume', request_type: 'approval', risk_ref: 'risk-1', reason: 'review', evidence_refs: ['evidence-1'], evidence_count: 1, expires_at: '2099-01-01T00:00:00Z', status: 'REQUESTED', version: 3, as_of: '2026-08-27T00:00:00Z', freshness: 'NOT_AVAILABLE', audit: [] }] }))
      .mockResolvedValueOnce(envelope({ availability: 'CURRENT', gate_id: 'gate-1', project_id: 'project-1', production_name: 'Real Project', action: 'project:resume', request_type: 'approval', risk_ref: 'risk-1', reason: 'review', evidence_refs: ['evidence-1'], evidence_count: 1, expires_at: '2099-01-01T00:00:00Z', status: 'REQUESTED', version: 3, as_of: '2026-08-27T00:00:00Z', freshness: 'NOT_AVAILABLE', audit: [] }))
      .mockResolvedValueOnce(envelope({ availability: 'CURRENT', command_id: 'cmd-1', gate_request_id: 'gate-1', gate_decision_id: 'decision-1', receipt_status: 'APPLIED', result_code: 'HUMAN_GATE_APPROVED', request_state: 'APPROVED', request_version: 4, decision: 'APPROVE', event_ids: ['event-1'], completion_claim: 'GATE_DECISION_RECEIPT_IS_NOT_PROJECT_RESUME' }));
    vi.stubGlobal('fetch', fetchMock);
    const api = productApiAdapters();
    expect(await api.gates.listGates()).toMatchObject({ kind: 'data', value: [{ gateId: 'gate-1' }] });
    expect(await api.gates.getGate('gate-1')).toMatchObject({ kind: 'data', value: { version: 3, evidenceRefs: ['evidence-1'] } });
    expect(await api.gates.submitDecision('gate-1', 'APPROVE', { reason: 'reviewed', expectedGateVersion: 3 })).toMatchObject({ kind: 'data', value: { resultCode: 'HUMAN_GATE_APPROVED', receiptStatus: 'APPLIED' } });
    const [path, options] = fetchMock.mock.calls[2] as [string, RequestInit];
    expect(path).toContain('/factory-home/gates/gate-1/decisions');
    expect(options.credentials).toBe('include'); expect(options.method).toBe('POST');
    const payload = JSON.parse(String(options.body));
    expect(Object.keys(payload).sort()).toEqual(['command_id', 'decision', 'expected_gate_version', 'gate_decision_id', 'idempotency_key', 'reason']);
    expect(payload.decision).toBe('APPROVE'); expect(payload.expected_gate_version).toBe(3);
    for (const forbidden of ['actor', 'requester', 'approver', 'project_id', 'task_id', 'action_scope', 'authorization_ref', 'assertion_id', 'assertion_hash', 'evidence_refs', 'constraints', 'state']) expect(payload).not.toHaveProperty(forbidden);
  });

  it('treats unavailable scope as unavailable, not as an empty portfolio', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(envelope({
      availability: 'NOT_AVAILABLE', reason: 'PORTFOLIO_READ_MODEL_NOT_CONFIGURED', items: [],
    })));
    const result = await productApiAdapters().portfolio.listProductions();
    expect(result).toMatchObject({ kind: 'not_implemented', message: 'PORTFOLIO_READ_MODEL_NOT_CONFIGURED' });
  });

  it('submits only the approved E11 pause/resume payload over the cookie-backed receipt transport', async () => {
    const fetchMock = vi.fn().mockResolvedValue(envelope({
      command_id: 'cmd-1', receipt_status: 'APPLIED', result_code: 'PROJECT_PAUSED',
      target_version: 2, event_ids: ['event-1'], projection_status: 'AWAITING_E7_RECONCILIATION',
    }));
    vi.stubGlobal('fetch', fetchMock);
    const result = await productApiAdapters().production.resume('p-1', {
      reason: 'operator request', idempotencyKey: 'idem-1', expectedVersion: 1,
    });
    expect(result).toMatchObject({ kind: 'data', value: {
      commandId: 'cmd-1', action: null, receiptStatus: 'APPLIED', resultCode: 'PROJECT_PAUSED', targetVersion: 2,
      eventIds: ['event-1'], projectionStatus: 'AWAITING_E7_RECONCILIATION',
    } });
    const [path, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(path).toContain('/factory-home/productions/p-1/commands/resume');
    expect(options.credentials).toBe('include');
    const payload = JSON.parse(String(options.body));
    expect(payload).toMatchObject({ expected_version: 1, idempotency_key: 'idem-1', reason: 'operator request' });
    expect(Object.keys(payload).sort()).toEqual(['command_id', 'expected_version', 'idempotency_key', 'reason']);
    for (const forbidden of ['actor', 'requested_by', 'scope', 'project_id', 'command_type', 'executor', 'state', 'new_state']) expect(payload).not.toHaveProperty(forbidden);
  });
  it('maps a source-derived Live Production snapshot without inventing progress or authority controls', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(envelope({ availability: 'CURRENT', freshness: 'CURRENT', as_of: '2026-08-21T00:00:00Z', projection_schema_version: 'e7-live-production-projection/1', snapshot_watermark: 9, item: { production_id: 'p-1', project: { project_id: 'p-1', title: 'Real Project', state: 'IMPLEMENTING', version: 3, updated_at: '2026-08-21T00:00:00Z' }, workflow: { nodes: [{ node_id: 'task-1', title: 'Build', state: 'RUNNING', version: 2, source_identity: 'task-1' }], edges: [] }, execution_requests: [], verification: { plans: [], results: [] }, evidence: { valid_count: 0, invalidated_count: 1, missing_count: 1, items: [] }, gates: [], recovery: [], recent_events: [] } })));
    const result = await productApiAdapters().production.getLiveSnapshot('p-1');
    expect(result.kind).toBe('data');
    if (result.kind === 'data') {
      expect(result.value.snapshotWatermark).toBe(9);
      expect(result.value.workflow.nodes[0].sourceIdentity).toBe('task-1');
      expect(result.value.evidence.invalidatedCount).toBe(1);
      expect(result.value.asOf).toBe('2026-08-21T00:00:00Z');
    }
  });
  it('reads an existing creator-scoped E11 receipt with cookie credentials and AbortSignal for post-refresh reconciliation', async () => {
    const fetchMock = vi.fn().mockResolvedValue(envelope({ availability: 'CURRENT', command_id: 'cmd-1', action: null, receipt_status: 'APPLIED', result_code: 'PROJECT_PAUSED', target_version: 2, event_ids: ['event-1'], projection_status: 'AWAITING_E7_RECONCILIATION' }));
    vi.stubGlobal('fetch', fetchMock);
    const controller = new AbortController();
    const result = await productApiAdapters().production.getCommandReceipt('p-1', 'cmd-1', controller.signal);
    expect(result).toMatchObject({ kind: 'data', value: { commandId: 'cmd-1', action: null, targetVersion: 2 } });
    const [path, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(path).toContain('/factory-home/productions/p-1/commands/cmd-1');
    expect(options.credentials).toBe('include');
    expect(options.signal).toBe(controller.signal);
    expect(options.method).toBeUndefined();
  });
  it('preserves stable E11 HTTP failures and network timeout as read failures rather than commands', async () => {
    for (const code of ['UNAUTHORIZED', 'FORBIDDEN', 'E11_COMMAND_NOT_AVAILABLE', 'VERSION_CONFLICT', 'E11_COMMAND_REASON_REQUIRED', 'RATE_LIMITED', 'INTERNAL_ERROR']) {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(failure(code)));
      await expect(productApiAdapters().production.getCommandReceipt('p-1', 'cmd-1')).resolves.toMatchObject({ kind: 'error', message: code });
      vi.unstubAllGlobals();
    }
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new DOMException('timeout', 'AbortError')));
    await expect(productApiAdapters().production.getLiveSnapshot('p-1')).resolves.toMatchObject({ kind: 'error' });
  });
  it('returns a stable E11 read error for a malformed snapshot instead of manufacturing projection facts', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(envelope({ availability: 'CURRENT', freshness: 'CURRENT', projection_schema_version: 'e7-live-production-projection/1', snapshot_watermark: 2, item: null })));
    await expect(productApiAdapters().production.getLiveSnapshot('p-1')).resolves.toMatchObject({ kind: 'error', message: 'E11_PROJECTION_SNAPSHOT_MALFORMED' });
  });
  it('preserves a stale cursor response for snapshot rehydration rather than treating it as a live event stream', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(envelope({ availability: 'STALE', reason: 'LIVE_PRODUCTION_CURSOR_AHEAD', items: [], snapshot_watermark: 9 })));
    const result = await productApiAdapters().production.getLiveEvents('p-1', 10, 50);
    expect(result.kind).toBe('data');
    if (result.kind === 'data') expect(result.value.availability).toBe('STALE');
  });

});
