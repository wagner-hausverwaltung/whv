import { useState, type ReactNode, type MouseEvent } from "react";
import {
  Link as RouterLink,
  useNavigate,
} from "react-router-dom";
import {
  AppBar,
  Avatar,
  Box,
  Button,
  Container,
  Divider,
  IconButton,
  ListItemIcon,
  ListItemText,
  Menu,
  MenuItem,
  Stack,
  Toolbar,
  Typography,
  useMediaQuery,
  useTheme,
} from "@mui/material";
import LogoutIcon from "@mui/icons-material/Logout";
import SettingsIcon from "@mui/icons-material/Settings";
import { useTranslation } from "react-i18next";
import { API_BASE_URL } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { ColorSchemeToggle } from "@/components/ColorSchemeToggle";
import { Footer } from "@/components/Footer";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { LibraryBackdrop } from "@/components/LibraryBackdrop";
import { PropertySwitcher } from "@/components/PropertySwitcher";

function initialsOf(email: string): string {
  // Fallback: take the bit before "@", split on common separators, take the
  // first letter of up to two parts. "luis.wagner@x" → "LW",
  // "info@whv" → "I". Used only until the user uploads an avatar image.
  const local = email.split("@")[0] ?? email;
  const parts = local.split(/[._\s-]+/).filter(Boolean).slice(0, 2);
  if (parts.length === 0) return "?";
  return parts.map((p) => p[0]?.toUpperCase() ?? "").join("") || "?";
}

export function Layout({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const theme = useTheme();
  const isWide = useMediaQuery(theme.breakpoints.up("sm"));

  const [menuAnchor, setMenuAnchor] = useState<HTMLElement | null>(null);

  const onLogout = async () => {
    setMenuAnchor(null);
    await logout();
    navigate("/login", { replace: true });
  };

  const openMenu = (e: MouseEvent<HTMLElement>) => setMenuAnchor(e.currentTarget);
  const closeMenu = () => setMenuAnchor(null);

  return (
    <Box sx={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <LibraryBackdrop />

      <AppBar
        position="static"
        color="default"
        elevation={0}
        // Hidden in print so the rendered document / announcement /
        // ticket is the only thing on the printed page (§9.3).
        className="no-print"
        sx={{
          bgcolor: (theme) =>
            theme.palette.mode === "dark"
              ? "rgba(24, 26, 32, 0.85)"
              : "rgba(255, 255, 255, 0.85)",
          backdropFilter: "blur(8px)",
          borderBottom: 1,
          borderColor: "divider",
        }}
      >
        <Container maxWidth="lg">
          <Toolbar disableGutters sx={{ minHeight: 64, gap: 1 }}>
            {/* Logo links home — the workspace + switcher provide the
                property identity directly to the right. */}
            <Box
              component={RouterLink}
              to="/"
              sx={{
                display: "flex",
                alignItems: "center",
                textDecoration: "none",
                color: "inherit",
                flexShrink: 0,
              }}
              aria-label={`${t("common.appName")} — ${t("common.portal")}`}
            >
              <Box
                component="img"
                src="/wagner-logo.png"
                alt={t("common.appName")}
                sx={{ height: 40, width: "auto" }}
              />
            </Box>

            {/* Active property + dropdown to switch. Only renders for
                signed-in users who have at least one property; on
                pre-auth pages there's no /me/properties to fetch so
                we just don't mount it. */}
            {user && <PropertySwitcher />}

            <Box sx={{ flex: 1 }} />

            {user && (
              <>
                {isWide && (
                  <Stack direction="row" spacing={0.5} sx={{ mr: 1 }}>
                    <Button
                      component={RouterLink}
                      to="/tickets"
                      color="inherit"
                      size="small"
                    >
                      {t("nav.tickets")}
                    </Button>
                    <Button
                      component={RouterLink}
                      to="/resolutions"
                      color="inherit"
                      size="small"
                    >
                      {t("nav.resolutions")}
                    </Button>
                  </Stack>
                )}
                <LanguageSwitcher />
                <ColorSchemeToggle />
                <IconButton
                  onClick={openMenu}
                  size="small"
                  aria-label={user.email}
                  sx={{ ml: 0.5 }}
                >
                  <Avatar
                    src={
                      user.avatar_url
                        ? `${API_BASE_URL}${user.avatar_url}`
                        : undefined
                    }
                    sx={{
                      width: 32,
                      height: 32,
                      bgcolor: "primary.main",
                      color: "primary.contrastText",
                      fontSize: "0.85rem",
                    }}
                  >
                    {initialsOf(user.email)}
                  </Avatar>
                </IconButton>
                <Menu
                  anchorEl={menuAnchor}
                  open={Boolean(menuAnchor)}
                  onClose={closeMenu}
                  slotProps={{
                    paper: { sx: { minWidth: 220 } },
                  }}
                >
                  <MenuItem disabled sx={{ opacity: "1 !important" }}>
                    <Stack spacing={0} sx={{ overflow: "hidden" }}>
                      <Typography variant="body2" sx={{ fontWeight: 600 }} noWrap>
                        {user.email}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {user.role}
                      </Typography>
                    </Stack>
                  </MenuItem>
                  <Divider />
                  <MenuItem
                    component={RouterLink}
                    to="/settings"
                    onClick={closeMenu}
                  >
                    <ListItemIcon>
                      <SettingsIcon fontSize="small" />
                    </ListItemIcon>
                    <ListItemText>{t("common.settings")}</ListItemText>
                  </MenuItem>
                  <MenuItem onClick={onLogout}>
                    <ListItemIcon>
                      <LogoutIcon fontSize="small" />
                    </ListItemIcon>
                    <ListItemText>{t("common.logout")}</ListItemText>
                  </MenuItem>
                </Menu>
              </>
            )}
          </Toolbar>
        </Container>
      </AppBar>

      <Container component="main" maxWidth="lg" sx={{ flex: 1, py: 5 }}>
        {children}
      </Container>

      <Footer />
    </Box>
  );
}
