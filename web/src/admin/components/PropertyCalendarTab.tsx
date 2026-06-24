// Kalender tab on the admin property detail (ADR-0018). Month grid with the
// property's events + derived ETV dates; the Verwalter adds/edits
// Winterdienst/Kehrwoche/Termin entries and exports a WHV-design month PDF.

import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import DownloadIcon from "@mui/icons-material/Download";
import { api } from "@/api/client";
import {
  CALENDAR_KIND_LABELS,
  type CalendarEntry,
  type CalendarEventCreateRequest,
  type CalendarEventType,
} from "@/api/types";
import { CalendarMonth } from "@/components/CalendarMonth";

const MONTHS_DE = [
  "Januar", "Februar", "März", "April", "Mai", "Juni",
  "Juli", "August", "September", "Oktober", "November", "Dezember",
];
const EVENT_TYPES: CalendarEventType[] = ["WINTERDIENST", "KEHRWOCHE", "TERMIN"];

interface DialogState {
  id: string | null; // null = create
  event_type: CalendarEventType;
  title: string;
  starts_on: string;
  ends_on: string;
  assigned_label: string;
  note: string;
}

function entryToDialog(e: CalendarEntry): DialogState {
  return {
    id: e.id,
    event_type: (e.kind === "ETV" ? "TERMIN" : e.kind) as CalendarEventType,
    title: e.title,
    starts_on: e.starts_on,
    ends_on: e.ends_on ?? "",
    assigned_label: e.assigned_label ?? "",
    note: e.note ?? "",
  };
}

