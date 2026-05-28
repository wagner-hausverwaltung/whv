/**
 * Property "Konto" tab (owner-facing).
 *
 * Shows whichever financial view applies to the property:
 *   - WEG owners → Hausgeldkonto: Saldo (signed sum of bookings) +
 *     booking history (GET /me/properties/{id}/account).
 *   - MV owners → Mietabrechnung: rental-income / payout statements per
 *     period (GET /me/properties/{id}/rent-settlements).
 *
 * A property is one or the other, so normally a single section renders.
 * Balances/amounts are shown NEUTRALLY (no Guthaben/Forderung claim)
 * until the sign convention is confirmed against real Impower data.
 */

import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { Box, Divider, Paper, Stack, Typography } from "@mui/material";
import { api } from "@/api/client";
import type { HausgeldAccountResponse, RentSettlement } from "@/api/types";

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

// One state object keyed by the property id, so setState only happens in
// async resolution (never synchronously in the effect — satisfies
// react-hooks/set-state-in-effect) and a stale result is ignored.
type LoadState = {
  id: string;
  account: HausgeldAccountResponse | null;
  settlements: RentSettlement[];
};

export function PropertyAccountPage() {
  const { id } = useParams<{ id: string }>();
  const [state, setState] = useState<LoadState | null>(null);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    Promise.allSettled([
      api.get<HausgeldAccountResponse>(`/me/properties/${id}/account`),
      api.get<RentSettlement[]>(`/me/properties/${id}/rent-settlements`),
    ]).then(([acc, set]) => {
      if (cancelled) return;
      const account =
        acc.status === "fulfilled" && acc.value.data.account_id !== null
          ? acc.value.data
          : null;
      const settlements = set.status === "fulfilled" ? set.value.data : [];
      setState({ id, account, settlements });
    });
    return () => {
      cancelled = true;
    };
  }, [id]);

  const ready = state !== null && state.id === id;
  if (!ready) {
    return (
      <Typography variant="body2" color="text.secondary">
        Wird geladen…
      </Typography>
    );
  }

  const { account, settlements } = state;

  if (!account && settlements.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary">
        Für diese Liegenschaft ist kein Konto und keine Mietabrechnung hinterlegt.
      </Typography>
    );
  }

  return (
    <Stack spacing={3} sx={{ maxWidth: 760 }}>
      {account && (
        <Stack spacing={2}>
          <Paper variant="outlined" sx={{ p: 2.5 }}>
            <Typography variant="overline" color="text.secondary">
              Saldo Hausgeldkonto
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
              Live aus Impower, ohne Gewähr. Bei Fragen wenden Sie sich an die
              Verwaltung.
            </Typography>
          </Paper>

          {account.bookings.length > 0 && (
            <Box>
              <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1 }}>
                Buchungen
              </Typography>
              <Paper variant="outlined">
                <Stack divider={<Divider />}>
                  {account.bookings.map((b, i) => (
                    <Stack key={i} direction="row" spacing={2} sx={{ p: 1.5, alignItems: "baseline" }}>
                      <Typography variant="caption" color="text.secondary" sx={{ width: 84, flexShrink: 0 }}>
                        {formatDate(b.post_date)}
                      </Typography>
                      <Typography variant="body2" sx={{ flexGrow: 1, minWidth: 0 }}>
                        {b.booking_text || "—"}
                      </Typography>
                      <Typography
                        variant="body2"
                        sx={{ flexShrink: 0, fontFamily: "ui-monospace, Menlo, monospace", fontVariantNumeric: "tabular-nums" }}
                      >
                        {formatEur(b.amount)}
                      </Typography>
                    </Stack>
                  ))}
                </Stack>
              </Paper>
            </Box>
          )}
        </Stack>
      )}

      {settlements.length > 0 && (
        <Box>
          <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1 }}>
            Mietabrechnung
          </Typography>
          <Paper variant="outlined">
            <Stack divider={<Divider />}>
              {settlements.map((s, i) => (
                <Stack key={i} spacing={0.5} sx={{ p: 1.75 }}>
                  <Stack direction="row" spacing={2} sx={{ justifyContent: "space-between", alignItems: "baseline" }}>
                    <Typography variant="body2" sx={{ fontWeight: 600 }}>
                      {formatDate(s.period_from)} – {formatDate(s.period_until)}
                    </Typography>
                    <Typography
                      variant="body2"
                      sx={{ fontWeight: 700, fontFamily: "ui-monospace, Menlo, monospace" }}
                    >
                      {formatEur(s.payout)}
                    </Typography>
                  </Stack>
                  <Typography variant="caption" color="text.secondary">
                    Mieteinnahmen {formatEur(s.rent_income)}
                    {s.due_date ? ` · fällig ${formatDate(s.due_date)}` : ""}
                  </Typography>
                </Stack>
              ))}
            </Stack>
          </Paper>
          <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1 }}>
            Auszahlung = Betrag an Sie als Eigentümer. Live aus Impower, ohne Gewähr.
          </Typography>
        </Box>
      )}
    </Stack>
  );
}
