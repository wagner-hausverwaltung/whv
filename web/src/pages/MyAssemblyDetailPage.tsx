/**
 * Portal detail of a single Eigentümerversammlung.
 *
 * Layout mirrors the iOS AssemblyDetailView: header card (status +
 * datetime + location), free-text description, Tagesordnung with per-
 * TOP type chip + Beschluss tally + Diskussion log, signed-protocol
 * PDF download.
 *
 * Protocol download uses fetch+blob+createObjectURL so the JWT in the
 * Authorization header is actually sent. A plain `<a href>` would
 * fail auth (the backend's FileResponse endpoint runs an owner-scope
 * check on every fetch).
 */

import { useCallback, useEffect, useState } from "react";
import { Link as RouterLink, useParams } from "react-router-dom";
import {
  Alert,
  Box,
  Breadcrumbs,
  Button,
  Chip,
  Link as MuiLink,
  Paper,
  Stack,
  Typography,
} from "@mui/material";
import CalendarIcon from "@mui/icons-material/CalendarMonthOutlined";
import DownloadIcon from "@mui/icons-material/DownloadOutlined";
import HomeWorkIcon from "@mui/icons-material/HomeWorkOutlined";
import LocationIcon from "@mui/icons-material/LocationOnOutlined";
import PictureAsPdfIcon from "@mui/icons-material/PictureAsPdfOutlined";
import VideocamIcon from "@mui/icons-material/Videocam";
import { api } from "@/api/client";
import { AssemblyComments } from "@/pages/AssemblyComments";
import {
  AGENDA_ITEM_TYPE_LABELS,
  VOTING_BASIS_LABELS,
  ASSEMBLY_STATUS_LABELS,
  type AgendaItemAttachmentResponse,
  type AgendaItemResponse,
  type AgendaItemType,
  type AssemblyDetailResponse,
  type AssemblyStatus,
} from "@/api/types";

const STATUS_COLOR: Record<
  AssemblyStatus,
  "default" | "primary" | "success" | "error"
> = {
  GEPLANT: "default",
  EINGELADEN: "primary",
  ABGEHALTEN: "success",
  ABGESAGT: "error",
};

const TYPE_COLOR: Record<AgendaItemType, "default" | "primary" | "warning"> = {
  INFORMATION: "default",
  BESCHLUSS: "primary",
  DISKUSSION: "warning",
};

function formatLongDateRange(startIso: string, endIso: string): string {
  const start = new Date(startIso);
  const end = new Date(endIso);
  const sameDay =
    start.getFullYear() === end.getFullYear() &&
    start.getMonth() === end.getMonth() &&
    start.getDate() === end.getDate();
  const date = new Intl.DateTimeFormat("de-DE", {
    weekday: "long",
    day: "2-digit",
    month: "long",
    year: "numeric",
  });
  const time = new Intl.DateTimeFormat("de-DE", {
    hour: "2-digit",
    minute: "2-digit",
  });
  if (sameDay) {
    return `${date.format(start)}, ${time.format(start)}–${time.format(end)} Uhr`;
  }
  return `${date.format(start)} – ${date.format(end)}`;
}

