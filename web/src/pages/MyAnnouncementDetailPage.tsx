/**
 * Portal detail view for one Mitteilung.
 *
 * Read-only for owners except the comment thread at the bottom —
 * authenticated users on the property whose role matches the
 * announcement audience can post a comment. Hidden comments are
 * filtered out server-side; the user has no signal that anything
 * was moderated.
 */

import { useCallback, useEffect, useState } from "react";
import { Link as RouterLink, useParams } from "react-router-dom";
import {
  Alert,
  Box,
  Breadcrumbs,
  Button,
  CircularProgress,
  Divider,
  IconButton,
  Link as MuiLink,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import AttachFileIcon from "@mui/icons-material/AttachFile";
import DownloadIcon from "@mui/icons-material/Download";
import EditIcon from "@mui/icons-material/Edit";
import { useTranslation } from "react-i18next";
import { API_BASE_URL, api } from "@/api/client";
import type {
  AnnouncementCommentResponse,
  AnnouncementDetailResponse,
} from "@/api/types";
import { useAuth } from "@/auth/AuthContext";

function downloadUrl(announcementId: string, attachmentId: string): string {
  return `${API_BASE_URL}/me/announcements/${announcementId}/attachments/${attachmentId}/download`;
}

export function MyAnnouncementDetailPage() {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();
  const { user } = useAuth();
  const [data, setData] = useState<AnnouncementDetailResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [commentBody, setCommentBody] = useState("");
  const [posting, setPosting] = useState(false);
  const [postError, setPostError] = useState<string | null>(null);
  // editingCommentId: which comment row is currently in edit mode.
  // editingBody: the live text in the edit form (separate from
  // commentBody so the compose box and the edit box don't clobber).
  const [editingCommentId, setEditingCommentId] = useState<string | null>(
    null,
  );
  const [editingBody, setEditingBody] = useState("");
  const [savingEdit, setSavingEdit] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!id) return;
    setError(null);
    try {
      const r = await api.get<AnnouncementDetailResponse>(
        `/me/announcements/${id}`,
      );
      setData(r.data);
    } catch {
      setError(t("portal.announcementDetail.loadFailed"));
    }
  }, [id, t]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const beginEdit = (c: AnnouncementCommentResponse) => {
    setEditingCommentId(c.id);
    setEditingBody(c.body);
    setEditError(null);
  };

  const cancelEdit = () => {
    setEditingCommentId(null);
    setEditingBody("");
    setEditError(null);
  };

  const saveEdit = async () => {
    if (!id || !editingCommentId || !editingBody.trim()) return;
    setEditError(null);
    setSavingEdit(true);
    try {
      await api.patch(
        `/me/announcements/${id}/comments/${editingCommentId}`,
        { body: editingBody.trim() },
      );
      setEditingCommentId(null);
      setEditingBody("");
      await load();
    } catch {
      setEditError(t("portal.announcementDetail.editFailed"));
    } finally {
      setSavingEdit(false);
    }
  };

  const submitComment = async () => {
    if (!id || !commentBody.trim()) return;
    setPostError(null);
    setPosting(true);
    try {
      await api.post(`/me/announcements/${id}/comments`, {
        body: commentBody.trim(),
      });
      setCommentBody("");
      await load();
    } catch {
      setPostError(t("portal.announcementDetail.commentFailed"));
    } finally {
      setPosting(false);
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

  return (
    <Stack spacing={3}>
      <Breadcrumbs>
        <MuiLink component={RouterLink} to="/" color="text.secondary">
          {t("portal.announcementsPage.crumbHome")}
        </MuiLink>
        <MuiLink
          component={RouterLink}
          to={`/properties/${data.property_id}/announcements`}
          color="text.secondary"
        >
          {t("portal.announcementsPage.title")}
        </MuiLink>
        <Typography color="text.primary">{data.title}</Typography>
      </Breadcrumbs>

      {/* Title + meta */}
      <Box>
        <Typography variant="h4" component="h1" gutterBottom>
          {data.title}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {data.property_name && `${data.property_name} · `}
          {data.notification_sent_at &&
            new Date(data.notification_sent_at).toLocaleString("de-DE")}
          {data.is_edited && (
            <>
              {" · "}
              <Box component="span" sx={{ fontStyle: "italic" }}>
                {t("portal.announcementDetail.editedAt", {
                  when: new Date(data.updated_at).toLocaleString("de-DE"),
                })}
              </Box>
            </>
          )}
        </Typography>
      </Box>

      {/* Body */}
      {data.body && (
        <Paper variant="outlined" sx={{ p: 2 }}>
          <Typography variant="body1" sx={{ whiteSpace: "pre-wrap" }}>
            {data.body}
          </Typography>
        </Paper>
      )}

      {/* Attachments */}
      {data.attachments.length > 0 && (
        <Box>
          <Typography variant="h6" gutterBottom>
            {t("portal.announcementDetail.attachmentsTitle")}
          </Typography>
          <Stack spacing={1}>
            {data.attachments.map((a) => (
              <Paper
                key={a.id}
                variant="outlined"
                sx={{
                  p: 1.5,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: 2,
                }}
              >
                <Stack
                  direction="row"
                  spacing={1.5}
                  sx={{ alignItems: "center", minWidth: 0 }}
                >
                  <AttachFileIcon fontSize="small" color="action" />
                  <Box sx={{ minWidth: 0 }}>
                    <Typography
                      variant="body2"
                      sx={{
                        fontWeight: 500,
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {a.filename}
                    </Typography>
                    <Typography
                      variant="caption"
                      color="text.secondary"
                    >
                      {Math.round(a.size_bytes / 1024)} KB
                    </Typography>
                  </Box>
                </Stack>
                <IconButton
                  component={MuiLink}
                  href={downloadUrl(data.id, a.id)}
                  target="_blank"
                  rel="noreferrer"
                  size="small"
                  aria-label={t("common.download")}
                >
                  <DownloadIcon fontSize="small" />
                </IconButton>
              </Paper>
            ))}
          </Stack>
        </Box>
      )}

      <Divider />

      {/* Comments */}
      <Box>
        <Typography variant="h6" gutterBottom>
          {t("portal.announcementDetail.commentsTitle", {
            count: data.comments.length,
          })}
        </Typography>

        {data.comments.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            {t("portal.announcementDetail.commentsEmpty")}
          </Typography>
        ) : (
          <Stack spacing={1.5}>
            {data.comments.map((c: AnnouncementCommentResponse) => {
              const isMine = user?.id === c.author_user_id;
              const isEditing = editingCommentId === c.id;
              return (
                <Paper key={c.id} variant="outlined" sx={{ p: 1.5 }}>
                  <Stack
                    direction="row"
                    spacing={1}
                    sx={{
                      justifyContent: "space-between",
                      alignItems: "flex-start",
                    }}
                  >
                    <Typography variant="caption" color="text.secondary">
                      {c.author_email ?? "—"} ·{" "}
                      {new Date(c.created_at).toLocaleString("de-DE")}
                      {c.edited_at && (
                        <Box
                          component="span"
                          sx={{ fontStyle: "italic" }}
                        >
                          {" · "}
                          {t("portal.announcementDetail.commentEdited")}
                        </Box>
                      )}
                    </Typography>
                    {isMine && !isEditing && (
                      <IconButton
                        size="small"
                        onClick={() => beginEdit(c)}
                        aria-label={t(
                          "portal.announcementDetail.editComment",
                        )}
                      >
                        <EditIcon fontSize="small" />
                      </IconButton>
                    )}
                  </Stack>
                  {isEditing ? (
                    <Box sx={{ mt: 1 }}>
                      <TextField
                        value={editingBody}
                        onChange={(e) => setEditingBody(e.target.value)}
                        multiline
                        minRows={2}
                        maxRows={8}
                        fullWidth
                        autoFocus
                      />
                      {editError && (
                        <Alert severity="error" sx={{ mt: 1 }}>
                          {editError}
                        </Alert>
                      )}
                      <Box
                        sx={{
                          mt: 1,
                          display: "flex",
                          justifyContent: "flex-end",
                          gap: 1,
                        }}
                      >
                        <Button onClick={cancelEdit} disabled={savingEdit}>
                          {t("common.cancel")}
                        </Button>
                        <Button
                          variant="contained"
                          onClick={saveEdit}
                          disabled={savingEdit || !editingBody.trim()}
                        >
                          {savingEdit
                            ? t("common.loading")
                            : t("common.save")}
                        </Button>
                      </Box>
                    </Box>
                  ) : (
                    <Typography
                      variant="body2"
                      sx={{ whiteSpace: "pre-wrap", mt: 0.5 }}
                    >
                      {c.body}
                    </Typography>
                  )}
                </Paper>
              );
            })}
          </Stack>
        )}

        <Box sx={{ mt: 2 }}>
          <Typography variant="body2" gutterBottom color="text.secondary">
            {t("portal.announcementDetail.composeLabel")}
          </Typography>
          <TextField
            value={commentBody}
            onChange={(e) => setCommentBody(e.target.value)}
            placeholder={t("portal.announcementDetail.composePlaceholder")}
            multiline
            minRows={2}
            maxRows={8}
            fullWidth
          />
          {postError && (
            <Alert severity="error" sx={{ mt: 1 }}>
              {postError}
            </Alert>
          )}
          <Box sx={{ mt: 1, display: "flex", justifyContent: "flex-end" }}>
            <Button
              variant="contained"
              onClick={submitComment}
              disabled={posting || !commentBody.trim()}
            >
              {posting
                ? t("common.loading")
                : t("portal.announcementDetail.composeSubmit")}
            </Button>
          </Box>
        </Box>
      </Box>
    </Stack>
  );
}
