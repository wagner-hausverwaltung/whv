import { useEffect, useState } from "react";
import { Box, GlobalStyles } from "@mui/material";
import { useColorScheme } from "@/theme/colorScheme";

const SESSION_KEY = "whv.pxaSplashShown";
const SHOW_MS = 2800;
const FADE_MS = 450;

/**
 * Plus X Award "Top 100 Hausverwaltungen Deutschlands 2024" — a slowly
 * pulsing badge shown once per browser session before the sign-in form
 * (mirrors the iOS onboarding splash). White badge on white in light mode,
 * black badge on black in dark mode; a click skips; `prefers-reduced-motion`
 * disables the pulse.
 */
export function PlusXAwardSplash() {
  const { resolved } = useColorScheme();
  const [phase, setPhase] = useState<"shown" | "fading" | "done">(() =>
    typeof sessionStorage !== "undefined" && sessionStorage.getItem(SESSION_KEY)
      ? "done"
      : "shown",
  );

  useEffect(() => {
    if (phase !== "shown") return;
    sessionStorage.setItem(SESSION_KEY, "1");
    const t = window.setTimeout(() => setPhase("fading"), SHOW_MS);
    return () => window.clearTimeout(t);
  }, [phase]);

  useEffect(() => {
    if (phase !== "fading") return;
    const t = window.setTimeout(() => setPhase("done"), FADE_MS);
    return () => window.clearTimeout(t);
  }, [phase]);

  if (phase === "done") return null;

  return (
    <Box
      onClick={() => setPhase("fading")}
      role="img"
      aria-label="Plus X Award – Top 100 Hausverwaltungen Deutschlands, ausgezeichnet 2024"
      sx={{
        position: "fixed",
        inset: 0,
        zIndex: (theme) => theme.zIndex.modal + 1,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        bgcolor: resolved === "dark" ? "#000" : "#fff",
        cursor: "pointer",
        opacity: phase === "fading" ? 0 : 1,
        transition: `opacity ${FADE_MS}ms ease-out`,
      }}
    >
      <GlobalStyles
        styles={{
          "@keyframes pxaPulse": {
            from: { transform: "scale(1)" },
            to: { transform: "scale(1.05)" },
          },
        }}
      />
      <Box
        component="img"
        src={resolved === "dark" ? "/pxa-award-black.png" : "/pxa-award-white.png"}
        alt=""
        sx={{
          width: "min(190px, 42vw)",
          animation: "pxaPulse 1.4s ease-in-out infinite alternate",
          "@media (prefers-reduced-motion: reduce)": { animation: "none" },
        }}
      />
    </Box>
  );
}
