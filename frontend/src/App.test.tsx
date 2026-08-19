import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import App from './App';

describe('Factory Home authority safety', () => {
  it('renders the Production Entry prompt without claiming a production exists', async () => {
    render(<MemoryRouter initialEntries={['/home']}><App /></MemoryRouter>);
    expect(await screen.findByRole('heading', { name: 'What do you want to build?' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /create draft/i })).toBeDisabled();
    expect(screen.queryByText(/production created/i)).not.toBeInTheDocument();
  });
  it('renders the explicit pending boundary when no authority adapter exists', async () => {
    render(<MemoryRouter initialEntries={['/productions']}><App /></MemoryRouter>);
    expect(await screen.findByText(/portfolio load failed/i)).toBeInTheDocument();
    expect(screen.getByText(/does not invent production state/i)).toBeInTheDocument();
  });
  it('keeps the primary CTA at the required 44px target through its shared class', async () => {
    render(<MemoryRouter initialEntries={['/home']}><App /></MemoryRouter>);
    const button = await screen.findByRole('button', { name: /create draft/i });
    expect(button).toHaveClass('factory-button-primary');
  });
});
