// Org-wide Versorgungsverträge board — every property's supply/service
// contracts, soonest-ending first, with a traffic light for expiring ones:
//   red    = ended (without auto-renewal), or the cancellation deadline
//            (Ende − Kündigungsfrist) is within the next 2 months or past
//   orange = ends within the next 6 months, or auto-renewed past its end
//            date (the stored Ende needs updating)
//   green  = comfortable runway
//   grey   = open-ended (no end date), or manually GEKUENDIGT/BEENDET
//            (a cancelled contract must not scream red)
// Full CRUD lives here too (shared dialog with the property tab), plus:
// provider click → linked Dienstleister contact (or link one), price click
// → the latest Belege from the DMS, inline status select.
// All date math is done on ISO date STRINGS (YYYY-MM-DD compares
// lexicographically) — no Date objects, no setMonth overflow.

import { useCallback, useEffect, useMemo, useState } from "react";
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
  IconButton,
  InputAdornment,
  Link,
  List,
  ListItemButton,
  ListItemText,
  MenuItem,
  Select,
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
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutlineOutlined";
import EditIcon from "@mui/icons-material/Edit";
import SearchIcon from "@mui/icons-material/Search";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import {
  SUPPLIER_CATEGORY_LABELS,
  SUPPLIER_STATUS_LABELS,
  type AdminContactListItem,
  type SupplierContractCategory,
  type SupplierContractDocumentItem,
  type SupplierContractResponse,
  type SupplierContractStatus,
} from "@/api/types";
import { fmtContractDate, fmtPrice } from "@/lib/supplierContracts";
import { SupplierContractDialog } from "@/admin/components/SupplierContractDialog";
import {
  EMPTY_DRAFT,
  bodyFromDraft,
  bodyFromRow,
  draftFrom,
  type ContractDraft,
} from "@/lib/supplierContracts";

type Ampel = "red" | "orange" | "green" | "grey";

const AMPEL_COLOR: Record<Ampel, string> = {
  red: "#e53935",
  orange: "#fb8c00",
  green: "#43a047",
  grey: "#9e9e9e",
};

const STATUSES = Object.keys(SUPPLIER_STATUS_LABELS) as SupplierContractStatus[];

function localTodayISO(): string {
  const n = new Date();
  const m = String(n.getMonth() + 1).padStart(2, "0");
  const d = String(n.getDate()).padStart(2, "0");
  return `${n.getFullYear()}-${m}-${d}`;
}

// Shift an ISO date by whole months, clamping the day to the target month's
// last day — § 188 Abs. 3 BGB: "31. Februar" is the last day of February,
// NOT March 3rd (which plain Date.setMonth would produce).
function shiftMonthsISO(iso: string, months: number): string {
  const [y = 0, m = 1, d = 1] = iso.split("-").map(Number);
  const total = y * 12 + (m - 1) + months;
  const ty = Math.floor(total / 12);
  const tm = total - ty * 12; // 0-based target month
  const lastDay = new Date(Date.UTC(ty, tm + 1, 0)).getUTCDate();
  const td = Math.min(d, lastDay);
  return `${String(ty).padStart(4, "0")}-${String(tm + 1).padStart(2, "0")}-${String(td).padStart(2, "0")}`;
}

// Latest day the contract can still be cancelled: Ende − Kündigungsfrist.
function cancellationDeadlineISO(c: SupplierContractResponse): string | null {
  if (!c.end_date || c.cancellation_months == null) return null;
  return shiftMonthsISO(c.end_date, -c.cancellation_months);
}

function ampelFor(c: SupplierContractResponse, todayISO: string): Ampel {
  if (c.status !== "AKTIV") return "grey";
  if (!c.end_date) return "grey";
  // The end date itself is still a valid contract day ("bis 31.12.").
  if (c.end_date < todayISO) return c.auto_renew ? "orange" : "red";
  const deadline = cancellationDeadlineISO(c);
  if (deadline !== null && deadline < shiftMonthsISO(todayISO, 2)) return "red";
  if (c.end_date < shiftMonthsISO(todayISO, 6)) return "orange";
  return "green";
}

