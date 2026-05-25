import { useEffect, useState, type FormEvent } from "react";
import { Link as RouterLink, useParams } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Card,
  FormControl,
  IconButton,
  InputLabel,
  Link,
  MenuItem,
  Paper,
  Select,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutlineOutlined";
import { api } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import {
  TICKET_CATEGORY_LABELS,
  TICKET_SHARE_SCOPE_LABELS,
  TICKET_STATUS_LABELS,
  type TicketDetailResponse,
  type TicketShareScope,
} from "@/api/types";
import { MessageTimeline } from "@/components/MessageTimeline";

export function TicketDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { user } = useAuth();
  const [ticket, setTicket] = useState<TicketDetailResponse | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reply, setReply] = useState("");
  const [posting, setPosting] = useState(false);
  const [closing, setClosing] = useState(false);

  const [newParticipantEmail, setNewParticipantEmail] = useState("");
  const [participantError, setParticipantError] = useState<string | null>(null);
  const [addingParticipant, setAddingParticipant] = useState(false);

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
    setPosting(true);
    try {
      await api.post(`/me/tickets/${ticket.id}/messages`, {
        body: reply.trim(),
        is_internal_note: false,
      });
      setReply("");
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
          is hidden — the thread cards are already linear and short there. */}
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: { xs: "1fr", md: "minmax(0, 1fr) 280px" },
          gap: 3,
          alignItems: "start",
        }}
      >
        <Stack spacing={3} sx={{ minWidth: 0 }}>
          <Paper variant="outlined" sx={{ p: 2.5 }}>
        <Stack
          direction="row"
          sx={{
            justifyContent: "space-between",
            alignItems: "baseline",
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
          {canManage ? (
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
          ) : (
            <Typography variant="body2" color="text.secondary">
              {TICKET_SHARE_SCOPE_LABELS[ticket.share_scope]}
            </Typography>
          )}
        </Stack>

        {ticket.participants.length > 0 ? (
          <Stack spacing={1} sx={{ mb: canManage ? 2 : 0 }}>
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
          <Typography
            variant="body2"
            color="text.secondary"
            sx={{ mb: canManage ? 2 : 0 }}
          >
            Keine namentlichen Teilnehmer.
          </Typography>
        )}

        {canManage && (
          <Box component="form" onSubmit={onAddParticipant}>
            {participantError && (
              <Alert severity="error" sx={{ mb: 1 }}>
                {participantError}
              </Alert>
            )}
            <Stack direction="row" spacing={1}>
              <TextField
                type="email"
                size="small"
                required
                placeholder="E-Mail-Adresse eines WHV-Kontos"
                value={newParticipantEmail}
                onChange={(e) => setNewParticipantEmail(e.target.value)}
                disabled={addingParticipant}
                sx={{ flex: 1 }}
              />
              <Button
                type="submit"
                variant="outlined"
                disabled={addingParticipant || !newParticipantEmail}
              >
                {addingParticipant ? "Wird hinzugefügt…" : "Hinzufügen"}
              </Button>
            </Stack>
            <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: "block" }}>
              Die Person braucht ein WHV-Portal-Konto. Hinzugefügte Teilnehmer
              erhalten E-Mail-Updates bei jeder neuen Nachricht und können
              selbst antworten.
            </Typography>
          </Box>
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
              <Typography variant="body2" sx={{ whiteSpace: "pre-wrap" }}>
                {m.body}
              </Typography>
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
                <Stack direction="row" spacing={2}>
                  <Button type="submit" variant="contained" disabled={posting}>
                    {posting ? "Wird gesendet…" : "Antwort senden"}
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
              </Stack>
            </Paper>
          )}
        </Stack>

        {/* Sticky timeline rail on md+. The component bails on empty
            arrays, but a ticket always has at least the original message. */}
        <Box sx={{ display: { xs: "none", md: "block" } }}>
          <MessageTimeline
            messages={ticket.messages}
            ticketSubject={ticket.subject}
          />
        </Box>
      </Box>
    </Stack>
  );
}
