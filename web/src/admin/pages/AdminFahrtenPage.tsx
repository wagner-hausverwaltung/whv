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
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutlineOutlined";
import DownloadIcon from "@mui/icons-material/Download";
import EditIcon from "@mui/icons-material/Edit";
import MapIcon from "@mui/icons-material/Map";
import PictureAsPdfIcon from "@mui/icons-material/PictureAsPdf";
import ReceiptLongIcon from "@mui/icons-material/ReceiptLong";
import { useTranslation } from "react-i18next";
import { api } from "@/api/client";
import type {
  AdminTripListResponse,
  TripInvoiceResponse,
  TripResponse,
} from "@/api/types";
import { TripEditDialog } from "@/admin/components/TripEditDialog";
import { TripInvoiceDialog } from "@/admin/components/TripInvoiceDialog";
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
  const [invoices, setInvoices] = useState<TripInvoiceResponse[]>([]);
  const [invoiceDialog, setInvoiceDialog] = useState<{ propertyId?: string } | null>(null);
  const [invoiceError, setInvoiceError] = useState<string | null>(null);

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

  const loadInvoices = useCallback(async () => {
    try {
      const r = await api.get<TripInvoiceResponse[]>("/admin/trips/invoices?limit=25");
      setInvoices(r.data);
      setInvoiceError(null);
    } catch {
      setInvoiceError(t("admin.fahrten.invoice.loadFailed"));
    }
  }, [t]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadInvoices();
  }, [loadInvoices]);

  const downloadInvoice = async (inv: TripInvoiceResponse) => {
    const r = await api.get<Blob>(`/admin/trips/invoices/${inv.id}/invoice.pdf`, { responseType: "blob" });
    const url = URL.createObjectURL(r.data as Blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `Rechnung-${inv.number}.pdf`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  const deleteTrip = async (r: TripResponse) => {
    const when = new Date(r.started_at).toLocaleString("de-DE", { dateStyle: "short", timeStyle: "short" });
    if (!window.confirm(t("admin.fahrten.deleteConfirm", { when, km: fmtKm(r.distance_m) }))) return;
    try {
      await api.delete(`/admin/trips/${r.id}`);
      await load();
    } catch {
      setError(t("admin.fahrten.deleteFailed"));
    }
  };

  const cancelInvoice = async (inv: TripInvoiceResponse) => {
    if (!window.confirm(t("admin.fahrten.invoice.cancelConfirm", { number: inv.number }))) return;
    try {
      await api.delete(`/admin/trips/invoices/${inv.id}`);
      await Promise.all([loadInvoices(), load()]);
    } catch {
      setInvoiceError(t("admin.fahrten.invoice.cancelFailed"));
    }
  };

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
                  <TableCell sx={{ whiteSpace: "nowrap" }}>
                    {start.toLocaleDateString("de-DE")}{" "}
                    <Typography component="span" variant="caption" color="text.secondary">
                      {start.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" })}
                      {end ? `–${end.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" })}` : ""}
                    </Typography>
                  </TableCell>
                  {/* Local part only — the domain is always ours and the full
                      address is one hover away; keeps the row on one line. */}
                  <TableCell sx={{ whiteSpace: "nowrap" }} title={r.user_email ?? undefined}>
                    {r.user_email ? r.user_email.split("@")[0] : "—"}
                  </TableCell>
                  <TableCell sx={{ minWidth: 220 }}>
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
                    {r.invoice_id && (
                      <Chip
                        size="small"
                        label={t("admin.fahrten.invoice.billed")}
                        color="success"
                        variant="outlined"
                        sx={{ ml: 0.5 }}
                      />
                    )}
                  </TableCell>
                  <TableCell align="right" sx={{ whiteSpace: "nowrap" }}>{fmtKm(r.distance_m)}</TableCell>
                  <TableCell align="right" sx={{ whiteSpace: "nowrap" }}>{fmtEur(r.amount_cents)}</TableCell>
                  <TableCell sx={{ whiteSpace: "nowrap" }}>
                    <Typography variant="caption" color="text.secondary">{r.source}</Typography>
                  </TableCell>
                  <TableCell align="right" sx={{ whiteSpace: "nowrap" }}>
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
                    <IconButton
                      size="small"
                      onClick={() => void deleteTrip(r)}
                      disabled={!!r.invoice_id}
                      aria-label={t("common.delete")}
                      title={r.invoice_id ? t("admin.fahrten.deleteBilled") : t("common.delete")}
                    >
                      <DeleteOutlineIcon fontSize="small" />
                    </IconButton>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </Paper>

      <Paper variant="outlined" sx={{ p: 2 }}>
        <Stack direction="row" spacing={2} sx={{ alignItems: "center", mb: 1 }}>
          <Typography variant="subtitle1" sx={{ flex: 1 }}>
            {t("admin.fahrten.invoice.sectionTitle")}
          </Typography>
          <Button
            variant="contained"
            size="small"
            startIcon={<ReceiptLongIcon />}
            onClick={() => setInvoiceDialog({ propertyId: propertyId || undefined })}
          >
            {t("admin.fahrten.invoice.new")}
          </Button>
        </Stack>
        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 1.5 }}>
          {t("admin.fahrten.invoice.sectionHint")}
        </Typography>
        {invoiceError && <Alert severity="error" sx={{ mb: 1 }}>{invoiceError}</Alert>}
        {invoices.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            {t("admin.fahrten.invoice.empty")}
          </Typography>
        ) : (
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>{t("admin.fahrten.invoice.number")}</TableCell>
                <TableCell>{t("admin.fahrten.invoice.issuedOn")}</TableCell>
                <TableCell>{t("admin.fahrten.property")}</TableCell>
                <TableCell>{t("admin.fahrten.invoice.period")}</TableCell>
                <TableCell align="right">{t("admin.fahrten.trips")}</TableCell>
                <TableCell align="right">km</TableCell>
                <TableCell align="right">{t("admin.fahrten.invoice.gross")}</TableCell>
                <TableCell />
              </TableRow>
            </TableHead>
            <TableBody>
              {invoices.map((inv) => (
                <TableRow key={inv.id} hover>
                  <TableCell>
                    <Typography variant="body2" sx={{ fontFamily: "monospace" }}>{inv.number}</Typography>
                  </TableCell>
                  <TableCell>{new Date(inv.issued_on).toLocaleDateString("de-DE")}</TableCell>
                  <TableCell>{inv.property_name ?? "—"}</TableCell>
                  <TableCell>
                    {new Date(inv.period_from).toLocaleDateString("de-DE")}
                    {inv.period_from !== inv.period_to ? ` – ${new Date(inv.period_to).toLocaleDateString("de-DE")}` : ""}
                  </TableCell>
                  <TableCell align="right">{inv.trip_count}</TableCell>
                  <TableCell align="right">{fmtKm(inv.distance_m)}</TableCell>
                  <TableCell align="right">
                    {fmtEur(inv.gross_cents)}
                    <Typography component="span" variant="caption" color="text.secondary" sx={{ ml: 0.5 }}>
                      ({fmtEur(inv.net_cents)} + {t("admin.fahrten.invoice.vatShort")})
                    </Typography>
                  </TableCell>
                  <TableCell align="right" sx={{ whiteSpace: "nowrap" }}>
                    <IconButton size="small" onClick={() => void downloadInvoice(inv)} aria-label="PDF">
                      <PictureAsPdfIcon fontSize="small" />
                    </IconButton>
                    <IconButton
                      size="small"
                      onClick={() => void cancelInvoice(inv)}
                      disabled={!inv.cancellable}
                      aria-label={t("admin.fahrten.invoice.cancel")}
                      title={inv.cancellable ? t("admin.fahrten.invoice.cancel") : t("admin.fahrten.invoice.cancelOnlyLatest")}
                    >
                      <DeleteOutlineIcon fontSize="small" />
                    </IconButton>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Paper>

      {invoiceDialog && (
        <TripInvoiceDialog
          defaultPropertyId={invoiceDialog.propertyId}
          onClose={() => setInvoiceDialog(null)}
          onCreated={() => {
            setInvoiceDialog(null);
            void Promise.all([loadInvoices(), load()]);
          }}
        />
      )}

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
