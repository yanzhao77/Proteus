import { MemoryRouter } from 'react-router-dom';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ExecutionQueueItemViewModel, WorkerDetailViewModel, WorkerFleetItemViewModel } from './models';

const mocks = vi.hoisted(() => ({ listWorkers: vi.fn(), getWorker: vi.fn(), getExecutionQueue: vi.fn() }));

import App from './App';

const workerFleet: WorkerFleetItemViewModel = {
  workerId: 'wt-shell-1',
  revision: 3,
  runtimeKind: 'hermes-shell',
  trustLevel: 'STANDARD',
  availabilityStatus: 'AVAILABLE',
  admissionStatus: 'ADMISSIBLE',
  availabilityVersion: 2,
  concurrencyCapacity: 4,
  activeAssignments: 1,
  totalAssignments: 2,
  projectId: 'project-alice',
  reason: null,
  updatedAt: '2026-09-01T00:00:00Z',
};
const workerDetail: WorkerDetailViewModel = {
  ...workerFleet,
  assignments: [
    {
      assignmentId: 'assign-1',
      projectId: 'project-alice',
      taskId: 'task-1',
      executionRequestId: 'req-1',
      executionAttempt: 0,
      assignmentState: 'ASSIGNED',
      workerAgentIdentity: 'agent-1',
      contextIdentity: 'ctx-1',
      startedAt: '2026-09-01T00:00:00Z',
      terminalAt: null,
      terminalReason: null,
    },
  ],
  leases: [
    {
      leaseId: 'lease-1',
      executionRequestId: 'req-1',
      projectId: 'project-alice',
      taskId: 'task-1',
      schedulerId: 'sched-1',
      leaseState: 'ACTIVE',
      grantedAt: '2026-09-01T00:00:00Z',
      heartbeatAt: '2026-09-01T00:01:00Z',
      expiresAt: '2026-09-01T01:00:00Z',
      terminalReason: null,
      terminalAt: null,
    },
  ],
};
const queueItems: ExecutionQueueItemViewModel[] = [
  {
    queueItemId: 'queue-1',
    executionRequestId: 'req-1',
    projectId: 'project-alice',
    taskId: 'task-1',
    priority: 10,
    availableAt: '2026-09-01T00:00:00Z',
    enqueuedAt: '2026-09-01T00:00:00Z',
    queueState: 'QUEUED',
    requestState: 'QUEUED',
    workerTemplateId: 'wt-shell-1',
    workerTemplateRevision: 3,
    currentLeaseId: null,
    updatedAt: '2026-09-01T00:00:00Z',
  },
  {
    queueItemId: 'queue-2',
    executionRequestId: 'req-2',
    projectId: 'project-alice',
    taskId: 'task-2',
    priority: 5,
    availableAt: '2026-09-01T00:05:00Z',
    enqueuedAt: '2026-09-01T00:05:00Z',
    queueState: 'LEASED',
    requestState: 'EXECUTING',
    workerTemplateId: 'wt-shell-2',
    workerTemplateRevision: 1,
    currentLeaseId: 'lease-2',
    updatedAt: '2026-09-01T00:05:00Z',
  },
];

beforeEach(() => {
  mocks.listWorkers.mockReset();
  mocks.getWorker.mockReset();
  mocks.getExecutionQueue.mockReset();
  (window as unknown as { __adapters?: { workers?: unknown } }).__adapters = { workers: mocks };
});

