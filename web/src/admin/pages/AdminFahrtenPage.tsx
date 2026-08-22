// Fahrtenbuch (ADR-0020): every Verwalter's Dienstfahrten for one month,
// with Kilometergeld totals, the Auslagen split per Objekt, inline
// correction of purpose/property, and a CSV export for the statement.
//
// Filters are derived from the loaded month (drivers + properties that
// actually have trips) — no extra lookups, and the dropdowns never list
// empty choices.

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  FormControl,
  IconButton,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import DownloadIcon from "@mui/icons-material/Download";
import EditIcon from "@mui/icons-material/Edit";
import MapIcon from "@mui/icons-material/Map";
import PictureAsPdfIcon from "@mui/icons-material/PictureAsPdf";
import { useTranslation } from "react-i18next";
import { api } from "@/api/client";
import type {
  AdminTripListResponse,
  TripResponse,
} from "@/api/types";
import { TripEditDialog } from "@/admin/components/TripEditDialog";
import { TripMapDialog } from "@/admin/components/TripMapDialog";
import { purposeLabel } from "@/lib/trips";

function monthKey(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function fmtKm(m: number | null | undefined): string {
  return `${((m ?? 0) / 1000).toLocaleString("de-DE", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} km`;
}

function fmtEur(cents: number): string {
  return (cents / 100).toLocaleString("de-DE", { style: "currency", currency: "EUR" });
}

export function AdminFahrtenPage() {
  const { t } = useTranslation();
  const [month, setMonth] = useState<Date>(() => {
    const d = new Date();
    d.setDate(1);
    return d;
  });
  const [data, setData] = useState<AdminTripListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [driver, setDriver] = useState<string>("");
  const [propertyId, setPropertyId] = useState<string>("");
  const [editing, setEditing] = useState<TripResponse | null>(null);
  const [mapTrips, setMapTrips] = useState<{ title: string; trips: TripResponse[] } | null>(null);

  const key = monthKey(month);

  const load = useCallback(async () => {
    try {
      const r = await api.get<AdminTripListResponse>(`/admin/trips?month=${key}`);
      setData(r.data);
      setError(null);
    } catch {
      setError(t("admin.fahrten.loadFailed"));
    }
  }, [key, t]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  // Filter client-side: the month payload is small (dozens of rows) and the
  // dropdowns then only offer drivers/properties that really occur.
  const drivers = useMemo(
    () => Array.from(new Set((data?.items ?? []).map((i) => i.user_email ?? ""))).filter(Boolean).sort(),
    [data],
  );
  const properties = useMemo(() => {
    const m = new Map<string, string>();
    for (const i of data?.items ?? []) if (i.property_id && i.property_name) m.set(i.property_id, i.property_name);
    return Array.from(m.entries()).sort((a, b) => a[1].localeCompare(b[1]));
  }, [data]);

  const rows = useMemo(
    () =>
      (data?.items ?? []).filter(
        (i) => (!driver || i.user_email === driver) && (!propertyId || i.property_id === propertyId),
      ),
    [data, driver, propertyId],
  );
  const totals = useMemo(() => {
    const billable = rows.filter((r) => r.purpose !== "PRIVAT" && (r.distance_m ?? 0) > 0);
    return {
      trips: rows.length,
      km: rows.reduce((s, r) => s + (r.distance_m ?? 0), 0),
      billableKm: billable.reduce((s, r) => s + (r.distance_m ?? 0), 0),
      eur: rows.reduce((s, r) => s + r.amount_cents, 0),
      open: rows.filter((r) => r.status === "OPEN").length,
    };
  }, [rows]);

  const shift = (by: number) => {
    const d = new Date(month);
    d.setMonth(d.getMonth() + by);
    setMonth(d);
  };
  const isCurrent = monthKey(new Date()) === key;

  const exportPdf = async () => {
    const q = new URLSearchParams({ month: key });
    // The statement is per driver; with the driver filter set, export that
    // driver, otherwise the calling Verwalter's own.
    const drv = driver ? rows.find((r) => r.user_email === driver) : undefined;
    if (drv) q.set("user_id", drv.user_id);
    const r = await api.get<Blob>(`/admin/trips/statement.pdf?${q.toString()}`, { responseType: "blob" });
    const url = URL.createObjectURL(r.data as Blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `Fahrtenbuch-${key}.pdf`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  const exportCsv = async () => {
    const q = new URLSearchParams({ month: key });
    if (propertyId) q.set("property_id", propertyId);
    const r = await api.get<Blob>(`/admin/trips/export.csv?${q.toString()}`, { responseType: "blob" });
    const url = URL.createObjectURL(r.data as Blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `Fahrtenbuch-${key}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  return (
    <Stack spacing={3}>
      <Box>
        <Typography variant="h4" component="h1" gutterBottom>
          {t("admin.fahrten.title")}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {t("admin.fahrten.subtitle")}
        </Typography>
      </Box>

      {error && <Alert severity="error">{error}</Alert>}

      <Stack direction={{ xs: "column", md: "row" }} spacing={2} sx={{ alignItems: { md: "center" } }}>
        <Stack direction="row" spacing={0.5} sx={{ alignItems: "center" }}>
          <IconButton size="small" onClick={() => shift(-1)} aria-label="Vormonat">
            <ChevronLeftIcon />
          </IconButton>
          <Typography variant="h6" sx={{ minWidth: 160, textAlign: "center" }}>
            {month.toLocaleDateString("de-DE", { month: "long", year: "numeric" })}
          </Typography>
          <IconButton size="small" onClick={() => shift(1)} disabled={isCurrent} aria-label="Folgemonat">
            <ChevronRightIcon />
          </IconButton>
        </Stack>
        <FormControl size="small" sx={{ minWidth: 220 }}>
          <InputLabel>{t("admin.fahrten.driver")}</InputLabel>
          <Select value={driver} label={t("admin.fahrten.driver")} onChange={(e) => setDriver(e.target.value)}>
            <MenuItem value="">{t("admin.fahrten.all")}</MenuItem>
            {drivers.map((d) => (
              <MenuItem key={d} value={d}>{d}</MenuItem>
            ))}
          </Select>
        </FormControl>
        <FormControl size="small" sx={{ minWidth: 260 }}>
          <InputLabel>{t("admin.fahrten.property")}</InputLabel>
          <Select value={propertyId} label={t("admin.fahrten.property")} onChange={(e) => setPropertyId(e.target.value)}>
            <MenuItem value="">{t("admin.fahrten.all")}</MenuItem>
            {properties.map(([id, name]) => (
              <MenuItem key={id} value={id}>{name}</MenuItem>
            ))}
          </Select>
        </FormControl>
        <Box sx={{ flex: 1 }} />
        <Button variant="outlined" startIcon={<DownloadIcon />} onClick={() => void exportCsv()} disabled={!data}>
          {t("admin.fahrten.exportCsv")}
        </Button>
        <Button variant="outlined" startIcon={<PictureAsPdfIcon />} onClick={() => void exportPdf()} disabled={!data}>
          {t("admin.fahrten.exportPdf")}
        </Button>
        <Button
          variant="outlined"
          startIcon={<MapIcon />}
          onClick={() => setMapTrips({ title: t("admin.fahrten.mapMonth"), trips: rows })}
          disabled={rows.length === 0}
        >
          {t("admin.fahrten.map")}
        </Button>
      </Stack>

      <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
        <Stat label={t("admin.fahrten.trips")} value={String(totals.trips)} hint={totals.open ? `${totals.open} ${t("admin.fahrten.openHint")}` : undefined} />
        <Stat label={t("admin.fahrten.distance")} value={fmtKm(totals.km)} hint={`${fmtKm(totals.billableKm)} ${t("admin.fahrten.billable")}`} />
        <Stat label={t("admin.fahrten.kilometergeld")} value={fmtEur(totals.eur)} hint={t("admin.fahrten.rateHint")} />
      </Stack>

      {data && data.by_property.length > 0 && !propertyId && (
        <Paper variant="outlined" sx={{ p: 2 }}>
          <Typography variant="subtitle2" gutterBottom>
            {t("admin.fahrten.byProperty")}
          </Typography>
          <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: "wrap" }}>
            {data.by_property.map((p) => (
              <Chip
                key={p.property_id ?? "none"}
                label={`${p.property_name} · ${fmtKm(p.distance_m)} · ${fmtEur(p.amount_cents)}`}
                onClick={p.property_id ? () => setPropertyId(p.property_id!) : undefined}
                variant="outlined"
              />
            ))}
          </Stack>
        </Paper>
      )}

      <Paper variant="outlined">
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>{t("admin.fahrten.colDate")}</TableCell>
              <TableCell>{t("admin.fahrten.driver")}</TableCell>
              <TableCell>{t("admin.fahrten.property")}</TableCell>
              <TableCell>{t("admin.fahrten.purpose")}</TableCell>
              <TableCell align="right">km</TableCell>
              <TableCell align="right">€</TableCell>
              <TableCell>{t("admin.fahrten.source")}</TableCell>
              <TableCell />
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.length === 0 && (
              <TableRow>
                <TableCell colSpan={8}>
                  <Typography variant="body2" color="text.secondary" sx={{ py: 2, textAlign: "center" }}>
                    {t("admin.fahrten.empty")}
                  </Typography>
                </TableCell>
              </TableRow>
            )}
            {rows.map((r) => {
              const start = new Date(r.started_at);
              const end = r.ended_at ? new Date(r.ended_at) : null;
              return (
                <TableRow key={r.id} hover>
                  <TableCell>
                    {start.toLocaleDateString("de-DE")}{" "}
                    <Typography component="span" variant="caption" color="text.secondary">
                      {start.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" })}
                      {end ? `–${end.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" })}` : ""}
                    </Typography>
                  </TableCell>
                  <TableCell>{r.user_email ?? "—"}</TableCell>
                  <TableCell>
                    {r.property_name ??
                      (r.inquiry_id ? (
                        <Chip
                          size="small"
                          variant="outlined"
                          color="info"
                          label={`${t("admin.fahrten.inquiry")}: ${r.inquiry_address ?? "—"}`}
                        />
                      ) : (
                        <Typography component="span" variant="caption" color="text.secondary">—</Typography>
                      ))}
                  </TableCell>
                  <TableCell>
                    <Chip
                      size="small"
                      label={purposeLabel(r.purpose)}
                      color={r.status === "OPEN" ? "warning" : r.purpose === "PRIVAT" ? "default" : "primary"}
                      variant={r.status === "OPEN" ? "filled" : "outlined"}
                    />
                  </TableCell>
                  <TableCell align="right">{fmtKm(r.distance_m)}</TableCell>
                  <TableCell align="right">{fmtEur(r.amount_cents)}</TableCell>
                  <TableCell>
                    <Typography variant="caption" color="text.secondary">{r.source}</Typography>
                  </TableCell>
                  <TableCell align="right">
                    <IconButton
                      size="small"
                      onClick={() => setMapTrips({ title: `${r.property_name ?? r.inquiry_address ?? purposeLabel(r.purpose)} · ${start.toLocaleDateString("de-DE")}`, trips: [r] })}
                      aria-label={t("admin.fahrten.map")}
                      disabled={!r.route_polyline && !(r.start_lat && r.start_lng)}
                    >
                      <MapIcon fontSize="small" />
                    </IconButton>
                    <IconButton size="small" onClick={() => setEditing(r)} aria-label={t("common.edit")}>
                      <EditIcon fontSize="small" />
                    </IconButton>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </Paper>

      {mapTrips && (
        <TripMapDialog title={mapTrips.title} trips={mapTrips.trips} onClose={() => setMapTrips(null)} />
      )}
      {editing && (
        <TripEditDialog
          trip={editing}
          properties={properties}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            void load();
          }}
        />
      )}
    </Stack>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Paper variant="outlined" sx={{ p: 2, flex: 1 }}>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
      <Typography variant="h5">{value}</Typography>
      {hint && <Typography variant="caption" color="text.secondary">{hint}</Typography>}
    </Paper>
  );
}
