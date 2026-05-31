import { useState, type MouseEvent, type ReactNode } from "react";
import { Link as RouterLink, useLocation, useNavigate } from "react-router-dom";
import {
  AppBar,
  Avatar,
  Box,
  Button,
  Chip,
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
import OpenInNewIcon from "@mui/icons-material/OpenInNew";
import { useTranslation } from "react-i18next";
import { API_BASE_URL } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { AssistantWidget } from "@/components/AssistantWidget";
import { ColorSchemeToggle } from "@/components/ColorSchemeToggle";
import { Footer } from "@/components/Footer";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { LibraryBackdrop } from "@/components/LibraryBackdrop";

function initialsOf(email: string): string {
  const local = email.split("@")[0] ?? email;
  const parts = local
    .split(/[._\s-]+/)
    .filter(Boolean)
    .slice(0, 2);
  if (parts.length === 0) return "?";
  return parts.map((p) => p[0]?.toUpperCase() ?? "").join("") || "?";
}

// Admin shell — mirrors the portal Layout 1:1 so the two surfaces feel like
// the same product. The only differences are the "Admin" pill next to the
// logo, admin-specific nav targets, and a "Portal" shortcut in the avatar
// menu instead of "Settings" (the portal is where the Verwalter goes to act
// as a regular user when needed).
export function AdminLayout({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
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

  // Active nav entry by longest-prefix path match. /admin/tickets/{id} keeps
  // the Tickets button visually selected via the `current-page` data attr —
  // MUI doesn't have a built-in active state on Button, so we just bump
  // fontWeight + add a subtle background.
  const NAV: { to: string; label: string }[] = [
    { to: "/admin", label: t("admin.dashboard") },
    { to: "/admin/tickets", label: t("admin.tickets") },
    { to: "/admin/resolutions", label: t("admin.resolutions") },
    { to: "/admin/assemblies", label: t("admin.assemblies") },
    { to: "/admin/signatures", label: t("admin.signatures") },
    { to: "/admin/announcements", label: t("admin.announcements") },
    { to: "/admin/invites", label: t("admin.invites") },
    { to: "/admin/assistant-log", label: t("admin.assistantLog") },
  ];
  const activePath = (() => {
    const sorted = [...NAV].sort((a, b) => b.to.length - a.to.length);
    for (const item of sorted) {
      if (
        location.pathname === item.to ||
        location.pathname.startsWith(item.to + "/")
      ) {
        return item.to;
      }
    }
    return NAV[0]!.to;
  })();

  return (
    <Box sx={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <LibraryBackdrop />

      <AppBar
        position="static"
        color="default"
        elevation={0}
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
            <Box
              component={RouterLink}
              to="/admin"
              sx={{
                display: "flex",
                alignItems: "center",
                gap: 1.5,
                textDecoration: "none",
                color: "inherit",
              }}
              aria-label={`${t("common.appName")} — ${t("admin.title")}`}
            >
              <Box
                component="img"
                src="/wagner-logo.png"
                alt={t("common.appName")}
                sx={{ height: 40, width: "auto" }}
              />
              <Chip
                label={t("admin.title")}
                size="small"
                color="primary"
                variant="outlined"
                sx={{
                  fontFamily: "'Montserrat', system-ui, sans-serif",
                  letterSpacing: "0.05em",
                  textTransform: "uppercase",
                  height: 22,
                  fontSize: "0.7rem",
                  fontWeight: 600,
                }}
              />
            </Box>

            <Box sx={{ flex: 1 }} />

            {user && (
              <>
                {isWide && (
                  <Stack direction="row" spacing={0.5} sx={{ mr: 1 }}>
                    {NAV.map((item) => (
                      <Button
                        key={item.to}
                        component={RouterLink}
                        to={item.to}
                        color="inherit"
                        size="small"
                        sx={{
                          fontWeight: activePath === item.to ? 700 : 500,
                          bgcolor:
                            activePath === item.to
                              ? "action.selected"
                              : "transparent",
                        }}
                      >
                        {item.label}
                      </Button>
                    ))}
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
                    paper: { sx: { minWidth: 240 } },
                  }}
                >
                  <MenuItem disabled sx={{ opacity: "1 !important" }}>
                    <Stack spacing={0} sx={{ overflow: "hidden" }}>
                      <Typography
                        variant="body2"
                        sx={{ fontWeight: 600 }}
                        noWrap
                      >
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
                    to="/"
                    onClick={closeMenu}
                  >
                    <ListItemIcon>
                      <OpenInNewIcon fontSize="small" />
                    </ListItemIcon>
                    <ListItemText>{t("common.portal")}</ListItemText>
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

      {/* Floating RAG assistant — reachable from every admin page. */}
      <AssistantWidget />
    </Box>
  );
}
