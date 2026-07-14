// Shared create/edit dialog for Versorgungsverträge — used by the property
// detail tab and the org-wide /admin/vertraege board (the board also picks
// the Objekt when creating).

import { useEffect, useState } from "react";
import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  MenuItem,
  Stack,
  Switch,
  TextField,
} from "@mui/material";
import { api } from "@/api/client";
import {
  SUPPLIER_CATEGORY_LABELS,
  SUPPLIER_STATUS_LABELS,
  type MeterResponse,
  type SupplierContractCategory,
  type SupplierContractStatus,
} from "@/api/types";
import type { ContractDraft } from "@/lib/supplierContracts";

const CATEGORIES = Object.keys(SUPPLIER_CATEGORY_LABELS) as SupplierContractCategory[];
const STATUSES = Object.keys(SUPPLIER_STATUS_LABELS) as SupplierContractStatus[];

interface Props {
  draft: ContractDraft | null;
  setDraft: (d: ContractDraft | null) => void;
  busy: boolean;
  error: string | null;
  onSave: () => void;
  // Property context: fixed (tab) or selectable (board create).
  propertyId: string;
  propertyPicker?: {
    properties: { id: string; name: string }[];
    onChange: (propertyId: string) => void;
  };
}

export function SupplierContractDialog({
  draft,
  setDraft,
  busy,
  error,
  onSave,
  propertyId,
  propertyPicker,
}: Props) {
  const [meters, setMeters] = useState<MeterResponse[]>([]);

  useEffect(() => {
    if (!draft || !propertyId) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setMeters([]);
      return;
    }
    let cancelled = false;
    api
      .get<MeterResponse[]>(`/admin/properties/${propertyId}/meters`)
      .then((r) => {
        if (!cancelled) setMeters(r.data);
      })
      .catch(() => {
        if (!cancelled) setMeters([]);
      });
    return () => {
      cancelled = true;
    };
  }, [draft !== null, propertyId]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <Dialog open={draft !== null} onClose={() => setDraft(null)} fullWidth maxWidth="sm">
      <DialogTitle>{draft?.id ? "Vertrag bearbeiten" : "Vertrag anlegen"}</DialogTitle>
      {draft && (
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            {propertyPicker && !draft.id && (
              <TextField
                select
                label="Objekt"
                value={propertyId}
                onChange={(e) => {
                  // A meter belongs to exactly one Objekt — drop the selection
                  // when the Objekt changes, or Save 400s on a stale meter_id
                  // that the (now blank) Zähler select can't even show.
                  propertyPicker.onChange(e.target.value);
                  setDraft({ ...draft, meter_id: "" });
                }}
                fullWidth
              >
                {propertyPicker.properties.map((p) => (
                  <MenuItem key={p.id} value={p.id}>
                    {p.name}
                  </MenuItem>
                ))}
              </TextField>
            )}
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <TextField
                select
                label="Kategorie"
                value={draft.category}
                onChange={(e) =>
                  setDraft({ ...draft, category: e.target.value as SupplierContractCategory })
                }
                fullWidth
              >
                {CATEGORIES.map((c) => (
                  <MenuItem key={c} value={c}>
                    {SUPPLIER_CATEGORY_LABELS[c]}
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                label="Anbieter"
                value={draft.provider_name}
                onChange={(e) => setDraft({ ...draft, provider_name: e.target.value })}
                fullWidth
              />
            </Stack>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <TextField
                select
                label="Status"
                value={draft.status}
                onChange={(e) =>
                  setDraft({ ...draft, status: e.target.value as SupplierContractStatus })
                }
                fullWidth
              >
                {STATUSES.map((s) => (
                  <MenuItem key={s} value={s}>
                    {SUPPLIER_STATUS_LABELS[s]}
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                select
                label="Zähler (optional)"
                value={draft.meter_id}
                onChange={(e) => setDraft({ ...draft, meter_id: e.target.value })}
                fullWidth
              >
                <MenuItem value="">Kein Zähler</MenuItem>
                {meters.map((m) => (
                  <MenuItem key={m.id} value={m.id}>
                    {m.meter_number} ({m.meter_type})
                  </MenuItem>
                ))}
              </TextField>
            </Stack>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <TextField
                label="Vertragsnummer"
                value={draft.contract_number}
                onChange={(e) => setDraft({ ...draft, contract_number: e.target.value })}
                fullWidth
              />
              <TextField
                label="Kundennummer"
                value={draft.customer_number}
                onChange={(e) => setDraft({ ...draft, customer_number: e.target.value })}
                fullWidth
              />
            </Stack>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <TextField
                label="Beginn"
                type="date"
                value={draft.start_date}
                onChange={(e) => setDraft({ ...draft, start_date: e.target.value })}
                slotProps={{ inputLabel: { shrink: true } }}
                fullWidth
              />
              <TextField
                label="Ende"
                type="date"
                value={draft.end_date}
                onChange={(e) => setDraft({ ...draft, end_date: e.target.value })}
                slotProps={{ inputLabel: { shrink: true } }}
                fullWidth
              />
            </Stack>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <TextField
                label="Kündigungsfrist (Monate)"
                type="number"
                value={draft.cancellation_months}
                onChange={(e) => setDraft({ ...draft, cancellation_months: e.target.value })}
                slotProps={{ htmlInput: { min: 0, max: 60 } }}
                fullWidth
              />
              <FormControlLabel
                sx={{ minWidth: 220 }}
                control={
                  <Switch
                    checked={draft.auto_renew}
                    onChange={(e) => setDraft({ ...draft, auto_renew: e.target.checked })}
                  />
                }
                label="Verlängert sich automatisch"
              />
            </Stack>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <TextField
                label="Preis (€)"
                type="number"
                value={draft.price}
                onChange={(e) => setDraft({ ...draft, price: e.target.value })}
                slotProps={{ htmlInput: { min: 0, step: "0.01" } }}
                fullWidth
              />
              <TextField
                select
                label="Turnus"
                value={draft.price_period}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    price_period: e.target.value as ContractDraft["price_period"],
                  })
                }
                fullWidth
              >
                <MenuItem value="MONATLICH">monatlich</MenuItem>
                <MenuItem value="JAEHRLICH">jährlich</MenuItem>
              </TextField>
            </Stack>
            <TextField
              label="Notiz"
              value={draft.notes}
              onChange={(e) => setDraft({ ...draft, notes: e.target.value })}
              multiline
              minRows={2}
              fullWidth
            />
            {error && <Alert severity="error">{error}</Alert>}
          </Stack>
        </DialogContent>
      )}
      <DialogActions>
        <Button onClick={() => setDraft(null)}>Abbrechen</Button>
        <Button
          variant="contained"
          onClick={onSave}
          disabled={busy || !draft?.provider_name.trim() || (!draft?.id && !propertyId)}
        >
          Speichern
        </Button>
      </DialogActions>
    </Dialog>
  );
}
