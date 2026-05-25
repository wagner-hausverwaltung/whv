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
  Popover,
  Select,
  Stack,
  Switch,
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
import {
  TICKET_CATEGORY_LABELS,
  TICKET_SHARE_SCOPE_LABELS,
  TICKET_STATUS_LABELS,
  type TicketDetailResponse,
  type TicketShareScope,
  type TicketStatus,
} from "@/api/types";
import { MessageAttachments } from "@/components/MessageAttachments";
import { MessageBody } from "@/components/MessageBody";
import { MessageTimeline } from "@/components/MessageTimeline";
import { TicketAttachmentsRollup } from "@/components/TicketAttachmentsRollup";

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
  // The add form lives in a Popover anchored to the "+" icon; null means
  // closed. State lives at page scope so submit handlers can close it.
  const [addAnchor, setAddAnchor] = useState<HTMLElement | null>(null);

  const closeAddPopover = () => {
    setAddAnchor(null);
    setParticipantError(null);
  };

  const addParticipant = async (e: FormEvent) => {
    e.preventDefault();
    if (!id || !newEmail) return;
    setAdding(true);
    setParticipantError(null);
    try {
      await api.post(`/admin/tickets/${id}/participants`, { email: newEmail });
      setNewEmail("");
      setAddAnchor(null);
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
  // Pending file picks staged before submit. Files upload after the
  // message POST returns (we need its id to attach against).
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);

  const sendReply = async (e: FormEvent) => {
    e.preventDefault();
    if (!id || !reply.trim()) return;
    setPosting(true);
    try {
      const res = await api.post<{ id: string }>(
        `/admin/tickets/${id}/messages`,
        { body: reply, is_internal_note: internal },
      );
      const newMessageId = res.data.id;
      // Best-effort: upload each pending file. One failure doesn't abort
      // the rest — surface a generic toast at the end if any fail.
      let uploadFailures = 0;
      for (const file of pendingFiles) {
        try {
          const form = new FormData();
          form.append("file", file);
          await api.post(
            `/admin/tickets/${id}/messages/${newMessageId}/attachments`,
            form,
          );
        } catch {
          uploadFailures += 1;
        }
      }
      if (uploadFailures > 0) {
        setError(t("tickets.attachments.uploadFailed"));
      }
      setReply("");
      setInternal(false);
      setPendingFiles([]);
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

      {/* Status + share-scope controls. The share-scope help note now
          rides along as a hover tooltip on the (i) icon next to the
          dropdown — frees up a row of vertical chrome and keeps the
          long explanation out of the way until the Verwalter looks for it. */}
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
        <Stack direction="row" spacing={0.5} sx={{ alignItems: "center" }}>
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
          <Tooltip
            title={t("admin.ticketDetail.shareScopeHelp")}
            placement="top"
            arrow
          >
            <IconButton
              size="small"
              // Skip in tab order — the tooltip content is informational
              // and reachable via the visible label/select for screen
              // readers via aria-describedby? Not wired here; the help
              // text is short enough that a sighted hover-discoverable
              // hint is the right tradeoff for now.
              tabIndex={-1}
              sx={{ color: "text.secondary" }}
              aria-label={t("admin.ticketDetail.shareScopeHelpAria")}
            >
              <InfoOutlinedIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        </Stack>
      </Stack>

      {/* Below the controls, the body splits into the main column
          (participants + thread + reply) and a sticky timeline rail on
          md+ screens. On narrow screens the timeline hides — thread
          cards remain linear and short.

          Note on alignment: NO `alignItems: "start"` here. Grid's
          default `stretch` is exactly what we want so the right column
          tracks the main column's height — that's what gives
          `position: sticky` on the rail enough scroll range to stay
          pinned through the whole thread. With `start`, the right
          column was only as tall as the rail itself and sticky ran out
          of room after ~one screen of scrolling. */}
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: { xs: "1fr", md: "minmax(0, 1fr) 280px" },
          gap: 3,
        }}
      >
        <Stack spacing={3} sx={{ minWidth: 0 }}>
      {/* Participants. Header carries the count + a "+" icon that pops
          the add-form open in a small floating panel — keeps the
          baseline list clean (no empty input field on a fresh ticket)
          and the error alert is scoped to the popover instead of
          dangling under the section title. */}
      <Paper variant="outlined" sx={{ p: 2 }}>
        <Stack
          direction="row"
          sx={{ alignItems: "center", justifyContent: "space-between", mb: 1 }}
        >
          <Typography variant="subtitle1">
            {t("admin.ticketDetail.participants")} (
            {ticket.participants.length})
          </Typography>
          <Tooltip title={t("admin.ticketDetail.addParticipant")}>
            <IconButton
              size="small"
              color="primary"
              onClick={(e) => setAddAnchor(e.currentTarget)}
              aria-label={t("admin.ticketDetail.addParticipant")}
            >
              <AddIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        </Stack>
        {ticket.participants.length > 0 ? (
          <Stack spacing={1}>
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
        ) : (
          <Typography variant="caption" color="text.secondary">
            {t("admin.ticketDetail.noParticipants")}
          </Typography>
        )}
        <Popover
          open={Boolean(addAnchor)}
          anchorEl={addAnchor}
          onClose={closeAddPopover}
          anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
          transformOrigin={{ vertical: "top", horizontal: "right" }}
          slotProps={{ paper: { sx: { p: 2, width: 360, maxWidth: "90vw" } } }}
        >
          <Box component="form" onSubmit={addParticipant}>
            <Stack spacing={1.5}>
              <Typography variant="subtitle2">
                {t("admin.ticketDetail.addParticipant")}
              </Typography>
              {participantError && (
                <Alert severity="error">{participantError}</Alert>
              )}
              <TextField
                type="email"
                value={newEmail}
                onChange={(e) => setNewEmail(e.target.value)}
                placeholder={t(
                  "admin.ticketDetail.addParticipantPlaceholder",
                )}
                size="small"
                fullWidth
                required
                autoFocus
              />
              <Stack
                direction="row"
                spacing={1}
                sx={{ justifyContent: "flex-end" }}
              >
                <Button size="small" onClick={closeAddPopover}>
                  {t("common.cancel")}
                </Button>
                <Button
                  type="submit"
                  variant="contained"
                  size="small"
                  disabled={adding || !newEmail}
                >
                  {t("admin.ticketDetail.addParticipant")}
                </Button>
              </Stack>
            </Stack>
          </Box>
        </Popover>
      </Paper>

      {/* Thread */}
      <Stack spacing={2}>
        <Typography variant="subtitle1">
          {t("admin.ticketDetail.thread")} ({ticket.messages.length})
        </Typography>
        {ticket.messages.map((m) => (
          <Card
            key={m.id}
            id={`msg-${m.id}`}
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
              // Sticky AppBar offset so the timeline-jump doesn't park
              // the card under the header.
              scrollMarginTop: 88,
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
            <MessageBody body={m.body} />
            {id && (
              <MessageAttachments
                ticketId={id}
                attachments={m.attachments ?? []}
                scope="admin"
              />
            )}
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
            <FormControlLabel
              control={
                <Switch
                  checked={internal}
                  onChange={(e) => setInternal(e.target.checked)}
                />
              }
              label={t("admin.ticketDetail.internalCheckbox")}
            />
            <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
              <Button
                type="submit"
                variant="contained"
                disabled={posting || !reply.trim()}
              >
                {posting ? t("common.loading") : t("admin.ticketDetail.send")}
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
                    // Reset so picking the same file again still fires.
                    e.target.value = "";
                  }}
                />
              </Button>
            </Stack>
          </Stack>
        </Box>
      </Paper>
        </Stack>

        {/* Sticky right rail (md+). Hidden on narrow screens. Wraps the
            timeline + attachments roll-up in a single sticky frame so
            they scroll together. */}
        <Box sx={{ display: { xs: "none", md: "block" } }}>
          <Box
            sx={{
              position: "sticky",
              top: 88,
              // Cap to viewport so a ticket with a tall timeline +
              // attachment roll-up scrolls internally instead of
              // pushing the bottom items below the fold while pinned.
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
                  scope="admin"
                />
              )}
            </Stack>
          </Box>
        </Box>
      </Box>
    </Stack>
  );
}
