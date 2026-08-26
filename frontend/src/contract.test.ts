import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { developmentFixtureAdapters } from './api/fixtureAdapters';
const app = readFileSync('src/App.tsx', 'utf8');
const selector = readFileSync('src/api/index.ts', 'utf8');
describe('E9-only workspace and authority contracts', () => {
  it('keeps every existing workspace route outside a chat entry point', () => {
    for (const route of ['/home','/new','/drafts','/drafts/:id','/productions','/productions/:id','/productions/:id/operations','/gates']) expect(app).toContain(`path="${route}"`);
    expect(app).not.toContain('path="/chat"');
  });
  it('isolates fixtures to explicit development demo mode', async () => {
    expect(selector).toContain("import.meta.env.DEV && import.meta.env.VITE_PROTEUS_DEMO === 'true'");
    const fixture = developmentFixtureAdapters(); expect((await fixture.portfolio.listProductions()).kind).toBe('data');
  });
  it('keeps E11 partial: source-backed snapshots, navigational recovery, and only receipt-first pause/resume transport', () => {
    for (const field of ['getLiveSnapshot(id)','live.workflow.nodes','live.executionRequests','live.verification.plans','live.evidence.items','live.waiting','live.recovery']) expect(app).toContain(field);
    expect(app).toContain('controlledRecovery'); expect(app).toContain("t('operationsDetail')");
    expect(app).toContain("action: 'pause' | 'resume'");
    expect(app).toContain('adapters.production.pause(live.project.projectId, metadata)');
    expect(app).toContain('adapters.production.resume(live.project.projectId, metadata)');
    expect(app).toContain('RECEIPT_PENDING');
    expect(app).toContain('data-testid="e11-command-receipt"');
    for (const forbidden of ['setProjectState','createExecutionRequest','setTaskState','submitGateDecision',"submit('cancel')",'actor:', 'requested_by', 'scope:']) expect(app).not.toContain(forbidden);
  });
  it('does not embed production fixture content or browser credentials', () => { expect(app).not.toContain('demo-gate-001'); expect(app).not.toMatch(/authorization|refresh_token|api[_-]?key/i); });
});
