import { useEffect, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  Link,
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
import EditIcon from "@mui/icons-material/Edit";
import { useTranslation } from "react-i18next";
import { api } from "@/api/client";
import type {
  AdminUnitDistributionKeysUpdate,
  AdminUnitListItem,
} from "@/api/types";
import { propertyHasOwnershipShares, propertyTypeLabel } from "@/lib/propertyType";

export function AdminUnitsPage() {
  const { t } = useTranslation();
  const [rows, setRows] = useState<AdminUnitListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // The unit currently in the inline-edit dialog. null = dialog closed.
  // We track the whole row (not just the id) so the dialog body has
  // immediate access to property_type for gating the MEA field — saves
  // an extra round-trip + matches what the user just clicked.
  const [editing, setEditing] = useState<AdminUnitListItem | null>(null);

  useEffect(() => {
    api
      .get<AdminUnitListItem[]>("/admin/units")
      .then((r) => setRows(r.data))
      .catch(() => setError(t("admin.stammdaten.loadFailed")));
  }, [t]);

  /// Called by the dialog after a successful PUT. Replaces the row
  /// in-place so the table reflects the new values without a full
  /// refetch (and without scroll-jumping the operator).
  const handleSaved = (updated: AdminUnitListItem) => {
    setRows((prev) =>
      prev ? prev.map((u) => (u.id === updated.id ? updated : u)) : prev,
    );
    setEditing(null);
  };

  if (error) return <Alert severity="error">{error}</Alert>;
  if (rows === null) {
    return (
      <Typography variant="body2" color="text.secondary">
        {t("common.loading")}
      </Typography>
    );
  }

  return (
    <Stack spacing={3}>
      <Typography variant="h4" component="h1">
        {t("admin.unitsPage.title")}
      </Typography>
      <Alert severity="info" variant="outlined">
        {/* Manual-fill note: Impower's REST API doesn't expose the
            distribution-keys panel ("Eigenschaften der Einheiten"),
            so the Verwalter enters MEA + Fläche + Heizfläche +
            Personen here. See ADR-0009 for the eventual browser-
            extension path that auto-fills from an open Impower tab. */}
        Distributionsschlüssel (MEA, Fläche, Heizfläche, Personen) müssen
        derzeit manuell gepflegt werden — die Impower-API liefert sie
        nicht aus. Eine Browser-Erweiterung zum Auto-Ausfüllen aus
        Impower ist geplant.
      </Alert>

      {rows.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          {t("admin.stammdaten.empty")}
        </Typography>
      ) : (
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>{t("admin.unitsPage.property")}</TableCell>
                <TableCell>{t("admin.unitsPage.unit")}</TableCell>
                <TableCell>{t("admin.unitsPage.type")}</TableCell>
                <TableCell>{t("admin.unitsPage.floor")}</TableCell>
                <TableCell>{t("admin.unitsPage.position")}</TableCell>
                <TableCell align="right">MEA</TableCell>
                <TableCell align="right">Fläche (m²)</TableCell>
                <TableCell align="right">Heizfl. (m²)</TableCell>
                <TableCell align="right">Personen</TableCell>
                <TableCell align="right" />
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((u) => (
                <TableRow key={u.id} hover>
                  <TableCell>
                    <Stack
                      direction="row"
                      spacing={1}
                      sx={{ alignItems: "center" }}
                    >
                      <Link
                        component={RouterLink}
                        to={`/admin/properties/${u.property_id}`}
                        underline="hover"
                        sx={{ fontWeight: 500 }}
                      >
                        {u.property_name}
                      </Link>
                      <Typography
                        variant="caption"
                        color="text.secondary"
                        sx={{
                          border: "1px solid",
                          borderColor: "divider",
                          borderRadius: 0.5,
                          px: 0.5,
                          fontSize: "0.7rem",
                          letterSpacing: 0.5,
                        }}
                      >
                        {propertyTypeLabel(u.property_type)}
                      </Typography>
                    </Stack>
                  </TableCell>
                  <TableCell
                    sx={{ fontFamily: "ui-monospace, Menlo, monospace" }}
                  >
                    {u.unit_hr_id ?? "—"}
                  </TableCell>
                  <TableCell>
                    <Typography variant="caption" color="text.secondary">
                      {u.type}
                    </Typography>
                  </TableCell>
                  <TableCell>{u.floor ?? "—"}</TableCell>
                  <TableCell>{u.position ?? "—"}</TableCell>
                  <TableCell align="right">
                    {/* MEA only meaningful for WEG/SEV — show "—" for
                        MV rather than the bare number, so the operator
                        knows the column doesn't apply rather than
                        thinking the value is unset. */}
                    {propertyHasOwnershipShares(u.property_type)
                      ? u.voting_share != null
                        ? u.voting_share.toLocaleString("de-DE", {
                            minimumFractionDigits: 0,
                            maximumFractionDigits: 4,
                          })
                        : "—"
                      : "—"}
                  </TableCell>
                  <TableCell align="right">
                    {u.area_m2 != null
                      ? u.area_m2.toLocaleString("de-DE", {
                          minimumFractionDigits: 2,
                          maximumFractionDigits: 2,
                        })
                      : "—"}
                  </TableCell>
                  <TableCell align="right">
                    {u.heated_area_m2 != null
                      ? u.heated_area_m2.toLocaleString("de-DE", {
                          minimumFractionDigits: 2,
                          maximumFractionDigits: 2,
                        })
                      : "—"}
                  </TableCell>
                  <TableCell align="right">
                    {u.persons != null
                      ? u.persons.toLocaleString("de-DE", {
                          minimumFractionDigits: 0,
                          maximumFractionDigits: 1,
                        })
                      : "—"}
                  </TableCell>
                  <TableCell align="right">
                    <IconButton
                      size="small"
                      onClick={() => setEditing(u)}
                      aria-label="Verteilungsschlüssel bearbeiten"
                    >
                      <EditIcon fontSize="small" />
                    </IconButton>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}
      {rows.length >= 200 && (
        <Typography variant="caption" color="text.secondary">
          {t("admin.stammdaten.limitNote")}
        </Typography>
      )}

      {editing && (
        <DistributionKeysDialog
          unit={editing}
          onClose={() => setEditing(null)}
          onSaved={handleSaved}
        />
      )}
    </Stack>
  );
}

/// Inline editor for the four manual-fill distribution keys.
///
/// Number-input UX is deliberately permissive: empty string = clear
/// the field (PUT null). The MEA field is hidden entirely on MV
/// properties — there's no "Anteile" concept on a rental, so showing
/// an editable cell would invite bad data. Saves go through
/// `PUT /admin/units/{id}/distribution-keys`; the response is the
/// updated row, which the parent splices into the table.
function DistributionKeysDialog({
  unit,
  onClose,
  onSaved,
}: {
  unit: AdminUnitListItem;
  onClose: () => void;
  onSaved: (u: AdminUnitListItem) => void;
}) {
  const showMea = propertyHasOwnershipShares(unit.property_type);
  // String state — TextField type="number" still returns string from
  // onChange and we want to distinguish "" (clear → null) from "0"
  // (explicit zero). Parsing happens at submit time.
  const [mea, setMea] = useState<string>(
    unit.voting_share != null ? String(unit.voting_share) : "",
  );
  const [area, setArea] = useState<string>(
    unit.area_m2 != null ? String(unit.area_m2) : "",
  );
  const [heated, setHeated] = useState<string>(
    unit.heated_area_m2 != null ? String(unit.heated_area_m2) : "",
  );
  const [persons, setPersons] = useState<string>(
    unit.persons != null ? String(unit.persons) : "",
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setError(null);
    setBusy(true);
    try {
      const body: AdminUnitDistributionKeysUpdate = {
        voting_share: showMea && mea.trim() !== "" ? Number(mea) : null,
        area_m2: area.trim() !== "" ? Number(area) : null,
        heated_area_m2: heated.trim() !== "" ? Number(heated) : null,
        persons: persons.trim() !== "" ? Number(persons) : null,
      };
      const r = await api.put<AdminUnitListItem>(
        `/admin/units/${unit.id}/distribution-keys`,
        body,
      );
      onSaved(r.data);
    } catch {
      setError("Speichern fehlgeschlagen. Bitte erneut versuchen.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open onClose={busy ? undefined : onClose} maxWidth="xs" fullWidth>
      <DialogTitle>
        Verteilungsschlüssel · {unit.property_name} · {unit.unit_hr_id ?? "—"}
      </DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          {showMea && (
            <TextField
              label="MEA (Miteigentumsanteil)"
              type="number"
              value={mea}
              onChange={(e) => setMea(e.target.value)}
              fullWidth
              slotProps={{ htmlInput: { step: "any", min: 0 } }}
              helperText="z. B. 276 von 1.000"
            />
          )}
          <TextField
            label="Fläche (m²)"
            type="number"
            value={area}
            onChange={(e) => setArea(e.target.value)}
            fullWidth
            slotProps={{ htmlInput: { step: "any", min: 0 } }}
          />
          <TextField
            label="Heizfläche (m²)"
            type="number"
            value={heated}
            onChange={(e) => setHeated(e.target.value)}
            fullWidth
            slotProps={{ htmlInput: { step: "any", min: 0 } }}
            helperText="Optional — leer lassen, wenn unbekannt"
          />
          <TextField
            label="Personen"
            type="number"
            value={persons}
            onChange={(e) => setPersons(e.target.value)}
            fullWidth
            slotProps={{ htmlInput: { step: "any", min: 0 } }}
          />
          {error && <Alert severity="error">{error}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={busy}>
          Abbrechen
        </Button>
        <Button onClick={submit} variant="contained" disabled={busy}>
          {busy ? "Speichert…" : "Speichern"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
