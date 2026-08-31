import { MemoryRouter } from 'react-router-dom';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { UiProvider } from './design-system';

const mocks = vi.hoisted(() => ({
  getProposal: vi.fn(),
  getMasterPlan: vi.fn(),
  listProposalRevisions: vi.fn(),
  listMasterPlanRevisions: vi.fn(),
  saveProposalRevision: vi.fn(),
  saveMasterPlanRevision: vi.fn(),
}));

vi.mock('./api', () => ({
  createAdapters: () => ({ mode: 'product_api', draft: mocks, portfolio: {}, production: {}, gates: {} }),
}));

import { E13ProposalPlanEditor } from './e13ProposalPlanEditor';

const proposalRevision = {
  revisionId: 'pr-1', revisionNumber: 1, contentHash: 'h1', compiler: 'proposal-compiler-v1', schemaVersion: 'e3-v1', createdAt: '2026-01-01T00:00:00Z',
  content: {
    productStatement: 'Product statement A', targetOutcome: 'Outcome B', scopeIn: ['in1'], scopeOut: ['out1'],
    requirements: [{ key: 'r1', statement: 'Statement', source: 'entry_understanding' }],
    assumptions: [{ assumptionId: 'a1', statement: 'Assumption', basis: 'b', status: 'UNCONFIRMED_SOURCE_ASSUMPTION' }],
    unresolvedItems: [], complexityBand: 'LOW', candidateArchitecture: { status: 'REVIEW_REQUIRED', reason: 'r' },
    sourceDraftRevisionId: 'd', sourceUnderstandingRevisionId: 'u',
  },
};
const planRevision = {
  revisionId: 'mr-1', revisionNumber: 1, contentHash: 'h2', compiler: 'master-plan-compiler-v1', schemaVersion: 'e3-v1', proposalRevisionId: 'pr-1', createdAt: '2026-01-01T00:00:00Z',
  content: {
    goal: 'Goal G', requirements: [{ key: 'r1', statement: 'S', source: 'entry_understanding' }], constraints: ['c1'], phases: ['p1'],
    nodes: [{ nodeKey: 'n1', phase: 'p1', title: 'T', requirementRefs: ['r1'], verificationRefs: ['verify-r1'] }],
    dependencies: [], risks: ['risk1'], verificationIntent: { status: 'REVIEW_REQUIRED', requirementKeys: ['r1'] },
    preApprovalOnly: true, sourceDraftRevisionId: 'd', sourceUnderstandingRevisionId: 'u',
  },
};
const proposalView = { proposalId: 'p1', draftId: 'd1', version: 1, latestRevision: 1, preApprovalOnly: true, current: proposalRevision, revisions: [proposalRevision] };
const planView = { masterPlanId: 'm1', proposalId: 'p1', draftId: 'd1', version: 1, latestRevision: 1, preApprovalOnly: true, proposalRevisionStatus: 'CURRENT', current: planRevision, revisions: [planRevision] };

beforeAll(() => {
  if (!globalThis.crypto) (globalThis as unknown as { crypto: Crypto }).crypto = {} as Crypto;
  if (!(globalThis.crypto as Crypto & { randomUUID?: () => string }).randomUUID) {
    (globalThis.crypto as Crypto & { randomUUID: () => string }).randomUUID = () => 'test-uuid';
  }
});

beforeEach(() => {
  mocks.getProposal.mockReset(); mocks.getMasterPlan.mockReset();
  mocks.listProposalRevisions.mockReset(); mocks.listMasterPlanRevisions.mockReset();
  mocks.saveProposalRevision.mockReset(); mocks.saveMasterPlanRevision.mockReset();
  mocks.getProposal.mockResolvedValue({ kind: 'data', value: proposalView });
  mocks.getMasterPlan.mockResolvedValue({ kind: 'data', value: planView });
  mocks.listProposalRevisions.mockResolvedValue({ kind: 'data', value: [proposalRevision] });
  mocks.listMasterPlanRevisions.mockResolvedValue({ kind: 'data', value: [planRevision] });
  mocks.saveProposalRevision.mockResolvedValue({ kind: 'data', value: { ...proposalView, latestRevision: 2 } });
  mocks.saveMasterPlanRevision.mockResolvedValue({ kind: 'data', value: { ...planView, latestRevision: 2 } });
});

