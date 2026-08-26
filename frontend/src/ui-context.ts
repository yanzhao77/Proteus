import { createContext, useContext } from 'react';
import type { MessageKey, UiLocale } from './i18n';

export type UiTheme = 'system' | 'light' | 'dark' | 'high-contrast-light' | 'high-contrast-dark' | 'protanopia-safe' | 'deuteranopia-safe' | 'tritanopia-safe' | 'monochrome' | 'print';
export type UiAccent = 'cyan' | 'violet' | 'amber';
export type UiDensity = 'compact' | 'comfortable' | 'spacious';
export type UiFont = 'system' | 'cjk' | 'serif';
export type MonoFont = 'jetbrains' | 'system';
export type FontSize = 'small' | 'default' | 'large' | 'extra-large';
export type LineHeight = 'compact' | 'default' | 'relaxed';
export type UiContextValue = {
  theme: UiTheme;
  resolvedTheme: Exclude<UiTheme, 'system'>;
  locale: UiLocale;
  accent: UiAccent;
  density: UiDensity;
  uiFont: UiFont;
  monoFont: MonoFont;
  fontSize: FontSize;
  lineHeight: LineHeight;
  reducedMotion: boolean;
  setTheme: (value: UiTheme) => void;
  setLocale: (value: UiLocale) => void;
  setAccent: (value: UiAccent) => void;
  setDensity: (value: UiDensity) => void;
  setUiFont: (value: UiFont) => void;
  setMonoFont: (value: MonoFont) => void;
  setFontSize: (value: FontSize) => void;
  setLineHeight: (value: LineHeight) => void;
  setReducedMotion: (value: boolean) => void;
  t: (key: MessageKey, values?: Record<string, string | number>) => string;
  formatDate: (value: string | null | undefined) => string;
  formatNumber: (value: number) => string;
  formatPercent: (value: number) => string;
  formatDuration: (seconds: number) => string;
  formatBytes: (bytes: number) => string;
};
export const UiContext = createContext<UiContextValue | null>(null);
export function useUi() {
  const value = useContext(UiContext);
  if (!value) throw new Error('UiProvider is required');
  return value;
}
