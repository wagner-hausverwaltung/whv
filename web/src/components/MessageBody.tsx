import { useMemo, useState } from "react";
import { Box, Link, Typography } from "@mui/material";
import { useTranslation } from "react-i18next";
import { splitOnSignature } from "@/lib/messageBody";

interface MessageBodyProps {
  body: string;
  /** Fresh text of an e-mail reply (server-split). Falls back to `body`. */
  visibleBody?: string;
  /** Quoted thread below the reply; collapsed behind "Zitat anzeigen". */
  quotedBody?: string | null;
}

/** Renders a ticket message body with default signature / quote
 *  trimming and a "Mehr anzeigen" toggle. Falls through to a plain
 *  pre-wrap Typography when there's nothing worth trimming, so
 *  SPA-typed replies look identical to before.
 *
 *  Trim heuristic lives in `@/lib/messageBody`; this component just
 *  owns the visible/hidden state. The full body is always preserved
 *  in `splitOnSignature.full` so the toggle is purely client-side.
 */
export function MessageBody({ body, visibleBody, quotedBody }: MessageBodyProps) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const [quoteOpen, setQuoteOpen] = useState(false);
  // Two-stage: the server already stripped the quoted e-mail thread (it
  // knows the reply-header shapes); the client-side signature trim then
  // runs on what is left. Both toggles are independent.
  const base = visibleBody ?? body;
  const { visible, hiddenCount, full } = useMemo(
    () => splitOnSignature(base),
    [base],
  );

  const quote =
    quotedBody && quotedBody.trim().length > 0 ? (
      <Box sx={{ mt: 0.75 }}>
        <Link
          component="button"
          type="button"
          variant="caption"
          underline="hover"
          onClick={() => setQuoteOpen((v) => !v)}
          sx={{ display: "inline-block" }}
        >
          {quoteOpen
            ? t("tickets.messageBody.hideQuote")
            : t("tickets.messageBody.showQuote")}
        </Link>
        {quoteOpen && (
          <Typography
            variant="caption"
            component="div"
            sx={{
              whiteSpace: "pre-wrap",
              color: "text.secondary",
              borderLeft: 2,
              borderColor: "divider",
              pl: 1,
              mt: 0.5,
            }}
          >
            {quotedBody}
          </Typography>
        )}
      </Box>
    ) : null;

  if (hiddenCount === 0) {
    return (
      <Box>
        <Typography variant="body2" sx={{ whiteSpace: "pre-wrap" }}>
          {base}
        </Typography>
        {quote}
      </Box>
    );
  }

  return (
    <Box>
      <Typography variant="body2" sx={{ whiteSpace: "pre-wrap" }}>
        {expanded ? full : visible}
      </Typography>
      <Link
        component="button"
        type="button"
        variant="caption"
        underline="hover"
        onClick={() => setExpanded((v) => !v)}
        sx={{ mt: 0.5, display: "inline-block" }}
      >
        {expanded
          ? t("tickets.messageBody.showLess")
          : t("tickets.messageBody.showMore", { count: hiddenCount })}
      </Link>
      {quote}
    </Box>
  );
}
