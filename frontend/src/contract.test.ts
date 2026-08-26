import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { developmentFixtureAdapters } from './api/fixtureAdapters';

const app = readFileSync('src/App.tsx', 'utf8');
const selector = readFileSync('src/api/index.ts', 'utf8');

describe('E9–E11 workspace authority contracts', () => {
  it('keeps the product workspace routes outside a chat entry point', () => {
    for (const route of ['/home', '/new', '/drafts/:id', '/productions', '/productions/:id/operations', '/gates']) expect(app).toContain(`path="${route}"`);
    expect(app).not.toContain('path="/chat"');
  });
  it('isolates fixtures to explicit development demo mode', async () => {
    expect(selector).toContain("import.meta.env.DEV && import.meta.env.VITE_PROTEUS_DEMO === 'true'");
    expect(selector).toContain('return productApiAdapters();');
    const fixture = developmentFixtureAdapters();
    const projects = await fixture.portfolio.listProductions();
    expect(projects.kind).toBe('data');
  });
  it('keeps project cards and recovery entry navigational rather than direct authority mutations', () => {
    expect(app).toContain('/operations');
    expect(app).toContain('controlledRecovery');
    expect(app).toContain('cannot mutate tasks, workers, verification, gates, or recovery authority');
    for (const forbidden of ['setProjectState', 'createExecutionRequest', 'setTaskState', 'submitGateDecision', 'adapters.production.pause(', 'adapters.production.resume(', 'adapters.production.stop(']) expect(app).not.toContain(forbidden);
  });
  it('uses source-derived live snapshot fields for DAG, execution, verification, evidence and recovery', () => {
    for (const field of ['getLiveSnapshot(id)', 'live.workflow.nodes', 'live.executionRequests', 'live.verification.plans', 'live.evidence.items', 'live.waiting', 'live.recovery']) expect(app).toContain(field);
  });
  it('does not embed fixture content or credentials in the production application', () => {
    expect(app).not.toContain('demo-gate-001');
    expect(app).not.toMatch(/authorization|refresh_token|api[_-]?key/i);
  });
});