describe('E14 Worker Control Plane', () => {
  it('renders the worker fleet table with worker rows from listWorkers', async () => {
    mocks.listWorkers.mockResolvedValue({ kind: 'data', value: [workerFleet] });
    render(<MemoryRouter initialEntries={['/workers']}><App /></MemoryRouter>);
    expect(await screen.findByText('wt-shell-1')).toBeInTheDocument();
    expect(screen.getByText('V3')).toBeInTheDocument();
    expect(screen.getAllByText('hermes-shell').length).toBeGreaterThan(0);
    expect(screen.getByText('4')).toBeInTheDocument();
    expect(screen.getByText('1 / 2')).toBeInTheDocument();
    expect(mocks.listWorkers).toHaveBeenCalledTimes(1);
  });

  it('filters the worker fleet rows by template or runtime kind', async () => {
    mocks.listWorkers.mockResolvedValue({
      kind: 'data',
      value: [
        workerFleet,
        { ...workerFleet, workerId: 'wt-special-9', runtimeKind: 'hermes-rust' },
      ],
    });
    render(<MemoryRouter initialEntries={['/workers']}><App /></MemoryRouter>);
    expect(await screen.findByText('wt-shell-1')).toBeInTheDocument();
    expect(screen.getByText('wt-special-9')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Template / Runtime filter'), { target: { value: 'rust' } });
    expect(screen.queryByText('wt-shell-1')).not.toBeInTheDocument();
    expect(screen.getByText('wt-special-9')).toBeInTheDocument();
  });

  it('links each worker row to its detail page', async () => {
    mocks.listWorkers.mockResolvedValue({ kind: 'data', value: [workerFleet] });
    render(<MemoryRouter initialEntries={['/workers']}><App /></MemoryRouter>);
    expect(await screen.findByText('wt-shell-1')).toBeInTheDocument();
    const link = screen.getByRole('link', { name: /wt-shell-1/ });
    expect(link.getAttribute('href')).toContain('/workers/wt-shell-1');
  });

  it('shows the empty state when the fleet is empty', async () => {
    mocks.listWorkers.mockResolvedValue({ kind: 'data', value: [] });
    render(<MemoryRouter initialEntries={['/workers']}><App /></MemoryRouter>);
    await waitFor(() => expect(mocks.listWorkers).toHaveBeenCalledTimes(1));
    const status = await screen.findByRole('status');
    expect(status.getAttribute('data-state')).toBe('empty');
    expect(screen.queryByText('wt-shell-1')).not.toBeInTheDocument();
  });

  it('renders the worker detail template overview, assignments and leases from getWorker', async () => {
    mocks.getWorker.mockResolvedValue({ kind: 'data', value: workerDetail });
    render(<MemoryRouter initialEntries={['/workers/wt-shell-1']}><App /></MemoryRouter>);
    expect(await screen.findByText('wt-shell-1 · V3')).toBeInTheDocument();
    expect(screen.getAllByText('hermes-shell').length).toBeGreaterThan(0);
    expect(screen.getAllByText('task-1').length).toBeGreaterThan(0);
    expect(screen.getByText('agent-1')).toBeInTheDocument();
    expect(screen.getByText('sched-1')).toBeInTheDocument();
    expect(mocks.getWorker).toHaveBeenCalledWith('wt-shell-1');
  });

  it('shows the unavailable state when getWorker returns not_implemented', async () => {
    mocks.getWorker.mockResolvedValue({ kind: 'not_implemented', message: 'nope' });
    render(<MemoryRouter initialEntries={['/workers/wt-shell-1']}><App /></MemoryRouter>);
    await waitFor(() => expect(mocks.getWorker).toHaveBeenCalledWith('wt-shell-1'));
    const status = await screen.findByRole('status');
    expect(status.getAttribute('data-state')).toBe('unavailable');
    expect(screen.queryByText('assign-1')).not.toBeInTheDocument();
  });

  it('renders queue rows and an empty state from getExecutionQueue', async () => {
    mocks.getExecutionQueue.mockResolvedValue({ kind: 'data', value: queueItems });
    const { unmount } = render(<MemoryRouter initialEntries={['/execution-queue']}><App /></MemoryRouter>);
    expect(await screen.findByText('task-1')).toBeInTheDocument();
    expect(screen.getAllByText('QUEUED').length).toBeGreaterThan(0);
    expect(screen.getByText('EXECUTING')).toBeInTheDocument();
    expect(screen.getByText('wt-shell-1')).toBeInTheDocument();
    expect(screen.getAllByText('LEASED').length).toBeGreaterThan(0);
    expect(mocks.getExecutionQueue).toHaveBeenCalledTimes(1);
    unmount();

    mocks.getExecutionQueue.mockReset();
    mocks.getExecutionQueue.mockResolvedValue({ kind: 'data', value: [] });
    render(<MemoryRouter initialEntries={['/execution-queue']}><App /></MemoryRouter>);
    await waitFor(() => expect(mocks.getExecutionQueue).toHaveBeenCalledTimes(1));
    const status = await screen.findByRole('status');
    expect(status.getAttribute('data-state')).toBe('empty');
  });
});
