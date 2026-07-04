// Verträge tab on the admin property detail — the WEG's supply/service
// contracts (Versicherung, Strom, Gas, Müll, …) with term + pricing metadata
// and an optional link to the billing meter. Verwalter-only CRUD.

import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  IconButton,
  MenuItem,
  Stack,
  Switch,
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
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutlineOutlined";
import EditIcon from "@mui/icons-material/Edit";
import { api } from "@/api/client";
import {
  SUPPLIER_CATEGORY_LABELS,
  type MeterResponse,
  type SupplierContractBody,
  type SupplierContractCategory,
  type SupplierContractResponse,
} from "@/api/types";
import { fmtContractDate, fmtPrice } from "@/lib/supplierContracts";

const CATEGORIES = Object.keys(SUPPLIER_CATEGORY_LABELS) as SupplierContractCategory[];

interface DraftState {
  id: string | null; // null = create
  category: SupplierContractCategory;
  provider_name: string;
  contract_number: string;
  customer_number: string;
  meter_id: string;
  start_date: string;
  end_date: string;
  cancellation_months: string;
  auto_renew: boolean;
  price: string;
  price_period: "" | "MONATLICH" | "JAEHRLICH";
  notes: string;
}

const EMPTY_DRAFT: DraftState = {
  id: null,
  category: "VERSICHERUNG",
  provider_name: "",
  contract_number: "",
  customer_number: "",
  meter_id: "",
  start_date: "",
  end_date: "",
  cancellation_months: "",
  auto_renew: true,
  price: "",
  price_period: "MONATLICH",
  notes: "",
};

function draftFrom(c: SupplierContractResponse): DraftState {
  return {
    id: c.id,
    category: c.category,
    provider_name: c.provider_name,
    contract_number: c.contract_number ?? "",
    customer_number: c.customer_number ?? "",
    meter_id: c.meter_id ?? "",
    start_date: c.start_date ?? "",
    end_date: c.end_date ?? "",
    cancellation_months: c.cancellation_months != null ? String(c.cancellation_months) : "",
    auto_renew: c.auto_renew ?? true,
    price: c.price != null ? String(c.price) : "",
    price_period: c.price_period ?? "",
    notes: c.notes ?? "",
  };
}

