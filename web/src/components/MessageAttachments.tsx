import { useState } from "react";
import { Alert, Box, Chip, Stack } from "@mui/material";
import AttachFileOutlinedIcon from "@mui/icons-material/AttachFileOutlined";
import { useTranslation } from "react-i18next";
import type { TicketMessageAttachmentResponse } from "@/api/types";
import { downloadAttachment } from "@/lib/ticketAttachments";

interface MessageAttachmentsProps {
  ticketId: string;
  attachments: TicketMessageAttachmentResponse[];
  /** Which router prefix to download under — admin sees attachments
   *  even on internal notes, portal hides them. */
  scope: "admin" | "portal";
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

/** Row of clickable Chips under a message card. One per attached file. */
export function MessageAttachments({
  ticketId,
  attachments,
  scope,
}: MessageAttachmentsProps) {
  const { t } = useTranslation();
  const [error, setError] = useState<string | null>(null);

  if (attachments.length === 0) return null;

  const onClick = async (a: TicketMessageAttachmentResponse) => {
    setError(null);
    try {
      await downloadAttachment(ticketId, a, scope);
    } catch {
      setError(t("tickets.attachments.downloadFailed"));
    }
  };

  return (
    <Box sx={{ mt: 1.5 }}>
      <Stack
        direction="row"
        spacing={0.75}
        sx={{ flexWrap: "wrap", gap: 0.75, alignItems: "center" }}
      >
        {attachments.map((a) => (
          <Chip
            key={a.id}
            size="small"
            variant="outlined"
            icon={<AttachFileOutlinedIcon />}
            label={`${a.filename} · ${formatBytes(a.size_bytes)}`}
            onClick={() => void onClick(a)}
            clickable
            sx={{
              maxWidth: 320,
              "& .MuiChip-label": {
                overflow: "hidden",
                textOverflow: "ellipsis",
              },
            }}
          />
        ))}
      </Stack>
      {error && (
        <Alert
          severity="error"
          onClose={() => setError(null)}
          sx={{ mt: 1 }}
        >
          {error}
        </Alert>
      )}
    </Box>
  );
}
