import { useEffect, useMemo, useState, type ReactNode, type MouseEvent } from "react";
import {
  Link as RouterLink,
  matchPath,
  useLocation,
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
import { api, API_BASE_URL } from "@/api/client";
import type { PropertyResponse } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { ColorSchemeToggle } from "@/components/ColorSchemeToggle";
import { Footer } from "@/components/Footer";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { LibraryBackdrop } from "@/components/LibraryBackdrop";

function formatAddress(p: PropertyResponse | null | undefined): string | null {
  if (!p) return null;
  const street = [p.street, p.number].filter(Boolean).join(" ");
  const zip = [p.postal_code, p.city].filter(Boolean).join(" ");
  const combined = [street, zip].filter(Boolean).join(" · ");
  return combined || null;
}

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
  const location = useLocation();
  const theme = useTheme();
  const isWide = useMediaQuery(theme.breakpoints.up("sm"));

  const [properties, setProperties] = useState<PropertyResponse[] | null>(null);
  const [menuAnchor, setMenuAnchor] = useState<HTMLElement | null>(null);

  // Pull the user's properties once so we can:
  //  - show the address of the active property in the header
  //  - know whether to call out "Objekte" plurality in nav
  // Verwalter still sees /me/properties (returns all org properties) so the
  // shape is the same. Failure is silent — the header just degrades to the
  // app name.
  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    api
      .get<PropertyResponse[]>("/me/properties")
      .then((r) => {
        if (!cancelled) setProperties(r.data);
      })
      .catch(() => {
        if (!cancelled) setProperties([]);
      });
    return () => {
      cancelled = true;
    };
  }, [user]);

  // The "active" property is whichever one the URL points at; otherwise the
  // first/only one if the user is single-property. Multi-property users
  // without a route-level pick get no header address.
  const activeProperty = useMemo<PropertyResponse | null>(() => {
    if (!properties || properties.length === 0) return null;
    const match = matchPath("/properties/:id/*", location.pathname);
    if (match?.params.id) {
      return properties.find((p) => p.id === match.params.id) ?? null;
    }
    if (properties.length === 1) return properties[0] ?? null;
    return null;
  }, [properties, location.pathname]);

  const onLogout = async () => {
    setMenuAnchor(null);
    await logout();
    navigate("/login", { replace: true });
  };

  const openMenu = (e: MouseEvent<HTMLElement>) => setMenuAnchor(e.currentTarget);
  const closeMenu = () => setMenuAnchor(null);

  const addressLine = formatAddress(activeProperty);

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
              to="/"
              sx={{
                display: "flex",
                alignItems: "center",
                gap: 1.5,
                textDecoration: "none",
                color: "inherit",
              }}
              aria-label={`${t("common.appName")} — ${t("common.portal")}`}
            >
              <Box
                component="img"
                src="/wagner-logo.png"
                alt={t("common.appName")}
                sx={{ height: 40, width: "auto" }}
              />
              {addressLine && (
                <Stack spacing={0} sx={{ lineHeight: 1.2 }}>
                  {activeProperty?.name && isWide && (
                    <Typography variant="body2" sx={{ fontWeight: 600 }}>
                      {activeProperty.name}
                    </Typography>
                  )}
                  <Typography variant="caption" color="text.secondary">
                    {addressLine}
                  </Typography>
                </Stack>
              )}
            </Box>

            <Box sx={{ flex: 1 }} />

            {user && (
              <>
                {isWide && (
                  <Stack direction="row" spacing={0.5} sx={{ mr: 1 }}>
                    <Button
                      component={RouterLink}
                      to="/"
                      color="inherit"
                      size="small"
                    >
                      {t("nav.properties")}
                    </Button>
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
