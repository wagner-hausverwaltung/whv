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
  Autocomplete,
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
  AdminUnitListItem,
  AnnouncementDetailResponse,
  AnnouncementResendSummary,
  AnnouncementSendAttemptResponse,
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
  const [propertyUnits, setPropertyUnits] = useState<AdminUnitListItem[]>([]);
  const [selectedUnits, setSelectedUnits] = useState<AdminUnitListItem[]>([]);

  // Per-recipient send-attempt log (admin-only). Lazy-loaded on
  // demand because most admin sessions never need to inspect it; the
  // detail page itself stays snappy for the common path.
  const [attempts, setAttempts] = useState<
    AnnouncementSendAttemptResponse[] | null
  >(null);
  const [attemptsError, setAttemptsError] = useState<string | null>(null);
  const [resending, setResending] = useState(false);
  const [resendSummary, setResendSummary] =
    useState<AnnouncementResendSummary | null>(null);

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
      // Fetch the org-wide unit list once, then filter to this
      // property. Cheap at v1 scale; revisit if a customer ever
      // breaks 1000 units / property.
      try {
        const u = await api.get<AdminUnitListItem[]>("/admin/units");
        const propUnits = u.data.filter(
          (x) => x.property_id === r.data.property_id,
        );
        setPropertyUnits(propUnits);
        setSelectedUnits(
          propUnits.filter((x) => r.data.unit_ids.includes(x.id)),
        );
      } catch {
        // Leave picker empty if units endpoint fails — user can
        // still edit title/body/audience.
      }
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
        unit_ids: selectedUnits.map((u) => u.id),
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

  const loadAttempts = useCallback(async () => {
    if (!id) return;
    setAttemptsError(null);
    try {
      const r = await api.get<AnnouncementSendAttemptResponse[]>(
        `/admin/announcements/${id}/send-attempts`,
      );
      setAttempts(r.data);
    } catch {
      setAttemptsError(t("admin.announcementDetail.attemptsLoadFailed"));
    }
  }, [id, t]);

  // Auto-load attempts on first render — the table is small and admin
  // wants to see status immediately if they navigated here to debug
  // a failed send.
  useEffect(() => {
    if (data && data.notification_sent_at) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      void loadAttempts();
    }
  }, [data, loadAttempts]);

  const failedAttemptsByEmail = (() => {
    // Resolve "latest attempt per recipient", then filter to FAILED.
    if (!attempts) return new Set<string>();
    const latest = new Map<string, AnnouncementSendAttemptResponse>();
    // attempts come back newest-first; first sighting per email wins.
    for (const a of attempts) {
      if (!latest.has(a.recipient_email)) {
        latest.set(a.recipient_email, a);
      }
    }
    const failed = new Set<string>();
    for (const [email, a] of latest) {
      if (a.status === "FAILED") failed.add(email);
    }
    return failed;
  })();

  const resendFailed = async () => {
    if (!id) return;
    setResending(true);
    setResendSummary(null);
    try {
      const r = await api.post<AnnouncementResendSummary>(
        `/admin/announcements/${id}/resend-failed`,
      );
      setResendSummary(r.data);
      await loadAttempts();
    } catch {
      setAttemptsError(t("admin.announcementDetail.resendFailed"));
    } finally {
      setResending(false);
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
          <Autocomplete
            multiple
            options={propertyUnits}
            value={selectedUnits}
            onChange={(_, next) => setSelectedUnits(next)}
            getOptionLabel={(o) =>
              o.unit_hr_id ?? `${o.type} · ${o.floor ?? "—"}`
            }
            isOptionEqualToValue={(a, b) => a.id === b.id}
            renderInput={(params) => (
              <TextField
                {...params}
                label={t("admin.announcementsTab.unitsLabel")}
                placeholder={t("admin.announcementsTab.unitsPlaceholder")}
                helperText={t("admin.announcementsTab.unitsHelper")}
              />
            )}
          />
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

      {/* Send-attempt log (visible only post-publish) */}
      {isPublished && (
        <Paper variant="outlined" sx={{ p: 2 }}>
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
                {t("admin.announcementDetail.attemptsTitle")}
              </Typography>
              {failedAttemptsByEmail.size > 0 && (
                <Button
                  size="small"
                  variant="outlined"
                  color="warning"
                  onClick={resendFailed}
                  disabled={resending}
                >
                  {resending
                    ? t("common.loading")
                    : t("admin.announcementDetail.resendFailedButton", {
                        count: failedAttemptsByEmail.size,
                      })}
                </Button>
              )}
            </Box>
            {attemptsError && <Alert severity="error">{attemptsError}</Alert>}
            {resendSummary && (
              <Alert
                severity={
                  resendSummary.failed > 0 ? "warning" : "success"
                }
              >
                {t("admin.announcementDetail.resendSummary", {
                  attempted: resendSummary.attempted,
                  succeeded: resendSummary.succeeded,
                  failed: resendSummary.failed,
                })}
                {resendSummary.error_message_examples.length > 0 && (
                  <Box
                    component="ul"
                    sx={{ pl: 2, mt: 1, mb: 0, fontSize: "0.85rem" }}
                  >
                    {resendSummary.error_message_examples.map(
                      (e, i) => (
                        <Box component="li" key={i}>
                          {e}
                        </Box>
                      ),
                    )}
                  </Box>
                )}
              </Alert>
            )}
            {attempts === null ? (
              <Typography variant="body2" color="text.secondary">
                {t("common.loading")}
              </Typography>
            ) : attempts.length === 0 ? (
              <Typography variant="body2" color="text.secondary">
                {t("admin.announcementDetail.attemptsEmpty")}
              </Typography>
            ) : (
              <Stack spacing={0.5}>
                {attempts.map((a) => (
                  <Box
                    key={a.id}
                    sx={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "baseline",
                      gap: 1,
                      px: 1,
                      py: 0.5,
                      borderLeft: 3,
                      borderColor:
                        a.status === "SUCCESS"
                          ? "success.light"
                          : "error.light",
                      bgcolor:
                        a.status === "SUCCESS"
                          ? "transparent"
                          : "error.50",
                    }}
                  >
                    <Box sx={{ minWidth: 0, flex: 1 }}>
                      <Typography
                        variant="body2"
                        sx={{
                          fontFamily: "ui-monospace, Menlo, monospace",
                          fontSize: "0.85rem",
                        }}
                      >
                        {a.recipient_email}
                      </Typography>
                      {a.error_message && (
                        <Typography
                          variant="caption"
                          color="error.main"
                          sx={{ display: "block" }}
                        >
                          {a.error_message}
                        </Typography>
                      )}
                    </Box>
                    <Stack
                      direction="row"
                      spacing={1}
                      sx={{ alignItems: "center" }}
                    >
                      <Chip
                        size="small"
                        label={a.status}
                        color={a.status === "SUCCESS" ? "success" : "error"}
                        variant="outlined"
                      />
                      <Typography
                        variant="caption"
                        color="text.secondary"
                        sx={{ whiteSpace: "nowrap" }}
                      >
                        {new Date(a.attempted_at).toLocaleString("de-DE")}
                      </Typography>
                    </Stack>
                  </Box>
                ))}
              </Stack>
            )}
          </Stack>
        </Paper>
      )}

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
