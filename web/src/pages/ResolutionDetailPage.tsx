import { useEffect, useState } from "react";
import { Link as RouterLink, useParams } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Chip,
  Link,
  Paper,
  Stack,
  Typography,
} from "@mui/material";
import { api, API_BASE_URL } from "@/api/client";
import {
  RESOLUTION_MODE_LABELS,
  RESOLUTION_STATUS_LABELS,
  VOTE_CHOICE_LABELS,
  type ResolutionDetailResponse,
  type ResolutionStatus,
  type VoteChoice,
} from "@/api/types";

function StatusChip({ status }: { status: ResolutionStatus }) {
  const color: "success" | "error" | "info" | "default" =
    status === "ANGENOMMEN"
      ? "success"
      : status === "ABGELEHNT"
        ? "error"
        : status === "OFFEN"
          ? "info"
          : "default";
  return (
    <Chip
      size="small"
      label={RESOLUTION_STATUS_LABELS[status]}
      color={color}
      variant={status === "ENTWURF" || status === "GESCHLOSSEN" ? "outlined" : "filled"}
    />
  );
}

function ChoiceButton({
  label,
  active,
  onClick,
  disabled,
  tone,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
  disabled: boolean;
  tone: "green" | "red" | "neutral";
}) {
  // Map our tone semantics to MUI colors; "neutral" → inherit means the
  // theme's default button colors (works in dark mode unlike hard-coded slate).
  const color: "success" | "error" | "inherit" =
    tone === "green" ? "success" : tone === "red" ? "error" : "inherit";
  return (
    <Button
      type="button"
      onClick={onClick}
      disabled={disabled}
      variant={active ? "contained" : "outlined"}
      color={color}
      size="large"
    >
      {label}
    </Button>
  );
}

function StatCard({
  label,
  value,
  color,
}: {
  label: string;
  value: string | number;
  color?: string;
}) {
  return (
    <Box>
      <Typography variant="caption" color="text.secondary">
        {label}
      </Typography>
      <Typography
        variant="h5"
        sx={{ fontWeight: 600, color: color ?? "inherit" }}
      >
        {value}
      </Typography>
    </Box>
  );
}

