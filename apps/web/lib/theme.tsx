'use client';

import { createContext, useCallback, useContext, useEffect, useState } from 'react';

export type ThemeId = 'discovery' | 'architect' | 'delivery';

export const THEME_KEY = 'aivanta.theme';
export const DEFAULT_THEME: ThemeId = 'architect';

export const THEMES: { id: ThemeId; label: string; hint: string }[] = [
  { id: 'discovery', label: 'Discovery', hint: 'RFP · intake' },
  { id: 'architect', label: 'Architect', hint: 'Design · canvas' },
  { id: 'delivery', label: 'Delivery', hint: 'Pricing · run' },
];

function isTheme(v: string | null | undefined): v is ThemeId {
  return v === 'discovery' || v === 'architect' || v === 'delivery';
}

export function readStoredTheme(): ThemeId {
  try {
    const v = window.localStorage.getItem(THEME_KEY);
    if (isTheme(v)) return v;
  } catch {
    /* ignore */
  }
  return DEFAULT_THEME;
}

export function applyTheme(theme: ThemeId) {
  document.documentElement.setAttribute('data-theme', theme);
}

interface ThemeCtx {
  theme: ThemeId;
  setTheme: (id: ThemeId) => void;
}

const ThemeContext = createContext<ThemeCtx | null>(null);

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<ThemeId>(DEFAULT_THEME);

  useEffect(() => {
    const stored = readStoredTheme();
    setThemeState(stored);
    applyTheme(stored);
  }, []);

  const setTheme = useCallback((id: ThemeId) => {
    setThemeState(id);
    applyTheme(id);
    try {
      window.localStorage.setItem(THEME_KEY, id);
    } catch {
      /* ignore */
    }
  }, []);

  return <ThemeContext.Provider value={{ theme, setTheme }}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeCtx {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme must be used inside ThemeProvider');
  return ctx;
}

/** Compact segmented control for the three journey themes. */
export function ThemeSwitcher({ className = '' }: { className?: string }) {
  const { theme, setTheme } = useTheme();
  return (
    <div className={`theme-switch ${className}`} role="group" aria-label="Visual theme">
      {THEMES.map((t) => (
        <button
          key={t.id}
          type="button"
          className={`theme-chip ${theme === t.id ? 'on' : ''}`}
          title={`${t.label} — ${t.hint}`}
          aria-pressed={theme === t.id}
          onClick={() => setTheme(t.id)}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

/** Inline script for root layout — applies stored theme before paint to avoid flash. */
export const THEME_BOOT_SCRIPT = `(function(){try{var k='${THEME_KEY}';var d='${DEFAULT_THEME}';var v=localStorage.getItem(k);if(v!=='discovery'&&v!=='architect'&&v!=='delivery')v=d;document.documentElement.setAttribute('data-theme',v);}catch(e){document.documentElement.setAttribute('data-theme','${DEFAULT_THEME}');}})();`;
