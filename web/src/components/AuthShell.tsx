import type { ReactNode } from "react";
import {
  AppBar,
  Box,
  Card,
  CardContent,
  Stack,
  Toolbar,
  Typography,
} from "@mui/material";
import { ColorSchemeToggle } from "@/components/ColorSchemeToggle";
import { Footer } from "@/components/Footer";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { LibraryBackdrop } from "@/components/LibraryBackdrop";

// Shared chrome for pre-auth pages (login, invite redeem, forgot/reset).
// Library background (Stadtbibliothek Stuttgart) with a near-opaque overlay
// keeps the form card readable while signalling the brand. The minimal top
// bar carries the language switcher + dark-mode toggle so visitors can pick
// before they sign in.
export function AuthShell({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
}) {
  return (
    <Box
      sx={{
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
        bgcolor: "transparent",
      }}
    >
      <LibraryBackdrop />

      <AppBar
        position="static"
        color="transparent"
        elevation={0}
        sx={{ bgcolor: "transparent" }}
      >
        <Toolbar sx={{ minHeight: 56 }}>
          <Box sx={{ flex: 1 }} />
          <LanguageSwitcher />
          <ColorSchemeToggle />
        </Toolbar>
      </AppBar>

      <Box
        component="main"
        sx={{
          flex: 1,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          px: 2,
          py: 6,
        }}
      >
        <Stack spacing={3} sx={{ width: "100%", maxWidth: 380 }}>
          <Box sx={{ display: "flex", justifyContent: "center" }}>
            <Box
              component="img"
              src="/wagner-logo.png"
              alt="Wagner Hausverwaltung GmbH"
              sx={{ height: 80, width: "auto" }}
            />
          </Box>
          <Card variant="outlined">
            <CardContent>
              <Stack spacing={2.5}>
                <Stack spacing={0.75}>
                  <Typography variant="h5" component="h1">
                    {title}
                  </Typography>
                  {subtitle && (
                    <Typography variant="body2" color="text.secondary">
                      {subtitle}
                    </Typography>
                  )}
                </Stack>
                {children}
              </Stack>
            </CardContent>
          </Card>
        </Stack>
      </Box>

      <Footer />
    </Box>
  );
}
