import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { CssBaseline, ThemeProvider as MUIThemeProvider } from "@mui/material";
import { createTheme, type PaletteMode } from "@mui/material/styles";
import {
  ColorSchemeContext,
  STORAGE_KEY,
  readScheme,
  systemMode,
  type ColorScheme,
} from "./colorScheme";

// WHV palette — mirrors the marketing site (wagner-hausverwaltung.com) in
// light mode. Dark mode keeps the same brand blue but inverts surfaces;
// chosen against #1863DC, the blue stays vibrant enough at 4.5:1 contrast
// on a near-black background.
function buildTheme(mode: PaletteMode) {
  const isDark = mode === "dark";
  return createTheme({
    palette: {
      mode,
      primary: {
        main: "#1863DC",
        dark: "#0C66B4",
        light: isDark ? "#4D8AEC" : "#3E7DE2",
        contrastText: "#FFFFFF",
      },
      secondary: { main: isDark ? "#A3A3B1" : "#4E4B66" },
      background: {
        default: isDark ? "#0F1115" : "#FBFBFB",
        paper: isDark ? "#181A20" : "#FFFFFF",
      },
      text: {
        primary: isDark ? "#ECEDEE" : "#212121",
        secondary: isDark ? "#A1A4AB" : "#4E4B66",
      },
      divider: isDark ? "#2A2D34" : "#EBEBEB",
      success: { main: "#16A34A" },
      warning: { main: "#D97706" },
      error: { main: "#DC2626" },
      info: { main: "#1863DC" },
    },
    typography: {
      fontFamily: "'Noto Sans', system-ui, sans-serif",
      h1: { fontFamily: "'Montserrat', system-ui, sans-serif", fontWeight: 700 },
      h2: { fontFamily: "'Montserrat', system-ui, sans-serif", fontWeight: 700 },
      h3: { fontFamily: "'Montserrat', system-ui, sans-serif", fontWeight: 700 },
      h4: { fontFamily: "'Montserrat', system-ui, sans-serif", fontWeight: 700 },
      h5: { fontFamily: "'Montserrat', system-ui, sans-serif", fontWeight: 600 },
      h6: { fontFamily: "'Montserrat', system-ui, sans-serif", fontWeight: 600 },
      button: {
        fontFamily: "'Montserrat', system-ui, sans-serif",
        fontWeight: 500,
        textTransform: "none",
        letterSpacing: "0.02em",
      },
    },
    shape: { borderRadius: 6 },
    components: {
      MuiButton: {
        styleOverrides: { root: { paddingInline: 20, paddingBlock: 10 } },
        defaultProps: { disableElevation: true },
      },
      MuiPaper: { defaultProps: { elevation: 0 } },
      MuiCard: { defaultProps: { elevation: 0 } },
    },
  });
}

export function WhvThemeProvider({ children }: { children: ReactNode }) {
  const [scheme, setSchemeState] = useState<ColorScheme>(() => readScheme());
  // `osMode` tracks the OS preference — only consulted when scheme === "system".
  const [osMode, setOsMode] = useState<PaletteMode>(() => systemMode());

  // Subscribe to OS preference changes once. We update `osMode` regardless of
  // current scheme so switching back to "system" later picks up the latest
  // value without a re-subscribe.
  useEffect(() => {
    const mql = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = (e: MediaQueryListEvent) =>
      setOsMode(e.matches ? "dark" : "light");
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, []);

  const resolved: PaletteMode = scheme === "system" ? osMode : scheme;

  const setScheme = useCallback((s: ColorScheme) => {
    setSchemeState(s);
    if (s === "system") {
      window.localStorage.removeItem(STORAGE_KEY);
    } else {
      window.localStorage.setItem(STORAGE_KEY, s);
    }
  }, []);

  const theme = useMemo(() => buildTheme(resolved), [resolved]);

  // Tag the <html> element so non-MUI elements (loading screen, future CSS)
  // can react to dark mode via [data-color-scheme="dark"] selectors.
  useEffect(() => {
    document.documentElement.dataset.colorScheme = resolved;
  }, [resolved]);

  const value = useMemo(
    () => ({ scheme, setScheme, resolved }),
    [scheme, setScheme, resolved],
  );

  return (
    <ColorSchemeContext.Provider value={value}>
      <MUIThemeProvider theme={theme}>
        <CssBaseline />
        {children}
      </MUIThemeProvider>
    </ColorSchemeContext.Provider>
  );
}
