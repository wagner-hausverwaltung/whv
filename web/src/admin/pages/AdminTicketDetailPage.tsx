import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link as RouterLink, useParams } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Card,
  Chip,
  FormControl,
  FormControlLabel,
  IconButton,
  InputLabel,
  Link,
  MenuItem,
  Paper,
  Select,
  Stack,
  Switch,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutlineOutlined";
import { useTranslation } from "react-i18next";
import { api } from "@/api/client";
import {
  TICKET_CATEGORY_LABELS,
  TICKET_SHARE_SCOPE_LABELS,
  TICKET_STATUS_LABELS,
  type TicketDetailResponse,
  type TicketShareScope,
  type TicketStatus,
} from "@/api/types";

const STATUSES: TicketStatus[] = [
  "NEU",
  "OFFEN",
  "WARTET_AUF_KUNDE",
  "GESCHLOSSEN",
];
const SCOPES: TicketShareScope[] = ["PRIVATE", "PARTICIPANTS", "PROPERTY"];

function StatusChip({ status }: { status: TicketStatus }) {
  const color: "success" | "warning" | "default" | "info" =
    status === "GESCHLOSSEN"
      ? "default"
      : status === "WARTET_AUF_KUNDE"
        ? "warning"
        : status === "NEU"
          ? "info"
          : "success";
  return (
    <Chip
      size="small"
      label={TICKET_STATUS_LABELS[status]}
      color={color}
      variant={status === "GESCHLOSSEN" ? "outlined" : "filled"}
    />
  );
}

