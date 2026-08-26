import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import App from './App';

describe('E9 global workspace rendering', () => {
  it('renders the stable Home workspace and the production creation entry without claiming a project exists', async () => {
    render(<MemoryRouter initialEntries={['/home']}><App /></MemoryRouter>);
    expect(await screen.findByRole('heading', { name: 'Home' })).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: /new production/i }).some((link) => link.getAttribute('href') === '/new')).toBe(true);
    expect(screen.queryByText(/production created/i)).not.toBeInTheDocument();
  });

  it('renders an explicit unavailable or failed data state instead of inventing a portfolio', async () => {
    render(<MemoryRouter initialEntries={['/productions']}><App /></MemoryRouter>);
    expect(await screen.findByText(/request unavailable|session required/i)).toBeInTheDocument();
    expect(screen.queryByText(/0%/)).not.toBeInTheDocument();
  });

  it('exposes accessible workspace navigation and display settings', async () => {
    render(<MemoryRouter initialEntries={['/home']}><App /></MemoryRouter>);
    expect(await screen.findByRole('navigation', { name: 'Workspace navigation' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Display settings' })).toBeInTheDocument();
  });
});
