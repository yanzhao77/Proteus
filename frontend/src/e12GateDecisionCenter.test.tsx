import { MemoryRouter } from 'react-router-dom';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ listGates: vi.fn(), getGate: vi.fn(), submitDecision: vi.fn() }));

vi.mock('./api', () => ({
  createAdapters: () => ({ mode: 'product_api', draft: {}, portfolio: {}, production: {}, gates: mocks }),
}));

import App from './App';

const requestedGate = {
  gateId: 'gate-1', projectId: 'project-1', productionName: 'Safe Project', action: 'project:resume', requestType: 'approval',
  risk: 'not_available', riskRef: 'risk-1', reason: 'Review required', evidenceCount: 1, evidenceRefs: ['evidence-1'],
  expiresAt: '2099-01-01T00:00:00Z', freshness: { asOf: null, status: 'not_connected' as const, source: 'human_gate_requests' },
  status: 'REQUESTED', version: 3, asOf: '2026-08-27T00:00:00Z', audit: [],
};

beforeEach(() => {
  mocks.listGates.mockReset(); mocks.getGate.mockReset(); mocks.submitDecision.mockReset();
  mocks.listGates.mockResolvedValue({ kind: 'data', value: [{ gateId: 'gate-1', productionName: 'Safe Project', action: 'project:resume', risk: 'not_available', reason: 'Review required', evidenceCount: 1, expiresAt: '2099-01-01T00:00:00Z', freshness: { asOf: null, status: 'not_connected', source: 'human_gate_requests' } }] });
  mocks.getGate.mockResolvedValueOnce({ kind: 'data', value: requestedGate }).mockResolvedValue({ kind: 'data', value: { ...requestedGate, status: 'APPROVED', version: 4, audit: [{ decisionId: 'decision-1', decision: 'APPROVE', status: 'CURRENT', issuedAt: '2026-08-27T00:01:00Z', expiresAt: null }] } });
  mocks.submitDecision.mockResolvedValue({ kind: 'data', value: { commandId: 'cmd-1', gateRequestId: 'gate-1', gateDecisionId: 'decision-1', receiptStatus: 'APPLIED', resultCode: 'HUMAN_GATE_APPROVED', requestState: 'APPROVED', requestVersion: 4, decision: 'APPROVE', eventIds: ['event-1'], completionClaim: 'GATE_DECISION_RECEIPT_IS_NOT_PROJECT_RESUME' } });
});

describe('E12 Gate Decision Center', () => {
  it('requires a reason, submits only decision metadata, then refreshes safe detail before exposing audit and removing decision controls', async () => {
    render(<MemoryRouter initialEntries={['/gates/gate-1']}><App /></MemoryRouter>);
    expect(await screen.findByText('Safe Project')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
    expect(await screen.findByText('Decision reason is required or Gate is no longer pending.')).toBeInTheDocument();
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Reviewed the evidence.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
    await waitFor(() => expect(mocks.submitDecision).toHaveBeenCalledWith('gate-1', 'APPROVE', { reason: 'Reviewed the evidence.', expectedGateVersion: 3 }));
    expect(await screen.findByTestId('e12-gate-receipt')).toHaveTextContent('HUMAN_GATE_APPROVED');
    await waitFor(() => expect(mocks.getGate).toHaveBeenCalledTimes(2));
    expect(await screen.findByText('gate-1 · V4 · APPROVED')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Reject' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'View audit' }));
    expect(await screen.findByText('decision-1')).toBeInTheDocument();
    expect(screen.queryByText('Cancel')).not.toBeInTheDocument();
  });
});
