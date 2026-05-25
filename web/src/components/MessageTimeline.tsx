import { Box, Paper, Stack, Typography } from "@mui/material";
import { useTranslation } from "react-i18next";
import type { TicketMessageResponse } from "@/api/types";

interface MessageTimelineProps {
  messages: TicketMessageResponse[];
  /** Subject of the parent ticket — used as the "subject" of the very
   *  first (chronologically earliest) message. Subsequent messages
   *  surface their own first body line. */
  ticketSubject: string;
  /** Each message in the thread is rendered with `id={anchorPrefix-msg.id}`;
   *  the timeline scrolls to that id when a node is clicked. Defaults
   *  to `"msg"` to match the convention in TicketDetailPage. */
  anchorPrefix?: string;
}

/** Sleek vertical timeline that lives in the right column of the ticket
 *  detail view. One node per message, recency-descending (newest at the
 *  top per the user's spec), each row formatted as
 *  `DD.MM.YYYY HH:MM - <subject preview>` and clickable to scroll the
 *  thread to that message.
 *
 *  Messages don't carry their own subject in the data model — only the
 *  parent ticket does — so the first (original) message borrows the
 *  ticket subject and replies surface the first ~60 chars of their body
 *  as a stand-in. Good enough for a "what was said when" overview.
 */
export function MessageTimeline({
  messages,
  ticketSubject,
  anchorPrefix = "msg",
}: MessageTimelineProps) {
  const { t, i18n } = useTranslation();
  if (messages.length === 0) return null;

  // We need two views: chronological (to know which message is the
  // *original* — i.e. the one whose subject is the ticket subject) and
  // reverse-chronological (the order the timeline renders).
  const byOldestFirst = [...messages].sort((a, b) =>
    a.created_at.localeCompare(b.created_at),
  );
  const byNewestFirst = [...messages].sort((a, b) =>
    b.created_at.localeCompare(a.created_at),
  );
  const originalId = byOldestFirst[0]?.id;

  const locale = i18n.language?.startsWith("de") ? "de-DE" : "en-GB";

  const subjectFor = (m: TicketMessageResponse): string => {
    if (m.id === originalId) return ticketSubject;
    const firstLine = m.body.split("\n").find((l) => l.trim() !== "") ?? "";
    return firstLine.length > 60 ? `${firstLine.slice(0, 57)}…` : firstLine;
  };

  const scrollTo = (msgId: string) => {
    const el = document.getElementById(`${anchorPrefix}-${msgId}`);
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "start" });
    // Brief outline pulse so the user spots the target after the scroll
    // settles. Inline style — no global CSS — easy to reason about.
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
    <Paper
      variant="outlined"
      sx={{
        p: 2,
        // The timeline tracks the thread as the user scrolls. 88px keeps
        // it clear of the static AppBar (64px Toolbar + a bit of breathing
        // room).
        position: "sticky",
        top: 88,
      }}
    >
      <Typography
        variant="overline"
        color="text.secondary"
        sx={{ display: "block", mb: 1.5, letterSpacing: "0.08em" }}
      >
        {t("tickets.timeline.title")}
      </Typography>
      <Box sx={{ position: "relative" }}>
        {/* Vertical rail behind the nodes. Insets match the node radius
            so it stops cleanly at the first and last circles. */}
        <Box
          sx={{
            position: "absolute",
            left: 5,
            top: 8,
            bottom: 8,
            width: 2,
            bgcolor: "divider",
            borderRadius: 1,
          }}
        />
        <Stack spacing={1.25}>
          {byNewestFirst.map((m) => {
            const d = new Date(m.created_at);
            const isOriginal = m.id === originalId;
            const dateStr = d.toLocaleDateString(locale, {
              day: "2-digit",
              month: "2-digit",
              year: "numeric",
            });
            const timeStr = d.toLocaleTimeString(locale, {
              hour: "2-digit",
              minute: "2-digit",
            });
            return (
              <Box
                key={m.id}
                component="button"
                type="button"
                onClick={() => scrollTo(m.id)}
                sx={{
                  display: "flex",
                  alignItems: "flex-start",
                  gap: 1.25,
                  width: "100%",
                  textAlign: "left",
                  background: "none",
                  border: 0,
                  p: 0.5,
                  m: 0,
                  borderRadius: 1,
                  cursor: "pointer",
                  color: "inherit",
                  "&:hover": { bgcolor: "action.hover" },
                  "&:focus-visible": {
                    outline: "2px solid",
                    outlineColor: "primary.main",
                    outlineOffset: 2,
                  },
                }}
              >
                <Box
                  sx={{
                    position: "relative",
                    flex: "none",
                    mt: "3px",
                    width: 12,
                    height: 12,
                    borderRadius: "50%",
                    bgcolor: isOriginal ? "primary.main" : "background.paper",
                    border: 2,
                    borderColor: isOriginal ? "primary.main" : "primary.light",
                    boxShadow: (theme) =>
                      `0 0 0 3px ${theme.palette.background.paper}`,
                  }}
                />
                <Box sx={{ minWidth: 0, flex: 1 }}>
                  <Typography
                    variant="caption"
                    color="text.secondary"
                    sx={{
                      display: "block",
                      fontFeatureSettings: '"tnum" 1',
                    }}
                  >
                    {dateStr} {timeStr}
                  </Typography>
                  <Typography
                    variant="body2"
                    sx={{
                      fontWeight: isOriginal ? 600 : 400,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      display: "-webkit-box",
                      WebkitLineClamp: 2,
                      WebkitBoxOrient: "vertical",
                      wordBreak: "break-word",
                    }}
                  >
                    {"- "}
                    {subjectFor(m)}
                  </Typography>
                </Box>
              </Box>
            );
          })}
        </Stack>
      </Box>
    </Paper>
  );
}
