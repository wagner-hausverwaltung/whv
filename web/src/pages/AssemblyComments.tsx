/**
 * Q&A thread under an assembly. Eigentümer ↔ Verwalter.
 *
 * Distinct from `EtvDiscussionEntry` (the in-meeting Wortmeldungen
 * captured in the protocol) — those are part of the formal record;
 * these are post-publication conversation. Section header reads
 * "Fragen & Antworten" with a footnote making the distinction
 * explicit so a reader doesn't confuse comments with amendments.
 */

import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  IconButton,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import DeleteIcon from "@mui/icons-material/DeleteOutlined";
import EditIcon from "@mui/icons-material/EditOutlined";
import { api } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import type { AssemblyCommentResponse } from "@/api/types";

interface AssemblyCommentsProps {
  assemblyId: string;
}

function formatTs(iso: string): string {
  return new Date(iso).toLocaleString("de-DE", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function authorBadgeColor(role: string): "primary" | "success" | "default" {
  if (role === "verwalter") return "primary";
  if (role === "beirat") return "success";
  return "default";
}

function authorBadgeLabel(role: string): string {
  // Use German role labels mirroring the UserRole enum on the backend.
  switch (role) {
    case "verwalter":
      return "Verwalter";
    case "beirat":
      return "Beirat";
    case "eigentuemer":
      return "Eigentümer";
    case "mieter":
      return "Mieter";
    case "dienstleister":
      return "Dienstleister";
    default:
      return role;
  }
}

export function AssemblyComments({ assemblyId }: AssemblyCommentsProps) {
  const { user } = useAuth();
  const [comments, setComments] = useState<AssemblyCommentResponse[] | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingBody, setEditingBody] = useState("");

  const isVerwalter = user?.role === "verwalter";

  const load = useCallback(async () => {
    setError(null);
    try {
      const r = await api.get<AssemblyCommentResponse[]>(
        `/me/assemblies/${assemblyId}/comments`,
      );
      setComments(r.data);
    } catch {
      setError("Kommentare konnten nicht geladen werden.");
    }
  }, [assemblyId]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const submit = async () => {
    const body = draft.trim();
    if (!body) return;
    setSubmitting(true);
    setError(null);
    try {
      await api.post(`/me/assemblies/${assemblyId}/comments`, { body });
      setDraft("");
      await load();
    } catch {
      setError("Kommentar konnte nicht gespeichert werden.");
    } finally {
      setSubmitting(false);
    }
  };

  const startEdit = (c: AssemblyCommentResponse) => {
    setEditingId(c.id);
    setEditingBody(c.body);
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditingBody("");
  };

  const saveEdit = async (id: string) => {
    const body = editingBody.trim();
    if (!body) return;
    setError(null);
    try {
      await api.patch(`/me/assembly-comments/${id}`, { body });
      cancelEdit();
      await load();
    } catch {
      setError("Bearbeitung fehlgeschlagen.");
    }
  };

  const remove = async (id: string) => {
    if (!confirm("Kommentar wirklich löschen?")) return;
    setError(null);
    try {
      await api.delete(`/me/assembly-comments/${id}`);
      await load();
    } catch {
      setError("Löschen fehlgeschlagen.");
    }
  };

  if (comments === null) {
    return (
      <Box>
        <Typography variant="h5" component="h2" sx={{ mb: 2 }}>
          Fragen &amp; Antworten
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Wird geladen…
        </Typography>
      </Box>
    );
  }

  return (
    <Box>
      <Typography variant="h5" component="h2" sx={{ mb: 0.5 }}>
        Fragen &amp; Antworten
      </Typography>
      <Typography
        variant="caption"
        color="text.secondary"
        sx={{ display: "block", mb: 2 }}
      >
        Kommentare dienen Rückfragen — formale Anfechtungen erfolgen außerhalb
        des Portals.
      </Typography>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      <Stack spacing={2}>
        {comments.length === 0 && (
          <Typography variant="body2" color="text.secondary">
            Noch keine Fragen. Stellen Sie die erste — die Verwaltung wird
            antworten.
          </Typography>
        )}
        {comments.map((c) => {
          const canEdit = user?.id === c.author_user_id;
          const canDelete = canEdit || isVerwalter;
          const isEditing = editingId === c.id;
          return (
            <Box
              key={c.id}
              sx={{
                p: 2,
                borderRadius: 1,
                bgcolor: "background.paper",
                border: 1,
                borderColor: "divider",
              }}
            >
              <Stack
                direction="row"
                spacing={1}
                sx={{
                  alignItems: "center",
                  mb: 1,
                  flexWrap: "wrap",
                  rowGap: 0.5,
                }}
              >
                <Chip
                  size="small"
                  label={authorBadgeLabel(c.author_role)}
                  color={authorBadgeColor(c.author_role)}
                  variant={c.author_role === "verwalter" ? "filled" : "outlined"}
                />
                <Typography variant="body2" sx={{ fontWeight: 500 }}>
                  {c.author_label}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  · {formatTs(c.created_at)}
                </Typography>
                {c.edited_at && (
                  <Typography variant="caption" color="text.secondary">
                    · bearbeitet
                  </Typography>
                )}
                <Box sx={{ flex: 1 }} />
                {canEdit && !isEditing && (
                  <IconButton size="small" onClick={() => startEdit(c)} aria-label="Bearbeiten">
                    <EditIcon fontSize="small" />
                  </IconButton>
                )}
                {canDelete && !isEditing && (
                  <IconButton size="small" onClick={() => remove(c.id)} aria-label="Löschen">
                    <DeleteIcon fontSize="small" />
                  </IconButton>
                )}
              </Stack>

              {isEditing ? (
                <Stack spacing={1}>
                  <TextField
                    multiline
                    fullWidth
                    minRows={3}
                    value={editingBody}
                    onChange={(e) => setEditingBody(e.target.value)}
                  />
                  <Stack direction="row" spacing={1}>
                    <Button
                      variant="contained"
                      size="small"
                      onClick={() => saveEdit(c.id)}
                    >
                      Speichern
                    </Button>
                    <Button size="small" onClick={cancelEdit}>
                      Abbrechen
                    </Button>
                  </Stack>
                </Stack>
              ) : (
                <Typography variant="body2" sx={{ whiteSpace: "pre-wrap" }}>
                  {c.body}
                </Typography>
              )}
            </Box>
          );
        })}

        <Box
          sx={{
            p: 2,
            borderRadius: 1,
            bgcolor: "background.default",
            border: "1px dashed",
            borderColor: "divider",
          }}
        >
          <Typography variant="caption" color="text.secondary" sx={{ mb: 1, display: "block" }}>
            {isVerwalter ? "Antwort" : "Frage"}
          </Typography>
          <Stack spacing={1}>
            <TextField
              multiline
              fullWidth
              minRows={2}
              placeholder={
                isVerwalter
                  ? "Antwort an die Eigentümer…"
                  : "Frage an die Verwaltung…"
              }
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
            />
            <Stack direction="row">
              <Button
                variant="contained"
                size="small"
                onClick={submit}
                disabled={submitting || draft.trim().length === 0}
              >
                {submitting ? "Wird gesendet…" : "Absenden"}
              </Button>
            </Stack>
          </Stack>
        </Box>
      </Stack>
    </Box>
  );
}
