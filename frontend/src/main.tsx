import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import './styles/index.css';
import App from './App';

try {
  const raw = window.localStorage.getItem('proteus.e9.preferences.v2');
  if (raw) {
    const prefs = JSON.parse(raw) as Record<string, unknown>;
    const root = document.documentElement;
    const theme = typeof prefs.theme === 'string' ? prefs.theme : 'system';
    root.dataset.theme = theme === 'system' ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light') : theme;
    if (typeof prefs.locale === 'string') { root.lang = prefs.locale; root.dir = ['ar-SA', 'he-IL'].includes(prefs.locale) ? 'rtl' : 'ltr'; }
    for (const [key, dataKey] of [['accent', 'accent'], ['density', 'density'], ['uiFont', 'font'], ['monoFont', 'monoFont'], ['fontSize', 'fontSize'], ['lineHeight', 'lineHeight']] as const) if (typeof prefs[key] === 'string') root.dataset[dataKey] = prefs[key] as string;
    root.dataset.reducedMotion = String(Boolean(prefs.reducedMotion));
  }
} catch { /* optional presentation preference only */ }

createRoot(document.getElementById('root')!).render(<StrictMode><BrowserRouter><App /></BrowserRouter></StrictMode>);
