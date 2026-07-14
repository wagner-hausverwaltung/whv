// Verträge tab on the admin property detail — the WEG's supply/service
// contracts (Versicherung, Strom, Gas, Müll, …) with term + pricing metadata
// and an optional link to the billing meter. Verwalter-only CRUD; the
// create/edit dialog is shared with the org-wide board.

import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  IconButton,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutlineOutlined";
import EditIcon from "@mui/icons-material/Edit";
import { api } from "@/api/client";
import {
  SUPPLIER_CATEGORY_LABELS,
  SUPPLIER_STATUS_LABELS,
  type SupplierContractResponse,
} from "@/api/types";
import { fmtContractDate, fmtPrice } from "@/lib/supplierContracts";
import { SupplierContractDialog } from "@/admin/components/SupplierContractDialog";
import {
  EMPTY_DRAFT,
  bodyFromDraft,
  draftFrom,
  type ContractDraft,
} from "@/lib/supplierContracts";

export function PropertySupplierContractsTab({ propertyId }: { propertyId: string }) {
  const [rows, setRows] = useState<SupplierContractResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<ContractDraft | null>(null);
  const [busy, setBusy] = useState(false);
  const [dialogError, setDialogError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await api.get<SupplierContractResponse[]>(
        `/admin/properties/${propertyId}/supplier-contracts`,
      );
      setRows(r.data);
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

  async function save() {
    if (!draft) return;
    setBusy(true);
    setDialogError(null);
    try {
      if (draft.id) {
        const r = await api.put<SupplierContractResponse>(
          `/admin/supplier-contracts/${draft.id}`,
          bodyFromDraft(draft),
        );
        setRows((rs) => rs.map((x) => (x.id === draft.id ? r.data : x)));
      } else {
        const r = await api.post<SupplierContractResponse>(
          `/admin/properties/${propertyId}/supplier-contracts`,
          bodyFromDraft(draft),
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
                <TableCell>Status</TableCell>
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
                  <TableCell>
                    {c.status === "AKTIV" ? (
                      <Typography variant="caption" color="text.secondary">
                        Aktiv
                      </Typography>
                    ) : (
                      <Chip
                        size="small"
                        color={c.status === "GEKUENDIGT" ? "warning" : "default"}
                        variant="outlined"
                        label={SUPPLIER_STATUS_LABELS[c.status]}
                      />
                    )}
                  </TableCell>
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

      <SupplierContractDialog
        draft={draft}
        setDraft={setDraft}
        busy={busy}
        error={dialogError}
        onSave={() => void save()}
        propertyId={propertyId}
      />
    </Box>
  );
}