export function MyAssemblyDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [a, setAssembly] = useState<AssemblyDetailResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);

  const load = useCallback(async () => {
    if (!id) return;
    setError(null);
    try {
      const r = await api.get<AssemblyDetailResponse>(
        `/me/assemblies/${id}`,
      );
      setAssembly(r.data);
    } catch {
      setError("Versammlung konnte nicht geladen werden.");
    }
  }, [id]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const downloadPdf = async (
    kind: "protocol" | "invitation",
  ): Promise<void> => {
    if (!a) return;
    setDownloading(true);
    setError(null);
    try {
      const r = await api.get(`/me/assemblies/${a.id}/${kind}`, {
        responseType: "blob",
      });
      const url = URL.createObjectURL(r.data as Blob);
      const link = document.createElement("a");
      link.href = url;
      const stem = kind === "protocol" ? "protokoll" : "einladung";
      link.download = `${stem}-${a.id}.pdf`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch {
      setError(
        kind === "protocol"
          ? "Protokoll-Download fehlgeschlagen."
          : "Einladung-Download fehlgeschlagen.",
      );
    } finally {
      setDownloading(false);
    }
  };

  if (error && !a) {
    return (
      <Stack spacing={2}>
        <MuiLink component={RouterLink} to="/" color="text.secondary">
          ← Zurück
        </MuiLink>
        <Alert severity="error">{error}</Alert>
      </Stack>
    );
  }
  if (!a) {
    return (
      <Typography variant="body2" color="text.secondary">
        Wird geladen…
      </Typography>
    );
  }

  const sortedAgenda = [...a.agenda_items].sort(
    (x, y) => x.position - y.position,
  );

  return (
    <Stack spacing={3}>
      <Breadcrumbs>
        <MuiLink component={RouterLink} to="/" color="text.secondary">
          Liegenschaften
        </MuiLink>
        <MuiLink
          component={RouterLink}
          to={`/properties/${a.property_id}`}
          color="text.secondary"
        >
          Liegenschaft
        </MuiLink>
        <MuiLink
          component={RouterLink}
          to={`/properties/${a.property_id}/assemblies`}
          color="text.secondary"
        >
          Versammlungen
        </MuiLink>
        <Typography color="text.primary">Detail</Typography>
      </Breadcrumbs>

      {error && <Alert severity="error">{error}</Alert>}

      {/* Teams join CTA — pinned above the header so it's the first
          actionable affordance the owner sees. Microsoft Teams brand
          purple (#4B53BC), camera glyph, opens in a new tab. */}
      {a.teams_meeting_url && (
        <Button
          variant="contained"
          size="large"
          startIcon={<VideocamIcon />}
          component="a"
          href={a.teams_meeting_url}
          target="_blank"
          rel="noopener noreferrer"
          sx={{
            bgcolor: "#4B53BC",
            color: "#fff",
            fontWeight: 600,
            py: 1.5,
            "&:hover": { bgcolor: "#3D44A6" },
          }}
        >
          Teams-Meeting beitreten
        </Button>
      )}

      {/* Header card */}
      <Paper variant="outlined" sx={{ p: 3 }}>
        <Stack spacing={1.5}>
          <Stack direction="row" spacing={1} sx={{ alignItems: "center", flexWrap: "wrap" }}>
            <Chip
              size="small"
              label={ASSEMBLY_STATUS_LABELS[a.status]}
              color={STATUS_COLOR[a.status]}
            />
            {a.protocol_pdf_url && (
              <Chip
                size="small"
                icon={<PictureAsPdfIcon />}
                variant="outlined"
                color="success"
                label="Protokoll vorhanden"
              />
            )}
          </Stack>
          <Typography variant="h4" component="h1">
            {a.title}
          </Typography>
          <Stack spacing={0.5} sx={{ mt: 1 }}>
            {a.property_name && (
              <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
                <HomeWorkIcon
                  fontSize="small"
                  sx={{ color: "text.secondary" }}
                />
                <Typography
                  variant="body2"
                  color="text.secondary"
                  sx={{ fontWeight: 500 }}
                >
                  {a.property_name}
                  {a.property_hr_id && (
                    <Typography
                      component="span"
                      variant="caption"
                      color="text.disabled"
                      sx={{
                        ml: 1,
                        fontFamily: "ui-monospace, Menlo, monospace",
                      }}
                    >
                      {a.property_hr_id}
                    </Typography>
                  )}
                </Typography>
              </Stack>
            )}
            <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
              <CalendarIcon
                fontSize="small"
                sx={{ color: "text.secondary" }}
              />
              <Typography variant="body2" color="text.secondary">
                {formatLongDateRange(a.scheduled_start, a.scheduled_end)}
              </Typography>
            </Stack>
            <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
              <LocationIcon
                fontSize="small"
                sx={{ color: "text.secondary" }}
              />
              <Typography variant="body2" color="text.secondary">
                {a.location}
              </Typography>
            </Stack>
          </Stack>
        </Stack>
      </Paper>

      {a.description && (
        <Typography
          variant="body1"
          sx={{ whiteSpace: "pre-wrap", color: "text.primary" }}
        >
          {a.description}
        </Typography>
      )}

      {/* Agenda */}
      <Box>
        <Typography variant="h5" component="h2" sx={{ mb: 2 }}>
          Tagesordnung
        </Typography>
        {sortedAgenda.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            Die Tagesordnung wird vom Verwalter ergänzt.
          </Typography>
        ) : (
          <Stack spacing={2}>
            {sortedAgenda.map((item) => (
              <AgendaCard key={item.id} item={item} />
            ))}
          </Stack>
        )}
      </Box>

      {/* Invitation — pre-meeting PDF the Verwalter uploaded */}
      {a.invitation_pdf_url && (
        <Box>
          <Typography variant="h5" component="h2" sx={{ mb: 2 }}>
            Einladung
          </Typography>
          <Paper variant="outlined" sx={{ p: 2 }}>
            <Stack
              direction={{ xs: "column", sm: "row" }}
              spacing={2}
              sx={{
                alignItems: { sm: "center" },
                justifyContent: "space-between",
              }}
            >
              <Stack
                direction="row"
                spacing={1.5}
                sx={{ alignItems: "center" }}
              >
                <PictureAsPdfIcon color="primary" />
                <Box>
                  <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                    Einladung als PDF
                  </Typography>
                  {a.invitation_uploaded_at && (
                    <Typography variant="caption" color="text.secondary">
                      Hochgeladen am{" "}
                      {new Date(a.invitation_uploaded_at).toLocaleDateString(
                        "de-DE",
                      )}
                    </Typography>
                  )}
                </Box>
              </Stack>
              <Button
                variant="outlined"
                startIcon={<DownloadIcon />}
                onClick={() => downloadPdf("invitation")}
                disabled={downloading}
              >
                {downloading ? "Wird geladen…" : "Herunterladen"}
              </Button>
            </Stack>
          </Paper>
        </Box>
      )}

      {/* Protocol */}
      <Box>
        <Typography variant="h5" component="h2" sx={{ mb: 2 }}>
          Signiertes Protokoll
        </Typography>
        {a.protocol_pdf_url ? (
          <Paper variant="outlined" sx={{ p: 2 }}>
            <Stack
              direction={{ xs: "column", sm: "row" }}
              spacing={2}
              sx={{ alignItems: { sm: "center" }, justifyContent: "space-between" }}
            >
              <Stack
                direction="row"
                spacing={1.5}
                sx={{ alignItems: "center" }}
              >
                <PictureAsPdfIcon color="primary" />
                <Box>
                  <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                    Protokoll als PDF
                  </Typography>
                  {a.protocol_uploaded_at && (
                    <Typography variant="caption" color="text.secondary">
                      Hochgeladen am{" "}
                      {new Date(a.protocol_uploaded_at).toLocaleDateString(
                        "de-DE",
                      )}
                    </Typography>
                  )}
                </Box>
              </Stack>
              <Button
                variant="contained"
                startIcon={<DownloadIcon />}
                onClick={() => downloadPdf("protocol")}
                disabled={downloading}
              >
                {downloading ? "Wird geladen…" : "Herunterladen"}
              </Button>
            </Stack>
          </Paper>
        ) : (
          <Typography variant="body2" color="text.secondary">
            Das Protokoll wird in der Regel innerhalb von vier Wochen nach
            der Versammlung hochgeladen.
          </Typography>
        )}
      </Box>

      {/* Q&A — post-publication conversation, separate from the
          in-meeting Diskussion captured per-TOP above. */}
      <AssemblyComments assemblyId={a.id} />
    </Stack>
  );
}

