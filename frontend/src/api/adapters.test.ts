import { describe, expect, it } from 'vitest';
import { authorityPendingAdapters } from './adapters';

describe('authority pending adapters', () => {
  const adapters = authorityPendingAdapters();
  it('does not expose a development fixture as production authority', () => expect(adapters.mode).toBe('authority_pending'));
  it('does not create a draft when the Entry API is absent', async () => expect((await adapters.draft.createDraft('Title', 'idea', { reason: 'r', idempotencyKey: 'idem-r', expectedVersion: 1 })).kind).toBe('not_implemented'));
  it('does not invent a portfolio projection', async () => expect((await adapters.portfolio.listProductions()).kind).toBe('not_implemented'));
  it('does not invent a production snapshot', async () => expect((await adapters.production.getSnapshot('p-1')).kind).toBe('not_implemented'));
  it('does not resume a production from the browser adapter', async () => expect((await adapters.production.resume('p-1', { reason: 'r', idempotencyKey: 'idem-r', expectedVersion: 1 })).kind).toBe('not_implemented'));
  it('does not pause a production from the browser adapter', async () => expect((await adapters.production.pause('p-1', { reason: 'r', idempotencyKey: 'idem-r', expectedVersion: 1 })).kind).toBe('not_implemented'));
  it('does not submit a human gate decision without a semantic backend contract', async () => expect((await adapters.gates.submitDecision('g-1', 'APPROVE', { reason: 'r', expectedGateVersion: 1 })).kind).toBe('not_implemented'));
});
