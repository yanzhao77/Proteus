import type { AdapterResult, LiveProductionEventFeedViewModel, LiveProductionSnapshotViewModel, ProjectCommandReceiptViewModel } from './models';

export const E11_PROJECTION_SCHEMA_VERSION = 'e7-live-production-projection/1';
export const E11_RECONCILIATION_MAX_ATTEMPTS = 4;
export const E11_RECONCILIATION_BACKOFF_MS = [0, 75, 150, 300] as const;
export const E11_RECONCILIATION_EVENT_LIMIT = 50;

export interface E11ProjectionReader {
  getLiveSnapshot(projectId: string, signal?: AbortSignal): Promise<AdapterResult<LiveProductionSnapshotViewModel>>;
  getLiveEvents(projectId: string, after: number, limit?: number, signal?: AbortSignal): Promise<AdapterResult<LiveProductionEventFeedViewModel>>;
}

export interface E11ReconciliationContext {
  projectId: string;
  receipt: ProjectCommandReceiptViewModel;
  initialSnapshotWatermark: number;
}

type E11ReconciliationBase = { attempts: number; lastSnapshot: LiveProductionSnapshotViewModel | null };
export type E11ReconciliationOutcome =
  | ({ kind: 'applied'; snapshot: LiveProductionSnapshotViewModel } & E11ReconciliationBase)
  | ({ kind: 'uncertain'; code: string } & E11ReconciliationBase)
  | ({ kind: 'terminal_failure'; code: string } & E11ReconciliationBase)
  | ({ kind: 'cancelled' } & E11ReconciliationBase);

export interface E11ReconciliationOptions {
  maxAttempts?: number;
  wait?: (milliseconds: number, signal: AbortSignal) => Promise<boolean>;
}

const abortableWait = (milliseconds: number, signal: AbortSignal): Promise<boolean> => new Promise((resolve) => {
  if (signal.aborted) { resolve(false); return; }
  const timer = globalThis.setTimeout(() => {
    signal.removeEventListener('abort', onAbort);
    resolve(true);
  }, milliseconds);
  const onAbort = () => {
    globalThis.clearTimeout(timer);
    resolve(false);
  };
  signal.addEventListener('abort', onAbort, { once: true });
});

const failedReadCode = <T>(result: AdapterResult<T>, fallback: string) => result.kind === 'not_implemented' ? `${fallback}_NOT_AVAILABLE` : fallback;

const hasCurrentSnapshotContract = (snapshot: LiveProductionSnapshotViewModel, projectId: string) => (
  snapshot.productionId === projectId
  && snapshot.project.projectId === projectId
  && snapshot.freshness === 'CURRENT'
  && snapshot.projectionSchemaVersion === E11_PROJECTION_SCHEMA_VERSION
  && Number.isSafeInteger(snapshot.snapshotWatermark)
  && snapshot.snapshotWatermark >= 0
  && Number.isSafeInteger(snapshot.project.version)
  && snapshot.project.version >= 0
);

const hasStrictlyIncreasingSequences = (feed: LiveProductionEventFeedViewModel, after: number) => {
  let previous = after;
  for (const event of feed.items) {
    if (!Number.isSafeInteger(event.productionSequence) || event.productionSequence <= previous) return false;
    previous = event.productionSequence;
  }
  return true;
};

/**
 * Reconciles a durable E11 receipt against the existing creator-scoped E7 read
 * contracts. Events only trigger a fresh snapshot read; an event never marks a
 * command applied by itself.
 */
