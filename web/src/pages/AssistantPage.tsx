import { useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import DescriptionIcon from "@mui/icons-material/Description";
import SendIcon from "@mui/icons-material/Send";
import { AxiosError } from "axios";
import { useTranslation } from "react-i18next";
import { api } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";

// Mirrors the backend AssistantQueryResponse (POST /assistant/query, ADR-0013).
interface Citation {
  document_id: string;
  page: number | null;
  source_kind: string | null;
  contact_name: string | null;
}

interface AssistantResponse {
  answer: string;
  abstained: boolean;
  sources: Citation[];
}

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  sources?: Citation[];
}

function citationLabel(source: Citation): string {
  const parts = [source.source_kind, source.contact_name].filter(Boolean);
  const base = parts.length > 0 ? parts.join(" · ") : "Dokument";
  return source.page != null ? `${base} · S.${source.page}` : base;
}

/**
 * Shared RAG assistant chat — mounted in both the portal (/assistant) and the
 * admin SPA (/admin/assistant). The backend resolves the caller's ACL scope,
 * so the same component is safe for every role. Citations open the document
 * via the auth-gated download endpoint (which re-checks access), so a leaked
 * citation still can't be opened by someone without access.
 */
export function AssistantPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    const question = input.trim();
    if (!question || loading) return;
    setError(null);
    setMessages((prev) => [...prev, { id: crypto.randomUUID(), role: "user", text: question }]);
    setInput("");
    setLoading(true);
    try {
      const res = await api.post<AssistantResponse>("/assistant/query", { question });
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          text: res.data.answer,
          sources: res.data.sources,
        },
      ]);
    } catch (err) {
      const statusCode = (err as AxiosError).response?.status;
      setError(statusCode === 503 ? t("assistant.unavailable") : t("assistant.error"));
    } finally {
      setLoading(false);
    }
  };

  const openDocument = async (documentId: string) => {
    // Verwalter download is org-wide (/admin); everyone else goes through the
    // owner/tenant-scoped /me endpoint. Both re-check access server-side.
    const base = user?.role === "verwalter" ? "/admin/documents" : "/me/documents";
    try {
      const res = await api.get<Blob>(`${base}/${documentId}/file`, { responseType: "blob" });
      const objectUrl = URL.createObjectURL(res.data);
      window.open(objectUrl, "_blank", "noopener");
      setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
    } catch {
      setError(t("assistant.documentError"));
    }
  };

  return (
    <Box>
      <Typography variant="h4" sx={{ fontWeight: 700 }}>
        {t("assistant.title")}
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 3 }}>
        {t("assistant.subtitle")}
      </Typography>

      <Stack spacing={2} sx={{ mb: 3 }}>
        {messages.length === 0 && !loading && (
          <Alert severity="info" variant="outlined">
            {t("assistant.empty")}
          </Alert>
        )}
        {messages.map((message) => (
          <Paper
            key={message.id}
            variant="outlined"
            sx={{
              p: 2,
              alignSelf: message.role === "user" ? "flex-end" : "flex-start",
              maxWidth: "85%",
              bgcolor: message.role === "user" ? "action.hover" : "background.paper",
            }}
          >
            <Typography variant="caption" color="text.secondary">
              {message.role === "user" ? t("assistant.you") : t("assistant.assistant")}
            </Typography>
            <Typography sx={{ whiteSpace: "pre-wrap" }}>{message.text}</Typography>
            {message.sources && message.sources.length > 0 && (
              <Stack direction="row" spacing={1} useFlexGap sx={{ mt: 1.5, flexWrap: "wrap" }}>
                {message.sources.map((source) => (
                  <Chip
                    key={source.document_id}
                    size="small"
                    icon={<DescriptionIcon />}
                    clickable
                    onClick={() => void openDocument(source.document_id)}
                    label={citationLabel(source)}
                  />
                ))}
              </Stack>
            )}
          </Paper>
        ))}
        {loading && (
          <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
            <CircularProgress size={18} />
            <Typography color="text.secondary">{t("assistant.thinking")}</Typography>
          </Stack>
        )}
      </Stack>

      {error && (
        <Alert severity="warning" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      <Stack direction="row" spacing={1} sx={{ alignItems: "flex-end" }}>
        <TextField
          fullWidth
          multiline
          maxRows={4}
          value={input}
          placeholder={t("assistant.placeholder")}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void submit();
            }
          }}
          disabled={loading}
        />
        <Button
          variant="contained"
          onClick={() => void submit()}
          disabled={loading || input.trim().length === 0}
          endIcon={<SendIcon />}
          sx={{ flexShrink: 0 }}
        >
          {t("assistant.send")}
        </Button>
      </Stack>
      <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: "block" }}>
        {t("assistant.disclaimer")}
      </Typography>
    </Box>
  );
}
