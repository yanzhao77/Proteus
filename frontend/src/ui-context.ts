import { createContext, useContext } from 'react';

export type UiTheme = 'light' | 'dark' | 'system';
export type UiLocale = 'en-US' | 'zh-CN';
export type UiDensity = 'comfortable' | 'compact';


export type UiContextValue = {
  theme: UiTheme;
  locale: UiLocale;
  density: UiDensity;
  setTheme: (value: UiTheme) => void;
  setLocale: (value: UiLocale) => void;
  setDensity: (value: UiDensity) => void;
  t: (key: string) => string;
  formatDate: (value: string | null | undefined) => string;
};
export const UiContext = createContext<UiContextValue | null>(null);
export function useUi() {
  const value = useContext(UiContext);
  if (!value) throw new Error('UiProvider is required');
  return value;
}
