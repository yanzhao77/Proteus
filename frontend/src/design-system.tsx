import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { formatBytes, formatDate as intlDate, formatDuration, formatNumber, formatPercent, isRtl, localeNames, message, supportedLocales, type MessageKey, type UiLocale } from './i18n';
import { UiContext, useUi, type FontSize, type LineHeight, type MonoFont, type UiAccent, type UiContextValue, type UiDensity, type UiFont, type UiTheme } from './ui-context';

const preferenceKey = 'proteus.e9.preferences.v2';
const themes: UiTheme[] = ['system', 'light', 'dark', 'high-contrast-light', 'high-contrast-dark', 'protanopia-safe', 'deuteranopia-safe', 'tritanopia-safe', 'monochrome', 'print'];
const accents: UiAccent[] = ['cyan', 'violet', 'amber'];
const densities: UiDensity[] = ['compact', 'comfortable', 'spacious'];
const fonts: UiFont[] = ['system', 'cjk', 'serif'];
const monoFonts: MonoFont[] = ['jetbrains', 'system'];
const fontSizes: FontSize[] = ['small', 'default', 'large', 'extra-large'];
const lineHeights: LineHeight[] = ['compact', 'default', 'relaxed'];
type Preferences = { theme: UiTheme; locale: UiLocale; accent: UiAccent; density: UiDensity; uiFont: UiFont; monoFont: MonoFont; fontSize: FontSize; lineHeight: LineHeight; reducedMotion: boolean };
const defaults: Preferences = { theme: 'system', locale: 'en-US', accent: 'cyan', density: 'comfortable', uiFont: 'system', monoFont: 'jetbrains', fontSize: 'default', lineHeight: 'default', reducedMotion: false };
function readPreferences(): Preferences {
  try {
    const raw = window.localStorage.getItem(preferenceKey);
    if (!raw) return defaults;
    const candidate = JSON.parse(raw) as Partial<Preferences>;
    return {
      theme: themes.includes(candidate.theme as UiTheme) ? candidate.theme as UiTheme : defaults.theme,
      locale: supportedLocales.includes(candidate.locale as UiLocale) ? candidate.locale as UiLocale : defaults.locale,
      accent: accents.includes(candidate.accent as UiAccent) ? candidate.accent as UiAccent : defaults.accent,
      density: densities.includes(candidate.density as UiDensity) ? candidate.density as UiDensity : defaults.density,
      uiFont: fonts.includes(candidate.uiFont as UiFont) ? candidate.uiFont as UiFont : defaults.uiFont,
      monoFont: monoFonts.includes(candidate.monoFont as MonoFont) ? candidate.monoFont as MonoFont : defaults.monoFont,
      fontSize: fontSizes.includes(candidate.fontSize as FontSize) ? candidate.fontSize as FontSize : defaults.fontSize,
      lineHeight: lineHeights.includes(candidate.lineHeight as LineHeight) ? candidate.lineHeight as LineHeight : defaults.lineHeight,
      reducedMotion: Boolean(candidate.reducedMotion),
    };
  } catch { return defaults; }
}
function resolveTheme(theme: UiTheme, systemDark: boolean): Exclude<UiTheme, 'system'> { return theme === 'system' ? (systemDark ? 'dark' : 'light') : theme; }
export function UiProvider({ children }: { children: ReactNode }) {
  const initial = typeof window === 'undefined' ? defaults : readPreferences();
  const [preferences, setPreferences] = useState<Preferences>(initial);
  const [systemDark, setSystemDark] = useState(() => typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia('(prefers-color-scheme: dark)').matches);
  const resolvedTheme = resolveTheme(preferences.theme, systemDark);
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return undefined;
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    const change = () => setSystemDark(media.matches);
    media.addEventListener('change', change);
    return () => media.removeEventListener('change', change);
  }, []);
  useEffect(() => {
    const update = (event: StorageEvent) => { if (event.key === preferenceKey) setPreferences(readPreferences()); };
    window.addEventListener('storage', update);
    return () => window.removeEventListener('storage', update);
  }, []);
  useEffect(() => {
    const root = document.documentElement;
    root.lang = preferences.locale;
    root.dir = isRtl(preferences.locale) ? 'rtl' : 'ltr';
    root.dataset.theme = resolvedTheme;
    root.dataset.accent = preferences.accent;
    root.dataset.density = preferences.density;
    root.dataset.font = preferences.uiFont;
    root.dataset.monoFont = preferences.monoFont;
    root.dataset.fontSize = preferences.fontSize;
    root.dataset.lineHeight = preferences.lineHeight;
    root.dataset.reducedMotion = String(preferences.reducedMotion);
    document.title = `${message(preferences.locale, 'appName')} — ${message(preferences.locale, 'workspace')}`;
    try { window.localStorage.setItem(preferenceKey, JSON.stringify(preferences)); } catch { /* browser presentation preferences are optional */ }
  }, [preferences, resolvedTheme]);
  const update = <K extends keyof Preferences>(key: K, value: Preferences[K]) => setPreferences((current) => ({ ...current, [key]: value }));
  const value = useMemo<UiContextValue>(() => ({
    ...preferences, resolvedTheme,
    setTheme: (theme) => update('theme', theme), setLocale: (locale) => update('locale', locale), setAccent: (accent) => update('accent', accent), setDensity: (density) => update('density', density), setUiFont: (uiFont) => update('uiFont', uiFont), setMonoFont: (monoFont) => update('monoFont', monoFont), setFontSize: (fontSize) => update('fontSize', fontSize), setLineHeight: (lineHeight) => update('lineHeight', lineHeight), setReducedMotion: (reducedMotion) => update('reducedMotion', reducedMotion),
    t: (key, values) => message(preferences.locale, key, values), formatDate: (value) => intlDate(preferences.locale, value), formatNumber: (number) => formatNumber(preferences.locale, number), formatPercent: (number) => formatPercent(preferences.locale, number), formatDuration: (seconds) => formatDuration(preferences.locale, seconds), formatBytes: (bytes) => formatBytes(preferences.locale, bytes),
  }), [preferences, resolvedTheme]);
  return <UiContext.Provider value={value}>{children}</UiContext.Provider>;
}
const icons = { home: 'M3 11.5 12 4l9 7.5v8a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z', grid: 'M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z', gate: 'M5 3h14v18H5zM8 7h8M8 11h8M8 15h5', plus: 'M12 5v14M5 12h14', settings: 'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Zm0-5 1.2 2.3 2.5.7 2.1-1.5 1.8 1.8-1.5 2.1.7 2.5L21 12l-2.3 1.2-.7 2.5 1.5 2.1-1.8 1.8-2.1-1.5-2.5.7L12 21l-1.2-2.3-2.5-.7-2.1 1.5-1.8-1.8 1.5-2.1-.7-2.5L3 12l2.3-1.2.7-2.5-1.5-2.1 1.8-1.8 2.1 1.5 2.5-.7z', arrow: 'M5 12h13M13 6l6 6-6 6', info: 'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20ZM12 10v6M12 7h.01', refresh: 'M20 11a8 8 0 1 0 1 5M20 4v7h-7', shield: 'M12 3 20 6v5c0 5-3.4 8-8 10-4.6-2-8-5-8-10V6z', close: 'm6 6 12 12M18 6 6 18' } as const;
export function Icon({ name, className = '' }: { name: keyof typeof icons; className?: string }) { return <svg aria-hidden="true" className={`ui-icon ${className}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d={icons[name]} /></svg>; }
export function IconButton({ label, icon, onClick, pressed }: { label: string; icon: keyof typeof icons; onClick?: () => void; pressed?: boolean }) { return <button type="button" className="ui-icon-button" aria-label={label} aria-pressed={pressed} data-tooltip={label} onClick={onClick}><Icon name={icon} /></button>; }
const statusKey = (value: string) => { const normalized = value.toLowerCase(); if (normalized.includes('current') || normalized.includes('complete') || normalized.includes('accept') || normalized === 'true') return 'success'; if (normalized.includes('run')) return 'running'; if (normalized.includes('wait') || normalized.includes('pause')) return 'waiting'; if (normalized.includes('stale')) return 'warning'; if (normalized.includes('fail') || normalized.includes('error') || normalized === 'false') return 'failure'; if (normalized.includes('block') || normalized.includes('not_available')) return 'blocked'; return 'neutral'; };
export function StatusBadge({ value }: { value: string }) { const kind = statusKey(value); return <span className="ui-status" data-status={kind} aria-label={`${kind}: ${value}`}><span aria-hidden="true" className="ui-status-mark">{kind === 'success' ? '✓' : kind === 'failure' ? '!' : kind === 'waiting' ? '◌' : kind === 'running' ? '↻' : '•'}</span><span>{value.replaceAll('_', ' ')}</span></span>; }
export function ViewState({ kind, title, detail, onRetry }: { kind: 'loading' | 'pending' | 'error' | 'stale' | 'unavailable' | 'empty'; title?: string; detail?: string; onRetry?: () => void }) { const { t } = useUi(); const fallback: Record<typeof kind, MessageKey> = { loading: 'loading', pending: 'pending', error: 'dataRequestFailed', stale: 'stale', unavailable: 'unavailable', empty: 'empty' }; return <section className="ui-view-state" data-state={kind} role="status" aria-live="polite"><Icon name={kind === 'error' ? 'info' : kind === 'stale' ? 'refresh' : kind === 'unavailable' ? 'shield' : 'info'} /><div><h2>{title ?? t(fallback[kind])}</h2>{detail && <p>{detail}</p>}{onRetry && <button className="ui-button secondary" onClick={onRetry}>{t('retry')}</button>}</div></section>; }
function PreferenceSelect<T extends string>({ label, value, values, names, onChange }: { label: string; value: T; values: readonly T[]; names: Record<T, string>; onChange: (value: T) => void }) { return <label>{label}<select value={value} onChange={(event) => onChange(event.target.value as T)}>{values.map((entry) => <option key={entry} value={entry}>{names[entry]}</option>)}</select></label>; }
export function PreferencePanel({ onClose }: { onClose: () => void }) {
  const ui = useUi(); const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => { closeRef.current?.focus(); }, []);
  const labels: Record<UiTheme, MessageKey> = { system: 'system', light: 'light', dark: 'dark', 'high-contrast-light': 'highContrastLight', 'high-contrast-dark': 'highContrastDark', 'protanopia-safe': 'protanopiaSafe', 'deuteranopia-safe': 'deuteranopiaSafe', 'tritanopia-safe': 'tritanopiaSafe', monochrome: 'monochrome', print: 'print' };
  return <aside className="ui-preferences" role="dialog" aria-modal="true" aria-label={ui.t('displaySettings')} onKeyDown={(event) => { if (event.key === 'Escape') onClose(); }}><header><div><span className="ui-kicker">{ui.t('workspace')}</span><h2>{ui.t('displaySettings')}</h2></div><button ref={closeRef} type="button" className="ui-icon-button" aria-label={ui.t('close')} onClick={onClose}><Icon name="close" /></button></header><PreferenceSelect label={ui.t('theme')} value={ui.theme} values={themes} names={Object.fromEntries(themes.map((theme) => [theme, ui.t(labels[theme])])) as Record<UiTheme, string>} onChange={ui.setTheme}/><PreferenceSelect label={ui.t('locale')} value={ui.locale} values={supportedLocales} names={localeNames} onChange={ui.setLocale}/><PreferenceSelect label={ui.t('accent')} value={ui.accent} values={accents} names={{ cyan: 'Cyan', violet: 'Violet', amber: 'Amber' }} onChange={ui.setAccent}/><PreferenceSelect label={ui.t('uiFont')} value={ui.uiFont} values={fonts} names={{ system: 'Inter / system', cjk: 'CJK / system', serif: 'Serif / system' }} onChange={ui.setUiFont}/><PreferenceSelect label={ui.t('monoFont')} value={ui.monoFont} values={monoFonts} names={{ jetbrains: 'JetBrains Mono', system: 'System monospace' }} onChange={ui.setMonoFont}/><PreferenceSelect label={ui.t('fontSize')} value={ui.fontSize} values={fontSizes} names={{ small: ui.t('small'), default: ui.t('default'), large: ui.t('large'), 'extra-large': ui.t('extraLarge') }} onChange={ui.setFontSize}/><PreferenceSelect label={ui.t('lineHeight')} value={ui.lineHeight} values={lineHeights} names={{ compact: ui.t('compact'), default: ui.t('default'), relaxed: ui.t('relaxed') }} onChange={ui.setLineHeight}/><PreferenceSelect label={ui.t('density')} value={ui.density} values={densities} names={{ compact: ui.t('compact'), comfortable: ui.t('comfortable'), spacious: ui.t('spacious') }} onChange={ui.setDensity}/><label className="ui-checkbox"><input type="checkbox" checked={ui.reducedMotion} onChange={(event) => ui.setReducedMotion(event.target.checked)}/>{ui.t('reducedMotion')}</label></aside>;
}
