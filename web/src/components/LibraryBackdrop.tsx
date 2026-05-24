import { Box, useTheme } from "@mui/material";

// Fixed-position background: Stadtbibliothek Stuttgart photo, toned down
// behind a near-opaque overlay so foreground content stays readable. Used
// on both pre-auth screens (AuthShell) and authenticated screens (Layout).
// The overlay alpha differs by color scheme — dark mode keeps the image
// darker so light-text content has enough contrast.
export function LibraryBackdrop() {
  const theme = useTheme();
  const overlayColor =
    theme.palette.mode === "dark"
      ? "rgba(15, 17, 21, 0.86)"
      : "rgba(255, 255, 255, 0.78)";
  return (
    <>
      <Box
        aria-hidden
        sx={{
          position: "fixed",
          inset: 0,
          zIndex: -2,
          backgroundImage: "url('/library.webp')",
          backgroundSize: "cover",
          backgroundPosition: "center",
        }}
      />
      <Box
        aria-hidden
        sx={{
          position: "fixed",
          inset: 0,
          zIndex: -1,
          backgroundColor: overlayColor,
          backdropFilter: "blur(2px)",
        }}
      />
    </>
  );
}
