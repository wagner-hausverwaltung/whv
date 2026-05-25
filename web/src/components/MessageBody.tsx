import { useMemo, useState } from "react";
import { Box, Link, Typography } from "@mui/material";
import { useTranslation } from "react-i18next";
import { splitOnSignature } from "@/lib/messageBody";

interface MessageBodyProps {
  body: string;
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
export function MessageBody({ body }: MessageBodyProps) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const { visible, hiddenCount, full } = useMemo(
    () => splitOnSignature(body),
    [body],
  );

  if (hiddenCount === 0) {
    return (
      <Typography variant="body2" sx={{ whiteSpace: "pre-wrap" }}>
        {body}
      </Typography>
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
    </Box>
  );
}
