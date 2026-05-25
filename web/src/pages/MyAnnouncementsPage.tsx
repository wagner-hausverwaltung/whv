/**
 * Portal list of Mitteilungen for a single property.
 *
 * Audience filter is applied server-side: only published rows whose
 * audience flags include the caller's role come back. So if you see
 * an empty page it's either "no Mitteilungen" or "none addressed to
 * your role" — copy doesn't try to distinguish, because the user
 * can't act on the difference.
 */

import { useCallback, useEffect, useState } from "react";
import { Link as RouterLink, useParams } from "react-router-dom";
import {
  Alert,
  Box,
  Breadcrumbs,
  Chip,
  Link as MuiLink,
  Paper,
  Stack,
  Typography,
} from "@mui/material";
import AttachmentIcon from "@mui/icons-material/AttachFile";
import ChatBubbleOutlineIcon from "@mui/icons-material/ChatBubbleOutline";
import { useTranslation } from "react-i18next";
import { api } from "@/api/client";
import type { AnnouncementResponse } from "@/api/types";

export function MyAnnouncementsPage() {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();
  const [rows, setRows] = useState<AnnouncementResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!id) return;
    setError(null);
    try {
      const r = await api.get<AnnouncementResponse[]>(
        `/me/properties/${id}/announcements`,
      );
      setRows(r.data);
    } catch {
      setError(t("portal.announcementsPage.loadFailed"));
    }
  }, [id, t]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  return (
    <Stack spacing={3}>
      <Breadcrumbs>
        <MuiLink component={RouterLink} to="/" color="text.secondary">
          {t("portal.announcementsPage.crumbHome")}
        </MuiLink>
        <MuiLink
          component={RouterLink}
          to={`/properties/${id ?? ""}`}
          color="text.secondary"
        >
          {t("portal.announcementsPage.crumbProperty")}
        </MuiLink>
        <Typography color="text.primary">
          {t("portal.announcementsPage.title")}
        </Typography>
      </Breadcrumbs>

      <Typography variant="h4" component="h1">
        {t("portal.announcementsPage.title")}
      </Typography>

      {error && <Alert severity="error">{error}</Alert>}

      {rows === null ? (
        <Typography variant="body2" color="text.secondary">
          {t("common.loading")}
        </Typography>
      ) : rows.length === 0 ? (
        <Paper variant="outlined" sx={{ p: 3, textAlign: "center" }}>
          <Typography variant="body2" color="text.secondary">
            {t("portal.announcementsPage.empty")}
          </Typography>
        </Paper>
      ) : (
        <Stack spacing={1.5}>
          {rows.map((r) => (
            <Paper
              key={r.id}
              variant="outlined"
              component={RouterLink}
              to={`/announcements/${r.id}`}
              sx={{
                p: 2,
                display: "block",
                textDecoration: "none",
                color: "inherit",
                "&:hover": { borderColor: "primary.main" },
              }}
            >
              <Stack
                direction="row"
                spacing={2}
                sx={{
                  justifyContent: "space-between",
                  alignItems: "flex-start",
                }}
              >
                <Box sx={{ minWidth: 0, flex: 1 }}>
                  <Typography variant="h6" component="div" gutterBottom>
                    {r.title}
                    {r.is_edited && (
                      <Typography
                        component="span"
                        variant="caption"
                        color="text.secondary"
                        sx={{ ml: 1 }}
                      >
                        · {t("portal.announcementsPage.edited")}
                      </Typography>
                    )}
                  </Typography>
                  {r.body && (
                    <Typography
                      variant="body2"
                      color="text.secondary"
                      sx={{
                        display: "-webkit-box",
                        WebkitLineClamp: 2,
                        WebkitBoxOrient: "vertical",
                        overflow: "hidden",
                        whiteSpace: "pre-wrap",
                      }}
                    >
                      {r.body}
                    </Typography>
                  )}
                </Box>
                <Stack
                  direction="column"
                  spacing={0.5}
                  sx={{ alignItems: "flex-end" }}
                >
                  <Typography variant="caption" color="text.secondary">
                    {new Date(
                      r.notification_sent_at ?? r.scheduled_publish_at,
                    ).toLocaleDateString("de-DE")}
                  </Typography>
                  <Stack direction="row" spacing={0.5}>
                    {r.attachment_count > 0 && (
                      <Chip
                        icon={<AttachmentIcon />}
                        size="small"
                        variant="outlined"
                        label={r.attachment_count}
                      />
                    )}
                    {r.comment_count > 0 && (
                      <Chip
                        icon={<ChatBubbleOutlineIcon />}
                        size="small"
                        variant="outlined"
                        label={r.comment_count}
                      />
                    )}
                  </Stack>
                </Stack>
              </Stack>
            </Paper>
          ))}
        </Stack>
      )}
    </Stack>
  );
}