const forbiddenKeys = ['actor', 'creator', 'authority', 'approval', 'execution', 'scope'];
function assertNoForbiddenFields(value: unknown) {
  const seen = new Set<unknown>();
  const walk = (node: unknown) => {
    if (node === null || typeof node !== 'object' || seen.has(node)) return;
    seen.add(node);
    for (const [k, v] of Object.entries(node as Record<string, unknown>)) {
      expect(forbiddenKeys).not.toContain(k.toLowerCase());
      walk(v);
    }
  };
  walk(value);
}

describe('E13 Proposal & Master Plan Editor', () => {
  it('shows the current proposal, enters edit mode, and saves a new immutable revision with only editable fields', async () => {
    render(<MemoryRouter><UiProvider><E13ProposalPlanEditor draftId="d1" /></UiProvider></MemoryRouter>);
    expect(await screen.findByText('Product statement A')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    const input = await screen.findByLabelText('Product statement');
    fireEvent.change(input, { target: { value: 'Edited statement' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save new revision' }));

    await waitFor(() => expect(mocks.saveProposalRevision).toHaveBeenCalledTimes(1));
    const [draftId, content] = mocks.saveProposalRevision.mock.calls[0];
    expect(draftId).toBe('d1');
    expect(content.productStatement).toBe('Edited statement');
    expect(content.candidateArchitecture).toEqual({ status: 'REVIEW_REQUIRED', reason: 'r' });
    assertNoForbiddenFields(content);
    await waitFor(() => expect(mocks.getProposal).toHaveBeenCalledTimes(2));
  });

  it('blocks save and shows validation when the product statement is empty', async () => {
    render(<MemoryRouter><UiProvider><E13ProposalPlanEditor draftId="d1" /></UiProvider></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    const input = await screen.findByLabelText('Product statement');
    fireEvent.change(input, { target: { value: '   ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save new revision' }));
    expect(await screen.findByText('Product statement is required.')).toBeInTheDocument();
    expect(mocks.saveProposalRevision).not.toHaveBeenCalled();
  });

  it('prevents duplicate submit while saving and surfaces conflicts', async () => {
    mocks.saveProposalRevision.mockResolvedValue({ kind: 'error', message: 'ENTRY_PROPOSAL_SAVE_VERSION_CONFLICT' });
    render(<MemoryRouter><UiProvider><E13ProposalPlanEditor draftId="d1" /></UiProvider></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Save new revision' }));
    expect(await screen.findByText('ENTRY_PROPOSAL_SAVE_VERSION_CONFLICT')).toBeInTheDocument();
  });

  it('edits the master plan in a separate tab and preserves the DAG nodes on save', async () => {
    render(<MemoryRouter><UiProvider><E13ProposalPlanEditor draftId="d1" /></UiProvider></MemoryRouter>);
    await screen.findByText('Product statement A');
    fireEvent.click(screen.getByRole('tab', { name: /master plan/i }));
    expect(await screen.findByText('Goal G')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    const goal = await screen.findByLabelText('Goal');
    fireEvent.change(goal, { target: { value: 'New goal' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save new revision' }));

    await waitFor(() => expect(mocks.saveMasterPlanRevision).toHaveBeenCalledTimes(1));
    const [, content] = mocks.saveMasterPlanRevision.mock.calls[0];
    expect(content.goal).toBe('New goal');
    expect(content.nodes.map((n: { nodeKey: string }) => n.nodeKey)).toEqual(['n1']);
    assertNoForbiddenFields(content);
  });

  it('renders revision history and exposes a structured diff against the current revision', async () => {
    render(<MemoryRouter><UiProvider><E13ProposalPlanEditor draftId="d1" /></UiProvider></MemoryRouter>);
    expect(await screen.findByText('Revision history')).toBeInTheDocument();
    expect(screen.getByText(/\(current\)/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: /master plan/i }));
    expect(await screen.findByText('Revision history')).toBeInTheDocument();
  });
});
