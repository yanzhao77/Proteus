import { describe, expect, it } from 'vitest';
import { reconcileE11Receipt, type E11ProjectionReader } from './e11Reconciliation';
import type { AdapterResult, LiveProductionEventFeedViewModel, LiveProductionSnapshotViewModel, ProjectCommandReceiptViewModel } from './models';

const receipt: ProjectCommandReceiptViewModel = {
  commandId: 'command-1', action: 'pause', receiptStatus: 'APPLIED', resultCode: 'PROJECT_TRANSITION_APPLIED',
  targetVersion: 2, eventIds: ['event-2'], projectionStatus: 'AWAITING_E7_RECONCILIATION',
};
const snapshot = (version: number, watermark = version, schema = 'e7-live-production-projection/1'): LiveProductionSnapshotViewModel => ({
  productionId: 'project-1', project: { projectId: 'project-1', title: 'Project', state: version >= 2 ? 'PAUSED' : 'RUNNING', version, updatedAt: '2026-08-26T00:00:00Z' },
  snapshotWatermark: watermark, projectionSchemaVersion: schema, freshness: 'CURRENT', asOf: '2026-08-26T00:00:00Z',
  workflow: { nodes: [], edges: [] }, executionRequests: [], verification: { plans: [], results: [] }, evidence: { validCount: 0, invalidatedCount: 0, missingCount: 0, items: [] }, gates: [], waiting: [], recovery: [], recentEvents: [],
});
const eventFeed = (overrides: Partial<LiveProductionEventFeedViewModel> = {}): LiveProductionEventFeedViewModel => ({
  availability: 'CURRENT', reason: null, items: [], after: 1, nextCursor: 1, snapshotWatermark: 1, projectionSchemaVersion: 'e7-live-production-projection/1', ...overrides,
});
const data = <T,>(value: T): AdapterResult<T> => ({ kind: 'data', value });

class Reader implements E11ProjectionReader {
  snapshots: AdapterResult<LiveProductionSnapshotViewModel>[];
  events: AdapterResult<LiveProductionEventFeedViewModel>[];
  snapshotCalls = 0;
  eventCalls = 0;
  constructor(snapshots: AdapterResult<LiveProductionSnapshotViewModel>[], events: AdapterResult<LiveProductionEventFeedViewModel>[] = []) {
    this.snapshots = snapshots;
    this.events = events;
  }
  getLiveSnapshot(_projectId: string, _signal?: AbortSignal) {
    this.snapshotCalls += 1;
    return Promise.resolve(this.snapshots[Math.min(this.snapshotCalls - 1, this.snapshots.length - 1)]);
  }
  getLiveEvents(_projectId: string, _after: number, _limit?: number, _signal?: AbortSignal) {
    this.eventCalls += 1;
    return Promise.resolve(this.events[Math.min(this.eventCalls - 1, this.events.length - 1)] ?? data(eventFeed()));
  }
}
const context = (initialSnapshotWatermark = 1) => ({ projectId: 'project-1', receipt, initialSnapshotWatermark });
const noWait = async () => true;

