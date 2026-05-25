import { useMemo, useState } from "react";
import {
  Alert,
  Box,
  IconButton,
  Link,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  Paper,
  Stack,
  Tooltip,
  Typography,
} from "@mui/material";
import AttachFileOutlinedIcon from "@mui/icons-material/AttachFileOutlined";
import { useTranslation } from "react-i18next";
import type {
  TicketMessageAttachmentResponse,
  TicketMessageResponse,
} from "@/api/types";
import { downloadAttachment } from "@/lib/ticketAttachments";

interface TicketAttachmentsRollupProps {
  ticketId: string;
  messages: TicketMessageResponse[];
  scope: "admin" | "portal";
  /** DOM id prefix matching the message cards so clicks scroll the
   *  thread to the message that hosts the attachment. Defaults to
   *  the convention shared with MessageTimeline. */
  anchorPrefix?: string;
}

function formatBytes(bytes: number): string {
  if (bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  let n = bytes;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i++;
  }
  return `${n.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

/** Right-rail roll-up: every attachment on this ticket, across all
 *  messages, newest at the top. Clicking the filename downloads;
 *  clicking the floating "Zur Nachricht" icon scrolls the thread to
 *  the parent message. Hidden entirely when the ticket has nothing
 *  attached — the rail collapses to just the timeline.
 */
export function TicketAttachmentsRollup({
  ticketId,
  messages,
  scope,
  anchorPrefix = "msg",
}: TicketAttachmentsRollupProps) {
  const { t } = useTranslation();
  const [error, setError] = useState<string | null>(null);

  const flat = useMemo(() => {
    const entries: {
      a: TicketMessageAttachmentResponse;
      messageCreatedAt: string;
      messageId: string;
    }[] = [];
    for (const m of messages) {
      for (const a of m.attachments ?? []) {
        entries.push({ a, messageCreatedAt: m.created_at, messageId: m.id });
      }
    }
    // Newest first — match the timeline's recency-descending order.
    entries.sort((x, y) =>
      y.messageCreatedAt.localeCompare(x.messageCreatedAt),
    );
    return entries;
  }, [messages]);

  if (flat.length === 0) return null;

  const onDownload = async (a: TicketMessageAttachmentResponse) => {
    setError(null);
    try {
      await downloadAttachment(ticketId, a, scope);
    } catch {
      setError(t("tickets.attachments.downloadFailed"));
    }
  };

  const onJump = (messageId: string) => {
    const el = document.getElementById(`${anchorPrefix}-${messageId}`);
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "start" });
    // Brief outline pulse so the user spots the parent message after
    // the scroll. Same trick the timeline uses.
    const prev = el.style.outline;
    const prevOffset = el.style.outlineOffset;
    el.style.outline = "2px solid var(--mui-palette-primary-main, #1863DC)";
    el.style.outlineOffset = "4px";
    window.setTimeout(() => {
      el.style.outline = prev;
      el.style.outlineOffset = prevOffset;
    }, 1200);
  };

  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Typography
        variant="overline"
        color="text.secondary"
        sx={{
          display: "block",
          mb: 1,
          letterSpacing: "0.08em",
        }}
      >
        {t("tickets.attachments.rollupTitle")} ({flat.length})
      </Typography>
      <List disablePadding dense>
        {flat.map(({ a, messageId }) => (
          <ListItem
            key={a.id}
            disableGutters
            sx={{ alignItems: "flex-start", gap: 0.5 }}
            secondaryAction={
              <Tooltip title={t("tickets.attachments.jumpToMessage")}>
                <IconButton
                  size="small"
                  edge="end"
                  onClick={() => onJump(messageId)}
                  aria-label={t("tickets.attachments.jumpToMessage")}
                >
                  <Box
                    component="span"
                    sx={{
                      width: 16,
                      height: 16,
                      borderRadius: "50%",
                      border: "2px solid",
                      borderColor: "primary.light",
                      display: "inline-block",
                    }}
                  />
                </IconButton>
              </Tooltip>
            }
          >
            <ListItemIcon sx={{ minWidth: 32, mt: 0.5 }}>
              <AttachFileOutlinedIcon
                fontSize="small"
                sx={{ color: "text.secondary" }}
              />
            </ListItemIcon>
            <ListItemText
              primary={
                <Link
                  component="button"
                  type="button"
                  underline="hover"
                  onClick={() => void onDownload(a)}
                  sx={{
                    textAlign: "left",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    display: "-webkit-box",
                    WebkitLineClamp: 2,
                    WebkitBoxOrient: "vertical",
                    wordBreak: "break-word",
                    fontSize: "0.875rem",
                  }}
                >
                  {a.filename}
                </Link>
              }
              secondary={
                <Typography
                  variant="caption"
                  color="text.secondary"
                  component="span"
                >
                  {formatBytes(a.size_bytes)}
                </Typography>
              }
              slotProps={{ secondary: { component: "span" } }}
              sx={{ mr: 4 }}
            />
          </ListItem>
        ))}
      </List>
      {error && (
        <Alert
          severity="error"
          onClose={() => setError(null)}
          sx={{ mt: 1 }}
        >
          {error}
        </Alert>
      )}
      <Stack
        direction="row"
        spacing={0.5}
        sx={{ alignItems: "center", mt: 1, color: "text.disabled" }}
      >
        <Typography variant="caption" color="text.disabled">
          {t("tickets.attachments.rollupHint")}
        </Typography>
      </Stack>
    </Paper>
  );
}