export async function reconcileE11Receipt(
  reader: E11ProjectionReader,
  context: E11ReconciliationContext,
  signal: AbortSignal,
  options: E11ReconciliationOptions = {},
): Promise<E11ReconciliationOutcome> {
  const targetVersion = context.receipt.targetVersion;
  const maxAttempts = options.maxAttempts ?? E11_RECONCILIATION_MAX_ATTEMPTS;
  const wait = options.wait ?? abortableWait;
  let cursor = context.initialSnapshotWatermark;
  let lastSnapshot: LiveProductionSnapshotViewModel | null = null;

  if (!Number.isSafeInteger(targetVersion) || targetVersion === null || targetVersion < 0) {
    return { kind: 'terminal_failure', code: 'E11_RECEIPT_TARGET_VERSION_UNAVAILABLE', attempts: 0, lastSnapshot };
  }
  if (!Number.isSafeInteger(cursor) || cursor < 0) {
    return { kind: 'terminal_failure', code: 'E11_SNAPSHOT_WATERMARK_INVALID', attempts: 0, lastSnapshot };
  }

  for (let attempts = 1; attempts <= maxAttempts; attempts += 1) {
    if (signal.aborted) return { kind: 'cancelled', attempts: attempts - 1, lastSnapshot };
    const delay = E11_RECONCILIATION_BACKOFF_MS[Math.min(attempts - 1, E11_RECONCILIATION_BACKOFF_MS.length - 1)];
    if (delay > 0 && !(await wait(delay, signal))) return { kind: 'cancelled', attempts: attempts - 1, lastSnapshot };

    const snapshotResult = await reader.getLiveSnapshot(context.projectId, signal);
    if (signal.aborted) return { kind: 'cancelled', attempts, lastSnapshot };
    if (snapshotResult.kind !== 'data') {
      if (attempts === maxAttempts) return { kind: 'uncertain', code: failedReadCode(snapshotResult, 'E11_PROJECTION_READ_FAILED'), attempts, lastSnapshot };
      continue;
    }

    const snapshot = snapshotResult.value;
    lastSnapshot = snapshot;
    if (snapshot.projectionSchemaVersion !== E11_PROJECTION_SCHEMA_VERSION) {
      return { kind: 'terminal_failure', code: 'E11_PROJECTION_SCHEMA_UNSUPPORTED', attempts, lastSnapshot };
    }
    if (!hasCurrentSnapshotContract(snapshot, context.projectId)) {
      if (attempts === maxAttempts) return { kind: 'uncertain', code: 'E11_PROJECTION_SNAPSHOT_NOT_CURRENT', attempts, lastSnapshot };
      continue;
    }
    if (snapshot.project.version >= targetVersion) {
      return { kind: 'applied', snapshot, attempts, lastSnapshot };
    }

    const eventResult = await reader.getLiveEvents(context.projectId, cursor, E11_RECONCILIATION_EVENT_LIMIT, signal);
    if (signal.aborted) return { kind: 'cancelled', attempts, lastSnapshot };
    if (eventResult.kind !== 'data') {
      if (attempts === maxAttempts) return { kind: 'uncertain', code: failedReadCode(eventResult, 'E11_EVENT_READ_FAILED'), attempts, lastSnapshot };
      continue;
    }

    const feed = eventResult.value;
    if (feed.projectionSchemaVersion !== E11_PROJECTION_SCHEMA_VERSION) {
      return { kind: 'terminal_failure', code: 'E11_PROJECTION_SCHEMA_UNSUPPORTED', attempts, lastSnapshot };
    }
    if (feed.availability !== 'CURRENT' || feed.reason || !Number.isSafeInteger(feed.snapshotWatermark) || feed.snapshotWatermark < cursor || !hasStrictlyIncreasingSequences(feed, cursor)) {
      // Cursor gap/ahead/expiry, reordering, duplicates, and stale pages all
      // require the next loop to rehydrate from snapshot rather than patching UI.
      cursor = snapshot.snapshotWatermark;
      if (attempts === maxAttempts) return { kind: 'uncertain', code: feed.reason ?? 'E11_EVENT_FEED_STALE', attempts, lastSnapshot };
      continue;
    }

    const matchingAuthorityEvent = feed.items.some((event) => (
      context.receipt.eventIds.includes(event.eventId)
      && event.aggregateType === 'project'
      && event.aggregateId === context.projectId
      && typeof event.aggregateVersion === 'number'
      && event.aggregateVersion >= targetVersion
    ));
    cursor = feed.nextCursor;
    // Even a matching event is only a cue to rehydrate. The following snapshot
    // must independently expose a current Project version at or beyond target.
    if (!matchingAuthorityEvent && feed.nextCursor === feed.after) cursor = snapshot.snapshotWatermark;
  }
  return { kind: 'uncertain', code: 'E11_PROJECTION_RECONCILIATION_TIMEOUT', attempts: maxAttempts, lastSnapshot };
}