function AgendaCard({ item }: { item: AgendaItemResponse }) {
  const total = item.vote_yes + item.vote_no + item.vote_abstain;
  // Show the tally block when *any* vote-related field has data,
  // not just when sum > 0. A protocol can record voting_basis +
  // present_count + a result without the model returning per-vote
  // counts (some Verwalter protocols print "einstimmig angenommen"
  // without enumerating the tally).
  const hasVoteInfo =
    total > 0 ||
    item.vote_result !== null ||
    item.voting_basis !== null ||
    item.present_count !== null;
  return (
    <Paper variant="outlined" sx={{ p: 2.5 }}>
      <Stack spacing={1.5}>
        <Typography variant="h6" component="h3">
          {item.title}
        </Typography>
        {/* Type + result chips sit UNDER the heading — the title
            itself carries the TOP number, so a separate position
            chip is redundant. */}
        <Stack direction="row" spacing={1} sx={{ alignItems: "center", flexWrap: "wrap" }}>
          <Chip
            size="small"
            label={AGENDA_ITEM_TYPE_LABELS[item.type]}
            color={TYPE_COLOR[item.type]}
            variant={item.type === "BESCHLUSS" ? "filled" : "outlined"}
          />
          {item.vote_result && (
            <Chip
              size="small"
              label={item.vote_result === "ANGENOMMEN" ? "Angenommen" : "Abgelehnt"}
              color={item.vote_result === "ANGENOMMEN" ? "success" : "error"}
            />
          )}
        </Stack>
        {item.body && (
          <Typography
            variant="body2"
            color="text.secondary"
            sx={{ whiteSpace: "pre-wrap" }}
          >
            {item.body}
          </Typography>
        )}
        {item.beschluss_text && (
          <Box
            sx={{
              p: 1.5,
              bgcolor: "action.hover",
              borderLeft: 3,
              borderLeftColor: "primary.main",
            }}
          >
            <Typography
              variant="caption"
              color="text.secondary"
              sx={{ textTransform: "uppercase", letterSpacing: 0.5 }}
            >
              Beschlusstext
            </Typography>
            <Typography
              variant="body2"
              sx={{ whiteSpace: "pre-wrap", mt: 0.5 }}
            >
              {item.beschluss_text}
            </Typography>
          </Box>
        )}
        {item.attachments.length > 0 && (
          <AgendaItemAttachmentsBlock
            agendaItemId={item.id}
            attachments={item.attachments}
          />
        )}
        {item.type === "BESCHLUSS" && hasVoteInfo && (
          <Box>
            <Typography
              variant="caption"
              color="text.secondary"
              sx={{
                textTransform: "uppercase",
                letterSpacing: 0.5,
                display: "block",
                mb: 0.5,
              }}
            >
              Abstimmungsergebnis
            </Typography>
            {(item.voting_basis !== null || item.present_count !== null) && (
              <Stack
                direction="row"
                spacing={2}
                sx={{ mb: 1, flexWrap: "wrap", rowGap: 0.5 }}
              >
                {item.voting_basis !== null && (
                  <Box>
                    <Typography variant="caption" color="text.secondary">
                      Stimmrecht
                    </Typography>
                    <Typography variant="body2" sx={{ fontWeight: 500 }}>
                      {VOTING_BASIS_LABELS[item.voting_basis]}
                    </Typography>
                  </Box>
                )}
                {item.present_count !== null && (
                  <Box>
                    <Typography variant="caption" color="text.secondary">
                      Anwesend
                    </Typography>
                    <Typography variant="body2" sx={{ fontWeight: 500 }}>
                      {item.present_count}
                    </Typography>
                  </Box>
                )}
              </Stack>
            )}
            <Stack direction="row" spacing={2}>
              <VoteCell label="Ja" value={item.vote_yes} color="success.main" />
              <VoteCell label="Nein" value={item.vote_no} color="error.main" />
              <VoteCell
                label="Enthaltungen"
                value={item.vote_abstain}
                color="text.secondary"
              />
              {item.vote_required_quorum !== null && (
                <Box sx={{ ml: "auto" }}>
                  <Typography variant="caption" color="text.secondary">
                    Quorum: {item.vote_required_quorum}
                  </Typography>
                </Box>
              )}
            </Stack>
          </Box>
        )}
        {item.discussion.length > 0 && (
          <Box>
            <Typography
              variant="caption"
              color="text.secondary"
              sx={{
                textTransform: "uppercase",
                letterSpacing: 0.5,
                display: "block",
                mb: 1,
              }}
            >
              Diskussion
            </Typography>
            <Stack spacing={1}>
              {item.discussion
                .slice()
                .sort((x, y) => x.position - y.position)
                .map((d) => (
                  <Box
                    key={d.id}
                    sx={{
                      p: 1.5,
                      borderRadius: 1,
                      bgcolor: "background.default",
                      border: "1px dashed",
                      borderColor: "divider",
                    }}
                  >
                    <Typography
                      variant="caption"
                      color="text.secondary"
                      sx={{ fontWeight: 500 }}
                    >
                      {d.speaker_label}
                    </Typography>
                    <Typography
                      variant="body2"
                      sx={{ whiteSpace: "pre-wrap" }}
                    >
                      {d.content}
                    </Typography>
                  </Box>
                ))}
            </Stack>
          </Box>
        )}
      </Stack>
    </Paper>
  );
}

