/**
 * Tab container for a single property's workspace.
 *
 * Mounted under /properties/:id. Renders a row of tabs (Details /
 * Mitteilungen / Versammlungen / Dokumente) above the active child
 * route, which is provided by React Router's <Outlet />. The AppBar
 * already shows which property is active, so we don't repeat that
 * here — the tabs are pure navigation.
 *
 * Each tab corresponds to a URL segment so deep links keep working:
 *   /properties/:id/details        → "Details"
 *   /properties/:id/announcements  → "Mitteilungen"
 *   /properties/:id/assemblies     → "Versammlungen"
 *   /properties/:id/documents      → "Dokumente"
 *
 * The detail pages (/announcements/:id, /assemblies/:id) live outside
 * this workspace and have their own breadcrumbs.
 */

import { useMemo } from "react";
import {
  Outlet,
  useLocation,
  useNavigate,
  useParams,
} from "react-router-dom";
import { Box, Stack, Tab, Tabs } from "@mui/material";

const TAB_DEFS = [
  { value: "details", label: "Details" },
  { value: "announcements", label: "Mitteilungen" },
  { value: "assemblies", label: "Versammlungen" },
  { value: "documents", label: "Dokumente" },
  // "Dienstleister" — aggregates the property's RECHNUNG documents
  // by vendor contact so owners see who's done work on the
  // property + can call them back. Read-only; data comes for free
  // from the existing Impower invoice mirror.
  { value: "vendors", label: "Dienstleister" },
] as const;

type TabValue = (typeof TAB_DEFS)[number]["value"];

export function PropertyWorkspace() {
  const { id } = useParams<{ id: string }>();
  const location = useLocation();
  const navigate = useNavigate();

  // Pull the active tab off the URL segment, not from local state.
  // URL is the single source of truth so deep links + browser
  // back/forward + the AppBar switcher (which navigates) all stay
  // consistent. Anything unrecognised falls back to "details" so
  // /properties/:id (no segment) lands on the default tab.
  const activeTab: TabValue = useMemo(() => {
    const segments = location.pathname.split("/");
    const last = segments[segments.length - 1] ?? "";
    if (TAB_DEFS.some((t) => t.value === last)) {
      return last as TabValue;
    }
    return "details";
  }, [location.pathname]);

  const onTabChange = (_: unknown, v: TabValue) => {
    if (!id) return;
    navigate(`/properties/${id}/${v}`);
  };

  return (
    <Stack spacing={3}>
      <Box
        sx={{
          borderBottom: 1,
          borderColor: "divider",
          // Negate the Container's left/right padding so the bottom
          // border spans the full viewport width — feels more like a
          // proper workspace divider, less like a floating widget.
          mx: { xs: -2, sm: -3 },
          px: { xs: 2, sm: 3 },
        }}
      >
        <Tabs
          value={activeTab}
          onChange={onTabChange}
          variant="scrollable"
          scrollButtons="auto"
          allowScrollButtonsMobile
        >
          {TAB_DEFS.map((t) => (
            <Tab key={t.value} value={t.value} label={t.label} />
          ))}
        </Tabs>
      </Box>

      <Outlet />
    </Stack>
  );
}
