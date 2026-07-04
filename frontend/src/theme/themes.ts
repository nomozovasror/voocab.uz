/**
 * Theme registry. Each entry maps to a `[data-theme="<id>"]` block in
 * src/styles/globals.css. To add a theme: add the CSS block there and an entry
 * here — nothing else needs to change.
 *
 * `preview` holds a few key colors purely for rendering swatches in the theme
 * picker; the live UI is always driven by the CSS tokens, never these values.
 */
export type ThemeAppearance = "dark" | "light";

export interface Theme {
  id: string;
  label: string;
  appearance: ThemeAppearance;
  preview: {
    background: string;
    primary: string;
    foreground: string;
  };
}

export const THEMES: Theme[] = [
  {
    id: "serika-dark",
    label: "Serika Dark",
    appearance: "dark",
    preview: { background: "#323437", primary: "#e2b714", foreground: "#d1d0c5" },
  },
  {
    id: "serika-light",
    label: "Serika Light",
    appearance: "light",
    preview: { background: "#e1e1e3", primary: "#e2b714", foreground: "#2c2e31" },
  },
  {
    id: "dracula",
    label: "Dracula",
    appearance: "dark",
    preview: { background: "#282a36", primary: "#bd93f9", foreground: "#f8f8f2" },
  },
];

export const DEFAULT_THEME_ID = "serika-dark";

export const THEME_STORAGE_KEY = "voocab-theme";

export function getTheme(id: string | null | undefined): Theme | undefined {
  return THEMES.find((t) => t.id === id);
}
