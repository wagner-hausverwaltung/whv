/**
 * Admin detail view for a single Mitteilung.
 *
 * Edit (title / body / audience) lives in an inline form at the top;
 * attachments are managed in the middle; comments + moderation are
 * at the bottom. Publish-now + delete + "back to property list" are
 * the row actions in the header.
 *
 * Why everything on one page: a Mitteilung lifecycle is short
 * (compose → scheduled → published → comment thread). A tab-bar
 * would be more clicks than the user wants — they came here to
 * tweak one thing and leave.
 */

import { useCallback, useEffect, useState } from "react";
import { Link as RouterLink, useNavigate, useParams } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControlLabel,
  FormGroup,
  IconButton,
  Link as MuiLink,
  Paper,
  Stack,
  Switch,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import AttachFileIcon from "@mui/icons-material/AttachFile";
import DeleteIcon from "@mui/icons-material/Delete";
import DownloadIcon from "@mui/icons-material/Download";
import RocketLaunchIcon from "@mui/icons-material/RocketLaunch";
import VisibilityOffIcon from "@mui/icons-material/VisibilityOff";
import VisibilityIcon from "@mui/icons-material/Visibility";
import { useTranslation } from "react-i18next";
import { API_BASE_URL, api } from "@/api/client";
import type {
  AnnouncementDetailResponse,
  AnnouncementUpdateRequest,
} from "@/api/types";

function downloadUrl(announcementId: string, attachmentId: string): string {
  return `${API_BASE_URL}/admin/announcements/${announcementId}/attachments/${attachmentId}/download`;
}

