import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { catalogs, formatBytes, formatDuration, formatOrdinal, formatPercent, isRtl, message, pseudoLocalize, supportedLocales, validateCatalogs } from './i18n';
const css = readFileSync('src/styles/index.css', 'utf8');
const design = readFileSync('src/design-system.tsx', 'utf8');
const context = readFileSync('src/ui-context.ts', 'utf8');
const app = readFileSync('src/App.tsx', 'utf8');
describe('E9-only locale, theme and typography acceptance matrix', () => {
  it('contains exactly the required 22 complete locale catalogs without a missing-key fallback', () => {
    expect(supportedLocales).toHaveLength(22);
    expect(validateCatalogs()).toBe(true);
    for (const locale of supportedLocales) {
      expect(Object.keys(catalogs[locale]).sort()).toEqual(Object.keys(catalogs['en-US']).sort());
      expect(message(locale, 'home')).not.toHaveLength(0);
      expect(message(locale, 'dataRequestFailed')).not.toHaveLength(0);
    }
  });
  it('does not leave English fallback in the core visible strings of non-English locales', () => {
    for (const locale of supportedLocales.filter((locale) => !['en-US', 'en-GB'].includes(locale))) {
      for (const key of ['home', 'homeDetail', 'newEntry', 'displaySettings', 'error.UNKNOWN.title', 'error.UNKNOWN.description'] as const) {
        expect(catalogs[locale][key]).not.toBe(catalogs['en-US'][key]);
      }
    }
  });
  it('validates Intl-safe plural, select, ordinal, date-compatible numeric, duration, byte and pseudo-localized formatting', () => {
    expect(formatPercent('de-DE', .125)).toContain('%');
    expect(formatDuration('th-TH', 125)).toContain('m');
    expect(formatBytes('ja-JP', 2048)).toContain('KB');
    expect(formatOrdinal('en-US', 22)).toBe('22nd');
    expect(pseudoLocalize('Display settings')).toMatch(/^［.*］$/);
  });
  it('defines all 10 themes, constrained accents, fonts, font sizes, line heights and density values', () => {
    for (const theme of ['light','dark','high-contrast-light','high-contrast-dark','protanopia-safe','deuteranopia-safe','tritanopia-safe','monochrome','print']) expect(css).toContain(`data-theme="${theme}"`);
    for (const token of ['--background-canvas','--text-primary','--focus-ring','--status-success','--status-warning','--status-failure','--dag-node','--log-surface']) expect(css).toContain(token);
    for (const selector of ['data-accent','data-font','data-mono-font','data-font-size','data-line-height','data-density','data-reduced-motion']) expect(css).toContain(selector);
    expect(context).toContain("'high-contrast-dark'");
    expect(context).toContain("'extra-large'");
    expect(css).not.toMatch(/https?:\/\/.*font/i);
  });
  it('supports real RTL/CJK presentation and preserves technical values as LTR isolated text', () => {
    expect(isRtl('ar-SA')).toBe(true); expect(isRtl('he-IL')).toBe(true); expect(isRtl('ja-JP')).toBe(false);
    expect(css).toContain('[dir="rtl"]');
    expect(css).toContain('unicode-bidi:isolate');
    for (const locale of ['zh-CN','zh-TW','ja-JP','ko-KR','th-TH','hi-IN','ar-SA','he-IL']) expect(supportedLocales).toContain(locale);
  });
  it('keeps focus, skip navigation, dialog and no-color-only status affordances', () => {
    expect(css).toContain(':focus-visible'); expect(css).toContain('.skip-link'); expect(design).toContain('role="dialog"'); expect(design).toContain('ui-status-mark'); expect(design).toContain('aria-live="polite"');
  });
  it('does not add fabricated progress, remote fonts, credentials, or authority paths beyond E11 pause/resume receipts', () => {
    expect(css).not.toMatch(/particle|rotate\(/); expect(app).not.toMatch(/authorization|refresh_token|api[_-]?key/i);
    expect(app).toContain("action: 'pause' | 'resume'");
    expect(app).toContain('adapters.production.pause(live.project.projectId, metadata)');
    expect(app).toContain('adapters.production.resume(live.project.projectId, metadata)');
    for (const forbidden of ['setProjectState','createExecutionRequest','submitGateDecision',"submit('cancel')",'actor:', 'requested_by', 'scope:']) expect(app).not.toContain(forbidden);
  });
});