export function AdminTicketDetailPage() {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();
  const [ticket, setTicket] = useState<TicketDetailResponse | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!id) return;
    try {
      const r = await api.get<TicketDetailResponse>(`/admin/tickets/${id}`);
      setTicket(r.data);
    } catch (err: unknown) {
      const httpStatus = (err as { response?: { status?: number } }).response
        ?.status;
      if (httpStatus === 404) setNotFound(true);
      else setError(t("admin.ticketDetail.loadFailed"));
    }
  }, [id, t]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh();
  }, [refresh]);

  const onStatusChange = async (next: TicketStatus) => {
    if (!id) return;
    try {
      await api.patch(`/admin/tickets/${id}`, { status: next });
      await refresh();
    } catch {
      setError(t("admin.ticketDetail.actionFailed"));
    }
  };

  const onScopeChange = async (next: TicketShareScope) => {
    if (!id) return;
    try {
      await api.patch(`/admin/tickets/${id}/share-scope`, {
        share_scope: next,
      });
      await refresh();
    } catch {
      setError(t("admin.ticketDetail.actionFailed"));
    }
  };

  // --- Participants ---------------------------------------------------------
  const [newEmail, setNewEmail] = useState("");
  const [adding, setAdding] = useState(false);
  const [participantError, setParticipantError] = useState<string | null>(null);

  const addParticipant = async (e: FormEvent) => {
    e.preventDefault();
    if (!id || !newEmail) return;
    setAdding(true);
    setParticipantError(null);
    try {
      await api.post(`/admin/tickets/${id}/participants`, { email: newEmail });
      setNewEmail("");
      await refresh();
    } catch (err: unknown) {
      const detail = (
        err as { response?: { data?: { detail?: string } } }
      ).response?.data?.detail;
      setParticipantError(detail ?? t("admin.ticketDetail.actionFailed"));
    } finally {
      setAdding(false);
    }
  };

  const removeParticipant = async (userId: string) => {
    if (!id) return;
    if (!window.confirm(t("admin.ticketDetail.removeConfirm"))) return;
    try {
      await api.delete(`/admin/tickets/${id}/participants/${userId}`);
      await refresh();
    } catch {
      setError(t("admin.ticketDetail.actionFailed"));
    }
  };

  // --- Reply ----------------------------------------------------------------
  const [reply, setReply] = useState("");
  const [internal, setInternal] = useState(false);
  const [posting, setPosting] = useState(false);

  const sendReply = async (e: FormEvent) => {
    e.preventDefault();
    if (!id || !reply.trim()) return;
    setPosting(true);
    try {
      await api.post(`/admin/tickets/${id}/messages`, {
        body: reply,
        is_internal_note: internal,
      });
      setReply("");
      setInternal(false);
      await refresh();
    } catch {
      setError(t("admin.ticketDetail.actionFailed"));
    } finally {
      setPosting(false);
    }
  };

  if (notFound) {
    return (
      <Stack spacing={2}>
        <Alert severity="error">{t("admin.ticketDetail.notFound")}</Alert>
        <Link component={RouterLink} to="/admin/tickets">
          {t("admin.ticketDetail.back")}
        </Link>
      </Stack>
    );
  }
  if (ticket === null) {
    if (error) return <Alert severity="error">{error}</Alert>;
    return (
      <Typography variant="body2" color="text.secondary">
        {t("common.loading")}
      </Typography>
    );
  }

  return (
    <Stack spacing={3}>
      <Box>
        <Link component={RouterLink} to="/admin/tickets" color="text.secondary">
          {t("admin.ticketDetail.back")}
        </Link>
      </Box>

      <Box>
        <Typography variant="h4" component="h1" gutterBottom>
          {ticket.subject}
        </Typography>
        <Stack
          direction="row"
          spacing={1}
          sx={{ alignItems: "center", flexWrap: "wrap", gap: 1 }}
        >
          <StatusChip status={ticket.status} />
          <Typography variant="caption" color="text.secondary">
            · {TICKET_CATEGORY_LABELS[ticket.category]} ·{" "}
            {t("admin.ticketDetail.createdAt")}{" "}
            {new Date(ticket.created_at).toLocaleString("de-DE")}
            {ticket.closed_at &&
              ` · ${t("admin.ticketDetail.closedAt")} ${new Date(
                ticket.closed_at,
              ).toLocaleString("de-DE")}`}
          </Typography>
        </Stack>
      </Box>

      {error && <Alert severity="error">{error}</Alert>}

      {/* Status + share-scope controls */}
      <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
        <FormControl size="small" sx={{ minWidth: 200 }}>
          <InputLabel>{t("admin.ticketDetail.status")}</InputLabel>
          <Select<TicketStatus>
            value={ticket.status}
            label={t("admin.ticketDetail.status")}
            onChange={(e) => onStatusChange(e.target.value as TicketStatus)}
          >
            {STATUSES.map((s) => (
              <MenuItem key={s} value={s}>
                {TICKET_STATUS_LABELS[s]}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
        <FormControl size="small" sx={{ minWidth: 260 }}>
          <InputLabel>{t("admin.ticketDetail.shareScope")}</InputLabel>
          <Select<TicketShareScope>
            value={ticket.share_scope}
            label={t("admin.ticketDetail.shareScope")}
            onChange={(e) =>
              onScopeChange(e.target.value as TicketShareScope)
            }
          >
            {SCOPES.map((s) => (
              <MenuItem key={s} value={s}>
                {TICKET_SHARE_SCOPE_LABELS[s]}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
      </Stack>
      <Typography variant="caption" color="text.secondary">
        {t("admin.ticketDetail.shareScopeHelp")}
      </Typography>

      {/* Participants */}
      <Paper variant="outlined" sx={{ p: 2 }}>
        <Typography variant="subtitle1" gutterBottom>
          {t("admin.ticketDetail.participants")} ({ticket.participants.length})
        </Typography>
        {ticket.participants.length > 0 && (
          <Stack spacing={1} sx={{ mb: 2 }}>
            {ticket.participants.map((p) => (
              <Stack
                key={p.user_id}
                direction="row"
                spacing={1}
                sx={{ alignItems: "center" }}
              >
                <Typography variant="body2" sx={{ flex: 1 }}>
                  {p.email}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {new Date(p.added_at).toLocaleDateString("de-DE")}
                </Typography>
                <Tooltip title={t("admin.ticketDetail.removeParticipant")}>
                  <IconButton
                    size="small"
                    onClick={() => removeParticipant(p.user_id)}
                    aria-label={t("admin.ticketDetail.removeParticipant")}
                  >
                    <DeleteOutlineIcon fontSize="small" />
                  </IconButton>
                </Tooltip>
              </Stack>
            ))}
          </Stack>
        )}
        {participantError && (
          <Alert severity="error" sx={{ mb: 1 }}>
            {participantError}
          </Alert>
        )}
        <Box component="form" onSubmit={addParticipant}>
          <Stack direction="row" spacing={1}>
            <TextField
              type="email"
              value={newEmail}
              onChange={(e) => setNewEmail(e.target.value)}
              placeholder={t("admin.ticketDetail.addParticipantPlaceholder")}
              size="small"
              sx={{ flex: 1 }}
              required
            />
            <Button
              type="submit"
              variant="outlined"
              disabled={adding || !newEmail}
            >
              {t("admin.ticketDetail.addParticipant")}
            </Button>
          </Stack>
        </Box>
      </Paper>

      {/* Thread */}
      <Stack spacing={2}>
        <Typography variant="subtitle1">
          {t("admin.ticketDetail.thread")} ({ticket.messages.length})
        </Typography>
        {ticket.messages.map((m) => (
          <Card
            key={m.id}
            variant="outlined"
            sx={{
              p: 2,
              bgcolor: m.is_internal_note
                ? (th) =>
                    th.palette.mode === "dark"
                      ? "rgba(217, 119, 6, 0.08)"
                      : "#fef9c3"
                : "background.paper",
              borderColor: m.is_internal_note ? "warning.light" : "divider",
            }}
          >
            <Stack
              direction="row"
              sx={{
                justifyContent: "space-between",
                alignItems: "baseline",
                mb: 1,
                gap: 1,
                flexWrap: "wrap",
              }}
            >
              <Typography variant="body2" sx={{ fontWeight: 600 }}>
                {m.author_email ?? m.author_user_id}
                {m.is_internal_note && (
                  <Typography
                    component="span"
                    variant="caption"
                    color="text.secondary"
                    sx={{ ml: 1 }}
                  >
                    {t("admin.ticketDetail.internalNote")}
                  </Typography>
                )}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                {new Date(m.created_at).toLocaleString("de-DE")}
              </Typography>
            </Stack>
            <Typography variant="body2" sx={{ whiteSpace: "pre-wrap" }}>
              {m.body}
            </Typography>
          </Card>
        ))}
      </Stack>

      {/* Reply form */}
      <Paper variant="outlined" sx={{ p: 2 }}>
        <Typography variant="subtitle1" gutterBottom>
          {t("admin.ticketDetail.reply")}
        </Typography>
        <Box component="form" onSubmit={sendReply}>
          <Stack spacing={1.5}>
            <TextField
              multiline
              minRows={4}
              value={reply}
              onChange={(e) => setReply(e.target.value)}
              placeholder={t("admin.ticketDetail.replyPlaceholder")}
              required
              fullWidth
            />
            <FormControlLabel
              control={
                <Switch
                  checked={internal}
                  onChange={(e) => setInternal(e.target.checked)}
                />
              }
              label={t("admin.ticketDetail.internalCheckbox")}
            />
            <Box>
              <Button
                type="submit"
                variant="contained"
                disabled={posting || !reply.trim()}
              >
                {posting ? t("common.loading") : t("admin.ticketDetail.send")}
              </Button>
            </Box>
          </Stack>
        </Box>
      </Paper>
    </Stack>
  );
}