describe('E11 receipt-to-E7 projection reconciliation', () => {
  it('marks applied only when a current creator-scoped snapshot reaches targetVersion', async () => {
    const reader = new Reader([data(snapshot(2, 4))]);
    const result = await reconcileE11Receipt(reader, context(), new AbortController().signal, { wait: noWait });
    expect(result.kind).toBe('applied');
    if (result.kind === 'applied') expect(result.snapshot.project.version).toBe(2);
    expect(reader.eventCalls).toBe(0);
  });

  it('keeps reading after delayed projection and applies only after a later snapshot confirms targetVersion', async () => {
    const reader = new Reader([data(snapshot(1, 1)), data(snapshot(2, 2))], [data(eventFeed({ after: 1, nextCursor: 2, snapshotWatermark: 2, items: [{ eventId: 'event-2', productionSequence: 2, aggregateType: 'project', aggregateId: 'project-1', aggregateVersion: 2, eventKind: 'project.paused', occurredAt: null, schemaVersion: 'event/1' }] }))]);
    const result = await reconcileE11Receipt(reader, context(), new AbortController().signal, { wait: noWait });
    expect(result.kind).toBe('applied');
    expect(reader.snapshotCalls).toBe(2);
    expect(reader.eventCalls).toBe(1);
  });

  it('does not treat a matching event as applied without a later snapshot confirmation', async () => {
    const reader = new Reader([data(snapshot(1, 1))], [data(eventFeed({ after: 1, nextCursor: 2, snapshotWatermark: 2, items: [{ eventId: 'event-2', productionSequence: 2, aggregateType: 'project', aggregateId: 'project-1', aggregateVersion: 2, eventKind: 'project.paused', occurredAt: null, schemaVersion: 'event/1' }] }))]);
    const result = await reconcileE11Receipt(reader, context(), new AbortController().signal, { maxAttempts: 2, wait: noWait });
    expect(result.kind).toBe('uncertain');
    if (result.kind !== 'uncertain') throw new Error('expected uncertain reconciliation outcome');
    expect(result.code).toBe('E11_EVENT_FEED_STALE');
  });

  it('rehydrates snapshot after stale cursor and applies only from the rehydrated snapshot', async () => {
    const reader = new Reader([data(snapshot(1, 1)), data(snapshot(2, 3))], [data(eventFeed({ availability: 'STALE', reason: 'LIVE_PRODUCTION_CURSOR_EXPIRED', snapshotWatermark: 3 }))]);
    const result = await reconcileE11Receipt(reader, context(), new AbortController().signal, { wait: noWait });
    expect(result.kind).toBe('applied');
    expect(reader.snapshotCalls).toBe(2);
  });

  it('rehydrates after duplicate or reordered event sequences instead of patching local projection state', async () => {
    const reader = new Reader([data(snapshot(1, 1)), data(snapshot(2, 3))], [data(eventFeed({ after: 1, nextCursor: 2, snapshotWatermark: 3, items: [{ eventId: 'old', productionSequence: 1, aggregateType: 'project', aggregateId: 'project-1', aggregateVersion: 1, eventKind: 'project.paused', occurredAt: null, schemaVersion: 'event/1' }] }))]);
    const result = await reconcileE11Receipt(reader, context(), new AbortController().signal, { wait: noWait });
    expect(result.kind).toBe('applied');
    expect(reader.snapshotCalls).toBe(2);
  });

  it('returns uncertain after bounded read failures without re-submitting an authority command', async () => {
    const reader = new Reader([{ kind: 'error', message: 'offline' }]);
    const result = await reconcileE11Receipt(reader, context(), new AbortController().signal, { maxAttempts: 2, wait: noWait });
    expect(result).toMatchObject({ kind: 'uncertain', code: 'E11_PROJECTION_READ_FAILED', attempts: 2 });
    expect(reader.eventCalls).toBe(0);
  });

  it('returns terminal failure for an incompatible E7 schema rather than comparing untrusted fields', async () => {
    const reader = new Reader([data(snapshot(2, 2, 'e7-live-production-projection/other'))]);
    const result = await reconcileE11Receipt(reader, context(), new AbortController().signal, { wait: noWait });
    expect(result).toMatchObject({ kind: 'terminal_failure', code: 'E11_PROJECTION_SCHEMA_UNSUPPORTED' });
  });

  it('stops before reads when the reconciliation controller is aborted', async () => {
    const reader = new Reader([data(snapshot(2))]);
    const controller = new AbortController();
    controller.abort();
    const result = await reconcileE11Receipt(reader, context(), controller.signal, { wait: noWait });
    expect(result.kind).toBe('cancelled');
    expect(reader.snapshotCalls).toBe(0);
  });
});
