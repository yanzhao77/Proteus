import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { UiContext, useUi, type UiContextValue, type UiDensity, type UiLocale, type UiTheme } from './ui-context';

const COPY: Record<UiLocale, Record<string, string>> = {
  'en-US': {
    appName: 'Proteus', workspace: 'Software Production Workspace', home: 'Home', productions: 'Projects', gates: 'Gate inbox', newEntry: 'New production', drafts: 'Drafts',
    operations: 'Operations', settings: 'Display settings', theme: 'Theme', locale: 'Language', density: 'Density', system: 'System', light: 'Light', dark: 'Dark',
    comfortable: 'Comfortable', compact: 'Compact', loading: 'Loading authoritative data', pending: 'Awaiting an authoritative source', error: 'Data request failed',
    stale: 'Snapshot is stale', unavailable: 'Not available for your current scope', empty: 'Nothing to show yet', retry: 'Retry', open: 'Open', review: 'Review',
    productionWorkspace: 'Project operations', readOnly: 'Read-only projection', evidence: 'Evidence', verification: 'Verification', execution: 'Execution', workflow: 'Workflow DAG', recovery: 'Recovery',
    controlledRecovery: 'Open controlled recovery', noDirectCommand: 'Recovery actions remain controlled by existing authority workflows.', signedOut: 'Session required',
    statusCurrent: 'Current', statusStale: 'Stale', statusDegraded: 'Degraded', statusUnavailable: 'Unavailable', statusRunning: 'Running', statusWaiting: 'Waiting', statusSuccess: 'Completed', statusWarning: 'Attention', statusFailure: 'Failed', statusBlocked: 'Blocked',
  },
  'zh-CN': {
    appName: 'Proteus', workspace: '软件生产工作区', home: '首页', productions: '项目', gates: '门禁收件箱', newEntry: '新建生产', drafts: '草稿',
    operations: '运营工作区', settings: '显示设置', theme: '主题', locale: '语言', density: '密度', system: '跟随系统', light: '浅色', dark: '深色',
    comfortable: '舒适', compact: '紧凑', loading: '正在加载权威数据', pending: '正在等待权威数据源', error: '数据请求失败',
    stale: '快照已过期', unavailable: '当前权限范围不可用', empty: '暂时没有可显示内容', retry: '重试', open: '打开', review: '审查',
    productionWorkspace: '项目运营', readOnly: '只读投影', evidence: '证据', verification: '验证', execution: '执行', workflow: '工作流 DAG', recovery: '恢复',
    controlledRecovery: '打开受控恢复入口', noDirectCommand: '恢复操作仍由既有 authority workflow 控制。', signedOut: '需要会话',
    statusCurrent: '当前', statusStale: '陈旧', statusDegraded: '降级', statusUnavailable: '不可用', statusRunning: '运行中', statusWaiting: '等待中', statusSuccess: '已完成', statusWarning: '需关注', statusFailure: '失败', statusBlocked: '受阻',
  },
};

const getStored = <T extends string>(key: string, fallback: T): T => {
  try { return (window.localStorage.getItem(key) as T | null) ?? fallback; } catch { return fallback; }
};

export function UiProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<UiTheme>(() => getStored('proteus.ui.theme', 'system'));
  const [locale, setLocale] = useState<UiLocale>(() => getStored('proteus.ui.locale', 'en-US'));
  const [density, setDensity] = useState<UiDensity>(() => getStored('proteus.ui.density', 'comfortable'));
  useEffect(() => {
    const resolved = theme === 'system' ? (window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light') : theme;
    document.documentElement.dataset.theme = resolved;
    document.documentElement.dataset.locale = locale;
    document.documentElement.dataset.density = density;
    try { window.localStorage.setItem('proteus.ui.theme', theme); window.localStorage.setItem('proteus.ui.locale', locale); window.localStorage.setItem('proteus.ui.density', density); } catch { /* UI preferences are optional. */ }
  }, [theme, locale, density]);
  const value = useMemo<UiContextValue>(() => ({
    theme, locale, density, setTheme, setLocale, setDensity,
    t: (key) => COPY[locale][key] ?? COPY['en-US'][key] ?? key,
    formatDate: (value) => value ? new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) : '—',
  }), [theme, locale, density]);
  return <UiContext.Provider value={value}>{children}</UiContext.Provider>;
}

