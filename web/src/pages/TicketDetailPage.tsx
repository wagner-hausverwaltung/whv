import { useEffect, useState, type FormEvent } from "react";
import { Link as RouterLink, useParams } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Card,
  Chip,
  FormControl,
  IconButton,
  InputLabel,
  Link,
  MenuItem,
  Paper,
  Popover,
  Select,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import AttachFileOutlinedIcon from "@mui/icons-material/AttachFileOutlined";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutlineOutlined";
import InfoOutlinedIcon from "@mui/icons-material/InfoOutlined";
import { useTranslation } from "react-i18next";
import { api } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import {
  TICKET_CATEGORY_LABELS,
  TICKET_SHARE_SCOPE_LABELS,
  TICKET_STATUS_LABELS,
  type TicketDetailResponse,
  type TicketShareScope,
} from "@/api/types";
import { MessageAttachments } from "@/components/MessageAttachments";
import { MessageBody } from "@/components/MessageBody";
import { MessageTimeline } from "@/components/MessageTimeline";
import { TicketAttachmentsRollup } from "@/components/TicketAttachmentsRollup";
import { describeUploadError } from "@/lib/ticketAttachments";

export function TicketDetailPage() {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();
  const { user } = useAuth();
  const [ticket, setTicket] = useState<TicketDetailResponse | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reply, setReply] = useState("");
  const [posting, setPosting] = useState(false);
  const [closing, setClosing] = useState(false);
  // Files staged for the next reply. Uploaded one by one to
  // /me/tickets/{id}/messages/{msg_id}/attachments after the message
  // POST returns (we need its id to attach against).
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  // Per-file failures from the last submit — shown inline under the
  // reply form so the user knows which file the server rejected.
  const [uploadErrors, setUploadErrors] = useState<
    { name: string; detail?: string }[]
  >([]);

  const [newParticipantEmail, setNewParticipantEmail] = useState("");
  const [participantError, setParticipantError] = useState<string | null>(null);
  const [addingParticipant, setAddingParticipant] = useState(false);
  // The add form sits inside a Popover behind a "+" icon — keeps the
  // section clean by default. Mirrors the admin treatment.
  const [addAnchor, setAddAnchor] = useState<HTMLElement | null>(null);
  const closeAddPopover = () => {
    setAddAnchor(null);
    setParticipantError(null);
  };

  const refresh = async () => {
    if (!id) return;
    try {
      const r = await api.get<TicketDetailResponse>(`/me/tickets/${id}`);
      setTicket(r.data);
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } }).response
        ?.status;
      if (status === 404) setNotFound(true);
      else setError("Ticket konnte nicht geladen werden.");
    }
  };

  useEffect(() => {
    // eslint-disable-next-line react-hooks/exhaustive-deps, react-hooks/set-state-in-effect
    void refresh();
  }, [id]);

  if (notFound) {
    return (
      <Stack spacing={2}>
        <Alert severity="error">Ticket nicht gefunden oder nicht zugänglich.</Alert>
        <Link component={RouterLink} to="/tickets" color="text.secondary">
          ← Zurück zu meinen Tickets
        </Link>
      </Stack>
    );
  }
  if (error && !ticket) return <Alert severity="error">{error}</Alert>;
  if (!ticket) {
    return (
      <Typography variant="body2" color="text.secondary">
        Wird geladen…
      </Typography>
    );
  }

  const isClosed = ticket.status === "GESCHLOSSEN";
  const isCreator = user?.id === ticket.created_by_user_id;
  const canManage = isCreator;
  const canClose = !isClosed && isCreator;
  const isPropertyEligible = ticket.property_id !== null;

  const onReply = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setUploadErrors([]);
    setPosting(true);
    try {
      // Defer the notification email when files are queued — backend
      // sends it via the explicit /notify endpoint after uploads land,
      // and only then can it include the binary in Resend's
      // `attachments` field.
      const hasAttachments = pendingFiles.length > 0;
      const res = await api.post<{ id: string }>(
        `/me/tickets/${ticket.id}/messages`,
        {
          body: reply.trim(),
          is_internal_note: false,
          defer_notification: hasAttachments,
        },
      );
      const newMessageId = res.data.id;
      // Best-effort attachment upload — failures don't abort the rest.
      // We capture the server's `detail` field so the inline Alert can
      // tell the user *why* a specific file rejected (unsupported type,
      // size cap exceeded, etc.).
      const failures: { name: string; detail?: string }[] = [];
      for (const file of pendingFiles) {
        try {
          const form = new FormData();
          form.append("file", file);
          await api.post(
            `/me/tickets/${ticket.id}/messages/${newMessageId}/attachments`,
            form,
          );
        } catch (err: unknown) {
          // Diagnostic-rich message covering 401/404/413/415/5xx/network.
          failures.push({ name: file.name, detail: describeUploadError(err) });
        }
      }
      // Trigger deferred email send so the recipient gets the files.
      if (hasAttachments) {
        try {
          await api.post(
            `/me/tickets/${ticket.id}/messages/${newMessageId}/notify`,
          );
        } catch {
          // Best-effort — the in-portal thread already succeeded.
        }
      }
      setReply("");
      if (failures.length > 0) {
        setUploadErrors(failures);
        // Keep failed files in the picker so the user can adjust
        // (compress / change type) and retry without re-picking.
        const failedNames = new Set(failures.map((f) => f.name));
        setPendingFiles((prev) => prev.filter((f) => failedNames.has(f.name)));
      } else {
        setPendingFiles([]);
      }
      await refresh();
    } catch {
      setError("Antwort konnte nicht gesendet werden.");
    } finally {
      setPosting(false);
    }
  };

  const onClose = async () => {
    if (!window.confirm("Ticket wirklich schließen?")) return;
    setClosing(true);
    try {
      await api.post(`/me/tickets/${ticket.id}/close`);
      await refresh();
    } catch {
      setError("Ticket konnte nicht geschlossen werden.");
    } finally {
      setClosing(false);
    }
  };

  const onChangeScope = async (next: TicketShareScope) => {
    if (next === ticket.share_scope) return;
    setError(null);
    try {
      await api.patch(`/me/tickets/${ticket.id}/share-scope`, {
        share_scope: next,
      });
      await refresh();
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } }).response?.data
          ?.detail ?? "Sichtbarkeit konnte nicht geändert werden.";
      setError(detail);
    }
  };

  const onAddParticipant = async (e: FormEvent) => {
    e.preventDefault();
    setParticipantError(null);
    setAddingParticipant(true);
    try {
      await api.post(`/me/tickets/${ticket.id}/participants`, {
        email: newParticipantEmail.trim().toLowerCase(),
      });
      setNewParticipantEmail("");
      setAddAnchor(null);
      await refresh();
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } }).response?.data
          ?.detail ?? "Teilnehmer konnte nicht hinzugefügt werden.";
      setParticipantError(detail);
    } finally {
      setAddingParticipant(false);
    }
  };

  const onRemoveParticipant = async (userId: string) => {
    if (!window.confirm("Teilnehmer entfernen?")) return;
    try {
      await api.delete(`/me/tickets/${ticket.id}/participants/${userId}`);
      await refresh();
    } catch {
      setError("Teilnehmer konnte nicht entfernt werden.");
    }
  };

  return (
    <Stack spacing={3}>
      <Box>
        <Link component={RouterLink} to="/tickets" color="text.secondary" underline="hover">
          ← Meine Tickets
        </Link>
      </Box>

      <Box>
        <Typography variant="h4" component="h1" gutterBottom>
          {ticket.subject}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {TICKET_CATEGORY_LABELS[ticket.category]} ·{" "}
          {TICKET_STATUS_LABELS[ticket.status]} · erstellt{" "}
          {new Date(ticket.created_at).toLocaleString("de-DE")}
          {ticket.closed_at && (
            <>
              {" "}
              · geschlossen{" "}
              {new Date(ticket.closed_at).toLocaleString("de-DE")}
            </>
          )}
        </Typography>
      </Box>

      {error && <Alert severity="error">{error}</Alert>}

      {/* Body splits into a main column (visibility, thread, reply) and
          a sticky timeline on md+ screens. On small screens the timeline
          is hidden — the thread cards are already linear and short there.

          Note: NO `alignItems: "start"` — grid's default `stretch`
          makes the right column track the main column's height, which
          is what gives the sticky rail enough scroll range to stay
          pinned through the whole thread. */}
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: { xs: "1fr", md: "minmax(0, 1fr) 280px" },
          gap: 3,
        }}
      >
        <Stack spacing={3} sx={{ minWidth: 0 }}>
          <Paper variant="outlined" sx={{ p: 2.5 }}>
        {/* Header: section label + scope dropdown (with info-icon
            tooltip when the user can manage) + a "+" icon that opens
            the add-participant Popover. Mirrors the admin treatment. */}
        <Stack
          direction="row"
          sx={{
            justifyContent: "space-between",
            alignItems: "center",
            gap: 2,
            flexWrap: "wrap",
            mb: 2,
          }}
        >
          <Typography
            variant="overline"
            color="text.secondary"
            sx={{ letterSpacing: "0.08em" }}
          >
            Sichtbarkeit & Teilnehmer
          </Typography>
          <Stack direction="row" spacing={0.5} sx={{ alignItems: "center" }}>
            {canManage ? (
              <>
                <FormControl size="small" sx={{ minWidth: 240 }}>
                  <InputLabel>Sichtbarkeit</InputLabel>
                  <Select<TicketShareScope>
                    value={ticket.share_scope}
                    label="Sichtbarkeit"
                    onChange={(e) =>
                      onChangeScope(e.target.value as TicketShareScope)
                    }
                  >
                    <MenuItem value="PRIVATE">
                      {TICKET_SHARE_SCOPE_LABELS.PRIVATE}
                    </MenuItem>
                    <MenuItem value="PARTICIPANTS">
                      {TICKET_SHARE_SCOPE_LABELS.PARTICIPANTS}
                    </MenuItem>
                    <MenuItem value="PROPERTY" disabled={!isPropertyEligible}>
                      {TICKET_SHARE_SCOPE_LABELS.PROPERTY}
                      {!isPropertyEligible ? " (kein Objekt verknüpft)" : ""}
                    </MenuItem>
                  </Select>
                </FormControl>
                <Tooltip
                  title="PRIVATE: nur Sie + Verwalter · PARTICIPANTS: + namentlich hinzugefügte · PROPERTY: + alle Eigentümer/Mieter mit Vertrag auf diesem Objekt"
                  placement="top"
                  arrow
                >
                  <IconButton
                    size="small"
                    tabIndex={-1}
                    sx={{ color: "text.secondary" }}
                    aria-label="Sichtbarkeit erklärt"
                  >
                    <InfoOutlinedIcon fontSize="small" />
                  </IconButton>
                </Tooltip>
                <Tooltip title="Teilnehmer hinzufügen">
                  <IconButton
                    size="small"
                    color="primary"
                    onClick={(e) => setAddAnchor(e.currentTarget)}
                    aria-label="Teilnehmer hinzufügen"
                  >
                    <AddIcon fontSize="small" />
                  </IconButton>
                </Tooltip>
              </>
            ) : (
              <Typography variant="body2" color="text.secondary">
                {TICKET_SHARE_SCOPE_LABELS[ticket.share_scope]}
              </Typography>
            )}
          </Stack>
        </Stack>

        {ticket.participants.length > 0 ? (
          <Stack spacing={1}>
            {ticket.participants.map((p) => (
              <Stack
                key={p.user_id}
                direction="row"
                sx={{ alignItems: "center", gap: 1 }}
              >
                <Typography variant="body2" sx={{ flex: 1 }}>
                  {p.email}
                  <Typography
                    component="span"
                    variant="caption"
                    color="text.secondary"
                    sx={{ ml: 1 }}
                  >
                    seit {new Date(p.added_at).toLocaleDateString("de-DE")}
                  </Typography>
                </Typography>
                {canManage && (
                  <Tooltip title="Entfernen">
                    <IconButton
                      size="small"
                      onClick={() => onRemoveParticipant(p.user_id)}
                      aria-label="Entfernen"
                    >
                      <DeleteOutlineIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                )}
              </Stack>
            ))}
          </Stack>
        ) : (
          <Typography variant="body2" color="text.secondary">
            Keine namentlichen Teilnehmer.
          </Typography>
        )}

        {canManage && (
          <Popover
            open={Boolean(addAnchor)}
            anchorEl={addAnchor}
            onClose={closeAddPopover}
            anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
            transformOrigin={{ vertical: "top", horizontal: "right" }}
            slotProps={{
              paper: { sx: { p: 2, width: 360, maxWidth: "90vw" } },
            }}
          >
            <Box component="form" onSubmit={onAddParticipant}>
              <Stack spacing={1.5}>
                <Typography variant="subtitle2">
                  Teilnehmer hinzufügen
                </Typography>
                {participantError && (
                  <Alert severity="error">{participantError}</Alert>
                )}
                <TextField
                  type="email"
                  size="small"
                  required
                  placeholder="E-Mail-Adresse eines WHV-Kontos"
                  value={newParticipantEmail}
                  onChange={(e) => setNewParticipantEmail(e.target.value)}
                  disabled={addingParticipant}
                  fullWidth
                  autoFocus
                />
                <Typography variant="caption" color="text.secondary">
                  Die Person braucht ein WHV-Portal-Konto. Hinzugefügte
                  Teilnehmer erhalten E-Mail-Updates bei jeder neuen
                  Nachricht und können selbst antworten.
                </Typography>
                <Stack
                  direction="row"
                  spacing={1}
                  sx={{ justifyContent: "flex-end" }}
                >
                  <Button size="small" onClick={closeAddPopover}>
                    Abbrechen
                  </Button>
                  <Button
                    type="submit"
                    variant="contained"
                    size="small"
                    disabled={addingParticipant || !newParticipantEmail}
                  >
                    {addingParticipant ? "Wird hinzugefügt…" : "Hinzufügen"}
                  </Button>
                </Stack>
              </Stack>
            </Box>
          </Popover>
        )}
      </Paper>

      <Stack spacing={1.5}>
        {ticket.messages.map((m) => {
          const isMine = m.author_user_id === user?.id;
          const author = isMine
            ? "Sie"
            : m.author_user_id === ticket.created_by_user_id
              ? "Ersteller"
              : (ticket.participants.find(
                  (p) => p.user_id === m.author_user_id,
                )?.email ?? m.author_email ?? "Wagner Hausverwaltung");
          return (
            <Card
              key={m.id}
              id={`msg-${m.id}`}
              variant="outlined"
              sx={{
                p: 2,
                borderColor: isMine ? "primary.main" : "divider",
                // Sticky header offset so the timeline-jump lands the
                // card below the AppBar instead of behind it.
                scrollMarginTop: 88,
              }}
            >
              <Stack
                direction="row"
                sx={{ justifyContent: "space-between", mb: 1, gap: 1 }}
              >
                <Typography variant="body2" sx={{ fontWeight: 500 }}>
                  {author}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {new Date(m.created_at).toLocaleString("de-DE")}
                </Typography>
              </Stack>
              <MessageBody body={m.body} />
              {id && (
                <MessageAttachments
                  ticketId={id}
                  attachments={m.attachments ?? []}
                  scope="portal"
                />
              )}
            </Card>
          );
        })}
      </Stack>

          {isClosed ? (
            <Typography variant="body2" color="text.secondary">
              Dieses Ticket ist geschlossen. Für eine neue Frage erstellen Sie
              bitte ein neues Ticket.
            </Typography>
          ) : (
            <Paper
              variant="outlined"
              component="form"
              onSubmit={onReply}
              sx={{ p: 2.5 }}
            >
              <Stack spacing={1.5}>
                <TextField
                  id="reply"
                  label="Antworten"
                  required
                  multiline
                  minRows={5}
                  value={reply}
                  onChange={(e) => setReply(e.target.value)}
                  placeholder="Ihre Antwort…"
                  slotProps={{ htmlInput: { minLength: 1, maxLength: 10_000 } }}
                  fullWidth
                />
                {pendingFiles.length > 0 && (
                  <Stack
                    direction="row"
                    spacing={0.75}
                    sx={{ flexWrap: "wrap", gap: 0.75 }}
                  >
                    {pendingFiles.map((f, i) => (
                      <Chip
                        key={`${f.name}-${i}`}
                        size="small"
                        icon={<AttachFileOutlinedIcon />}
                        label={f.name}
                        onDelete={() =>
                          setPendingFiles((prev) =>
                            prev.filter((_, idx) => idx !== i),
                          )
                        }
                        sx={{ maxWidth: 320 }}
                      />
                    ))}
                  </Stack>
                )}
                <Stack direction="row" spacing={2} sx={{ alignItems: "center" }}>
                  <Button type="submit" variant="contained" disabled={posting}>
                    {posting ? "Wird gesendet…" : "Antwort senden"}
                  </Button>
                  <Button
                    component="label"
                    variant="outlined"
                    size="small"
                    startIcon={<AttachFileOutlinedIcon />}
                    disabled={posting}
                  >
                    {t("tickets.attachments.addLabel")}
                    <input
                      type="file"
                      hidden
                      multiple
                      onChange={(e) => {
                        const picked = Array.from(e.target.files ?? []);
                        if (picked.length === 0) return;
                        setPendingFiles((prev) => [...prev, ...picked]);
                        // Stale failures from a prior submit no longer
                        // describe what's queued — clear them.
                        setUploadErrors([]);
                        e.target.value = "";
                      }}
                    />
                  </Button>
                  {canClose && (
                    <Button
                      type="button"
                      variant="outlined"
                      onClick={onClose}
                      disabled={closing}
                    >
                      {closing ? "Wird geschlossen…" : "Ticket schließen"}
                    </Button>
                  )}
                </Stack>
                {uploadErrors.length > 0 && (
                  <Alert
                    severity="error"
                    onClose={() => setUploadErrors([])}
                    sx={{ mt: 0.5 }}
                  >
                    <Typography
                      variant="body2"
                      sx={{ fontWeight: 600, mb: 0.5 }}
                    >
                      {t("tickets.attachments.uploadFailed")}
                    </Typography>
                    {uploadErrors.map((errInfo, i) => (
                      <Typography
                        key={`${errInfo.name}-${i}`}
                        variant="caption"
                        component="div"
                        sx={{ ml: 0.5 }}
                      >
                        {errInfo.name}
                        {errInfo.detail ? ` — ${errInfo.detail}` : ""}
                      </Typography>
                    ))}
                  </Alert>
                )}
              </Stack>
            </Paper>
          )}
        </Stack>

        {/* Sticky right rail (md+). Hidden on narrow screens. Wraps the
            timeline + attachments roll-up so they share one sticky frame. */}
        <Box sx={{ display: { xs: "none", md: "block" } }}>
          <Box
            sx={{
              position: "sticky",
              top: 88,
              // Cap to viewport so a tall rail scrolls internally
              // instead of overflowing below the fold while pinned.
              maxHeight: "calc(100vh - 104px)",
              overflowY: "auto",
            }}
          >
            <Stack spacing={2}>
              <MessageTimeline
                messages={ticket.messages}
                ticketSubject={ticket.subject}
              />
              {id && (
                <TicketAttachmentsRollup
                  ticketId={id}
                  messages={ticket.messages}
                  scope="portal"
                />
              )}
            </Stack>
          </Box>
        </Box>
      </Box>
    </Stack>
  );
}
