import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import App from './App';

const envelope = (data: unknown, status = 200) => new Response(JSON.stringify({ data, error: null, request_id: 'request-1' }), { status, headers: { 'Content-Type': 'application/json' } });
const snapshot = (version: number, state: string, watermark = version) => ({
  availability: 'CURRENT', reason: null, freshness: 'CURRENT', as_of: '2026-08-27T00:00:00Z', projection_schema_version: 'e7-live-production-projection/1', snapshot_watermark: watermark,
  item: { production_id: 'project-1', project: { project_id: 'project-1', title: 'Project One', state, version, updated_at: '2026-08-27T00:00:00Z' }, workflow: { nodes: [], edges: [] }, execution_requests: [], verification: { plans: [], results: [] }, evidence: { valid_count: 0, invalidated_count: 0, missing_count: 0, items: [] }, gates: [], waiting: [], recovery: [], recent_events: [] },
});
const receipt = () => ({ availability: 'CURRENT', command_id: 'command-1', action: 'pause', receipt_status: 'APPLIED', result_code: 'PROJECT_PAUSED', target_version: 2, event_ids: ['event-2'], projection_status: 'AWAITING_E7_RECONCILIATION' });
const pauseRequests = (mock: ReturnType<typeof vi.fn>) => mock.mock.calls.filter(([path, init]) => String(path).includes('/commands/pause') && (init as RequestInit | undefined)?.method === 'POST');

const renderOperations = (entry = '/productions/project-1/operations') => render(<MemoryRouter initialEntries={[entry]}><App /></MemoryRouter>);
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('E11 Operations receipt-to-projection reconciliation', () => {
  it('keeps the source snapshot pending after a receipt and marks applied only after a later E7 snapshot reaches target version', async () => {
    let liveReads = 0;
    let resolveDelayed: ((response: Response) => void) | undefined;
    const delayed = new Promise<Response>((resolve) => { resolveDelayed = resolve; });
    const fetchMock = vi.fn((path: string) => {
      if (path.endsWith('/live')) return ++liveReads === 1 ? Promise.resolve(envelope(snapshot(1, 'IMPLEMENTING', 1))) : delayed;
      if (path.includes('/commands/pause')) return Promise.resolve(envelope(receipt(), 202));
      return Promise.resolve(envelope({ availability: 'CURRENT', items: [], after: 1, next_cursor: 1, snapshot_watermark: 1, projection_schema_version: 'e7-live-production-projection/1' }));
    });
    vi.stubGlobal('fetch', fetchMock);
    renderOperations();
    await screen.findByText('Project One');
    fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'operator requested pause' } });
    fireEvent.click(screen.getByRole('button', { name: 'project.pause' }));
    await screen.findByTestId('e11-command-reconciliation');
    expect(screen.getByTestId('e11-command-reconciliation')).toHaveAttribute('data-phase', 'reconciling');
    expect(screen.getByText(/AWAITING E7 RECONCILIATION/)).toBeInTheDocument();
    expect(screen.getByText(/snapshot V1/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'project.resume' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'project.resume' }));
    expect(pauseRequests(fetchMock)).toHaveLength(1);
    expect(screen.queryByRole('button', { name: /cancel/i })).not.toBeInTheDocument();
    resolveDelayed!(envelope(snapshot(2, 'PAUSED', 2)));
    await waitFor(() => expect(screen.getByTestId('e11-command-reconciliation')).toHaveAttribute('data-phase', 'applied'));
    expect(screen.getByText(/snapshot V2/)).toBeInTheDocument();
    expect(screen.getByText('PAUSED')).toBeInTheDocument();
  });

  it('recovers a receipt from the existing GET endpoint after refresh and performs reads only', async () => {
    const fetchMock = vi.fn((path: string, init?: RequestInit) => {
      if (path.includes('/commands/command-1')) return Promise.resolve(envelope(receipt()));
      if (path.endsWith('/live')) return Promise.resolve(envelope(snapshot(2, 'PAUSED', 2)));
      throw new Error(`unexpected path ${path} ${init?.method ?? 'GET'}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    renderOperations('/productions/project-1/operations?e11_command=command-1');
    await waitFor(() => expect(screen.getByTestId('e11-command-reconciliation')).toHaveAttribute('data-phase', 'applied'));
    expect(fetchMock.mock.calls.some(([path]) => String(path).includes('/commands/command-1'))).toBe(true);
    expect(fetchMock.mock.calls.every(([, init]) => !init || !(init as RequestInit).method || (init as RequestInit).method === 'GET')).toBe(true);
  });

  it('aborts an active reconciliation read when Operations unmounts', async () => {
    let liveReads = 0;
    let aborted = false;
    const fetchMock = vi.fn((path: string, init?: RequestInit) => {
      if (path.endsWith('/live')) {
        if (++liveReads === 1) return Promise.resolve(envelope(snapshot(1, 'IMPLEMENTING', 1)));
        return new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => { aborted = true; reject(new DOMException('aborted', 'AbortError')); }, { once: true });
        });
      }
      if (path.includes('/commands/pause')) return Promise.resolve(envelope(receipt(), 202));
      return Promise.resolve(envelope({ availability: 'CURRENT', items: [], after: 1, next_cursor: 1, snapshot_watermark: 1, projection_schema_version: 'e7-live-production-projection/1' }));
    });
    vi.stubGlobal('fetch', fetchMock);
    const rendered = renderOperations();
    await screen.findByText('Project One');
    fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'operator requested pause' } });
    fireEvent.click(screen.getByRole('button', { name: 'project.pause' }));
    await screen.findByTestId('e11-command-reconciliation');
    rendered.unmount();
    await waitFor(() => expect(aborted).toBe(true));
  });
});