const icons: Record<string, string> = {
  home: 'M3 11.5 12 4l9 7.5v8a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z',
  grid: 'M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z',
  gate: 'M5 3h14v18H5zM8 7h8M8 11h8M8 15h5',
  plus: 'M12 5v14M5 12h14',
  settings: 'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Zm0-5 1.2 2.3 2.5.7 2.1-1.5 1.8 1.8-1.5 2.1.7 2.5L21 12l-2.3 1.2-.7 2.5 1.5 2.1-1.8 1.8-2.1-1.5-2.5.7L12 21l-1.2-2.3-2.5-.7-2.1 1.5-1.8-1.8 1.5-2.1-.7-2.5L3 12l2.3-1.2.7-2.5-1.5-2.1 1.8-1.8 2.1 1.5 2.5-.7z',
  arrow: 'M5 12h13M13 6l6 6-6 6',
  info: 'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20ZM12 10v6M12 7h.01',
  refresh: 'M20 11a8 8 0 1 0 1 5M20 4v7h-7',
  shield: 'M12 3 20 6v5c0 5-3.4 8-8 10-4.6-2-8-5-8-10V6z',
  close: 'm6 6 12 12M18 6 6 18',
};
export function Icon({ name, className = '' }: { name: keyof typeof icons; className?: string }) {
  return <svg aria-hidden="true" className={`ui-icon ${className}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d={icons[name]} /></svg>;
}
export function IconButton({ label, icon, onClick, pressed }: { label: string; icon: keyof typeof icons; onClick?: () => void; pressed?: boolean }) {
  return <button type="button" className="ui-icon-button" aria-label={label} aria-pressed={pressed} data-tooltip={label} onClick={onClick}><Icon name={icon} /></button>;
}

const statusKey = (value: string) => {
  const normalized = value.toLowerCase();
  if (normalized.includes('current') || normalized.includes('complete') || normalized.includes('accept')) return 'success';
  if (normalized.includes('run')) return 'running';
  if (normalized.includes('wait') || normalized.includes('pause')) return 'waiting';
  if (normalized.includes('stale')) return 'warning';
  if (normalized.includes('fail') || normalized.includes('error')) return 'failure';
  if (normalized.includes('block') || normalized.includes('not_available')) return 'blocked';
  return 'neutral';
};
export function StatusBadge({ value }: { value: string }) {
  const kind = statusKey(value);
  return <span className="ui-status" data-status={kind}><span aria-hidden="true" className="ui-status-mark">{kind === 'success' ? '✓' : kind === 'failure' ? '!' : kind === 'waiting' ? '◌' : kind === 'running' ? '↻' : '•'}</span><span>{value.replaceAll('_', ' ')}</span></span>;
}
export function ViewState({ kind, title, detail, onRetry }: { kind: 'loading' | 'pending' | 'error' | 'stale' | 'unavailable' | 'empty'; title?: string; detail?: string; onRetry?: () => void }) {
  const { t } = useUi();
  const fallback = { loading: t('loading'), pending: t('pending'), error: t('error'), stale: t('stale'), unavailable: t('unavailable'), empty: t('empty') }[kind];
  return <section className="ui-view-state" data-state={kind}><Icon name={kind === 'error' ? 'info' : kind === 'stale' ? 'refresh' : kind === 'unavailable' ? 'shield' : 'info'} /><div><h2>{title ?? fallback}</h2>{detail && <p>{detail}</p>}{onRetry && <button className="ui-button secondary" onClick={onRetry}>{t('retry')}</button>}</div></section>;
}
export function PreferencePanel({ onClose }: { onClose: () => void }) {
  const { theme, locale, density, setTheme, setLocale, setDensity, t } = useUi();
  return <aside className="ui-preferences" aria-label={t('settings')}><header><div><span className="ui-kicker">WORKSPACE</span><h2>{t('settings')}</h2></div><IconButton icon="close" label="Close" onClick={onClose} /></header><label>{t('theme')}<select value={theme} onChange={(event) => setTheme(event.target.value as UiTheme)}><option value="system">{t('system')}</option><option value="light">{t('light')}</option><option value="dark">{t('dark')}</option></select></label><label>{t('locale')}<select value={locale} onChange={(event) => setLocale(event.target.value as UiLocale)}><option value="en-US">English</option><option value="zh-CN">简体中文</option></select></label><label>{t('density')}<select value={density} onChange={(event) => setDensity(event.target.value as UiDensity)}><option value="comfortable">{t('comfortable')}</option><option value="compact">{t('compact')}</option></select></label></aside>;
}
