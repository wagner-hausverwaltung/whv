// Zähler tab on the admin property detail (ADR-0016).
//
// Verwalter manages a property's meters: create one, bulk-import a
// pasted list (the extracted EnBW etc. numbers), edit/deactivate, view
// each meter's reading history (with photo), and export all readings as
// CSV to forward to the supplier out-of-band (v1 has no in-app send).

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Collapse,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  MenuItem,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import DownloadIcon from "@mui/icons-material/Download";
import EditIcon from "@mui/icons-material/Edit";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import KeyboardArrowRightIcon from "@mui/icons-material/KeyboardArrowRight";
import PhotoCameraIcon from "@mui/icons-material/PhotoCamera";
import PlaylistAddIcon from "@mui/icons-material/PlaylistAdd";
import SwapHorizIcon from "@mui/icons-material/SwapHoriz";
import { api } from "@/api/client";
import {
  METER_TYPE_LABELS,
  type MeterBulkCreateResponse,
  type MeterCreateRequest,
  type MeterReadingResponse,
  type MeterReplaceRequest,
  type MeterResponse,
  type MeterType,
} from "@/api/types";

const METER_TYPES = Object.keys(METER_TYPE_LABELS) as MeterType[];

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

async function openReadingPhoto(meterId: string, readingId: string): Promise<void> {
  const r = await api.get(`/admin/meters/${meterId}/readings/${readingId}/photo`, {
    responseType: "blob",
  });
  const url = URL.createObjectURL(r.data as Blob);
  window.open(url, "_blank", "noopener");
  // Revoke a bit later so the new tab has time to load the blob.
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

// --- create / edit dialog -----------------------------------------------------

interface MeterFormState {
  meter_number: string;
  meter_type: MeterType;
  description: string;
  location: string;
  unit_label: string;
  supplier_name: string;
  supplier_email: string;
  installation_date: string;
  calibration_valid_until: string;
  reading_due_date: string;
}

const EMPTY_FORM: MeterFormState = {
  meter_number: "",
  meter_type: "STROM",
  description: "",
  location: "",
  unit_label: "",
  supplier_name: "",
  supplier_email: "",
  installation_date: "",
  calibration_valid_until: "",
  reading_due_date: "",
};

// Mounted fresh per open (parent gates with `{formOpen && …}` + a key), so
// initial state comes straight from `editing` — no reset effect needed.
function MeterFormDialog({
  propertyId,
  editing,
  onClose,
  onSaved,
}: {
  propertyId: string;
  editing: MeterResponse | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState<MeterFormState>(() =>
    editing
      ? {
          meter_number: editing.meter_number,
          meter_type: editing.meter_type,
          description: editing.description ?? "",
          location: editing.location ?? "",
          unit_label: editing.unit_label ?? "",
          supplier_name: editing.supplier_name ?? "",
          supplier_email: editing.supplier_email ?? "",
          installation_date: editing.installation_date ?? "",
          calibration_valid_until: editing.calibration_valid_until ?? "",
          reading_due_date: editing.reading_due_date ?? "",
        }
      : EMPTY_FORM,
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const set = (k: keyof MeterFormState, v: string) =>
    setForm((prev) => ({ ...prev, [k]: v }));

  const save = async () => {
    if (!form.meter_number.trim()) {
      setError("Zählernummer ist erforderlich.");
      return;
    }
    setBusy(true);
    setError(null);
    const body: MeterCreateRequest = {
      meter_number: form.meter_number.trim(),
      meter_type: form.meter_type,
      description: form.description.trim() || null,
      location: form.location.trim() || null,
      unit_label: form.unit_label.trim() || null,
      supplier_name: form.supplier_name.trim() || null,
      supplier_email: form.supplier_email.trim() || null,
      installation_date: form.installation_date || null,
      calibration_valid_until: form.calibration_valid_until || null,
      reading_due_date: form.reading_due_date || null,
    };
    try {
      if (editing) {
        await api.patch(`/admin/meters/${editing.id}`, body);
      } else {
        await api.post(`/admin/properties/${propertyId}/meters`, body);
      }
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
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{editing ? "Zähler bearbeiten" : "Zähler hinzufügen"}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {error && <Alert severity="error">{error}</Alert>}
          <TextField
            label="Zählernummer"
            value={form.meter_number}
            onChange={(e) => set("meter_number", e.target.value)}
            required
            fullWidth
            size="small"
          />
          <TextField
            select
            label="Typ"
            value={form.meter_type}
            onChange={(e) => set("meter_type", e.target.value)}
            fullWidth
            size="small"
          >
            {METER_TYPES.map((t) => (
              <MenuItem key={t} value={t}>
                {METER_TYPE_LABELS[t]}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            label="Beschreibung (z. B. Allgemeinstrom, Betriebsstrom)"
            value={form.description}
            onChange={(e) => set("description", e.target.value)}
            fullWidth
            size="small"
          />
          <Stack direction="row" spacing={2}>
            <TextField
              label="Standort"
              value={form.location}
              onChange={(e) => set("location", e.target.value)}
              fullWidth
              size="small"
            />
            <TextField
              label="Einheit (kWh, m³)"
              value={form.unit_label}
              onChange={(e) => set("unit_label", e.target.value)}
              fullWidth
              size="small"
            />
          </Stack>
          <Stack direction="row" spacing={2}>
            <TextField
              label="Versorger"
              value={form.supplier_name}
              onChange={(e) => set("supplier_name", e.target.value)}
              fullWidth
              size="small"
            />
            <TextField
              label="Versorger-E-Mail"
              value={form.supplier_email}
              onChange={(e) => set("supplier_email", e.target.value)}
              fullWidth
              size="small"
            />
          </Stack>
          <Stack direction="row" spacing={2}>
            <TextField
              label="Einbaudatum"
              type="date"
              value={form.installation_date}
              onChange={(e) => set("installation_date", e.target.value)}
              fullWidth
              size="small"
              slotProps={{ inputLabel: { shrink: true } }}
            />
            <TextField
              label="Eichung gültig bis"
              type="date"
              value={form.calibration_valid_until}
              onChange={(e) => set("calibration_valid_until", e.target.value)}
              fullWidth
              size="small"
              slotProps={{ inputLabel: { shrink: true } }}
            />
          </Stack>
          <TextField
            label="Nächste Ablesung fällig"
            type="date"
            value={form.reading_due_date}
            onChange={(e) => set("reading_due_date", e.target.value)}
            fullWidth
            size="small"
            helperText="Erinnert Eigentümer/Mieter, den Zählerstand bis zu diesem Datum zu erfassen."
            slotProps={{ inputLabel: { shrink: true } }}
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={busy}>
          Abbrechen
        </Button>
        <Button variant="contained" onClick={save} disabled={busy}>
          {busy ? "Speichert…" : "Speichern"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

// --- Zählerwechsel (meter replacement) dialog ---------------------------------

// Mounted fresh per open (parent gates with `{replacing && …}` + a key), so the
// initial form state comes straight from the meter being replaced.
function MeterReplaceDialog({
  meter,
  onClose,
  onSaved,
}: {
  meter: MeterResponse;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [changeDate, setChangeDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [newNumber, setNewNumber] = useState("");
  const [oldFinal, setOldFinal] = useState("");
  const [newInitial, setNewInitial] = useState("0");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    if (!changeDate) {
      setError("Wechseldatum ist erforderlich.");
      return;
    }
    if (!newNumber.trim()) {
      setError("Neue Zählernummer ist erforderlich.");
      return;
    }
    if (oldFinal.trim() === "" || newInitial.trim() === "") {
      setError("Schlussstand und Anfangsstand sind erforderlich.");
      return;
    }
    setBusy(true);
    setError(null);
    const body: MeterReplaceRequest = {
      change_date: changeDate,
      new_meter_number: newNumber.trim(),
      old_final_reading: oldFinal.trim(),
      new_initial_reading: newInitial.trim(),
    };
    try {
      await api.post(`/admin/meters/${meter.id}/replace`, body);
      onSaved();
      onClose();
    } catch (e) {
      const detail =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Zählerwechsel fehlgeschlagen.";
      setError(detail);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Zähler wechseln</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {error && <Alert severity="error">{error}</Alert>}
          <Typography variant="body2" color="text.secondary">
            Alter Zähler <strong>{meter.meter_number}</strong> wird mit dem
            Schlussstand stillgelegt; ein neuer aktiver Zähler wird mit dem
            Anfangsstand angelegt. Die Historie des alten Zählers bleibt erhalten.
          </Typography>
          <TextField
            label="Wechseldatum"
            type="date"
            value={changeDate}
            onChange={(e) => setChangeDate(e.target.value)}
            required
            fullWidth
            size="small"
            slotProps={{ inputLabel: { shrink: true } }}
          />
          <TextField
            label="Neue Zählernummer"
            value={newNumber}
            onChange={(e) => setNewNumber(e.target.value)}
            required
            fullWidth
            size="small"
          />
          <Stack direction="row" spacing={2}>
            <TextField
              label={`Schlussstand (alt)${meter.unit_label ? ` in ${meter.unit_label}` : ""}`}
              type="number"
              value={oldFinal}
              onChange={(e) => setOldFinal(e.target.value)}
              required
              fullWidth
              size="small"
            />
            <TextField
              label={`Anfangsstand (neu)${meter.unit_label ? ` in ${meter.unit_label}` : ""}`}
              type="number"
              value={newInitial}
              onChange={(e) => setNewInitial(e.target.value)}
              required
              fullWidth
              size="small"
            />
          </Stack>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={busy}>
          Abbrechen
        </Button>
        <Button variant="contained" onClick={save} disabled={busy}>
          {busy ? "Wechselt…" : "Zähler wechseln"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

// --- bulk-import dialog --------------------------------------------------------

// Mounted fresh per open (parent gates with `{bulkOpen && …}`), so initial
// state is empty without a reset effect.
function BulkImportDialog({
  propertyId,
  onClose,
  onSaved,
}: {
  propertyId: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<MeterBulkCreateResponse | null>(null);

  // One meter per line: "Zählernummer; Typ; Beschreibung". Typ + Beschreibung
  // optional (Typ defaults to STROM). Separator ; or tab or comma.
  const parsed = useMemo<MeterCreateRequest[]>(() => {
    const out: MeterCreateRequest[] = [];
    for (const raw of text.split("\n")) {
      const line = raw.trim();
      if (!line) continue;
      const parts = line.split(/[;\t,]/).map((p) => p.trim());
      const number = parts[0];
      if (!number) continue;
      const typeRaw = (parts[1] ?? "").toUpperCase();
      const meter_type = (METER_TYPES as string[]).includes(typeRaw)
        ? (typeRaw as MeterType)
        : "STROM";
      out.push({
        meter_number: number,
        meter_type,
        description: parts[2] || null,
      });
    }
    return out;
  }, [text]);

  const submit = async () => {
    if (parsed.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.post<MeterBulkCreateResponse>(
        `/admin/properties/${propertyId}/meters/bulk`,
        { meters: parsed },
      );
      setResult(r.data);
      if (r.data.created.length > 0) onSaved();
    } catch {
      setError("Import fehlgeschlagen.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Zähler importieren</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {error && <Alert severity="error">{error}</Alert>}
          <Typography variant="body2" color="text.secondary">
            Eine Zeile pro Zähler: <code>Zählernummer; Typ; Beschreibung</code>.
            Typ ist optional ({METER_TYPES.join(" / ")}; Standard STROM),
            Beschreibung optional.
          </Typography>
          <TextField
            multiline
            minRows={6}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={"1ESY1234567890; STROM; Allgemeinstrom\n0815-GAS; GAS; Heizung Keller"}
            fullWidth
            disabled={!!result}
          />
          {!result && (
            <Typography variant="caption" color="text.secondary">
              {parsed.length} Zähler erkannt
            </Typography>
          )}
          {result && (
            <Alert severity={result.errors.length === 0 ? "success" : "warning"}>
              {result.created.length} angelegt
              {result.errors.length > 0 && `, ${result.errors.length} übersprungen`}
              {result.errors.length > 0 && (
                <Box component="ul" sx={{ m: 0, pl: 2 }}>
                  {result.errors.map((er) => (
                    <li key={er.index}>
                      Zeile {er.index + 1}
                      {er.meter_number ? ` (${er.meter_number})` : ""}: {er.error}
                    </li>
                  ))}
                </Box>
              )}
            </Alert>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={busy}>
          {result ? "Schließen" : "Abbrechen"}
        </Button>
        {!result && (
          <Button
            variant="contained"
            onClick={submit}
            disabled={busy || parsed.length === 0}
          >
            {busy ? "Importiert…" : `${parsed.length} anlegen`}
          </Button>
        )}
      </DialogActions>
    </Dialog>
  );
}

// --- readings panel (per-meter expand) ----------------------------------------

function ReadingsPanel({ meterId }: { meterId: string }) {
  const [rows, setRows] = useState<MeterReadingResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const r = await api.get<MeterReadingResponse[]>(`/admin/meters/${meterId}/readings`);
        if (!cancelled) setRows(r.data);
      } catch {
        if (!cancelled) setError("Ablesungen konnten nicht geladen werden.");
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
        Lade Ablesungen…
      </Typography>
    );
  if (rows.length === 0)
    return (
      <Typography variant="caption" color="text.secondary">
        Noch keine Ablesungen.
      </Typography>
    );

  return (
    <Table size="small">
      <TableHead>
        <TableRow>
          <TableCell>Datum</TableCell>
          <TableCell align="right">Wert</TableCell>
          <TableCell>Quelle</TableCell>
          <TableCell>Erfasst von</TableCell>
          <TableCell>Notiz</TableCell>
          <TableCell align="right">Foto</TableCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {rows.map((r) => (
          <TableRow key={r.id}>
            <TableCell>{fmtDate(r.read_on)}</TableCell>
            <TableCell align="right">{fmtNum(r.value)}</TableCell>
            <TableCell>
              <Chip
                size="small"
                variant="outlined"
                label={r.source === "OCR" ? "Foto/OCR" : "Manuell"}
              />
            </TableCell>
            <TableCell>
              <Typography variant="caption" color="text.secondary">
                {r.reported_by_email ?? "—"}
              </Typography>
            </TableCell>
            <TableCell>
              <Typography variant="caption" color="text.secondary">
                {r.note ?? "—"}
              </Typography>
            </TableCell>
            <TableCell align="right">
              {r.has_photo ? (
                <IconButton
                  size="small"
                  onClick={() => void openReadingPhoto(meterId, r.id)}
                  aria-label="Foto öffnen"
                >
                  <PhotoCameraIcon fontSize="small" />
                </IconButton>
              ) : (
                "—"
              )}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

// --- main tab -----------------------------------------------------------------

export function PropertyMetersTab({ propertyId }: { propertyId: string }) {
  const [meters, setMeters] = useState<MeterResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<MeterResponse | null>(null);
  const [replacing, setReplacing] = useState<MeterResponse | null>(null);
  const [bulkOpen, setBulkOpen] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const r = await api.get<MeterResponse[]>(`/admin/properties/${propertyId}/meters`);
      setMeters(r.data);
    } catch {
      setError("Zähler konnten nicht geladen werden.");
    }
  }, [propertyId]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const exportCsv = async () => {
    const r = await api.get(`/admin/properties/${propertyId}/meters/readings.csv`, {
      responseType: "blob",
    });
    const url = URL.createObjectURL(r.data as Blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `zaehlerstaende-${propertyId.slice(0, 8)}.csv`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 10_000);
  };

  if (meters === null) {
    return (
      <Typography variant="body2" color="text.secondary">
        Lade Zähler…
      </Typography>
    );
  }

  return (
    <Stack spacing={2}>
      {error && <Alert severity="error">{error}</Alert>}

      <Stack direction="row" spacing={1} sx={{ alignItems: "center", flexWrap: "wrap" }}>
        <Typography variant="body2" color="text.secondary" sx={{ flex: 1 }}>
          {meters.length} Zähler
        </Typography>
        <Button size="small" startIcon={<DownloadIcon />} onClick={() => void exportCsv()}>
          CSV-Export
        </Button>
        <Button
          size="small"
          variant="outlined"
          startIcon={<PlaylistAddIcon />}
          onClick={() => setBulkOpen(true)}
        >
          Importieren
        </Button>
        <Button
          size="small"
          variant="contained"
          startIcon={<AddIcon />}
          onClick={() => {
            setEditing(null);
            setFormOpen(true);
          }}
        >
          Zähler hinzufügen
        </Button>
      </Stack>

      <TableContainer sx={{ border: 1, borderColor: "divider", borderRadius: 1 }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell sx={{ width: 40 }} />
              <TableCell>Zählernummer</TableCell>
              <TableCell>Typ</TableCell>
              <TableCell>Beschreibung</TableCell>
              <TableCell align="right">Letzter Stand</TableCell>
              <TableCell>Versorger</TableCell>
              <TableCell align="right">Aktion</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {meters.map((m) => {
              const isOpen = expanded === m.id;
              return [
                <TableRow key={m.id} hover>
                  <TableCell>
                    <IconButton
                      size="small"
                      onClick={() => setExpanded(isOpen ? null : m.id)}
                      aria-label="Ablesungen anzeigen"
                    >
                      {isOpen ? <ExpandMoreIcon /> : <KeyboardArrowRightIcon />}
                    </IconButton>
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2" sx={{ fontWeight: 500 }}>
                      {m.meter_number}
                    </Typography>
                    {!m.is_active && (
                      <Chip size="small" label="inaktiv" sx={{ ml: 0.5 }} />
                    )}
                  </TableCell>
                  <TableCell>{METER_TYPE_LABELS[m.meter_type]}</TableCell>
                  <TableCell>
                    <Typography variant="caption" color="text.secondary">
                      {m.description ?? "—"}
                      {m.unit_name ? ` · ${m.unit_name}` : ""}
                    </Typography>
                  </TableCell>
                  <TableCell align="right">
                    {m.latest_reading_value !== null ? (
                      <>
                        {fmtNum(m.latest_reading_value)} {m.unit_label ?? ""}
                        <Typography
                          variant="caption"
                          color="text.secondary"
                          sx={{ display: "block" }}
                        >
                          {fmtDate(m.latest_reading_on)} · {m.reading_count}×
                        </Typography>
                      </>
                    ) : (
                      "—"
                    )}
                  </TableCell>
                  <TableCell>
                    <Typography variant="caption" color="text.secondary">
                      {m.supplier_name ?? "—"}
                    </Typography>
                  </TableCell>
                  <TableCell align="right">
                    {m.is_active && (
                      <Tooltip title="Zähler wechseln">
                        <IconButton size="small" onClick={() => setReplacing(m)}>
                          <SwapHorizIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    )}
                    <Tooltip title="Bearbeiten">
                      <IconButton
                        size="small"
                        onClick={() => {
                          setEditing(m);
                          setFormOpen(true);
                        }}
                      >
                        <EditIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  </TableCell>
                </TableRow>,
                <TableRow key={`${m.id}-readings`}>
                  <TableCell colSpan={7} sx={{ py: 0, border: 0 }}>
                    <Collapse in={isOpen} timeout="auto" unmountOnExit>
                      <Box sx={{ py: 1.5 }}>
                        <ReadingsPanel meterId={m.id} />
                      </Box>
                    </Collapse>
                  </TableCell>
                </TableRow>,
              ];
            })}
            {meters.length === 0 && (
              <TableRow>
                <TableCell colSpan={7}>
                  <Typography variant="body2" color="text.secondary" sx={{ p: 2 }}>
                    Noch keine Zähler. Über „Zähler hinzufügen" oder „Importieren" anlegen.
                  </Typography>
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </TableContainer>

      {formOpen && (
        <MeterFormDialog
          key={editing?.id ?? "new"}
          propertyId={propertyId}
          editing={editing}
          onClose={() => setFormOpen(false)}
          onSaved={() => void load()}
        />
      )}
      {bulkOpen && (
        <BulkImportDialog
          propertyId={propertyId}
          onClose={() => setBulkOpen(false)}
          onSaved={() => void load()}
        />
      )}
      {replacing && (
        <MeterReplaceDialog
          key={replacing.id}
          meter={replacing}
          onClose={() => setReplacing(null)}
          onSaved={() => void load()}
        />
      )}
    </Stack>
  );
}
