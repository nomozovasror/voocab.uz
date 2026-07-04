import { createContext } from "react";
import type { Theme } from "./themes";

export interface ThemeContextValue {
  /** The currently active theme. */
  theme: Theme;
  /** All themes available in the registry. */
  themes: Theme[];
  /** Switch to a theme by id; persists the choice and re-paints the UI. */
  setTheme: (id: string) => void;
}

/* Kept in its own module so the provider file only exports components
   (keeps React Fast Refresh happy). */
export const ThemeContext = createContext<ThemeContextValue | undefined>(
  undefined,
);
