import { useEffect, useState } from "react";
import {
  Alert,
  Box,
  Card,
  CardActionArea,
  CardContent,
  Stack,
  Typography,
} from "@mui/material";
import { Link as RouterLink } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { api } from "@/api/client";

interface DashboardStats {
  pending_invites: number;
  consumed_invites: number;
  properties: number;
  units: number;
  contracts: number;
  contacts: number;
  open_tickets: number;
  open_resolutions: number;
}

type StatKey = keyof DashboardStats;

// Every stat card drills into a list. The admin SPA reuses the legacy Jinja
// pages for master data (Objekte / Einheiten / Verträge / Kontakte) until
// those screens are ported — the placeholder pages handle the visual jump.
const NAV_TARGETS: Record<StatKey, string> = {
  pending_invites: "/admin/invites",
  consumed_invites: "/admin/invites",
  open_tickets: "/admin/tickets",
  open_resolutions: "/admin/resolutions",
  properties: "/admin/properties",
  units: "/admin/units",
  contracts: "/admin/contracts",
  contacts: "/admin/contacts",
};

export function AdminDashboardPage() {
  const { t } = useTranslation();
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<DashboardStats>("/admin/dashboard-stats")
      .then((r) => setStats(r.data))
      .catch(() => setError(t("admin.loadFailed")));
  }, [t]);

  if (error) return <Alert severity="error">{error}</Alert>;
  if (stats === null) {
    return (
      <Typography variant="body2" color="text.secondary">
        {t("common.loading")}
      </Typography>
    );
  }

  // Display order = workflow priority. Operator wakes up + sees open tickets
  // and active resolutions first; master-data counts are secondary.
  const ORDER: StatKey[] = [
    "open_tickets",
    "open_resolutions",
    "pending_invites",
    "consumed_invites",
    "properties",
    "units",
    "contracts",
    "contacts",
  ];

  return (
    <Stack spacing={4}>
      <Box>
        <Typography variant="h4" component="h1" gutterBottom>
          {t("admin.dashboard")}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {t("admin.subtitle")}
        </Typography>
      </Box>

      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: {
            xs: "1fr 1fr",
            sm: "repeat(3, 1fr)",
            md: "repeat(4, 1fr)",
          },
          gap: 2,
        }}
      >
        {ORDER.map((key) => {
          const value = stats[key];
          const to = NAV_TARGETS[key];
          return (
            <Card key={key} variant="outlined">
              <CardActionArea component={RouterLink} to={to}>
                <CardContent sx={{ textAlign: "center", py: 3 }}>
                  <Typography
                    variant="h3"
                    sx={{ fontWeight: 700, lineHeight: 1, mb: 0.5 }}
                  >
                    {value}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    {t(`admin.stats.${key}`)}
                  </Typography>
                </CardContent>
              </CardActionArea>
            </Card>
          );
        })}
      </Box>

    </Stack>
  );
}
