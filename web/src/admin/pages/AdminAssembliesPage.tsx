// Cross-property list of Eigentümerversammlungen with inline "new"
// dialog. Mirrors the AdminResolutionsPage shape (status chips, table,
// click-row → detail) so the two admin areas feel like the same app.
//
// "Neu" picks a property + start/end/title up front; everything else
// (description, agenda, location refinements, protocol upload) is
// edited on the detail page so this dialog stays simple.

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  MenuItem,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import { Link as RouterLink, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { api } from "@/api/client";
import {
  ASSEMBLY_STATUS_LABELS,
  type AssemblyResponse,
  type AssemblyStatus,
  type PropertyResponse,
} from "@/api/types";

const STATUS_COLOR: Record<
  AssemblyStatus,
  "default" | "primary" | "success" | "error"
> = {
  GEPLANT: "default",
  EINGELADEN: "primary",
  ABGEHALTEN: "success",
  ABGESAGT: "error",
};

function StatusChip({ status }: { status: AssemblyStatus }) {
  return (
    <Chip
      size="small"
      label={ASSEMBLY_STATUS_LABELS[status]}
      color={STATUS_COLOR[status]}
      variant={status === "GEPLANT" || status === "ABGESAGT" ? "outlined" : "filled"}
    />
  );
}

function formatDt(iso: string): string {
  return new Date(iso).toLocaleString("de-DE", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function AdminAssembliesPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [rows, setRows] = useState<AssemblyResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    setRows(null);
    try {
      const r = await api.get<AssemblyResponse[]>("/admin/assemblies");
      setRows(r.data);
    } catch {
      setError("Versammlungen konnten nicht geladen werden.");
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  return (
    <Stack spacing={3}>
      <Box
        sx={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          flexWrap: "wrap",
          gap: 2,
        }}
      >
        <Typography variant="h4" component="h1">
          {t("admin.assemblies")}
        </Typography>
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          onClick={() => setDialogOpen(true)}
        >
          Neue Versammlung
        </Button>
      </Box>

      {error && <Alert severity="error">{error}</Alert>}

      {rows === null ? (
        <Typography variant="body2" color="text.secondary">
          {t("common.loading")}
        </Typography>
      ) : rows.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          Es sind noch keine Versammlungen angelegt.
        </Typography>
      ) : (
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Status</TableCell>
                <TableCell>Titel</TableCell>
                <TableCell>Ort</TableCell>
                <TableCell>Beginn</TableCell>
                <TableCell>Ende</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((a) => (
                <TableRow
                  key={a.id}
                  hover
                  component={RouterLink}
                  to={`/admin/assemblies/${a.id}`}
                  sx={{
                    textDecoration: "none",
                    cursor: "pointer",
                    "& td": { color: "text.primary" },
                  }}
                >
                  <TableCell>
                    <StatusChip status={a.status} />
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2" sx={{ fontWeight: 500 }}>
                      {a.title}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      {a.protocol_pdf_url ? "Protokoll hochgeladen" : "Kein Protokoll"}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="caption" color="text.secondary">
                      {a.location}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="caption" color="text.secondary">
                      {formatDt(a.scheduled_start)}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="caption" color="text.secondary">
                      {formatDt(a.scheduled_end)}
                    </Typography>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      <NewAssemblyDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        onCreated={(id) => {
          setDialogOpen(false);
          navigate(`/admin/assemblies/${id}`);
        }}
      />
    </Stack>
  );
}

interface NewAssemblyDialogProps {
  open: boolean;
  onClose: () => void;
  onCreated: (id: string) => void;
}

function NewAssemblyDialog({ open, onClose, onCreated }: NewAssemblyDialogProps) {
  const [properties, setProperties] = useState<PropertyResponse[] | null>(null);
  const [propertyId, setPropertyId] = useState("");
  const [title, setTitle] = useState("Ordentliche Eigentümerversammlung");
  const [description, setDescription] = useState("");
  const [location, setLocation] = useState("");
  const [start, setStart] = useState<string>(suggestDateTime(7, 18));
  const [end, setEnd] = useState<string>(suggestDateTime(7, 21));
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    void api
      .get<PropertyResponse[]>("/me/properties")
      .then((r) => {
        if (!cancelled) {
          setProperties(r.data);
          const first = r.data[0];
          if (first && !propertyId) {
            setPropertyId(first.id);
          }
        }
      })
      .catch(() => {
        if (!cancelled) {
          setProperties([]);
          setError("Liegenschaften konnten nicht geladen werden.");
        }
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const canSubmit = useMemo(
    () =>
      !!propertyId &&
      title.trim().length >= 3 &&
      location.trim().length > 0 &&
      !!start &&
      !!end &&
      new Date(end) > new Date(start) &&
      !submitting,
    [propertyId, title, location, start, end, submitting],
  );

  const submit = async () => {
    if (!canSubmit) return;
    setError(null);
    setSubmitting(true);
    try {
      const r = await api.post<{ id: string }>(
        `/admin/properties/${propertyId}/assemblies`,
        {
          property_id: propertyId,
          title: title.trim(),
          description: description.trim(),
          scheduled_start: new Date(start).toISOString(),
          scheduled_end: new Date(end).toISOString(),
          location: location.trim(),
        },
      );
      onCreated(r.data.id);
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Anlegen fehlgeschlagen.";
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Neue Versammlung anlegen</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {error && <Alert severity="error">{error}</Alert>}
          <TextField
            label="Liegenschaft"
            select
            value={propertyId}
            onChange={(e) => setPropertyId(e.target.value)}
            required
            fullWidth
            disabled={properties === null}
          >
            {(properties ?? []).map((p) => (
              <MenuItem key={p.id} value={p.id}>
                {p.name}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            label="Titel"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
            fullWidth
          />
          <TextField
            label="Ort"
            value={location}
            onChange={(e) => setLocation(e.target.value)}
            required
            helperText="z. B. Vereinsheim Königstraße 42, 70173 Stuttgart"
            fullWidth
          />
          <Stack direction="row" spacing={2}>
            <TextField
              label="Beginn"
              type="datetime-local"
              value={start}
              onChange={(e) => setStart(e.target.value)}
              required
              fullWidth
              slotProps={{ inputLabel: { shrink: true } }}
            />
            <TextField
              label="Ende"
              type="datetime-local"
              value={end}
              onChange={(e) => setEnd(e.target.value)}
              required
              fullWidth
              slotProps={{ inputLabel: { shrink: true } }}
            />
          </Stack>
          <TextField
            label="Beschreibung (optional)"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            multiline
            minRows={3}
            fullWidth
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={submitting}>
          Abbrechen
        </Button>
        <Button
          variant="contained"
          onClick={submit}
          disabled={!canSubmit}
        >
          {submitting ? "Wird angelegt…" : "Anlegen"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

// Returns a value compatible with <input type="datetime-local"> set to
// `offsetDays` from now at `hour:00` local time.
function suggestDateTime(offsetDays: number, hour: number): string {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  d.setHours(hour, 0, 0, 0);
  // Strip seconds + tz to match the input format
  const pad = (n: number) => n.toString().padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
