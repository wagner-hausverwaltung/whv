/**
 * Cross-property admin queue for Mitteilungen.
 *
 * Lives at /admin/announcements (no property_id). Shows every
 * Mitteilung the Verwalter has authored across the whole org, with a
 * `property` column so they can tell which property each one
 * belongs to. Useful for "did I already send this month's
 * Wartungsmeldung anywhere" without drilling into each property tab.
 *
 * Per-property compose still lives on the property-detail tab — this
 * page is read-only on creation (rows link to the existing detail
 * page for edits + publish-now + delete + moderation).
 */

import { useCallback, useEffect, useState } from "react";
import { Link as RouterLink, useSearchParams } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Chip,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import { useTranslation } from "react-i18next";
import { api } from "@/api/client";
import type { AnnouncementResponse } from "@/api/types";
import { AnnouncementComposeDialog } from "@/components/AnnouncementComposeDialog";

type StatusFilter = "all" | "scheduled" | "published";

const FILTERS: StatusFilter[] = ["all", "scheduled", "published"];

function StatusBadge({ row }: { row: AnnouncementResponse }) {
  const { t } = useTranslation();
  const [mountedAt] = useState(() => Date.now());
  if (row.notification_sent_at) {
    return (
      <Chip
        size="small"
        color="success"
        variant="filled"
        label={t("admin.announcementsTab.statusPublished")}
      />
    );
  }
  const due = new Date(row.scheduled_publish_at).getTime();
  const minutes = Math.max(0, Math.round((due - mountedAt) / 60000));
  const label =
    minutes <= 0
      ? t("admin.announcementsTab.statusImminent")
      : t("admin.announcementsTab.statusInMinutes", { count: minutes });
  return <Chip size="small" color="warning" variant="outlined" label={label} />;
}

export function AdminAnnouncementsAllPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const statusFilter = (params.get("status") ?? "all") as StatusFilter;
  const [rows, setRows] = useState<AnnouncementResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [composeOpen, setComposeOpen] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      const url =
        statusFilter === "all"
          ? "/admin/announcements"
          : `/admin/announcements?status=${statusFilter}`;
      const r = await api.get<AnnouncementResponse[]>(url);
      setRows(r.data);
    } catch {
      setError(t("admin.announcementsAll.loadFailed"));
    }
  }, [statusFilter, t]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const setFilter = (next: StatusFilter) => {
    if (next === "all") {
      setParams({});
    } else {
      setParams({ status: next });
    }
  };

  return (
    <Stack spacing={3}>
      <Box
        sx={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          gap: 2,
          flexWrap: "wrap",
        }}
      >
        <Box>
          <Typography variant="h4" component="h1">
            {t("admin.announcementsAll.title")}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {t("admin.announcementsAll.subtitle")}
          </Typography>
        </Box>
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          onClick={() => setComposeOpen(true)}
        >
          {t("admin.announcementsTab.newButton")}
        </Button>
      </Box>

      <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", gap: 1 }}>
        {FILTERS.map((f) => (
          <Chip
            key={f}
            label={t(`admin.announcementsAll.filter.${f}`)}
            color={statusFilter === f ? "primary" : "default"}
            variant={statusFilter === f ? "filled" : "outlined"}
            onClick={() => setFilter(f)}
            clickable
          />
        ))}
      </Stack>

      {error && <Alert severity="error">{error}</Alert>}

      {rows === null ? (
        <Typography variant="body2" color="text.secondary">
          {t("common.loading")}
        </Typography>
      ) : rows.length === 0 ? (
        <Paper variant="outlined" sx={{ p: 3, textAlign: "center" }}>
          <Typography variant="body2" color="text.secondary">
            {t("admin.announcementsAll.empty")}
          </Typography>
        </Paper>
      ) : (
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>{t("admin.announcementsTab.colStatus")}</TableCell>
                <TableCell>{t("admin.announcementsAll.colProperty")}</TableCell>
                <TableCell>{t("admin.announcementsTab.colTitle")}</TableCell>
                <TableCell>{t("admin.announcementsTab.colAudience")}</TableCell>
                <TableCell>{t("admin.announcementsTab.colAttachments")}</TableCell>
                <TableCell>{t("admin.announcementsTab.colComments")}</TableCell>
                <TableCell>{t("admin.announcementsTab.colDate")}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((r) => (
                <TableRow
                  key={r.id}
                  hover
                  component={RouterLink}
                  to={`/admin/announcements/${r.id}`}
                  sx={{
                    textDecoration: "none",
                    cursor: "pointer",
                    "& td": { color: "text.primary" },
                  }}
                >
                  <TableCell>
                    <StatusBadge row={r} />
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2">
                      {r.property_name ?? (
                        <Box
                          component="span"
                          sx={{ color: "text.secondary" }}
                        >
                          {r.property_id.slice(0, 8)}
                        </Box>
                      )}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2" sx={{ fontWeight: 500 }}>
                      {r.title}
                    </Typography>
                    {r.is_edited && (
                      <Typography
                        variant="caption"
                        color="text.secondary"
                        sx={{ display: "block" }}
                      >
                        {t("admin.announcementsTab.edited")}
                      </Typography>
                    )}
                  </TableCell>
                  <TableCell>
                    <Stack
                      direction="row"
                      spacing={0.5}
                      sx={{ flexWrap: "wrap", gap: 0.5 }}
                    >
                      {r.audience_eigentuemer && (
                        <Chip size="small" variant="outlined" label="Eig." />
                      )}
                      {r.audience_mieter && (
                        <Chip size="small" variant="outlined" label="Mieter" />
                      )}
                      {r.audience_beirat && (
                        <Chip size="small" variant="outlined" label="Beirat" />
                      )}
                      {r.unit_ids.length > 0 && (
                        <Chip
                          size="small"
                          color="info"
                          variant="filled"
                          label={t("admin.announcementsTab.unitsChip", {
                            count: r.unit_ids.length,
                          })}
                        />
                      )}
                    </Stack>
                  </TableCell>
                  <TableCell>{r.attachment_count}</TableCell>
                  <TableCell>{r.comment_count}</TableCell>
                  <TableCell>
                    <Typography variant="caption" color="text.secondary">
                      {new Date(
                        r.notification_sent_at ?? r.scheduled_publish_at,
                      ).toLocaleDateString("de-DE")}
                    </Typography>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      <AnnouncementComposeDialog
        propertyId={null}
        open={composeOpen}
        onClose={() => setComposeOpen(false)}
        onCreated={() => void load()}
      />
    </Stack>
  );
}