export function AdminAnnouncementDetailPage() {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [data, setData] = useState<AnnouncementDetailResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [savingEdit, setSavingEdit] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);
  const [publishing, setPublishing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  // Local edit-form state — initialised on load, bumped on every reload.
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [audE, setAudE] = useState(true);
  const [audM, setAudM] = useState(true);
  const [audB, setAudB] = useState(true);

  const load = useCallback(async () => {
    if (!id) return;
    setError(null);
    try {
      const r = await api.get<AnnouncementDetailResponse>(
        `/admin/announcements/${id}`,
      );
      setData(r.data);
      setTitle(r.data.title);
      setBody(r.data.body);
      setAudE(r.data.audience_eigentuemer);
      setAudM(r.data.audience_mieter);
      setAudB(r.data.audience_beirat);
    } catch {
      setError(t("admin.announcementDetail.loadFailed"));
    }
  }, [id, t]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const isPublished = !!data?.notification_sent_at;

  const saveEdit = async () => {
    if (!id) return;
    setEditError(null);
    if (!title.trim()) {
      setEditError(t("admin.announcementsTab.composeTitleRequired"));
      return;
    }
    if (!(audE || audM || audB)) {
      setEditError(t("admin.announcementsTab.composeAudienceRequired"));
      return;
    }
    setSavingEdit(true);
    try {
      const payload: AnnouncementUpdateRequest = {
        title: title.trim(),
        body,
        audience_eigentuemer: audE,
        audience_mieter: audM,
        audience_beirat: audB,
      };
      await api.patch(`/admin/announcements/${id}`, payload);
      await load();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })
        .response?.data?.detail;
      setEditError(detail ?? t("admin.announcementDetail.editFailed"));
    } finally {
      setSavingEdit(false);
    }
  };

  const publishNow = async () => {
    if (!id) return;
    setPublishing(true);
    try {
      await api.post(`/admin/announcements/${id}/publish-now`);
      await load();
    } catch {
      setError(t("admin.announcementDetail.publishFailed"));
    } finally {
      setPublishing(false);
    }
  };

  const doDelete = async () => {
    if (!id) return;
    setDeleting(true);
    try {
      await api.delete(`/admin/announcements/${id}`);
      if (data) {
        navigate(`/admin/properties/${data.property_id}`);
      } else {
        navigate("/admin/properties");
      }
    } catch {
      setError(t("admin.announcementDetail.deleteFailed"));
      setDeleting(false);
      setConfirmDelete(false);
    }
  };

  const onAttachmentPicked = async (
    e: React.ChangeEvent<HTMLInputElement>,
  ) => {
    if (!id || !e.target.files) return;
    const files = Array.from(e.target.files);
    e.target.value = "";
    for (const f of files) {
      const form = new FormData();
      form.append("file", f);
      try {
        await api.post(`/admin/announcements/${id}/attachments`, form);
      } catch (err: unknown) {
        const detail = (err as { response?: { data?: { detail?: string } } })
          .response?.data?.detail;
        setError(
          detail ?? t("admin.announcementsTab.attachmentFailed", { name: f.name }),
        );
      }
    }
    await load();
  };

  const removeAttachment = async (attachmentId: string) => {
    if (!id) return;
    try {
      await api.delete(
        `/admin/announcements/${id}/attachments/${attachmentId}`,
      );
      await load();
    } catch {
      setError(t("admin.announcementDetail.attachmentDeleteFailed"));
    }
  };

  const toggleCommentHidden = async (
    commentId: string,
    nextHidden: boolean,
  ) => {
    try {
      await api.patch(`/admin/announcement-comments/${commentId}`, {
        is_hidden: nextHidden,
      });
      await load();
    } catch {
      setError(t("admin.announcementDetail.moderationFailed"));
    }
  };

  if (!data) {
    return (
      <Box sx={{ display: "flex", justifyContent: "center", p: 4 }}>
        {error ? (
          <Alert severity="error">{error}</Alert>
        ) : (
          <CircularProgress size={32} />
        )}
      </Box>
    );
  }

  const publishAt = new Date(data.scheduled_publish_at);
  const publishedAt = data.notification_sent_at
    ? new Date(data.notification_sent_at)
    : null;

  return (
    <Stack spacing={3}>
      {/* Header row: back link, status, action buttons. */}
      <Box
        sx={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: 2,
        }}
      >
        <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
          <IconButton
            component={RouterLink}
            to={`/admin/properties/${data.property_id}`}
            aria-label={t("admin.announcementDetail.backToProperty")}
            size="small"
          >
            <ArrowBackIcon />
          </IconButton>
          <Typography variant="h5" component="h1">
            {data.title}
          </Typography>
        </Stack>
        <Stack direction="row" spacing={1}>
          {!isPublished && (
            <Tooltip
              title={t("admin.announcementDetail.publishNowTooltip")}
            >
              <span>
                <Button
                  startIcon={<RocketLaunchIcon />}
                  variant="outlined"
                  onClick={publishNow}
                  disabled={publishing}
                >
                  {publishing
                    ? t("common.loading")
                    : t("admin.announcementDetail.publishNow")}
                </Button>
              </span>
            </Tooltip>
          )}
          <Button
            startIcon={<DeleteIcon />}
            color="error"
            variant="text"
            onClick={() => setConfirmDelete(true)}
          >
            {t("admin.announcementDetail.delete")}
          </Button>
        </Stack>
      </Box>

      {error && <Alert severity="error">{error}</Alert>}

      {/* Status line */}
      <Paper variant="outlined" sx={{ p: 2 }}>
        <Stack
          direction="row"
          spacing={3}
          sx={{ flexWrap: "wrap", rowGap: 1 }}
        >
          <Box>
            <Typography variant="caption" color="text.secondary">
              {t("admin.announcementDetail.statusLabel")}
            </Typography>
            <Box>
              {isPublished ? (
                <Chip
                  size="small"
                  color="success"
                  label={t("admin.announcementDetail.statusPublishedAt", {
                    when: publishedAt!.toLocaleString("de-DE"),
                  })}
                />
              ) : (
                <Chip
                  size="small"
                  color="warning"
                  variant="outlined"
                  label={t("admin.announcementDetail.statusScheduledAt", {
                    when: publishAt.toLocaleString("de-DE"),
                  })}
                />
              )}
            </Box>
          </Box>
          <Box>
            <Typography variant="caption" color="text.secondary">
              {t("admin.announcementDetail.propertyLabel")}
            </Typography>
            <Typography variant="body2">
              {data.property_name ?? "—"}
            </Typography>
          </Box>
          <Box>
            <Typography variant="caption" color="text.secondary">
              {t("admin.announcementDetail.creatorLabel")}
            </Typography>
            <Typography variant="body2">
              {data.creator_email ?? "—"}
            </Typography>
          </Box>
          {data.is_edited && (
            <Box>
              <Typography variant="caption" color="text.secondary">
                {t("admin.announcementDetail.lastEditLabel")}
              </Typography>
              <Typography variant="body2">
                {new Date(data.updated_at).toLocaleString("de-DE")}
              </Typography>
            </Box>
          )}
        </Stack>
      </Paper>

      {/* Edit form */}
      <Paper variant="outlined" sx={{ p: 2 }}>
        <Stack spacing={2}>
          <Typography variant="h6">
            {t("admin.announcementDetail.editTitle")}
          </Typography>
          {!isPublished && (
            <Alert severity="info" variant="outlined">
              {t("admin.announcementDetail.editResetsTimerHint")}
            </Alert>
          )}
          <TextField
            label={t("admin.announcementsTab.fieldTitle")}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            fullWidth
          />
          <TextField
            label={t("admin.announcementsTab.fieldBody")}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            multiline
            minRows={4}
            maxRows={20}
            fullWidth
          />
          <Box>
            <Typography variant="body2" color="text.secondary" gutterBottom>
              {t("admin.announcementsTab.audienceLabel")}
            </Typography>
            <FormGroup row>
              <FormControlLabel
                control={
                  <Switch
                    checked={audE}
                    onChange={(e) => setAudE(e.target.checked)}
                  />
                }
                label={t("admin.announcementsTab.audienceEigentuemer")}
              />
              <FormControlLabel
                control={
                  <Switch
                    checked={audM}
                    onChange={(e) => setAudM(e.target.checked)}
                  />
                }
                label={t("admin.announcementsTab.audienceMieter")}
              />
              <FormControlLabel
                control={
                  <Switch
                    checked={audB}
                    onChange={(e) => setAudB(e.target.checked)}
                  />
                }
                label={t("admin.announcementsTab.audienceBeirat")}
              />
            </FormGroup>
          </Box>
          {editError && <Alert severity="error">{editError}</Alert>}
          <Box>
            <Button
              variant="contained"
              onClick={saveEdit}
              disabled={savingEdit}
            >
              {savingEdit
                ? t("common.loading")
                : t("admin.announcementDetail.saveEdit")}
            </Button>
          </Box>
        </Stack>
      </Paper>

      {/* Attachments */}
      <Paper variant="outlined" sx={{ p: 2 }}>
        <Stack spacing={2}>
          <Box
            sx={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <Typography variant="h6">
              {t("admin.announcementDetail.attachmentsTitle")}
            </Typography>
            <Button
              component="label"
              variant="outlined"
              size="small"
              startIcon={<AttachFileIcon />}
            >
              {t("admin.announcementsTab.addAttachments")}
              <input
                type="file"
                multiple
                hidden
                onChange={onAttachmentPicked}
              />
            </Button>
          </Box>
          {data.attachments.length === 0 ? (
            <Typography variant="body2" color="text.secondary">
              {t("admin.announcementDetail.attachmentsEmpty")}
            </Typography>
          ) : (
            <Stack spacing={1}>
              {data.attachments.map((a) => (
                <Box
                  key={a.id}
                  sx={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    border: 1,
                    borderColor: "divider",
                    borderRadius: 1,
                    p: 1,
                  }}
                >
                  <Box>
                    <Typography variant="body2" sx={{ fontWeight: 500 }}>
                      {a.filename}
                    </Typography>
                    <Typography
                      variant="caption"
                      color="text.secondary"
                    >
                      {Math.round(a.size_bytes / 1024)} KB ·{" "}
                      {new Date(a.created_at).toLocaleDateString("de-DE")}
                    </Typography>
                  </Box>
                  <Stack direction="row" spacing={1}>
                    <Tooltip title={t("common.download")}>
                      <IconButton
                        component={MuiLink}
                        href={downloadUrl(data.id, a.id)}
                        target="_blank"
                        rel="noreferrer"
                        size="small"
                      >
                        <DownloadIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                    <Tooltip title={t("common.delete")}>
                      <IconButton
                        size="small"
                        onClick={() => void removeAttachment(a.id)}
                      >
                        <DeleteIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  </Stack>
                </Box>
              ))}
            </Stack>
          )}
        </Stack>
      </Paper>

      {/* Comments / moderation */}
      <Paper variant="outlined" sx={{ p: 2 }}>
        <Stack spacing={2}>
          <Typography variant="h6">
            {t("admin.announcementDetail.commentsTitle", {
              count: data.comments.length,
            })}
          </Typography>
          {data.comments.length === 0 ? (
            <Typography variant="body2" color="text.secondary">
              {t("admin.announcementDetail.commentsEmpty")}
            </Typography>
          ) : (
            <Stack spacing={1.5}>
              {data.comments.map((c) => (
                <Box
                  key={c.id}
                  sx={{
                    border: 1,
                    borderColor: c.is_hidden ? "warning.light" : "divider",
                    bgcolor: c.is_hidden ? "warning.50" : "background.paper",
                    borderRadius: 1,
                    p: 1.5,
                  }}
                >
                  <Stack
                    direction="row"
                    spacing={1}
                    sx={{
                      justifyContent: "space-between",
                      alignItems: "flex-start",
                    }}
                  >
                    <Box sx={{ minWidth: 0, flex: 1 }}>
                      <Typography variant="caption" color="text.secondary">
                        {c.author_email ?? "—"} ·{" "}
                        {new Date(c.created_at).toLocaleString("de-DE")}
                        {c.is_hidden && (
                          <>
                            {" · "}
                            <Box component="span" sx={{ fontStyle: "italic" }}>
                              {t("admin.announcementDetail.commentHidden")}
                              {c.hidden_reason && `: ${c.hidden_reason}`}
                            </Box>
                          </>
                        )}
                      </Typography>
                      <Typography
                        variant="body2"
                        sx={{ whiteSpace: "pre-wrap", mt: 0.5 }}
                      >
                        {c.body}
                      </Typography>
                    </Box>
                    <Tooltip
                      title={
                        c.is_hidden
                          ? t("admin.announcementDetail.unhideComment")
                          : t("admin.announcementDetail.hideComment")
                      }
                    >
                      <IconButton
                        size="small"
                        onClick={() =>
                          void toggleCommentHidden(c.id, !c.is_hidden)
                        }
                      >
                        {c.is_hidden ? (
                          <VisibilityIcon fontSize="small" />
                        ) : (
                          <VisibilityOffIcon fontSize="small" />
                        )}
                      </IconButton>
                    </Tooltip>
                  </Stack>
                </Box>
              ))}
            </Stack>
          )}
        </Stack>
      </Paper>

      {/* Delete confirmation */}
      <Dialog
        open={confirmDelete}
        onClose={() => !deleting && setConfirmDelete(false)}
      >
        <DialogTitle>{t("admin.announcementDetail.deleteConfirmTitle")}</DialogTitle>
        <DialogContent>
          <Typography>
            {t("admin.announcementDetail.deleteConfirmBody")}
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button
            onClick={() => setConfirmDelete(false)}
            disabled={deleting}
          >
            {t("common.cancel")}
          </Button>
          <Button
            onClick={doDelete}
            color="error"
            variant="contained"
            disabled={deleting}
          >
            {deleting ? t("common.loading") : t("common.delete")}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Divider at the bottom of the page */}
      <Divider sx={{ pt: 1 }} />
    </Stack>
  );
}
