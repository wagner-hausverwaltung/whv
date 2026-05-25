/**
 * Root `/` after sign-in: fetches the user's properties and bounces
 * to /properties/{first}/details. If the user has zero properties,
 * shows a friendly card explaining they haven't been assigned yet.
 *
 * The PropertySwitcher in the AppBar also fetches /me/properties —
 * that's one duplicate request on the initial `/` hit. Worth it for
 * the simplicity of "no shared property context". After redirect
 * we're on a /properties/:id/* route so RootRedirect doesn't render
 * again until the next cold `/` visit.
 */

import { useEffect, useState } from "react";
import { Link as RouterLink, Navigate } from "react-router-dom";
import {
  Alert,
  Button,
  Paper,
  Stack,
  Typography,
} from "@mui/material";
import HomeWorkOutlinedIcon from "@mui/icons-material/HomeWorkOutlined";
import { api } from "@/api/client";
import type { PropertyResponse } from "@/api/types";

type State =
  | { kind: "loading" }
  | { kind: "redirect"; to: string }
  | { kind: "empty" }
  | { kind: "error" };

export function RootRedirect() {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    api
      .get<PropertyResponse[]>("/me/properties")
      .then((r) => {
        if (cancelled) return;
        const first = r.data[0];
        if (first) {
          setState({
            kind: "redirect",
            to: `/properties/${first.id}/details`,
          });
        } else {
          setState({ kind: "empty" });
        }
      })
      .catch(() => {
        if (!cancelled) setState({ kind: "error" });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (state.kind === "redirect") {
    return <Navigate to={state.to} replace />;
  }
  if (state.kind === "error") {
    return (
      <Alert severity="error">
        Liegenschaften konnten nicht geladen werden. Bitte später erneut
        versuchen.
      </Alert>
    );
  }
  if (state.kind === "empty") {
    return (
      <Stack spacing={3} sx={{ maxWidth: 520, mx: "auto", mt: 6 }}>
        <Paper variant="outlined" sx={{ p: 4, textAlign: "center" }}>
          <HomeWorkOutlinedIcon
            sx={{ fontSize: 48, color: "text.disabled", mb: 1 }}
          />
          <Typography variant="h6" gutterBottom>
            Noch keine Liegenschaft zugewiesen
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
            Sobald Ihre Hausverwaltung Sie einer Liegenschaft zuordnet,
            erscheint sie hier. Bei Fragen wenden Sie sich bitte direkt an
            die Verwaltung.
          </Typography>
          <Button component={RouterLink} to="/tickets/new" variant="outlined">
            Anfrage senden
          </Button>
        </Paper>
      </Stack>
    );
  }
  return (
    <Typography variant="body2" color="text.secondary">
      Wird geladen…
    </Typography>
  );
}
