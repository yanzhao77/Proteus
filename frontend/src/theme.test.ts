import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const css = readFileSync('src/styles/index.css', 'utf8');
const design = readFileSync('src/design-system.tsx', 'utf8');
const context = readFileSync('src/ui-context.ts', 'utf8');
const app = readFileSync('src/App.tsx', 'utf8');

describe('E9 semantic design-system contracts', () => {
  it('defines the required semantic token layer and light/dark themes', () => {
    for (const token of ['--background-canvas', '--background-surface', '--text-primary', '--border-default', '--focus-ring', '--action-primary', '--status-running', '--chart-grid', '--dag-node', '--diff-add', '--log-surface', '--space-4', '--radius-md', '--shadow-surface', '--motion-fast']) expect(css).toContain(token);
    expect(css).toContain(':root[data-theme="dark"]');
  });
  it('provides locale, density, preference and Intl date formatting without storing credentials', () => {
    expect(context).toContain("'en-US'");
    expect(context).toContain("'zh-CN'");
    expect(design).toContain('Intl.DateTimeFormat');
    expect(design).toContain('proteus.ui.theme');
    expect(context).not.toMatch(/authorization|refresh_token/i);
  });
  it('provides keyboard focus, tooltip, reduced-motion and non-color status treatment', () => {
    expect(css).toContain(':focus-visible');
    expect(css).toContain('data-tooltip');
    expect(css).toContain('prefers-reduced-motion: reduce');
    expect(design).toContain('ui-status-mark');
    expect(design).toContain('StatusBadge');
  });
  it('does not add marketing particles, rotating HUDs or fabricated progress', () => {
    expect(css).not.toMatch(/particle|rotate\(/);
    expect(app).not.toContain('card.progress ?? 0');
    expect(app).toContain("card.progress === null ? '—'");
  });
});