export function AdminVertraegePage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [rows, setRows] = useState<SupplierContractResponse[]>([]);
  const [properties, setProperties] = useState<{ id: string; name: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState<"" | SupplierContractCategory>("");

  // dialog / CRUD state
  const [draft, setDraft] = useState<ContractDraft | null>(null);
  const [draftPropertyId, setDraftPropertyId] = useState("");
  const [busy, setBusy] = useState(false);
  const [dialogError, setDialogError] = useState<string | null>(null);

  // provider-contact dialog
  const [contactFor, setContactFor] = useState<SupplierContractResponse | null>(null);
  const [contactCandidates, setContactCandidates] = useState<AdminContactListItem[] | null>(null);
  const [contactFilter, setContactFilter] = useState("");

  // latest-documents menu (dialog list)
  const [docsFor, setDocsFor] = useState<SupplierContractResponse | null>(null);
  const [docs, setDocs] = useState<SupplierContractDocumentItem[] | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [contracts, props] = await Promise.all([
        api.get<SupplierContractResponse[]>("/admin/supplier-contracts"),
        api.get<{ id: string; name: string }[]>("/admin/properties"),
      ]);
      setRows(contracts.data);
      setProperties(props.data.map((p) => ({ id: p.id, name: p.name })));
    } catch {
      setError(t("admin.vertraegePage.loadError"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const todayISO = useMemo(() => localTodayISO(), []);

  // Tooltip for the traffic-light dot. Red is split into "deadline coming
  // up" vs "deadline already missed" so an actionable red is recognizable.
  function ampelTitle(c: SupplierContractResponse): string {
    if (c.status === "BEENDET") return t("admin.vertraegePage.ampelBeendetManuell");
    if (c.status === "GEKUENDIGT")
      return t("admin.vertraegePage.ampelGekuendigt", {
        date: c.end_date ? fmtContractDate(c.end_date) : "—",
      });
    const a = ampelFor(c, todayISO);
    if (a === "grey") return t("admin.vertraegePage.ampelUnbefristet");
    if (a === "green") return t("admin.vertraegePage.ampelLaeuft");
    if (c.end_date && c.end_date < todayISO) {
      return c.auto_renew
        ? t("admin.vertraegePage.ampelVerlaengert")
        : t("admin.vertraegePage.ampelAbgelaufen");
    }
    const deadline = cancellationDeadlineISO(c);
    if (ampelFor(c, todayISO) === "red" && deadline) {
      return deadline < todayISO
        ? t("admin.vertraegePage.ampelFristVerpasst", { date: fmtContractDate(deadline) })
        : t("admin.vertraegePage.ampelFristEndet", { date: fmtContractDate(deadline) });
    }
    return t("admin.vertraegePage.ampelEndetBald");
  }

  const visible = useMemo(() => {
    const tokens = search.trim().toLowerCase().split(/\s+/).filter(Boolean);
    return rows.filter((c) => {
      if (category && c.category !== category) return false;
      if (tokens.length === 0) return true;
      const haystack = [
        c.property_name,
        c.provider_name,
        c.contract_number,
        c.customer_number,
        c.meter_number,
        SUPPLIER_CATEGORY_LABELS[c.category],
      ]
        .filter((s): s is string => !!s)
        .join(" ")
        .toLowerCase();
      return tokens.every((tok) => haystack.includes(tok));
    });
  }, [rows, search, category]);

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
          `/admin/properties/${draftPropertyId}/supplier-contracts`,
          bodyFromDraft(draft),
        );
        setRows((rs) => [...rs, r.data]);
      }
      setDraft(null);
    } catch {
      setDialogError(t("admin.vertraegePage.saveError"));
    } finally {
      setBusy(false);
    }
  }

  async function remove(c: SupplierContractResponse) {
    if (
      !window.confirm(
        t("admin.vertraegePage.deleteConfirm", {
          provider: c.provider_name,
          category: SUPPLIER_CATEGORY_LABELS[c.category],
        }),
      )
    )
      return;
    setError(null);
    try {
      await api.delete(`/admin/supplier-contracts/${c.id}`);
      setRows((rs) => rs.filter((x) => x.id !== c.id));
    } catch {
      setError(t("admin.vertraegePage.deleteError"));
    }
  }

  // Inline status change — full PUT body built from the row so nothing else
  // gets clobbered. Optimistic with revert.
  async function setStatus(c: SupplierContractResponse, next: SupplierContractStatus) {
    const prev = c.status;
    setRows((rs) => rs.map((x) => (x.id === c.id ? { ...x, status: next } : x)));
    try {
      const r = await api.put<SupplierContractResponse>(
        `/admin/supplier-contracts/${c.id}`,
        { ...bodyFromRow(c), status: next },
      );
      setRows((rs) => rs.map((x) => (x.id === c.id ? r.data : x)));
    } catch {
      setRows((rs) => rs.map((x) => (x.id === c.id ? { ...x, status: prev } : x)));
      setError(t("admin.vertraegePage.statusError"));
    }
  }

  // Provider click: show the linked contact, or a searchable list to link
  // one. All contacts are loaded once; the filter field starts with the
  // provider name and is freely editable — short names like "RWE" or
  // stopword-heavy ones must never dead-end the linking flow.
  async function openContact(c: SupplierContractResponse) {
    setContactFor(c);
    setContactCandidates(null);
    setContactFilter(c.provider_name);
    if (c.contact_id) return; // linked — row already carries the details
    try {
      const r = await api.get<AdminContactListItem[]>("/admin/contacts?limit=1000");
      setContactCandidates(r.data);
    } catch {
      setContactCandidates([]);
    }
  }

  // Any-token match, min length 2 — an empty filter shows everything.
  function filteredCandidates(): AdminContactListItem[] {
    if (!contactCandidates) return [];
    const tokens = contactFilter
      .toLowerCase()
      .split(/[^\wäöüß]+/)
      .filter((tok) => tok.length >= 2);
    if (tokens.length === 0) return contactCandidates;
    return contactCandidates.filter((k) => {
      const name = k.name.toLowerCase();
      return tokens.some((tok) => name.includes(tok));
    });
  }

  async function linkContact(c: SupplierContractResponse, contactId: string) {
    try {
      const r = await api.put<SupplierContractResponse>(
        `/admin/supplier-contracts/${c.id}`,
        { ...bodyFromRow(c), contact_id: contactId },
      );
      setRows((rs) => rs.map((x) => (x.id === c.id ? r.data : x)));
      setContactFor(r.data);
    } catch {
      setError(t("admin.vertraegePage.contactLinkError"));
    }
  }

  // Price click: list the latest Belege, click-through downloads the file.
  async function openDocs(c: SupplierContractResponse) {
    setDocsFor(c);
    setDocs(null);
    try {
      const r = await api.get<SupplierContractDocumentItem[]>(
        `/admin/supplier-contracts/${c.id}/documents`,
      );
      setDocs(r.data);
    } catch {
      setDocs([]);
    }
  }

  async function downloadDoc(d: SupplierContractDocumentItem) {
    try {
      const r = await api.get(`/admin/documents/${d.id}/file`, { responseType: "blob" });
      const url = URL.createObjectURL(r.data as Blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = d.name;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 10_000);
    } catch {
      setError(t("admin.vertraegePage.docDownloadError"));
    }
  }

  return (
    <Box>
      <Stack
        direction="row"
        sx={{ justifyContent: "space-between", alignItems: "center", mb: 1 }}
      >
        <Typography variant="h4">{t("admin.vertraegePage.title")}</Typography>
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          onClick={() => {
            setDialogError(null);
            setDraftPropertyId(properties[0]?.id ?? "");
            setDraft(EMPTY_DRAFT);
          }}
        >
          {t("admin.vertraegePage.addContract")}
        </Button>
      </Stack>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        {t("admin.vertraegePage.subtitle")}
      </Typography>

      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {loading ? (
        <CircularProgress />
      ) : (
        <>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={2} sx={{ mb: 2 }}>
            <TextField
              size="small"
              placeholder={t("admin.vertraegePage.searchPlaceholder")}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              sx={{ maxWidth: 380, width: "100%" }}
              slotProps={{
                input: {
                  startAdornment: (
                    <InputAdornment position="start">
                      <SearchIcon fontSize="small" />
                    </InputAdornment>
                  ),
                },
              }}
            />
            <TextField
              select
              size="small"
              label={t("admin.vertraegePage.category")}
              value={category}
              onChange={(e) => setCategory(e.target.value as typeof category)}
              sx={{ minWidth: 200 }}
            >
              <MenuItem value="">{t("admin.vertraegePage.allCategories")}</MenuItem>
              {(Object.keys(SUPPLIER_CATEGORY_LABELS) as SupplierContractCategory[]).map((c) => (
                <MenuItem key={c} value={c}>
                  {SUPPLIER_CATEGORY_LABELS[c]}
                </MenuItem>
              ))}
            </TextField>
          </Stack>
          {rows.length === 0 ? (
            <Typography color="text.secondary">{t("admin.vertraegePage.empty")}</Typography>
          ) : visible.length === 0 ? (
            <Typography color="text.secondary">{t("admin.vertraegePage.noMatches")}</Typography>
          ) : (
            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell sx={{ width: 24 }} />
                    <TableCell>{t("admin.vertraegePage.colProperty")}</TableCell>
                    <TableCell>{t("admin.vertraegePage.colCategory")}</TableCell>
                    <TableCell>{t("admin.vertraegePage.colProvider")}</TableCell>
                    <TableCell>{t("admin.vertraegePage.colStatus")}</TableCell>
                    <TableCell>{t("admin.vertraegePage.colNumber")}</TableCell>
                    <TableCell>{t("admin.vertraegePage.colEnd")}</TableCell>
                    <TableCell>{t("admin.vertraegePage.colCancellation")}</TableCell>
                    <TableCell align="right">{t("admin.vertraegePage.colPrice")}</TableCell>
                    <TableCell />
                  </TableRow>
                </TableHead>
                <TableBody>
                  {visible.map((c) => (
                    <TableRow key={c.id} hover>
                      <TableCell>
                        <Tooltip title={ampelTitle(c)}>
                          <Box
                            sx={{
                              width: 10,
                              height: 10,
                              borderRadius: "50%",
                              bgcolor: AMPEL_COLOR[ampelFor(c, todayISO)],
                            }}
                          />
                        </Tooltip>
                      </TableCell>
                      <TableCell>
                        <Link
                          component="button"
                          underline="hover"
                          color="inherit"
                          onClick={() =>
                            navigate(`/admin/properties/${c.property_id}?tab=vertraege`)
                          }
                          sx={{ textAlign: "left" }}
                        >
                          {c.property_name ?? "—"}
                        </Link>
                      </TableCell>
                      <TableCell>
                        <Chip size="small" label={SUPPLIER_CATEGORY_LABELS[c.category]} />
                      </TableCell>
                      <TableCell>
                        <Tooltip title={t("admin.vertraegePage.contactTooltip")}>
                          <Link
                            component="button"
                            underline="hover"
                            color="inherit"
                            onClick={() => void openContact(c)}
                            sx={{ textAlign: "left" }}
                          >
                            {c.provider_name}
                          </Link>
                        </Tooltip>
                      </TableCell>
                      <TableCell>
                        <Select
                          size="small"
                          variant="standard"
                          value={c.status}
                          onChange={(e) =>
                            void setStatus(c, e.target.value as SupplierContractStatus)
                          }
                          sx={{ minWidth: 104, fontSize: "0.85rem" }}
                        >
                          {STATUSES.map((s) => (
                            <MenuItem key={s} value={s}>
                              {SUPPLIER_STATUS_LABELS[s]}
                            </MenuItem>
                          ))}
                        </Select>
                      </TableCell>
                      <TableCell>{c.contract_number ?? "—"}</TableCell>
                      <TableCell sx={{ whiteSpace: "nowrap" }}>
                        {fmtContractDate(c.end_date)}
                        {c.auto_renew && (
                          <Tooltip title={t("admin.vertraegePage.autoRenew")}>
                            <Box component="span" sx={{ ml: 0.5, color: "text.secondary" }}>
                              ↻
                            </Box>
                          </Tooltip>
                        )}
                      </TableCell>
                      <TableCell>
                        {c.cancellation_months != null
                          ? t("admin.vertraegePage.months", { count: c.cancellation_months })
                          : "—"}
                      </TableCell>
                      <TableCell align="right" sx={{ whiteSpace: "nowrap" }}>
                        {c.price != null ? (
                          <Tooltip title={t("admin.vertraegePage.docsTooltip")}>
                            <Link
                              component="button"
                              underline="hover"
                              color="inherit"
                              onClick={() => void openDocs(c)}
                            >
                              {fmtPrice(c)}
                            </Link>
                          </Tooltip>
                        ) : (
                          <Link
                            component="button"
                            underline="hover"
                            color="inherit"
                            onClick={() => void openDocs(c)}
                          >
                            —
                          </Link>
                        )}
                      </TableCell>
                      <TableCell align="right" sx={{ whiteSpace: "nowrap" }}>
                        <Tooltip title={t("admin.vertraegePage.edit")}>
                          <IconButton
                            size="small"
                            onClick={() => {
                              setDialogError(null);
                              setDraftPropertyId(c.property_id);
                              setDraft(draftFrom(c));
                            }}
                          >
                            <EditIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                        <Tooltip title={t("admin.vertraegePage.delete")}>
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
        </>
      )}

      <SupplierContractDialog
        draft={draft}
        setDraft={setDraft}
        busy={busy}
        error={dialogError}
        onSave={() => void save()}
        propertyId={draft?.id ? draftPropertyId : draftPropertyId}
        propertyPicker={{ properties, onChange: setDraftPropertyId }}
      />

      {/* Dienstleister contact details / linking */}
      <Dialog open={contactFor !== null} onClose={() => setContactFor(null)} fullWidth maxWidth="xs">
        <DialogTitle>{contactFor?.provider_name}</DialogTitle>
        <DialogContent>
          {contactFor?.contact_id ? (
            <Stack spacing={1} sx={{ mt: 1 }}>
              <Typography variant="subtitle2">{contactFor.contact_name ?? "—"}</Typography>
              <Typography variant="body2">
                {t("admin.vertraegePage.contactEmail")}:{" "}
                {contactFor.contact_email ? (
                  <Link href={`mailto:${contactFor.contact_email}`}>
                    {contactFor.contact_email}
                  </Link>
                ) : (
                  "—"
                )}
              </Typography>
              <Typography variant="body2">
                {t("admin.vertraegePage.contactPhone")}:{" "}
                {contactFor.contact_phone ? (
                  <Link href={`tel:${contactFor.contact_phone}`}>{contactFor.contact_phone}</Link>
                ) : (
                  "—"
                )}
              </Typography>
            </Stack>
          ) : (
            <Stack spacing={1} sx={{ mt: 1 }}>
              <Typography variant="body2" color="text.secondary">
                {t("admin.vertraegePage.contactNone")}
              </Typography>
              <TextField
                size="small"
                placeholder={t("admin.vertraegePage.contactFilterPlaceholder")}
                value={contactFilter}
                onChange={(e) => setContactFilter(e.target.value)}
                fullWidth
              />
              {contactCandidates === null ? (
                <CircularProgress size={20} />
              ) : filteredCandidates().length === 0 ? (
                <Typography variant="body2" color="text.secondary">
                  {t("admin.vertraegePage.contactSearchEmpty")}
                </Typography>
              ) : (
                <>
                  <List dense>
                    {filteredCandidates()
                      .slice(0, 12)
                      .map((k) => (
                        <ListItemButton
                          key={k.id}
                          onClick={() => contactFor && void linkContact(contactFor, k.id)}
                        >
                          <ListItemText
                            primary={k.name}
                            secondary={
                              [k.email, k.phone].filter(Boolean).join(" · ") || undefined
                            }
                          />
                        </ListItemButton>
                      ))}
                  </List>
                  <Typography variant="caption" color="text.secondary">
                    {t("admin.vertraegePage.contactLinkHint")}
                  </Typography>
                </>
              )}
            </Stack>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setContactFor(null)}>{t("common.back")}</Button>
        </DialogActions>
      </Dialog>

      {/* Latest Belege for a contract */}
      <Dialog open={docsFor !== null} onClose={() => setDocsFor(null)} fullWidth maxWidth="xs">
        <DialogTitle>
          {t("admin.vertraegePage.docsTitle", { provider: docsFor?.provider_name ?? "" })}
        </DialogTitle>
        <DialogContent>
          {docs === null ? (
            <CircularProgress size={20} sx={{ mt: 1 }} />
          ) : docs.length === 0 ? (
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
              {t("admin.vertraegePage.docsNone")}
            </Typography>
          ) : (
            <List dense>
              {docs.map((d) => (
                <ListItemButton key={d.id} onClick={() => void downloadDoc(d)}>
                  <ListItemText
                    primary={d.name}
                    secondary={[
                      d.issued_date ? fmtContractDate(d.issued_date) : null,
                      d.amount != null
                        ? `${Math.abs(Number(d.amount)).toLocaleString("de-DE", {
                            minimumFractionDigits: 2,
                            maximumFractionDigits: 2,
                          })} €`
                        : null,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  />
                </ListItemButton>
              ))}
            </List>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDocsFor(null)}>{t("common.back")}</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
