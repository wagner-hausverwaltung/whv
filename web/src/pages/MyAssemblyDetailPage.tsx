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
import {
  AGENDA_ITEM_TYPE_LABELS,
  ASSEMBLY_STATUS_LABELS,
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
    </Stack>
  );
}

function AgendaCard({ item }: { item: AgendaItemResponse }) {
  const total = item.vote_yes + item.vote_no + item.vote_abstain;
  return (
    <Paper variant="outlined" sx={{ p: 2.5 }}>
      <Stack spacing={1.5}>
        <Stack direction="row" spacing={1} sx={{ alignItems: "center", flexWrap: "wrap" }}>
          <Chip
            size="small"
            label={`TOP ${item.position}`}
            variant="outlined"
          />
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
        <Typography variant="h6" component="h3">
          {item.title}
        </Typography>
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
        {item.type === "BESCHLUSS" && total > 0 && (
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
              Abstimmungsergebnis ({total} Stimmen)
            </Typography>
            <Stack direction="row" spacing={2}>
              <VoteCell label="Ja" value={item.vote_yes} color="success.main" />
              <VoteCell label="Nein" value={item.vote_no} color="error.main" />
              <VoteCell
                label="Enthaltung"
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
