/**
 * Property "Zähler" tab (member-facing, ADR-0016).
 *
 * Every property member sees the meters the Verwalter set up and can
 * report a reading — ideally by photographing the meter: the photo is
 * OCR'd server-side to pre-fill the value, which the user confirms or
 * corrects before submitting. Manual entry (no photo) works too. The
 * per-meter history shows past readings.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Collapse,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import HistoryIcon from "@mui/icons-material/History";
import PhotoCameraIcon from "@mui/icons-material/PhotoCamera";
import SpeedIcon from "@mui/icons-material/Speed";
import { api } from "@/api/client";
import {
  METER_TYPE_LABELS,
  type MeterReadingOCRResult,
  type MeterReadingResponse,
  type MeterResponse,
} from "@/api/types";

function fmtNum(v: number | string | null): string {
  if (v === null || v === undefined) return "—";
  const n = Number(v);
  return Number.isFinite(n) ? n.toLocaleString("de-DE") : String(v);
}

function fmtDate(d: string | null): string {
  if (!d) return "—";
  const parsed = new Date(d);
  return Number.isNaN(parsed.getTime()) ? d : parsed.toLocaleDateString("de-DE");
}

function todayIso(): string {
  // Local date (not UTC) so "heute" matches the user's calendar day.
  const now = new Date();
  const off = now.getTimezoneOffset();
  return new Date(now.getTime() - off * 60_000).toISOString().slice(0, 10);
}

// --- report-reading dialog ----------------------------------------------------

function ReportReadingDialog({
  meter,
  onClose,
  onSaved,
}: {
  meter: MeterResponse;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [photo, setPhoto] = useState<File | null>(null);
  const [value, setValue] = useState("");
  const [readOn, setReadOn] = useState(todayIso());
  const [note, setNote] = useState("");
  const [ocrBusy, setOcrBusy] = useState(false);
  const [ocrApplied, setOcrApplied] = useState(false);
  const [ocrHint, setOcrHint] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onPickPhoto = async (file: File) => {
    setPhoto(file);
    setOcrApplied(false);
    setOcrHint(null);
    setOcrBusy(true);
    try {
      const fd = new FormData();
      fd.append("photo", file);
      const r = await api.post<MeterReadingOCRResult>(
        `/me/meters/${meter.id}/readings/ocr`,
        fd,
      );
      if (!r.data.provider_available) {
        setOcrHint("Automatische Erkennung nicht verfügbar — bitte Wert eintragen.");
      } else if (r.data.suggested_value != null) {
        setValue(String(r.data.suggested_value));
        setOcrApplied(true);
        setOcrHint("Wert aus Foto erkannt — bitte prüfen.");
      } else {
        setOcrHint("Konnte den Wert nicht sicher lesen — bitte manuell eintragen.");
      }
    } catch {
      setOcrHint("Erkennung fehlgeschlagen — bitte Wert eintragen.");
    } finally {
      setOcrBusy(false);
    }
  };

  const submit = async () => {
    const numeric = Number(value.replace(",", "."));
    if (!value.trim() || !Number.isFinite(numeric) || numeric < 0) {
      setError("Bitte einen gültigen Zählerstand eintragen.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const fd = new FormData();
      fd.append("value", String(numeric));
      fd.append("read_on", readOn);
      fd.append("source", ocrApplied ? "OCR" : "MANUAL");
      if (note.trim()) fd.append("note", note.trim());
      if (photo) fd.append("photo", photo);
      await api.post(`/me/meters/${meter.id}/readings`, fd);
      onSaved();
      onClose();
    } catch (e) {
      const detail =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Speichern fehlgeschlagen.";
      setError(detail);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="xs">
      <DialogTitle>Zählerstand melden</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <Typography variant="body2" color="text.secondary">
            {METER_TYPE_LABELS[meter.meter_type]} · {meter.meter_number}
            {meter.description ? ` · ${meter.description}` : ""}
          </Typography>
          {error && <Alert severity="error">{error}</Alert>}

          <Button
            component="label"
            variant="outlined"
            startIcon={ocrBusy ? <CircularProgress size={18} /> : <PhotoCameraIcon />}
            disabled={ocrBusy || busy}
          >
            {photo ? "Foto ersetzen" : "Foto aufnehmen"}
            <input
              hidden
              type="file"
              accept="image/*"
              capture="environment"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void onPickPhoto(f);
              }}
            />
          </Button>
          {photo && (
            <Typography variant="caption" color="text.secondary">
              {photo.name}
            </Typography>
          )}
          {ocrHint && (
            <Alert severity={ocrApplied ? "success" : "info"} sx={{ py: 0 }}>
              {ocrHint}
            </Alert>
          )}

          <TextField
            label={`Zählerstand${meter.unit_label ? ` (${meter.unit_label})` : ""}`}
            value={value}
            onChange={(e) => {
              setValue(e.target.value);
              setOcrApplied(false);
            }}
            inputMode="decimal"
            fullWidth
            autoFocus
          />
          <TextField
            label="Ablesedatum"
            type="date"
            value={readOn}
            onChange={(e) => setReadOn(e.target.value)}
            fullWidth
            slotProps={{ inputLabel: { shrink: true } }}
          />
          <TextField
            label="Notiz (optional)"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            fullWidth
            multiline
            minRows={2}
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={busy}>
          Abbrechen
        </Button>
        <Button variant="contained" onClick={submit} disabled={busy || ocrBusy}>
          {busy ? "Sendet…" : "Melden"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

// --- per-meter history --------------------------------------------------------

function MeterHistory({ meterId }: { meterId: string }) {
  const [rows, setRows] = useState<MeterReadingResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const r = await api.get<MeterReadingResponse[]>(`/me/meters/${meterId}/readings`);
        if (!cancelled) setRows(r.data);
      } catch {
        if (!cancelled) setError("Verlauf konnte nicht geladen werden.");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [meterId]);

  if (error) return <Alert severity="error">{error}</Alert>;
  if (rows === null)
    return (
      <Typography variant="caption" color="text.secondary">
        Lade Verlauf…
      </Typography>
    );
  if (rows.length === 0)
    return (
      <Typography variant="caption" color="text.secondary">
        Noch keine Ablesungen.
      </Typography>
    );

  return (
    <Stack spacing={0.5} divider={<Divider flexItem />}>
      {rows.map((r) => (
        <Stack
          key={r.id}
          direction="row"
          spacing={1}
          sx={{ alignItems: "center", justifyContent: "space-between" }}
        >
          <Typography variant="caption" color="text.secondary">
            {fmtDate(r.read_on)}
            {r.source === "OCR" ? " · Foto" : ""}
          </Typography>
          <Typography variant="body2" sx={{ fontWeight: 500 }}>
            {fmtNum(r.value)}
          </Typography>
        </Stack>
      ))}
    </Stack>
  );
}

// --- main page ----------------------------------------------------------------

export function MyMetersPage() {
  const { id: propertyId } = useParams<{ id: string }>();
  const [meters, setMeters] = useState<MeterResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reporting, setReporting] = useState<MeterResponse | null>(null);
  const [historyOpen, setHistoryOpen] = useState<Set<string>>(new Set());

  const load = useCallback(async () => {
    if (!propertyId) return;
    setError(null);
    try {
      const r = await api.get<MeterResponse[]>(`/me/properties/${propertyId}/meters`);
      setMeters(r.data);
    } catch {
      setError("Zähler konnten nicht geladen werden.");
    }
  }, [propertyId]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const toggleHistory = (id: string) =>
    setHistoryOpen((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const empty = useMemo(() => meters !== null && meters.length === 0, [meters]);

  if (meters === null && !error) {
    return (
      <Typography variant="body2" color="text.secondary">
        Lade Zähler…
      </Typography>
    );
  }

  return (
    <Stack spacing={2}>
      {error && <Alert severity="error">{error}</Alert>}

      {empty && (
        <Paper variant="outlined" sx={{ p: 3, textAlign: "center" }}>
          <SpeedIcon color="disabled" sx={{ fontSize: 40, mb: 1 }} />
          <Typography variant="body2" color="text.secondary">
            Für diese Liegenschaft sind noch keine Zähler hinterlegt.
          </Typography>
        </Paper>
      )}

      {(meters ?? []).map((m) => {
        const open = historyOpen.has(m.id);
        return (
          <Paper key={m.id} variant="outlined" sx={{ p: 2 }}>
            <Stack
              direction="row"
              spacing={1}
              sx={{ alignItems: "flex-start", justifyContent: "space-between" }}
            >
              <Box sx={{ minWidth: 0 }}>
                <Stack direction="row" spacing={1} sx={{ alignItems: "center", flexWrap: "wrap" }}>
                  <Chip size="small" label={METER_TYPE_LABELS[m.meter_type]} />
                  <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                    {m.meter_number}
                  </Typography>
                </Stack>
                {(m.description || m.location) && (
                  <Typography
                    variant="caption"
                    color="text.secondary"
                    sx={{ display: "block" }}
                  >
                    {[m.description, m.location].filter(Boolean).join(" · ")}
                  </Typography>
                )}
                <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                  Letzter Stand:{" "}
                  {m.latest_reading_value !== null ? (
                    <strong>
                      {fmtNum(m.latest_reading_value)} {m.unit_label ?? ""} ({fmtDate(m.latest_reading_on)})
                    </strong>
                  ) : (
                    "noch keiner"
                  )}
                </Typography>
              </Box>
              <Button
                variant="contained"
                size="small"
                startIcon={<SpeedIcon />}
                onClick={() => setReporting(m)}
                sx={{ flexShrink: 0 }}
              >
                Stand melden
              </Button>
            </Stack>

            <Button
              size="small"
              startIcon={<HistoryIcon />}
              onClick={() => toggleHistory(m.id)}
              sx={{ mt: 1 }}
            >
              Verlauf ({m.reading_count})
            </Button>
            <Collapse in={open} timeout="auto" unmountOnExit>
              <Box sx={{ mt: 1 }}>
                <MeterHistory meterId={m.id} />
              </Box>
            </Collapse>
          </Paper>
        );
      })}

      {reporting && (
        <ReportReadingDialog
          meter={reporting}
          onClose={() => setReporting(null)}
          onSaved={() => void load()}
        />
      )}
    </Stack>
  );
}
