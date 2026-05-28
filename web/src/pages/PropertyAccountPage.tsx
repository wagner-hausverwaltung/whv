/**
 * Property "Hausgeldkonto" tab (owner-facing).
 *
 * Shows the owner's own Impower account for this property: the balance
 * (signed sum of bookings) + the booking history. Pulled live from
 * GET /me/properties/{id}/account.
 *
 * The balance is presented NEUTRALLY as "Saldo" — we don't yet claim
 * Guthaben vs. offene Forderung, because the sign convention still has
 * to be confirmed against real Impower data. (Showing an owner the
 * wrong direction on their own account would be a trust-breaking bug.)
 */

import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { Alert, Box, Divider, Paper, Stack, Typography } from "@mui/material";
import { api } from "@/api/client";
import type { HausgeldAccountResponse } from "@/api/types";

const EUR = new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR" });

function formatEur(value: number | null): string {
  if (value === null || Number.isNaN(value)) return "—";
  return EUR.format(value);
}

function formatDate(raw: string | null): string {
  if (!raw) return "";
  const d = new Date(raw);
  return Number.isNaN(d.getTime()) ? raw : d.toLocaleDateString("de-DE");
}

// One state object keyed by the property id it belongs to, so the only
// setState calls happen in async resolution (never synchronously in the
// effect) — satisfies react-hooks/set-state-in-effect — and a stale
// result from the previous property is ignored via the id check.
type LoadState = {
  id: string;
  account: HausgeldAccountResponse | null;
  error: string | null;
  notFound: boolean;
};

export function PropertyAccountPage() {
  const { id } = useParams<{ id: string }>();
  const [state, setState] = useState<LoadState | null>(null);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    api
      .get<HausgeldAccountResponse>(`/me/properties/${id}/account`)
      .then((r) => {
        if (!cancelled) setState({ id, account: r.data, error: null, notFound: false });
      })
      .catch((err) => {
        if (cancelled) return;
        if (err?.response?.status === 404) {
          setState({ id, account: null, error: null, notFound: true });
        } else {
          setState({
            id,
            account: null,
            error: "Hausgeldkonto konnte nicht geladen werden.",
            notFound: false,
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  // Treat a result for a different property as "still loading".
  const ready = state !== null && state.id === id;

  if (!ready) {
    return (
      <Typography variant="body2" color="text.secondary">
        Wird geladen…
      </Typography>
    );
  }

  if (state.error) return <Alert severity="error">{state.error}</Alert>;

  if (state.notFound || state.account === null || state.account.account_id === null) {
    return (
      <Typography variant="body2" color="text.secondary">
        Für diese Liegenschaft ist kein persönliches Hausgeldkonto hinterlegt.
      </Typography>
    );
  }

  const account = state.account;

  return (
    <Stack spacing={2.5} sx={{ maxWidth: 760 }}>
      {/* Balance card */}
      <Paper variant="outlined" sx={{ p: 2.5 }}>
        <Typography variant="overline" color="text.secondary">
          Saldo
        </Typography>
        <Typography variant="h4" sx={{ fontWeight: 700, lineHeight: 1.2 }}>
          {formatEur(account.balance)}
        </Typography>
        {(account.name || account.account_hr_id) && (
          <Typography variant="caption" color="text.secondary">
            {[account.name, account.account_hr_id].filter(Boolean).join(" · ")}
          </Typography>
        )}
        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1 }}>
          Live aus Impower, ohne Gewähr. Bei Fragen zu einzelnen Buchungen
          wenden Sie sich an die Verwaltung.
        </Typography>
      </Paper>

      {/* Bookings */}
      <Box>
        <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1 }}>
          Buchungen
        </Typography>
        {account.bookings.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            Keine Buchungen vorhanden.
          </Typography>
        ) : (
          <Paper variant="outlined">
            <Stack divider={<Divider />}>
              {account.bookings.map((b, i) => (
                <Stack
                  key={i}
                  direction="row"
                  spacing={2}
                  sx={{ p: 1.5, alignItems: "baseline" }}
                >
                  <Typography
                    variant="caption"
                    color="text.secondary"
                    sx={{ width: 84, flexShrink: 0 }}
                  >
                    {formatDate(b.post_date)}
                  </Typography>
                  <Typography variant="body2" sx={{ flexGrow: 1, minWidth: 0 }}>
                    {b.booking_text || "—"}
                  </Typography>
                  <Typography
                    variant="body2"
                    sx={{
                      flexShrink: 0,
                      fontFamily: "ui-monospace, Menlo, monospace",
                      fontVariantNumeric: "tabular-nums",
                    }}
                  >
                    {formatEur(b.amount)}
                  </Typography>
                </Stack>
              ))}
            </Stack>
          </Paper>
        )}
      </Box>
    </Stack>
  );
}