function CalendarEventDialog({
  propertyId,
  initial,
  onClose,
  onSaved,
}: {
  propertyId: string;
  initial: DialogState;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState<DialogState>(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = (k: keyof DialogState, v: string) => setForm((p) => ({ ...p, [k]: v }));

  const save = async () => {
    if (!form.starts_on) {
      setError("Bitte ein Startdatum wählen.");
      return;
    }
    setBusy(true);
    setError(null);
    const body: CalendarEventCreateRequest = {
      event_type: form.event_type,
      title: form.title.trim() || null,
      starts_on: form.starts_on,
      ends_on: form.ends_on || null,
      assigned_label: form.assigned_label.trim() || null,
      note: form.note.trim() || null,
    };
    try {
      if (form.id) {
        await api.patch(`/admin/calendar/events/${form.id}`, body);
      } else {
        await api.post(`/admin/properties/${propertyId}/calendar/events`, body);
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

  const remove = async () => {
    if (!form.id) return;
    setBusy(true);
    try {
      await api.delete(`/admin/calendar/events/${form.id}`);
      onSaved();
      onClose();
    } catch {
      setError("Löschen fehlgeschlagen.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{form.id ? "Termin bearbeiten" : "Termin hinzufügen"}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {error && <Alert severity="error">{error}</Alert>}
          <TextField
            select
            label="Art"
            value={form.event_type}
            onChange={(e) => set("event_type", e.target.value)}
            size="small"
            fullWidth
          >
            {EVENT_TYPES.map((t) => (
              <MenuItem key={t} value={t}>
                {CALENDAR_KIND_LABELS[t]}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            label="Titel (optional)"
            value={form.title}
            onChange={(e) => set("title", e.target.value)}
            size="small"
            fullWidth
          />
          <Stack direction="row" spacing={2}>
            <TextField
              label="Von"
              type="date"
              value={form.starts_on}
              onChange={(e) => set("starts_on", e.target.value)}
              size="small"
              fullWidth
              slotProps={{ inputLabel: { shrink: true } }}
            />
            <TextField
              label="Bis (optional)"
              type="date"
              value={form.ends_on}
              onChange={(e) => set("ends_on", e.target.value)}
              size="small"
              fullWidth
              slotProps={{ inputLabel: { shrink: true } }}
            />
          </Stack>
          <TextField
            label="Zuständig (z. B. Familie Müller)"
            value={form.assigned_label}
            onChange={(e) => set("assigned_label", e.target.value)}
            size="small"
            fullWidth
          />
          <TextField
            label="Notiz (optional)"
            value={form.note}
            onChange={(e) => set("note", e.target.value)}
            size="small"
            fullWidth
            multiline
            minRows={2}
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        {form.id && (
          <Button color="error" onClick={() => void remove()} disabled={busy} sx={{ mr: "auto" }}>
            Löschen
          </Button>
        )}
        <Button onClick={onClose} disabled={busy}>
          Abbrechen
        </Button>
        <Button variant="contained" onClick={() => void save()} disabled={busy}>
          {busy ? "Speichert…" : "Speichern"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

export function PropertyCalendarTab({ propertyId }: { propertyId: string }) {
  const navigate = useNavigate();
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [entries, setEntries] = useState<CalendarEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dialog, setDialog] = useState<DialogState | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const r = await api.get<CalendarEntry[]>(
        `/admin/properties/${propertyId}/calendar?year=${year}&month=${month}`,
      );
      setEntries(r.data);
    } catch {
      setError("Kalender konnte nicht geladen werden.");
    }
  }, [propertyId, year, month]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const shift = (delta: number) => {
    const d = new Date(year, month - 1 + delta, 1);
    setYear(d.getFullYear());
    setMonth(d.getMonth() + 1);
  };

  const blankDialog = (date?: string): DialogState => ({
    id: null,
    event_type: "WINTERDIENST",
    title: "",
    starts_on: date ?? `${year}-${String(month).padStart(2, "0")}-01`,
    ends_on: "",
    assigned_label: "",
    note: "",
  });

  const onEntry = (e: CalendarEntry) => {
    if (e.source === "etv") {
      if (e.assembly_id) navigate(`/admin/assemblies/${e.assembly_id}`);
    } else {
      setDialog(entryToDialog(e));
    }
  };

  const exportPdf = async () => {
    const r = await api.get(
      `/admin/properties/${propertyId}/calendar.pdf?year=${year}&month=${month}`,
      { responseType: "blob" },
    );
    const url = URL.createObjectURL(r.data as Blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `kalender-${year}-${String(month).padStart(2, "0")}.pdf`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 10_000);
  };

  return (
    <Stack spacing={2}>
      {error && <Alert severity="error">{error}</Alert>}

      <Stack direction="row" spacing={1} sx={{ alignItems: "center", flexWrap: "wrap" }}>
        <IconButton onClick={() => shift(-1)} aria-label="Vorheriger Monat">
          <ChevronLeftIcon />
        </IconButton>
        <Typography variant="h6" sx={{ minWidth: 150, textAlign: "center" }}>
          {MONTHS_DE[month - 1]} {year}
        </Typography>
        <IconButton onClick={() => shift(1)} aria-label="Nächster Monat">
          <ChevronRightIcon />
        </IconButton>
        <span style={{ flex: 1 }} />
        <Button size="small" startIcon={<DownloadIcon />} onClick={() => void exportPdf()}>
          PDF
        </Button>
        <Button
          size="small"
          variant="contained"
          startIcon={<AddIcon />}
          onClick={() => setDialog(blankDialog())}
        >
          Termin hinzufügen
        </Button>
      </Stack>

      <CalendarMonth
        year={year}
        month={month}
        entries={entries ?? []}
        onDayClick={(iso) => setDialog(blankDialog(iso))}
        onEntryClick={onEntry}
      />

      <Typography variant="caption" color="text.secondary">
        Tag anklicken, um einen Termin anzulegen. ETV-Termine stammen aus den Versammlungen.
      </Typography>

      {dialog && (
        <CalendarEventDialog
          propertyId={propertyId}
          initial={dialog}
          onClose={() => setDialog(null)}
          onSaved={() => void load()}
        />
      )}
    </Stack>
  );
}
