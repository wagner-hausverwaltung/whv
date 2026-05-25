/**
 * Per-property Mitteilungen list for the admin SPA.
 *
 * Mounts as a tab on /admin/properties/:id alongside Übersicht /
 * Tickets / Dokumente / Firmen. Compose lives in a modal dialog
 * (right column on the list page) — keeps the admin on the list
 * while drafting, since they'll often publish-now or edit during
 * the 10-min buffer and don't need a separate page round-trip.
 *
 * Detail + comment moderation live on /admin/announcements/:id —
 * each row is a clickable link.
 */

import { useCallback, useEffect, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
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

interface Props {
  propertyId: string;
}

interface StatusBadgeProps {
  row: AnnouncementResponse;
}

function StatusBadge({ row }: StatusBadgeProps) {
  const { t } = useTranslation();
  // Anchor "now" to component mount so the countdown is stable across
  // re-renders of the same list row. Stale by the time the user
  // refreshes the list — acceptable for a chip; not worth a live tick.
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

// --- Main tab content ------------------------------------------------------

export function AdminAnnouncementsTab({ propertyId }: Props) {
  const { t } = useTranslation();
  const [rows, setRows] = useState<AnnouncementResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [composeOpen, setComposeOpen] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      const r = await api.get<AnnouncementResponse[]>(
        `/admin/properties/${propertyId}/announcements`,
      );
      setRows(r.data);
    } catch {
      setError(t("admin.announcementsTab.loadFailed"));
    }
  }, [propertyId, t]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  return (
    <Stack spacing={2}>
      <Box
        sx={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: 1,
        }}
      >
        <Typography variant="h6">
          {t("admin.announcementsTab.title")}
        </Typography>
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          onClick={() => setComposeOpen(true)}
        >
          {t("admin.announcementsTab.newButton")}
        </Button>
      </Box>

      {error && <Alert severity="error">{error}</Alert>}

      {rows === null ? (
        <Typography variant="body2" color="text.secondary">
          {t("common.loading")}
        </Typography>
      ) : rows.length === 0 ? (
        <Paper variant="outlined" sx={{ p: 3, textAlign: "center" }}>
          <Typography variant="body2" color="text.secondary">
            {t("admin.announcementsTab.empty")}
          </Typography>
        </Paper>
      ) : (
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>{t("admin.announcementsTab.colStatus")}</TableCell>
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
        propertyId={propertyId}
        open={composeOpen}
        onClose={() => setComposeOpen(false)}
        onCreated={() => void load()}
      />
    </Stack>
  );
}

