import { useCallback, useEffect, useMemo, useState } from "react";
import {
  DEFAULT_THEME_ID,
  THEME_STORAGE_KEY,
  THEMES,
  getTheme,
  type Theme,
} from "./themes";
import { ThemeContext } from "./theme-context";
import { updateFavicon } from "@/lib/favicon";

/** Apply a theme to <html>: data-theme drives the token block, the `dark`
 *  class + color-scheme drive shadcn `dark:` utilities and form controls.
 *  The favicon is regenerated from the new tokens so it recolors too. */
function applyTheme(theme: Theme) {
  const root = document.documentElement;
  root.dataset.theme = theme.id;
  root.classList.toggle("dark", theme.appearance === "dark");
  root.style.colorScheme = theme.appearance;
  updateFavicon();
}

/** Resolve the initial theme: stored choice → OS preference → default. */
function resolveInitialTheme(): Theme {
  const stored = getTheme(localStorage.getItem(THEME_STORAGE_KEY));
  if (stored) return stored;

  const prefersLight = window.matchMedia(
    "(prefers-color-scheme: light)",
  ).matches;
  const byPreference = THEMES.find(
    (t) => t.appearance === (prefersLight ? "light" : "dark"),
  );
  return byPreference ?? getTheme(DEFAULT_THEME_ID)!;
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(() => {
    const initial = resolveInitialTheme();
    applyTheme(initial);
    return initial;
  });

  const setTheme = useCallback((id: string) => {
    const next = getTheme(id);
    if (!next) return;
    applyTheme(next);
    localStorage.setItem(THEME_STORAGE_KEY, next.id);
    setThemeState(next);
  }, []);

  // Follow OS changes only while the user hasn't pinned a theme.
  useEffect(() => {
    if (localStorage.getItem(THEME_STORAGE_KEY)) return;
    const mql = window.matchMedia("(prefers-color-scheme: light)");
    const onChange = () => setThemeState(resolveInitialTheme());
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, []);

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  const value = useMemo(
    () => ({ theme, themes: THEMES, setTheme }),
    [theme, setTheme],
  );

  return (
    <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
  );
}
