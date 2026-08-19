import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const css = readFileSync('src/styles/index.css', 'utf8');
const app = readFileSync('src/App.tsx', 'utf8');

describe('Factory Home visual and authority contracts', () => {
  it('provides a 44px shared primary CTA target', () => expect(css).toContain('min-h-11'));
  it('provides a reduced-motion fallback', () => expect(css).toContain('prefers-reduced-motion: reduce'));
  it('provides a high-contrast fallback', () => expect(css).toContain('prefers-contrast: more'));
  it('provides state hatch treatment for stale snapshots', () => expect(css).toContain('factory-snapshot-stale'));
  it('does not use a continuous neon pulse utility', () => expect(css).not.toContain('animate-pulse'));
  it('does not add a particle or rotating HUD background', () => { expect(css).not.toMatch(/particle|rotate\(/); });
  it('renders unavailable progress rather than a fabricated zero', () => expect(app).toContain("PROGRESS {card.progress === null ? 'NOT AVAILABLE'"));
  it('keeps production creation text out of the default Home render', () => expect(app).toContain("CREATE DRAFT"));
});
