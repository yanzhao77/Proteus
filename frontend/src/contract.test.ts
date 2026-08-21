import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { developmentFixtureAdapters } from './api/fixtureAdapters';

const app = readFileSync('src/App.tsx', 'utf8');
const styles = readFileSync('src/styles/index.css', 'utf8');

describe('Factory Home product and visual contracts', () => {
  const fixture = developmentFixtureAdapters();

  it('keeps the requested Factory Home route set outside /chat', () => {
    for (const route of ['/home', '/new', '/drafts/:id', '/productions', '/productions/:id', '/gates']) expect(app).toContain(`path="${route}"`);
    expect(app).not.toContain('path="/chat"');
  });

  it('contains a dedicated loading skeleton rather than a fake empty portfolio', () => {
    expect(app).toContain('factory-skeleton');
    expect(app).toContain("portfolio.phase === 'loading'");
  });

  it('contains an explicit pending/error view instead of a false successful projection', () => {
    expect(app).toContain('BACKEND AUTHORITY BRIDGE PENDING');
    expect(app).toContain('does not invent production state');
  });

  it('contains an explicit stale state treatment with text and hatch pattern', () => {
    expect(styles).toContain('.factory-snapshot-stale');
    expect(app).toContain('SNAPSHOT STALE');
  });

  it('provides fixture production cards for state rendering only in development mode', async () => {
    const result = await fixture.portfolio.listProductions();
    expect(result.kind).toBe('data');
    if (result.kind === 'data') expect(result.value.map((card) => card.state)).toEqual(['running', 'paused', 'waiting']);
  });

  it('provides fixture Gate cards as a separately labelled read model', async () => {
    const result = await fixture.gates.listGates();
    expect(result.kind).toBe('data');
    if (result.kind === 'data') expect(result.value[0].reason).toContain('DEVELOPMENT fixture');
  });

  it('supports adapter-level Draft restore when a future server identity has a draft id', async () => {
    const created = await fixture.draft.createDraft('Fixture title', 'software outcome', { actor: 'test', reason: 'test', idempotencyKey: 'idempotent', expectedVersion: 0 });
    expect(created.kind).toBe('not_implemented');
    const restored = await fixture.draft.getDraft('demo-draft');
    expect(restored.kind).toBe('not_implemented');
  });

  it('preserves icon, label and pattern mechanisms for a non-color-only state system', () => {
    expect(app).toContain('statusGlyph');
    expect(app).toContain('statusLabel');
    expect(styles).toContain('.factory-production-card[data-state="running"]::after');
    expect(styles).toContain('.factory-production-card[data-state="failed"]::after');
  });

  it('never renders missing progress as a fabricated zero percent', () => {
    expect(app).toContain("card.progress === null ? 'NOT AVAILABLE'");
    expect(app).not.toContain("card.progress ?? 0");
  });

  it('does not include forbidden fake telemetry counter language', () => {
    expect(app).not.toMatch(/(?:^|[^A-Za-z0-9])(?:[0-9]+ workers|[0-9]+ tasks|[0-9]+% complete)(?:$|[^A-Za-z0-9])/i);
    expect(styles).not.toMatch(/particle|animate-pulse|rotate\(/);
  });

  it('keeps Home cards navigational rather than direct semantic mutations', () => {
    expect(app).toContain('REVIEW GATE →');
    expect(app).toContain('OPEN PRODUCTION →');
    expect(app).not.toContain('setProjectState');
    expect(app).not.toContain('createExecutionRequest');
  });
  it('keeps Product API as the production adapter and isolates fixture selection to explicit development demo mode', () => {
    const selector = readFileSync('src/api/index.ts', 'utf8');
    expect(selector).toContain("import.meta.env.DEV && import.meta.env.VITE_PROTEUS_DEMO === 'true'");
    expect(selector).toContain('return productApiAdapters();');
    expect(selector).not.toContain('VITE_PRODUCT_API_READS');
  });
  it('reuses the same draft idempotency key when command outcome is unknown', () => {
    expect(app).toContain('const pendingKey = useRef<string | null>(null)');
    expect(app).toContain('pendingKey.current ?? crypto.randomUUID()');
    expect(app).toContain('OUTCOME UNKNOWN — RETRY REUSES THE SAME KEY');
    expect(app).toContain('RECEIPT PENDING — DRAFT NOT YET APPLIED');
  });

});
