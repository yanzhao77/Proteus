import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import App from './App';
import { catalogs, supportedLocales } from './i18n';
afterEach(() => { cleanup(); window.localStorage.clear(); });
describe('E9 route rendering matrix', () => {
  it.each(supportedLocales)('renders Home once for locale %s without fixture facts', async (locale) => {
    window.localStorage.setItem('proteus.e9.preferences.v2', JSON.stringify({ locale, theme: 'light', accent: 'cyan', density: 'comfortable', uiFont: 'system', monoFont: 'jetbrains', fontSize: 'default', lineHeight: 'default', reducedMotion: false }));
    render(<MemoryRouter initialEntries={['/home']}><App /></MemoryRouter>);
    expect(await screen.findByRole('heading', { name: catalogs[locale].home })).toBeInTheDocument();
    expect(screen.queryByText(/production created/i)).not.toBeInTheDocument();
  });
  it.each(['light','dark','high-contrast-light','high-contrast-dark','protanopia-safe','deuteranopia-safe','tritanopia-safe','monochrome','print','system'] as const)('renders Home once for theme %s', async (theme) => {
    window.localStorage.setItem('proteus.e9.preferences.v2', JSON.stringify({ locale: 'en-US', theme, accent: 'violet', density: 'spacious', uiFont: 'cjk', monoFont: 'system', fontSize: 'extra-large', lineHeight: 'relaxed', reducedMotion: true }));
    render(<MemoryRouter initialEntries={['/home']}><App /></MemoryRouter>);
    expect(await screen.findByRole('heading', { name: 'Home' })).toBeInTheDocument();
  });
  it('persists only non-sensitive display preferences and applies RTL, font, density and motion attributes', async () => {
    render(<MemoryRouter initialEntries={['/home']}><App /></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: 'Display settings' }));
    const selects = screen.getAllByRole('combobox');
    fireEvent.change(selects[1], { target: { value: 'ar-SA' } });
    fireEvent.change(selects[3], { target: { value: 'cjk' } });
    fireEvent.change(selects[5], { target: { value: 'extra-large' } });
    fireEvent.change(selects[7], { target: { value: 'spacious' } });
    fireEvent.click(screen.getByRole('checkbox'));
    await waitFor(() => expect(document.documentElement.dir).toBe('rtl'));
    expect(document.documentElement.dataset.font).toBe('cjk');
    expect(document.documentElement.dataset.fontSize).toBe('extra-large');
    expect(document.documentElement.dataset.density).toBe('spacious');
    expect(document.documentElement.dataset.reducedMotion).toBe('true');
    const stored = window.localStorage.getItem('proteus.e9.preferences.v2') ?? '';
    expect(stored).toContain('ar-SA');
    expect(stored).not.toMatch(/authorization|refresh_token|api[_-]?key|bearer/i);
  });

});