export function PropertySupplierContractsTab({ propertyId }: { propertyId: string }) {
  const [rows, setRows] = useState<SupplierContractResponse[]>([]);
  const [meters, setMeters] = useState<MeterResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<DraftState | null>(null);
  const [busy, setBusy] = useState(false);
  const [dialogError, setDialogError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [contracts, meterList] = await Promise.all([
        api.get<SupplierContractResponse[]>(
          `/admin/properties/${propertyId}/supplier-contracts`,
        ),
        api.get<MeterResponse[]>(`/admin/properties/${propertyId}/meters`),
      ]);
      setRows(contracts.data);
      setMeters(meterList.data);
    } catch {
      setError("Verträge konnten nicht geladen werden.");
    } finally {
      setLoading(false);
    }
  }, [propertyId]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  function bodyFrom(d: DraftState): SupplierContractBody {
    return {
      category: d.category,
      provider_name: d.provider_name.trim(),
      contract_number: d.contract_number.trim() || null,
      customer_number: d.customer_number.trim() || null,
      meter_id: d.meter_id || null,
      start_date: d.start_date || null,
      end_date: d.end_date || null,
      cancellation_months: d.cancellation_months ? Number(d.cancellation_months) : null,
      auto_renew: d.auto_renew,
      price: d.price ? Number(d.price.replace(",", ".")) : null,
      price_period: d.price ? d.price_period || null : null,
      notes: d.notes.trim() || null,
    };
  }

  async function save() {
    if (!draft) return;
    setBusy(true);
    setDialogError(null);
    try {
      if (draft.id) {
        const r = await api.put<SupplierContractResponse>(
          `/admin/supplier-contracts/${draft.id}`,
          bodyFrom(draft),
        );
        setRows((rs) => rs.map((x) => (x.id === draft.id ? r.data : x)));
      } else {
        const r = await api.post<SupplierContractResponse>(
          `/admin/properties/${propertyId}/supplier-contracts`,
          bodyFrom(draft),
        );
        setRows((rs) => [...rs, r.data]);
      }
      setDraft(null);
    } catch {
      setDialogError("Vertrag konnte nicht gespeichert werden.");
    } finally {
      setBusy(false);
    }
  }

  async function remove(c: SupplierContractResponse) {
    if (
      !window.confirm(
        `Vertrag „${c.provider_name}“ (${SUPPLIER_CATEGORY_LABELS[c.category]}) löschen?`,
      )
    )
      return;
    setError(null);
    try {
      await api.delete(`/admin/supplier-contracts/${c.id}`);
      setRows((rs) => rs.filter((x) => x.id !== c.id));
    } catch {
      setError("Vertrag konnte nicht gelöscht werden.");
    }
  }

  if (loading) return <CircularProgress sx={{ mt: 2 }} />;

  return (
    <Box sx={{ mt: 2 }}>
      <Stack direction="row" sx={{ justifyContent: "space-between", alignItems: "center", mb: 2 }}>
        <Typography variant="h6">Versorgungsverträge</Typography>
        <Button
          variant="contained"
          size="small"
          startIcon={<AddIcon />}
          onClick={() => setDraft(EMPTY_DRAFT)}
        >
          Vertrag anlegen
        </Button>
      </Stack>
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {rows.length === 0 ? (
        <Typography color="text.secondary">Noch keine Verträge erfasst.</Typography>
      ) : (
        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Kategorie</TableCell>
                <TableCell>Anbieter</TableCell>
                <TableCell>Vertrags-Nr.</TableCell>
                <TableCell>Zähler</TableCell>
                <TableCell>Beginn</TableCell>
                <TableCell>Ende</TableCell>
                <TableCell>Kündigungsfrist</TableCell>
                <TableCell align="right">Preis</TableCell>
                <TableCell />
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((c) => (
                <TableRow key={c.id} hover>
                  <TableCell>
                    <Chip size="small" label={SUPPLIER_CATEGORY_LABELS[c.category]} />
                  </TableCell>
                  <TableCell>{c.provider_name}</TableCell>
                  <TableCell>{c.contract_number ?? "—"}</TableCell>
                  <TableCell>{c.meter_number ?? "—"}</TableCell>
                  <TableCell>{fmtContractDate(c.start_date)}</TableCell>
                  <TableCell sx={{ whiteSpace: "nowrap" }}>
                    {fmtContractDate(c.end_date)}
                    {c.auto_renew && (
                      <Tooltip title="Verlängert sich automatisch">
                        <Box component="span" sx={{ ml: 0.5, color: "text.secondary" }}>
                          ↻
                        </Box>
                      </Tooltip>
                    )}
                  </TableCell>
                  <TableCell>
                    {c.cancellation_months != null ? `${c.cancellation_months} Monate` : "—"}
                  </TableCell>
                  <TableCell align="right">{fmtPrice(c)}</TableCell>
                  <TableCell align="right" sx={{ whiteSpace: "nowrap" }}>
                    <Tooltip title="Bearbeiten">
                      <IconButton size="small" onClick={() => setDraft(draftFrom(c))}>
                        <EditIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                    <Tooltip title="Löschen">
                      <IconButton size="small" onClick={() => void remove(c)}>
                        <DeleteOutlineIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      <Dialog open={draft !== null} onClose={() => setDraft(null)} fullWidth maxWidth="sm">
        <DialogTitle>{draft?.id ? "Vertrag bearbeiten" : "Vertrag anlegen"}</DialogTitle>
        {draft && (
          <DialogContent>
            <Stack spacing={2} sx={{ mt: 1 }}>
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
              <TextField
                select
                label="Zähler (optional)"
                value={draft.meter_id}
                onChange={(e) => setDraft({ ...draft, meter_id: e.target.value })}
                helperText="Für Strom/Gas/Wasser: der Zähler, über den abgerechnet wird"
                fullWidth
              >
                <MenuItem value="">Kein Zähler</MenuItem>
                {meters.map((m) => (
                  <MenuItem key={m.id} value={m.id}>
                    {m.meter_number} ({m.meter_type})
                  </MenuItem>
                ))}
              </TextField>
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
                      price_period: e.target.value as DraftState["price_period"],
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
              {dialogError && <Alert severity="error">{dialogError}</Alert>}
            </Stack>
          </DialogContent>
        )}
        <DialogActions>
          <Button onClick={() => setDraft(null)}>Abbrechen</Button>
          <Button
            variant="contained"
            onClick={() => void save()}
            disabled={busy || !draft?.provider_name.trim()}
          >
            Speichern
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
