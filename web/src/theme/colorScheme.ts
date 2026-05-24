import { createContext, useContext } from "react";
import type { PaletteMode } from "@mui/material/styles";

export type ColorScheme = "light" | "dark" | "system";

export interface ColorSchemeCtx {
  scheme: ColorScheme;
  setScheme: (s: ColorScheme) => void;
  resolved: PaletteMode;
}

export const ColorSchemeContext = createContext<ColorSchemeCtx | null>(null);

export const STORAGE_KEY = "whv:color-scheme";

export function readScheme(): ColorScheme {
  if (typeof window === "undefined") return "system";
  const v = window.localStorage.getItem(STORAGE_KEY);
  return v === "light" || v === "dark" ? v : "system";
}

export function systemMode(): PaletteMode {
  if (typeof window === "undefined") return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

export function useColorScheme(): ColorSchemeCtx {
  const ctx = useContext(ColorSchemeContext);
  if (!ctx) {
    throw new Error("useColorScheme must be used inside WhvThemeProvider");
  }
  return ctx;
}