export function ResolutionDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [resolution, setResolution] = useState<ResolutionDetailResponse | null>(
    null,
  );
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [voting, setVoting] = useState(false);
  const [flash, setFlash] = useState<string | null>(null);

  const refresh = async () => {
    if (!id) return;
    try {
      const r = await api.get<ResolutionDetailResponse>(`/me/resolutions/${id}`);
      setResolution(r.data);
    } catch (err: unknown) {
      const httpStatus = (err as { response?: { status?: number } }).response
        ?.status;
      if (httpStatus === 404) setNotFound(true);
      else setError("Beschluss konnte nicht geladen werden.");
    }
  };

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh();
  }, [id]);

  const castVote = async (choice: VoteChoice) => {
    if (!id || voting) return;
    setVoting(true);
    setError(null);
    try {
      await api.post(`/me/resolutions/${id}/vote`, { choice });
      setFlash(`Ihre Stimme (${VOTE_CHOICE_LABELS[choice]}) wurde gespeichert.`);
      await refresh();
    } catch (err: unknown) {
      const httpStatus = (err as { response?: { status?: number } }).response
        ?.status;
      setError(
        httpStatus === 400
          ? "Abstimmung ist nicht (mehr) offen."
          : "Stimme konnte nicht gespeichert werden.",
      );
    } finally {
      setVoting(false);
    }
  };

  if (notFound) {
    return (
      <Stack spacing={2}>
        <Alert severity="error">
          Beschluss nicht gefunden oder nicht zugänglich.
        </Alert>
        <Link component={RouterLink} to="/resolutions" color="text.secondary">
          ← Zurück zur Übersicht
        </Link>
      </Stack>
    );
  }
  if (error && !resolution) return <Alert severity="error">{error}</Alert>;
  if (resolution === null) {
    return (
      <Typography variant="body2" color="text.secondary">
        Wird geladen…
      </Typography>
    );
  }

  const t = resolution.tally;
  const isOpen = resolution.status === "OFFEN";
  const myChoice = resolution.my_vote?.choice ?? null;

  return (
    <Stack spacing={3}>
      <Box>
        <Link
          component={RouterLink}
          to="/resolutions"
          color="text.secondary"
          underline="hover"
        >
          ← Beschlüsse
        </Link>
      </Box>

      <Box>
        <Typography variant="h4" component="h1" gutterBottom>
          {resolution.title}
        </Typography>
        <Stack
          direction="row"
          spacing={1}
          sx={{ alignItems: "center", flexWrap: "wrap", gap: 1 }}
        >
          <StatusChip status={resolution.status} />
          <Typography variant="caption" color="text.secondary">
            · {RESOLUTION_MODE_LABELS[resolution.mode]} · Frist{" "}
            {new Date(resolution.closes_at).toLocaleString("de-DE")}
          </Typography>
        </Stack>
      </Box>

      {flash && <Alert severity="success">{flash}</Alert>}
      {error && resolution && <Alert severity="error">{error}</Alert>}

      <Paper variant="outlined" sx={{ p: 2.5 }}>
        <Typography variant="h6" gutterBottom>
          Beschlusstext
        </Typography>
        <Typography variant="body2" sx={{ whiteSpace: "pre-wrap", lineHeight: 1.6 }}>
          {resolution.description}
        </Typography>
      </Paper>

      {resolution.am_eligible && isOpen && (
        <Paper variant="outlined" sx={{ p: 2.5 }}>
          <Typography variant="h6" gutterBottom>
            Ihre Stimme
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            {myChoice ? (
              <>
                Sie haben bereits mit{" "}
                <strong>{VOTE_CHOICE_LABELS[myChoice]}</strong> abgestimmt. Sie
                können Ihre Stimme bis zur Frist ändern.
              </>
            ) : (
              "Wählen Sie eine Option. Sie können Ihre Stimme bis zur Frist ändern."
            )}
          </Typography>
          <Stack direction="row" spacing={1.5} sx={{ flexWrap: "wrap", gap: 1.5 }}>
            <ChoiceButton
              label="JA"
              tone="green"
              active={myChoice === "JA"}
              disabled={voting}
              onClick={() => castVote("JA")}
            />
            <ChoiceButton
              label="NEIN"
              tone="red"
              active={myChoice === "NEIN"}
              disabled={voting}
              onClick={() => castVote("NEIN")}
            />
            <ChoiceButton
              label="Enthaltung"
              tone="neutral"
              active={myChoice === "ENTHALTUNG"}
              disabled={voting}
              onClick={() => castVote("ENTHALTUNG")}
            />
          </Stack>
        </Paper>
      )}

      {resolution.am_eligible && !isOpen && resolution.my_vote && (
        <Paper variant="outlined" sx={{ p: 2.5 }}>
          <Typography variant="h6" gutterBottom>
            Ihre abgegebene Stimme
          </Typography>
          <Typography variant="body2">
            <strong>{VOTE_CHOICE_LABELS[resolution.my_vote.choice]}</strong>{" "}
            <Typography component="span" variant="caption" color="text.secondary">
              · abgegeben{" "}
              {new Date(resolution.my_vote.voted_at).toLocaleString("de-DE")}
            </Typography>
          </Typography>
        </Paper>
      )}

      <Paper variant="outlined" sx={{ p: 2.5 }}>
        <Typography variant="h6" gutterBottom>
          Stand der Abstimmung
        </Typography>
        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: { xs: "1fr 1fr", sm: "repeat(3, 1fr)" },
            gap: 2,
          }}
        >
          <StatCard label="Stimmberechtigt" value={t.eligible_voters} />
          <StatCard label="Abgegeben" value={t.cast} />
          {resolution.mode === "MEHRHEITS" && (
            <StatCard
              label="Erforderliches Quorum"
              value={resolution.required_quorum}
            />
          )}
        </Box>
        {resolution.status !== "OFFEN" && (
          <Box
            sx={{
              display: "grid",
              gridTemplateColumns: "repeat(3, 1fr)",
              gap: 2,
              mt: 2,
            }}
          >
            <StatCard label="JA" value={t.ja} color="success.main" />
            <StatCard label="NEIN" value={t.nein} color="error.main" />
            <StatCard label="Enthaltung" value={t.enthaltung} />
          </Box>
        )}
        {resolution.result && (
          <Typography variant="body2" sx={{ mt: 2 }}>
            <strong>Ergebnis:</strong> {resolution.result}
          </Typography>
        )}
        {resolution.result_pdf_url && (
          <Box sx={{ mt: 1.5 }}>
            <Link
              href={`${API_BASE_URL}/me/resolutions/${resolution.id}/result.pdf`}
              target="_blank"
              rel="noopener noreferrer"
              underline="hover"
            >
              Protokoll-PDF herunterladen
            </Link>
          </Box>
        )}
      </Paper>
    </Stack>
  );
}
