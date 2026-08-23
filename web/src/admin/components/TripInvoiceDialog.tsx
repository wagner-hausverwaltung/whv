// "Neue Auslagen-Rechnung": pick an Objekt + cut-off date, see every
// confirmed, not-yet-billed trip of that Objekt, tick the ones the contract
// allows (the backend pre-selects per the default rule: WEG → only ETV at
// 0,42 €/km; MV/SEV → nothing pre-selected, 0,50 €/km), set the rate, create.
// Totals (net / USt / gross) update live so the Verwalter sees the amount
// before the number is consumed.

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import { useTranslation } from "react-i18next";
import { api } from "@/api/client";
import type {
  AdminPropertyListItem,
  BillableTripsResponse,
  TripInvoiceCreate,
  TripInvoiceResponse,
} from "@/api/types";
import { purposeLabel } from "@/lib/trips";

function fmtKm(m: number | null | undefined): string {
  return `${((m ?? 0) / 1000).toLocaleString("de-DE", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} km`;
}

function fmtEur(cents: number): string {
  return (cents / 100).toLocaleString("de-DE", { style: "currency", currency: "EUR" });
}

/** Last day of the previous month as YYYY-MM-DD — the usual cut-off. */
function defaultUntil(): string {
  const d = new Date();
  d.setDate(0);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function lineCents(distanceM: number, rateCents: number): number {
  return Math.round((distanceM / 1000) * rateCents);
}

export function TripInvoiceDialog({
  defaultPropertyId,
  onClose,
  onCreated,
}: {
  defaultPropertyId?: string;
  onClose: () => void;
  onCreated: (inv: TripInvoiceResponse) => void;
}) {
  const { t } = useTranslation();
  const [properties, setProperties] = useState<AdminPropertyListItem[]>([]);
  const [propertyId, setPropertyId] = useState(defaultPropertyId ?? "");
  const [until, setUntil] = useState(defaultUntil);
  const [rate, setRate] = useState<string>("");
  const [note, setNote] = useState("");
  const [billable, setBillable] = useState<BillableTripsResponse | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<AdminPropertyListItem[]>("/admin/properties")
      .then((r) => setProperties(r.data.slice().sort((a, b) => a.name.localeCompare(b.name))))
      .catch(() => setProperties([]));
  }, []);

  const load = useCallback(async () => {
    if (!propertyId || !until) {
      setBillable(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const q = new URLSearchParams({ property_id: propertyId, until });
      const r = await api.get<BillableTripsResponse>(`/admin/trips/billable?${q.toString()}`);
      setBillable(r.data);
      setSelected(new Set(r.data.suggested_trip_ids));
      setRate(String(r.data.rate_cents_per_km));
    } catch {
      setError(t("admin.fahrten.invoice.loadFailed"));
      setBillable(null);
    } finally {
      setLoading(false);
    }
  }, [propertyId, until, t]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const rateCents = Number.parseInt(rate, 10);
  const rateValid = Number.isFinite(rateCents) && rateCents >= 1 && rateCents <= 500;
  const totals = useMemo(() => {
    const chosen = (billable?.items ?? []).filter((i) => selected.has(i.id));
    const net = rateValid ? chosen.reduce((s, i) => s + lineCents(i.distance_m ?? 0, rateCents), 0) : 0;
    const vat = Math.round(net * 0.19);
    return {
      count: chosen.length,
      km: chosen.reduce((s, i) => s + (i.distance_m ?? 0), 0),
      net,
      vat,
      gross: net + vat,
    };
  }, [billable, selected, rateCents, rateValid]);

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const create = async () => {
    if (!rateValid || totals.count === 0) return;
    setBusy(true);
    setError(null);
    try {
      const body: TripInvoiceCreate = {
        property_id: propertyId,
        trip_ids: Array.from(selected),
        rate_cents_per_km: rateCents,
        note: note.trim() || null,
      };
      const r = await api.post<TripInvoiceResponse>("/admin/trips/invoices", body);
      onCreated(r.data);
    } catch {
      setError(t("admin.fahrten.invoice.createFailed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>{t("admin.fahrten.invoice.newTitle")}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
            <FormControl size="small" sx={{ minWidth: 280, flex: 1 }}>
              <InputLabel>{t("admin.fahrten.property")}</InputLabel>
              <Select value={propertyId} label={t("admin.fahrten.property")} onChange={(e) => setPropertyId(e.target.value)}>
                {properties.map((p) => (
                  <MenuItem key={p.id} value={p.id}>
                    {p.name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <TextField
              size="small"
              type="date"
              label={t("admin.fahrten.invoice.until")}
              value={until}
              onChange={(e) => setUntil(e.target.value)}
              slotProps={{ inputLabel: { shrink: true } }}
            />
            <TextField
              size="small"
              type="number"
              label={t("admin.fahrten.invoice.rate")}
              value={rate}
              onChange={(e) => setRate(e.target.value)}
              error={rate !== "" && !rateValid}
              slotProps={{ htmlInput: { min: 1, max: 500, step: 1 } }}
              sx={{ width: 140 }}
            />
          </Stack>

          {billable && (
            <Alert severity="info" variant="outlined">
              {billable.rule_hint}
            </Alert>
          )}
          {error && <Alert severity="error">{error}</Alert>}

          {billable && billable.items.length === 0 && !loading && (
            <Typography variant="body2" color="text.secondary">
              {t("admin.fahrten.invoice.nothingBillable")}
            </Typography>
          )}

          {billable && billable.items.length > 0 && (
            <Box sx={{ overflowX: "auto" }}>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell padding="checkbox">
                      <Checkbox
                        size="small"
                        checked={selected.size === billable.items.length}
                        indeterminate={selected.size > 0 && selected.size < billable.items.length}
                        onChange={(e) =>
                          setSelected(e.target.checked ? new Set(billable.items.map((i) => i.id)) : new Set())
                        }
                      />
                    </TableCell>
                    <TableCell>{t("admin.fahrten.colDate")}</TableCell>
                    <TableCell>{t("admin.fahrten.driver")}</TableCell>
                    <TableCell>{t("admin.fahrten.purpose")}</TableCell>
                    <TableCell>{t("admin.fahrten.note")}</TableCell>
                    <TableCell align="right">km</TableCell>
                    <TableCell align="right">€ netto</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {billable.items.map((i) => (
                    <TableRow key={i.id} hover onClick={() => toggle(i.id)} sx={{ cursor: "pointer" }}>
                      <TableCell padding="checkbox">
                        <Checkbox size="small" checked={selected.has(i.id)} onChange={() => toggle(i.id)} onClick={(e) => e.stopPropagation()} />
                      </TableCell>
                      <TableCell>{new Date(i.started_at).toLocaleDateString("de-DE")}</TableCell>
                      <TableCell>{i.user_email ?? "—"}</TableCell>
                      <TableCell>{purposeLabel(i.purpose)}</TableCell>
                      <TableCell sx={{ maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {i.note ?? ""}
                      </TableCell>
                      <TableCell align="right">{fmtKm(i.distance_m)}</TableCell>
                      <TableCell align="right">{rateValid ? fmtEur(lineCents(i.distance_m ?? 0, rateCents)) : "—"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Box>
          )}

          <TextField
            size="small"
            label={t("admin.fahrten.invoice.note")}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            multiline
            minRows={1}
            maxRows={3}
          />

          <Stack direction="row" spacing={3} sx={{ justifyContent: "flex-end" }}>
            <Typography variant="body2" color="text.secondary">
              {totals.count} {t("admin.fahrten.trips")} · {fmtKm(totals.km)}
            </Typography>
            <Typography variant="body2">
              {t("admin.fahrten.invoice.net")} {fmtEur(totals.net)} · {t("admin.fahrten.invoice.vat")} {fmtEur(totals.vat)}
            </Typography>
            <Typography variant="subtitle2">
              {t("admin.fahrten.invoice.gross")} {fmtEur(totals.gross)}
            </Typography>
          </Stack>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="contained" onClick={() => void create()} disabled={busy || !rateValid || totals.count === 0}>
          {t("admin.fahrten.invoice.create")}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
