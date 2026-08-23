// Correct a driver's trip from the admin Fahrtenbuch: purpose, property,
// note. Distance stays what the phone measured — the Verwalter fixes the
// bookkeeping side, not the GPS.

import { useEffect, useState } from "react";
import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { useTranslation } from "react-i18next";
import { api } from "@/api/client";
import type { AdminPropertyListItem, TripResponse } from "@/api/types";
import { purposeLabel } from "@/lib/trips";

const PURPOSES = [
  "BESICHTIGUNG",
  "ETV",
  "HANDWERKERTERMIN",
  "EIGENTUEMERTERMIN",
  "BUERO",
  "SONSTIGES",
  "PRIVAT",
] as const;
const WANTS_PROPERTY = new Set(["BESICHTIGUNG", "ETV", "HANDWERKERTERMIN", "EIGENTUEMERTERMIN"]);

interface Props {
  trip: TripResponse;
  /** [id, name] pairs offered in the property select (from the month's trips). */
  properties: [string, string][];
  onClose: () => void;
  onSaved: () => void;
}

export function TripEditDialog({ trip, properties, onClose, onSaved }: Props) {
  const { t } = useTranslation();
  const [purpose, setPurpose] = useState<string>(trip.purpose ?? "");
  const [propertyId, setPropertyId] = useState<string>(trip.property_id ?? "");
  const [note, setNote] = useState<string>(trip.note ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Offer EVERY property of the org (not just the month's), so a trip can be
  // pointed at any object; the month list is the instant fallback while the
  // full list loads. The trip's own property stays selectable regardless.
  const [allProperties, setAllProperties] = useState<[string, string][] | null>(null);
  useEffect(() => {
    api
      .get<AdminPropertyListItem[]>("/admin/properties")
      .then((r) =>
        setAllProperties(
          r.data
            .map((p): [string, string] => [p.id, p.name])
            .sort((a, b) => a[1].localeCompare(b[1])),
        ),
      )
      .catch(() => setAllProperties(null));
  }, []);
  const base = allProperties ?? properties;
  const options: [string, string][] =
    trip.property_id && trip.property_name && !base.some(([id]) => id === trip.property_id)
      ? [[trip.property_id, trip.property_name], ...base]
      : base;

  const wantsProperty = !purpose || WANTS_PROPERTY.has(purpose);

  const save = async () => {
    setBusy(true);
    setError(null);
    const body: Record<string, unknown> = { note: note || null };
    if (purpose) body.purpose = purpose;
    body.property_id = wantsProperty && propertyId ? propertyId : null;
    try {
      await api.patch(`/admin/trips/${trip.id}`, body);
      onSaved();
    } catch {
      setError(t("admin.fahrten.saveFailed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>{t("admin.fahrten.editTitle")}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <Typography variant="body2" color="text.secondary">
            {new Date(trip.started_at).toLocaleString("de-DE", { dateStyle: "medium", timeStyle: "short" })}
            {" · "}
            {trip.user_email ?? "—"}
            {" · "}
            {((trip.distance_m ?? 0) / 1000).toLocaleString("de-DE", { maximumFractionDigits: 1 })} km
          </Typography>
          {error && <Alert severity="error">{error}</Alert>}
          <FormControl size="small" fullWidth>
            <InputLabel>{t("admin.fahrten.purpose")}</InputLabel>
            <Select value={purpose} label={t("admin.fahrten.purpose")} onChange={(e) => setPurpose(e.target.value)}>
              {PURPOSES.map((p) => (
                <MenuItem key={p} value={p}>{purposeLabel(p)}</MenuItem>
              ))}
            </Select>
          </FormControl>
          {wantsProperty && (
            <FormControl size="small" fullWidth>
              <InputLabel>{t("admin.fahrten.property")}</InputLabel>
              <Select value={propertyId} label={t("admin.fahrten.property")} onChange={(e) => setPropertyId(e.target.value)}>
                <MenuItem value="">—</MenuItem>
                {options.map(([id, name]) => (
                  <MenuItem key={id} value={id}>{name}</MenuItem>
                ))}
              </Select>
            </FormControl>
          )}
          <TextField
            size="small"
            label={t("admin.fahrten.note")}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            multiline
            minRows={2}
            fullWidth
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={busy}>{t("common.cancel")}</Button>
        <Button variant="contained" onClick={() => void save()} disabled={busy}>{t("common.save")}</Button>
      </DialogActions>
    </Dialog>
  );
}
