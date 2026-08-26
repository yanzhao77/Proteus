import { afterEach, describe, expect, it, vi } from 'vitest';
import { productApiAdapters } from './productApiAdapters';

afterEach(() => vi.unstubAllGlobals());
const envelope = (data: unknown) => new Response(JSON.stringify({ data, error: null }), { status: 200 });

describe('E11 operations projection adapter', () => {
  it('maps existing E7 DAG, execution, verification, evidence, waiting and recovery facts without creating a command surface', async () => {
    const fetchMock = vi.fn().mockResolvedValue(envelope({ availability: 'CURRENT', freshness: 'CURRENT', projection_schema_version: 'e7/1', snapshot_watermark: 7, item: {
      production_id: 'project-1', project: { project_id: 'project-1', title: 'Project', state: 'RUNNING', version: 2, updated_at: null }, workflow: { nodes: [], edges: [] }, execution_requests: [], verification: { plans: [], results: [] }, evidence: { valid_count: 1, invalidated_count: 0, missing_count: 0, items: [] }, gates: [],
      waiting: [{ waiting_record_id: 'wait-1', task_id: 'task-1', waiting_type: 'GATE', reason: 'human review', waiting_state: 'WAITING', gate_request_id: 'gate-1' }],
      recovery: [{ finding_id: 'finding-1', finding_kind: 'VERIFICATION_FAILURE', status: 'OPEN', observed_sequence: 9 }], recent_events: []
    } }));
    vi.stubGlobal('fetch', fetchMock);
    const result = await productApiAdapters().production.getLiveSnapshot('project-1');
    expect(result.kind).toBe('data');
    if (result.kind === 'data') {
      expect(result.value.waiting).toEqual([{ waitingRecordId: 'wait-1', taskId: 'task-1', type: 'GATE', reason: 'human review', state: 'WAITING', gateId: 'gate-1' }]);
      expect(result.value.recovery).toEqual([{ findingId: 'finding-1', kind: 'VERIFICATION_FAILURE', status: 'OPEN', observedSequence: 9 }]);
    }
    expect(fetchMock).toHaveBeenCalledWith('/factory-home/productions/project-1/live', expect.objectContaining({ credentials: 'include', headers: { Accept: 'application/json' } }));
  });
});
