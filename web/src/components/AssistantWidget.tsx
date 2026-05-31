import { useEffect, useRef, useState } from "react";
import {
  Alert,
  Box,
  Chip,
  CircularProgress,
  Fab,
  Grow,
  IconButton,
  Paper,
  Stack,
  TextField,
  Typography,
  Zoom,
} from "@mui/material";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import ChatBubbleOutlineRoundedIcon from "@mui/icons-material/ChatBubbleOutlineRounded";
import CloseIcon from "@mui/icons-material/Close";
import DescriptionIcon from "@mui/icons-material/Description";
import HandymanIcon from "@mui/icons-material/Handyman";
import SendIcon from "@mui/icons-material/Send";
import { AxiosError } from "axios";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { getRememberedPropertyId } from "@/lib/activeProperty";

// Mirrors the backend AssistantQueryResponse (POST /assistant/query, ADR-0013).
interface Citation {
  // The [index] the answer cited — shown on the chip so the inline [n] maps to it.
  index: number;
  document_id: string;
  page: number | null;
  source_kind: string | null;
  contact_name: string | null;
  // "document" → open via download; "dienstleister"/… → a master-data card we
  // deep-link to the entity (contact_id + property_id locate it). ADR-0013 §4.
  source_type: string;
  contact_id: string | null;
  property_id: string | null;
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

function isMasterData(source: Citation): boolean {
  return source.source_type !== "document";
}

function citationLabel(source: Citation): string {
  if (isMasterData(source)) {
    // A Dienstleister/contact card — name it, no page number.
    return `Dienstleister: ${source.contact_name ?? "?"}`;
  }
  const parts = [source.source_kind, source.contact_name].filter(Boolean);
  const base = parts.length > 0 ? parts.join(" · ") : "Dokument";
  return source.page != null ? `${base} · S.${source.page}` : base;
}

/**
 * Floating RAG assistant — a docked chat launcher mounted once in both the
 * portal (Layout) and the admin shell (AdminLayout), so it's reachable from
 * every page. Collapsed it's a bottom-right FAB; expanded it's a ~30%-width
 * panel anchored bottom-right (full-screen on mobile). Replaces the former
 * /assistant tab.
 *
 * The backend resolves the caller's ACL scope from the JWT, so the same
 * component is safe for every role. Citations open the document via the
 * auth-gated download endpoint (which re-checks access), so a leaked citation
 * still can't be opened by someone without access.
 */
export function AssistantWidget() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const navigate = useNavigate();
  // One id per widget mount → groups this chat session's turns into a thread
  // in the admin overview.
  const conversationIdRef = useRef(crypto.randomUUID());
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  // Keep the latest message in view as the conversation grows.
  useEffect(() => {
    if (open && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, loading, open]);

  // Focus the composer when the panel opens (after the Grow transition starts).
  useEffect(() => {
    if (!open) return;
    const id = window.setTimeout(() => inputRef.current?.focus(), 60);
    return () => window.clearTimeout(id);
  }, [open]);

  // Pre-auth pages have no JWT, so there's nothing to ask about — don't mount.
  if (!user) return null;

  const submit = async () => {
    const question = input.trim();
    if (!question || loading) return;
    setError(null);
    // `messages` here is the conversation BEFORE this new question (the state
    // update below is async), so it's exactly the history to replay. Cap to
    // the last few turns to bound the request.
    const history = messages.slice(-8).map((m) => ({ role: m.role, content: m.text }));
    // Scope the search to the property selected in the AppBar switcher (if any),
    // so a question only looks in that property's documents.
    const property_id = getRememberedPropertyId();
    setMessages((prev) => [...prev, { id: crypto.randomUUID(), role: "user", text: question }]);
    setInput("");
    setLoading(true);
    try {
      const res = await api.post<AssistantResponse>("/assistant/query", {
        question,
        history,
        property_id,
        conversation_id: conversationIdRef.current,
      });
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

  const openCitation = (source: Citation) => {
    if (isMasterData(source)) {
      // Master-data card → deep-link to the entity on its property (there's no
      // PDF to download; its document_id is synthetic). Route by card type so
      // an ETV card lands on Versammlungen, not the vendor list. Close the
      // panel so the destination isn't hidden behind it.
      if (!source.property_id) return;
      setOpen(false);
      const pid = source.property_id;
      if (source.source_type === "etv") {
        navigate(`/properties/${pid}/assemblies`);
      } else if (source.source_type === "dienstleister") {
        navigate(`/properties/${pid}/vendors`);
      } else {
        navigate(`/properties/${pid}/details`);
      }
      return;
    }
    void openDocument(source.document_id);
  };

  return (
    // no-print: the launcher/panel must never appear on printed documents (§9.3).
    <Box className="no-print">
      <Zoom in={!open} unmountOnExit>
        <Fab
          color="primary"
          aria-label={t("assistant.open")}
          onClick={() => setOpen(true)}
          sx={{
            position: "fixed",
            bottom: { xs: 16, sm: 24 },
            right: { xs: 16, sm: 24 },
            zIndex: (theme) => theme.zIndex.fab,
          }}
        >
          <ChatBubbleOutlineRoundedIcon />
        </Fab>
      </Zoom>

      <Grow in={open} unmountOnExit style={{ transformOrigin: "bottom right" }}>
        <Paper
          elevation={8}
          sx={{
            position: "fixed",
            bottom: { xs: 0, sm: 24 },
            right: { xs: 0, sm: 24 },
            width: { xs: "100vw", sm: "30vw" },
            minWidth: { sm: 360 },
            maxWidth: { sm: 560 },
            height: { xs: "100dvh", sm: "min(72vh, 660px)" },
            maxHeight: { xs: "100dvh", sm: "calc(100vh - 48px)" },
            display: "flex",
            flexDirection: "column",
            borderRadius: { xs: 0, sm: 3 },
            overflow: "hidden",
            zIndex: (theme) => theme.zIndex.fab,
          }}
        >
          {/* Header */}
          <Stack
            direction="row"
            spacing={1}
            sx={{
              alignItems: "center",
              px: 2,
              py: 1.5,
              borderBottom: 1,
              borderColor: "divider",
            }}
          >
            <AutoAwesomeIcon color="primary" fontSize="small" />
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 700, lineHeight: 1.2 }} noWrap>
                {t("assistant.title")}
              </Typography>
              <Typography variant="caption" color="text.secondary" noWrap sx={{ display: "block" }}>
                {t("assistant.subtitle")}
              </Typography>
            </Box>
            <IconButton size="small" onClick={() => setOpen(false)} aria-label={t("assistant.close")}>
              <CloseIcon fontSize="small" />
            </IconButton>
          </Stack>

          {/* Conversation (scrolls) */}
          <Box ref={scrollRef} sx={{ flex: 1, overflowY: "auto", p: 2 }}>
            <Stack spacing={1.5}>
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
                    p: 1.5,
                    alignSelf: message.role === "user" ? "flex-end" : "flex-start",
                    maxWidth: "90%",
                    bgcolor: message.role === "user" ? "action.hover" : "background.paper",
                  }}
                >
                  <Typography variant="caption" color="text.secondary">
                    {message.role === "user" ? t("assistant.you") : t("assistant.assistant")}
                  </Typography>
                  <Typography variant="body2" sx={{ whiteSpace: "pre-wrap" }}>
                    {message.text}
                  </Typography>
                  {message.sources && message.sources.length > 0 && (
                    <Stack direction="row" spacing={1} useFlexGap sx={{ mt: 1.5, flexWrap: "wrap" }}>
                      {message.sources.map((source) => (
                        <Chip
                          key={source.index}
                          size="small"
                          icon={isMasterData(source) ? <HandymanIcon /> : <DescriptionIcon />}
                          clickable
                          onClick={() => openCitation(source)}
                          label={`[${source.index}] ${citationLabel(source)}`}
                        />
                      ))}
                    </Stack>
                  )}
                </Paper>
              ))}
              {loading && (
                <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
                  <CircularProgress size={16} />
                  <Typography variant="body2" color="text.secondary">
                    {t("assistant.thinking")}
                  </Typography>
                </Stack>
              )}
            </Stack>
          </Box>

          {/* Composer */}
          <Box sx={{ p: 1.5, borderTop: 1, borderColor: "divider" }}>
            {error && (
              <Alert severity="warning" sx={{ mb: 1 }} onClose={() => setError(null)}>
                {error}
              </Alert>
            )}
            <Stack direction="row" spacing={1} sx={{ alignItems: "flex-end" }}>
              <TextField
                fullWidth
                multiline
                maxRows={4}
                size="small"
                inputRef={inputRef}
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
              <IconButton
                color="primary"
                onClick={() => void submit()}
                disabled={loading || input.trim().length === 0}
                aria-label={t("assistant.send")}
                sx={{ mb: 0.25 }}
              >
                <SendIcon />
              </IconButton>
            </Stack>
            <Typography
              variant="caption"
              color="text.secondary"
              sx={{ mt: 0.75, display: "block" }}
            >
              {t("assistant.disclaimer")}
            </Typography>
          </Box>
        </Paper>
      </Grow>
    </Box>
  );
}
