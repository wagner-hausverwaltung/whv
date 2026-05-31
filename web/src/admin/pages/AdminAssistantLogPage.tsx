import { useEffect, useState } from "react";
import {
  Alert,
  Box,
  Chip,
  Dialog,
  DialogContent,
  DialogTitle,
  Divider,
  IconButton,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import DescriptionIcon from "@mui/icons-material/Description";
import HandymanIcon from "@mui/icons-material/Handyman";
import { api } from "@/api/client";

// Mirrors the backend admin_assistant responses (ADR-0013).
interface ConversationSummary {
  conversation_id: string;
  user_email: string | null;
  property_id: string | null;
  property_name: string | null;
  started_at: string;
  last_at: string;
  message_count: number;
  first_question: string;
}

interface Citation {
  index: number | null;
  document_id: string | null;
  document_name: string | null;
  page: number | null;
  source_kind: string | null;
  source_type: string | null;
  contact_name: string | null;
}

interface AssistantMessage {
  id: string;
  question: string;
  answer: string;
  abstained: boolean;
  property_id: string | null;
  citations: Citation[];
  created_at: string;
}

interface ConversationDetail {
  conversation_id: string;
  user_email: string | null;
  property_name: string | null;
  messages: AssistantMessage[];
}

function fmt(ts: string): string {
  return new Date(ts).toLocaleString("de-DE");
}

function citationLabel(c: Citation): string {
  const n = c.index != null ? `[${c.index}] ` : "";
  if (c.source_type && c.source_type !== "document") {
    return `${n}Dienstleister: ${c.contact_name ?? "?"}`;
  }
  const base = c.document_name ?? [c.source_kind, c.contact_name].filter(Boolean).join(" · ") ?? "Dokument";
  return c.page != null ? `${n}${base} · S.${c.page}` : `${n}${base}`;
}

export function AdminAssistantLogPage() {
  const [rows, setRows] = useState<ConversationSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<ConversationDetail | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);

  useEffect(() => {
    api
      .get<{ items: ConversationSummary[] }>("/admin/assistant/conversations")
      .then((r) => setRows(r.data.items))
      .catch(() => setError("Konversationen konnten nicht geladen werden."));
  }, []);

  const openDetail = async (id: string) => {
    setDetail(null);
    setDetailOpen(true);
    try {
      const res = await api.get<ConversationDetail>(`/admin/assistant/conversations/${id}`);
      setDetail(res.data);
    } catch {
      setError("Konversation konnte nicht geladen werden.");
      setDetailOpen(false);
    }
  };

  const openDocument = async (c: Citation) => {
    if (!c.document_id || (c.source_type && c.source_type !== "document")) return;
    try {
      const res = await api.get<Blob>(`/admin/documents/${c.document_id}/file`, {
        responseType: "blob",
      });
      const url = URL.createObjectURL(res.data);
      window.open(url, "_blank", "noopener");
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch {
      setError("Das Dokument konnte nicht geöffnet werden.");
    }
  };

  return (
    <Stack spacing={3}>
      <Box>
        <Typography variant="h4" component="h1" gutterBottom>
          KI-Protokoll
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Alle Assistent-Konversationen: Fragen, Antworten, genutzte Dokumente und Liegenschaft.
        </Typography>
      </Box>

      {error && <Alert severity="error">{error}</Alert>}

      {rows === null ? (
        <Typography variant="body2" color="text.secondary">
          Wird geladen…
        </Typography>
      ) : rows.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          Noch keine Konversationen.
        </Typography>
      ) : (
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Zuletzt</TableCell>
                <TableCell>Nutzer</TableCell>
                <TableCell>Liegenschaft</TableCell>
                <TableCell>Erste Frage</TableCell>
                <TableCell align="right">Nachrichten</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((r) => (
                <TableRow
                  key={r.conversation_id}
                  hover
                  sx={{ cursor: "pointer" }}
                  onClick={() => void openDetail(r.conversation_id)}
                >
                  <TableCell>
                    <Typography variant="caption" color="text.secondary">
                      {fmt(r.last_at)}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2">{r.user_email ?? "—"}</Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2">{r.property_name ?? "Alle"}</Typography>
                  </TableCell>
                  <TableCell sx={{ maxWidth: 360 }}>
                    <Typography variant="body2" noWrap>
                      {r.first_question}
                    </Typography>
                  </TableCell>
                  <TableCell align="right">{r.message_count}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      <Dialog open={detailOpen} onClose={() => setDetailOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle sx={{ pr: 6 }}>
          Konversation
          {detail && (
            <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
              {detail.user_email ?? "—"} · {detail.property_name ?? "Alle Liegenschaften"}
            </Typography>
          )}
          <IconButton
            onClick={() => setDetailOpen(false)}
            sx={{ position: "absolute", right: 8, top: 8 }}
            aria-label="Schließen"
          >
            <CloseIcon />
          </IconButton>
        </DialogTitle>
        <DialogContent dividers>
          {detail === null ? (
            <Typography variant="body2" color="text.secondary">
              Wird geladen…
            </Typography>
          ) : (
            <Stack spacing={2} divider={<Divider flexItem />}>
              {detail.messages.map((m) => (
                <Box key={m.id}>
                  <Typography variant="caption" color="text.secondary">
                    {fmt(m.created_at)}
                  </Typography>
                  <Typography variant="subtitle2" sx={{ mt: 0.5 }}>
                    Frage
                  </Typography>
                  <Typography variant="body2" sx={{ mb: 1 }}>
                    {m.question}
                  </Typography>
                  <Typography variant="subtitle2">Antwort</Typography>
                  <Typography variant="body2" sx={{ whiteSpace: "pre-wrap" }}>
                    {m.answer}
                  </Typography>
                  {m.citations.length > 0 && (
                    <Stack direction="row" spacing={1} useFlexGap sx={{ mt: 1.5, flexWrap: "wrap" }}>
                      {m.citations.map((c, i) => {
                        const isDoc = !c.source_type || c.source_type === "document";
                        return (
                          <Chip
                            key={c.index ?? `${c.document_id}-${i}`}
                            size="small"
                            icon={isDoc ? <DescriptionIcon /> : <HandymanIcon />}
                            label={citationLabel(c)}
                            clickable={isDoc && !!c.document_id}
                            onClick={isDoc ? () => void openDocument(c) : undefined}
                          />
                        );
                      })}
                    </Stack>
                  )}
                </Box>
              ))}
            </Stack>
          )}
        </DialogContent>
      </Dialog>
    </Stack>
  );
}