function VoteCell({
  label,
  value,
  color,
}: {
  label: string;
  value: number;
  color: string;
}) {
  return (
    <Box>
      <Typography variant="caption" color="text.secondary">
        {label}
      </Typography>
      <Typography variant="h6" sx={{ color, lineHeight: 1.1 }}>
        {value}
      </Typography>
    </Box>
  );
}

/// Per-TOP attachment chips. Each chip opens the file in a new tab
/// — for PDFs that lands in the browser's built-in viewer (= preview);
/// for non-PDF types it falls back to download. We deliberately don't
/// build an in-modal previewer here: native browser tabs already do
/// the right thing for the only file kinds that matter in practice.
function AgendaItemAttachmentsBlock({
  agendaItemId,
  attachments,
}: {
  agendaItemId: string;
  attachments: AgendaItemAttachmentResponse[];
}) {
  const [busyId, setBusyId] = useState<string | null>(null);

  const openAttachment = async (att: AgendaItemAttachmentResponse) => {
    setBusyId(att.id);
    try {
      const r = await api.get(
        `/me/agenda-items/${agendaItemId}/attachments/${att.id}/download`,
        { responseType: "blob" },
      );
      const blob = new Blob([r.data as Blob], {
        // The backend sends the right mime type but axios already
        // unpacks it; re-stamp from the row metadata so PDFs render
        // inline and other types still download.
        type: att.mime_type ?? "application/octet-stream",
      });
      const url = URL.createObjectURL(blob);
      const win = window.open(url, "_blank");
      // Some pop-up blockers cancel window.open — fall back to
      // a click-driven anchor so the user can still grab the file.
      if (win == null) {
        const link = document.createElement("a");
        link.href = url;
        link.download = att.filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
      }
      // Revoke after a delay so the new tab can finish parsing the
      // blob — immediate revoke breaks Firefox's PDF viewer.
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch {
      // Surface failures in the chip itself rather than the global
      // error alert — one bad attachment shouldn't blank the page.
    } finally {
      setBusyId(null);
    }
  };

  return (
    <Box>
      <Typography
        variant="caption"
        color="text.secondary"
        sx={{
          textTransform: "uppercase",
          letterSpacing: 0.5,
          display: "block",
          mb: 1,
        }}
      >
        Anhänge
      </Typography>
      <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", gap: 1 }}>
        {attachments.map((att) => (
          <Chip
            key={att.id}
            icon={<PictureAsPdfIcon />}
            label={`${att.filename}${
              att.size_bytes ? ` · ${formatBytes(att.size_bytes)}` : ""
            }`}
            variant="outlined"
            clickable
            disabled={busyId === att.id}
            onClick={() => void openAttachment(att)}
          />
        ))}
      </Stack>
    </Box>
  );
}

function formatBytes(b: number): string {
  if (b < 1024) return `${b} B`;
  if (b < 1024 * 1024) return `${Math.round(b / 1024)} KB`;
  return `${(b / (1024 * 1024)).toFixed(1)} MB`;
}
