/**
 * Public Umlaufbeschluss voting page — /abstimmung/:token
 *
 * No login. The token (from the invitation email) is the only
 * credential; it maps to one owner's ballot on one resolution. Owners
 * without a portal account vote here. One-shot: once cast (here or in
 * the portal) the page shows "bereits abgestimmt".
 */

import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { Alert, Box, Button, Paper, Stack, Typography } from "@mui/material";
import { api } from "@/api/client";
import { AuthShell } from "@/components/AuthShell";
import type { BallotView } from "@/api/types";

type Choice = "JA" | "NEIN" | "ENTHALTUNG";

const CHOICES: { value: Choice; label: string; color: "success" | "error" | "inherit" }[] = [
  { value: "JA", label: "Ja", color: "success" },
  { value: "NEIN", label: "Nein", color: "error" },
  { value: "ENTHALTUNG", label: "Enthaltung", color: "inherit" },
];

function formatDeadline(raw: string): string {
  const d = new Date(raw);
  return Number.isNaN(d.getTime())
    ? raw
    : d.toLocaleString("de-DE", { dateStyle: "long", timeStyle: "short" });
}

// Combined state keyed by token so setState only happens in async
// resolution (no synchronous setState in the effect).
type LoadState = { token: string; ballot: BallotView | null; notFound: boolean };

export function PublicVotePage() {
  const { token } = useParams<{ token: string }>();
  const [state, setState] = useState<LoadState | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [justVoted, setJustVoted] = useState(false);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    api
      .get<BallotView>(`/public/resolutions/ballot/${token}`)
      .then((r) => {
        if (!cancelled) setState({ token, ballot: r.data, notFound: false });
      })
      .catch(() => {
        if (!cancelled) setState({ token, ballot: null, notFound: true });
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  const ready = state !== null && state.token === token;

  const vote = async (choice: Choice) => {
    if (!token) return;
    setSubmitting(true);
    setError(null);
    try {
      const r = await api.post<BallotView>(`/public/resolutions/ballot/${token}/vote`, { choice });
      setState({ token, ballot: r.data, notFound: false });
      setJustVoted(true);
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? "Stimme konnte nicht gespeichert werden.");
    } finally {
      setSubmitting(false);
    }
  };

  if (!ready) {
    return (
      <AuthShell title="Abstimmung">
        <Typography variant="body2" color="text.secondary">
          Wird geladen…
        </Typography>
      </AuthShell>
    );
  }

  if (state.notFound || state.ballot === null) {
    return (
      <AuthShell title="Abstimmung">
        <Alert severity="error">
          Dieser Abstimmungslink ist ungültig oder abgelaufen. Bitte wenden Sie sich an
          Ihre Hausverwaltung.
        </Alert>
      </AuthShell>
    );
  }

  const b = state.ballot;

  return (
    <AuthShell title="Umlaufbeschluss">
      <Stack spacing={2}>
        {b.owner_name && (
          <Typography variant="body2" color="text.secondary">
            Hallo {b.owner_name},
          </Typography>
        )}
        <Box>
          <Typography variant="h6" sx={{ fontWeight: 700 }}>
            {b.resolution_title}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {b.property_name} · Frist: {formatDeadline(b.closes_at)}
          </Typography>
        </Box>
        <Paper variant="outlined" sx={{ p: 2, whiteSpace: "pre-wrap", fontSize: 14 }}>
          {b.description}
        </Paper>

        {error && <Alert severity="error">{error}</Alert>}

        {b.already_voted ? (
          <Alert severity={justVoted ? "success" : "info"}>
            {justVoted
              ? "Vielen Dank — Ihre Stimme wurde gespeichert."
              : "Für diese Liegenschaft wurde bereits abgestimmt."}
          </Alert>
        ) : !b.open_for_voting ? (
          <Alert severity="warning">Die Abstimmung ist nicht (mehr) offen.</Alert>
        ) : (
          <Stack spacing={1}>
            <Typography variant="body2" sx={{ fontWeight: 600 }}>
              Ihre Stimme:
            </Typography>
            <Stack direction="row" spacing={1}>
              {CHOICES.map((c) => (
                <Button
                  key={c.value}
                  variant={c.value === "ENTHALTUNG" ? "outlined" : "contained"}
                  color={c.color}
                  disabled={submitting}
                  onClick={() => vote(c.value)}
                  sx={{ flex: 1 }}
                >
                  {c.label}
                </Button>
              ))}
            </Stack>
            <Typography variant="caption" color="text.secondary">
              Hinweis: Die Stimme kann nur einmal abgegeben werden.
            </Typography>
          </Stack>
        )}
      </Stack>
    </AuthShell>
  );
}
