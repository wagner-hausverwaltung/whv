// Verwalter review queue for inbound anfragen@ inquiries (ADR-0019). Lists
// inquiries with status; each row expands to show the full email body, a shared
// note, a re-download of the generated offer, and a "send friendly reminder"
// action. For one that needs review, a dialog prefilled from the LLM extraction
// lets the Verwalter correct + send the offer.
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutlineOutlined";
import DownloadIcon from "@mui/icons-material/Download";
import KeyboardArrowDownIcon from "@mui/icons-material/KeyboardArrowDown";
import KeyboardArrowRightIcon from "@mui/icons-material/KeyboardArrowRight";
import SearchIcon from "@mui/icons-material/Search";
import SendIcon from "@mui/icons-material/Send";
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
  FormControlLabel,
  IconButton,
  InputAdornment,
  MenuItem,
  Select,
  Stack,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TableSortLabel,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
  Typography,
} from "@mui/material";
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";

type Art = "WEG" | "MV";

interface OfferInquiry {
  id: string;
  sender_email: string;
  sender_name: string | null;
  subject: string;
  status: string;
  lead_status: string;
  art: string | null;
  object_address: string | null;
  units: number | null;
  desired_start: string | null;
  confidence: number | null;
  sent_at: string | null;
  created_at: string;
  generated_offer_filename: string | null;
  last_reminder_at: string | null;
  reminder_count: number;
}

interface OfferInquiryDetail extends OfferInquiry {
  body: string;
  review_note: string | null;
  error: string | null;
  sent_message_id: string | null;
}

const LEAD_STATUSES = ["OPEN", "ON_HOLD", "ACCEPTED", "DECLINED"] as const;

type SortKey =
  | "sender"
  | "subject"
  | "art"
  | "object"
  | "units"
  | "confidence"
  | "status"
  | "lead";

// Sort value per column — numbers compare numerically, strings via
// localeCompare; null (empty cell) sorts last in both directions. "lead" is
// handled at the call site: it must sort by the LOCALIZED label the column
// displays (Angenommen/Abgelehnt/…), not the raw enum.
function readSortValue(r: OfferInquiry, key: Exclude<SortKey, "lead">): string | number | null {
  switch (key) {
    case "sender":
      return (r.sender_name || r.sender_email).toLowerCase() || null;
    case "subject":
      return r.subject.toLowerCase() || null;
    case "art":
      return r.art?.toLowerCase() ?? null;
    case "object":
      return r.object_address?.toLowerCase() ?? null;
    case "units":
      return r.units;
    case "confidence":
      return r.confidence;
    case "status":
      return r.status.toLowerCase() || null;
  }
}

const STATUS_COLOR: Record<
  string,
  "default" | "info" | "warning" | "success" | "error"
> = {
  NEW: "default",
  EXTRACTED: "info",
  NEEDS_REVIEW: "warning",
  SENT: "success",
  FAILED: "error",
  IGNORED: "default",
};

// Total columns including the leading expander cell — used as the Collapse
// row's colSpan so the panel spans the full table width.
const COL_SPAN = 10;

// 1 Jan of next year as an ISO date — mirrors the backend pricing default so the
// date field shows the real start instead of an empty input rendering today.
function defaultStartDate(): string {
  return `${new Date().getFullYear() + 1}-01-01`;
}

// Default contract Laufzeit (years) — mirrors the backend pricing default.
const DEFAULT_TERM_YEARS = 4;

// Mirrors the backend pricing engine for the dialog's live PREVIEW only. The
// authoritative figure is recomputed server-side; when the Verwalter overrides
// the fee, that value is what's sent + stamped.
function computedMonthlyNet(art: Art, unitsNum: number): number | null {
  if (!Number.isFinite(unitsNum) || unitsNum < 1) return null;
  if (art === "MV") return unitsNum * 30;
  const rate = unitsNum > 15 ? 35 : 45;
  return Math.max(unitsNum * rate, 270);
}

function grossFromNet(net: number): number {
  return Math.round(net * 1.19 * 100) / 100;
}

// start + DEFAULT_TERM_YEARS − 1 day, as an ISO date (yyyy-mm-dd).
function computedEndDate(startISO: string): string {
  if (!startISO) return "";
  const d = new Date(startISO);
  if (Number.isNaN(d.getTime())) return "";
  d.setFullYear(d.getFullYear() + DEFAULT_TERM_YEARS);
  d.setDate(d.getDate() - 1);
  return d.toISOString().slice(0, 10);
}

function formatEur(n: number): string {
  return n.toLocaleString("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatDateTime(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString();
}

// The LLM returns a single combined object address ("Straße 1, 70123 Stadt").
// Split it on the German 5-digit Postleitzahl so "Straße + Nr." and "PLZ + Ort"
// land in their own fields; fall back to street-only when there's no PLZ.
function splitGermanAddress(address: string | null): [string, string] {
  if (!address) return ["", ""];
  const a = address.trim();
  // Only a PLZ + city, no street (e.g. "70499 Stuttgart") → keep it in PLZ + Ort.
  if (/^\d{5}\s+\S/.test(a)) return ["", a];
  const m = a.match(/^(.*?)[,\s]+(\d{5}\s+.+)$/);
  if (m) return [(m[1] ?? "").replace(/[,\s]+$/, "").trim(), (m[2] ?? "").trim()];
  return [a, ""];
}

export function AdminAnfragenPage() {
  const { t } = useTranslation();
  const tp = (k: string, opts?: Record<string, unknown>) =>
    t(`admin.anfragenPage.${k}`, opts ?? {});

  const [rows, setRows] = useState<OfferInquiry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [autoMode, setAutoMode] = useState(false);
  const [autoBusy, setAutoBusy] = useState(false);

  // --- search / sort / delete ---
  const [search, setSearch] = useState("");
  // null = server order (newest first); a click sorts by that column.
  const [sortKey, setSortKey] = useState<SortKey | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [deleteBusy, setDeleteBusy] = useState<string | null>(null);

  const visibleRows = useMemo(() => {
    const tokens = search.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const filtered =
      tokens.length === 0
        ? rows
        : rows.filter((r) => {
            const haystack = [r.sender_name, r.sender_email, r.subject, r.object_address, r.art]
              .filter((s): s is string => !!s)
              .join(" ")
              .toLowerCase();
            return tokens.every((tok) => haystack.includes(tok));
          });
    if (!sortKey) return filtered;
    const value = (r: OfferInquiry): string | number | null =>
      sortKey === "lead"
        ? t(`admin.anfragenPage.lead.${r.lead_status}`).toLowerCase()
        : readSortValue(r, sortKey);
    return [...filtered].sort((a, b) => {
      const av = value(a);
      const bv = value(b);
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      const cmp =
        typeof av === "number" && typeof bv === "number"
          ? av - bv
          : String(av).localeCompare(String(bv), "de-DE", {
              sensitivity: "base",
              numeric: true,
            });
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [rows, search, sortKey, sortDir, t]);

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  };

  // --- row expansion / detail panel ---
  const [expandedId, setExpandedId] = useState<string | null>(null);
  // Ref mirror, set synchronously alongside the state: toggleExpand's async
  // detail fetch checks it on resolve so a LATE response (row since
  // collapsed, replaced, or deleted) can't reseed the shared edit drafts —
  // otherwise a deleted inquiry's data could get saved onto another row.
  const expandedIdRef = useRef<string | null>(null);
  function setExpanded(id: string | null) {
    expandedIdRef.current = id;
    setExpandedId(id);
  }
  const [details, setDetails] = useState<Record<string, OfferInquiryDetail>>({});
  const [detailBusy, setDetailBusy] = useState<string | null>(null);
  const [noteDraft, setNoteDraft] = useState("");
  const [panelBusy, setPanelBusy] = useState(false);
  const [panelError, setPanelError] = useState<string | null>(null);
  // Editable extracted fields (Art / Objekt-Adresse / Einheiten / Vertragsbeginn),
  // seeded from the loaded detail. Only one row is expanded at a time, so a
  // single set of edit-state vars is enough.
  const [editArt, setEditArt] = useState("");
  const [editAddress, setEditAddress] = useState("");
  const [editUnits, setEditUnits] = useState("");
  const [editStart, setEditStart] = useState("");

  function seedEdit(d: OfferInquiry) {
    setEditArt(d.art ?? "");
    setEditAddress(d.object_address ?? "");
    setEditUnits(d.units != null ? String(d.units) : "");
    setEditStart(d.desired_start ?? "");
  }

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [inq, settings] = await Promise.all([
        api.get<OfferInquiry[]>("/admin/offer-inquiries"),
        api.get<{ auto_send_enabled: boolean }>("/admin/offer-settings"),
      ]);
      setRows(inq.data);
      setAutoMode(settings.data.auto_send_enabled);
      // Drop cached detail + collapse on a fresh load so the panel never shows
      // stale body/note/reminder data.
      setDetails({});
      setExpanded(null);
    } catch {
      setError(tp("loadError"));
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  // Persist the Auto-Modus toggle org-wide. Optimistic, with revert on failure.
  async function toggleAutoMode(next: boolean) {
    setAutoBusy(true);
    setAutoMode(next);
    setError(null);
    try {
      await api.put("/admin/offer-settings", { auto_send_enabled: next });
    } catch {
      setAutoMode(!next);
      setError(tp("autoModeError"));
    } finally {
      setAutoBusy(false);
    }
  }

  // Per-offer sales status. Optimistic; revert the row's value on failure.
  async function updateLeadStatus(id: string, next: string) {
    const prev = rows.find((r) => r.id === id)?.lead_status;
    setRows((rs) => rs.map((r) => (r.id === id ? { ...r, lead_status: next } : r)));
    setError(null);
    try {
      await api.put(`/admin/offer-inquiries/${id}/lead-status`, { lead_status: next });
    } catch {
      setRows((rs) =>
        rs.map((r) => (r.id === id && prev ? { ...r, lead_status: prev } : r)),
      );
      setError(tp("leadStatusError"));
    }
  }

  // Hard-delete an inquiry (removes the prospect's PII). Confirmed, then the
  // row + any cached detail/expansion state are dropped locally.
  async function deleteInquiry(id: string) {
    if (!window.confirm(tp("deleteConfirm"))) return;
    setDeleteBusy(id);
    setError(null);
    try {
      await api.delete(`/admin/offer-inquiries/${id}`);
      setRows((rs) => rs.filter((r) => r.id !== id));
      setDetails((d) => {
        const next = { ...d };
        delete next[id];
        return next;
      });
      if (expandedIdRef.current === id) setExpanded(null);
    } catch {
      setError(tp("deleteError"));
    } finally {
      setDeleteBusy(null);
    }
  }

  // Lazy-fetch the detail (full body + note) the first time a row is expanded.
  async function toggleExpand(id: string) {
    setPanelError(null);
    if (expandedId === id) {
      setExpanded(null);
      return;
    }
    setExpanded(id);
    const cached = details[id];
    if (cached) {
      setNoteDraft(cached.review_note ?? "");
      seedEdit(cached);
      return;
    }
    setDetailBusy(id);
    try {
      const r = await api.get<OfferInquiryDetail>(`/admin/offer-inquiries/${id}`);
      // Stale response — the row was collapsed, replaced, or deleted while the
      // request was in flight. Don't cache it or reseed the shared drafts.
      if (expandedIdRef.current !== id) return;
      setDetails((d) => ({ ...d, [id]: r.data }));
      setNoteDraft(r.data.review_note ?? "");
      seedEdit(r.data);
    } catch {
      if (expandedIdRef.current === id) setPanelError(tp("detailError"));
    } finally {
      // Only clear our own spinner — a later expand may have its own fetch.
      setDetailBusy((b) => (b === id ? null : b));
    }
  }

  async function saveFields(id: string) {
    setPanelBusy(true);
    setPanelError(null);
    try {
      const r = await api.put<OfferInquiryDetail>(`/admin/offer-inquiries/${id}/fields`, {
        art: editArt || null,
        object_address: editAddress.trim() || null,
        units: editUnits ? Number(editUnits) : null,
        desired_start: editStart || null,
      });
      setDetails((d) => ({ ...d, [id]: r.data }));
      setRows((rs) =>
        rs.map((x) =>
          x.id === id
            ? {
                ...x,
                art: r.data.art,
                object_address: r.data.object_address,
                units: r.data.units,
                desired_start: r.data.desired_start,
              }
            : x,
        ),
      );
      seedEdit(r.data);
    } catch {
      setPanelError(tp("fieldsError"));
    } finally {
      setPanelBusy(false);
    }
  }

  async function saveNote(id: string) {
    setPanelBusy(true);
    setPanelError(null);
    try {
      const r = await api.put<OfferInquiryDetail>(`/admin/offer-inquiries/${id}/note`, {
        review_note: noteDraft,
      });
      setDetails((d) => ({ ...d, [id]: r.data }));
      setNoteDraft(r.data.review_note ?? "");
    } catch {
      setPanelError(tp("noteError"));
    } finally {
      setPanelBusy(false);
    }
  }

  async function sendReminder(id: string) {
    if (!window.confirm(tp("reminderConfirm"))) return;
    setPanelBusy(true);
    setPanelError(null);
    try {
      const r = await api.post<OfferInquiryDetail>(`/admin/offer-inquiries/${id}/reminder`);
      setDetails((d) => ({ ...d, [id]: r.data }));
      setRows((rs) =>
        rs.map((x) =>
          x.id === id
            ? {
                ...x,
                last_reminder_at: r.data.last_reminder_at,
                reminder_count: r.data.reminder_count,
              }
            : x,
        ),
      );
    } catch {
      setPanelError(tp("reminderError"));
    } finally {
      setPanelBusy(false);
    }
  }

  async function downloadOffer(id: string, filename: string | null) {
    setPanelBusy(true);
    setPanelError(null);
    try {
      const r = await api.get(`/admin/offer-inquiries/${id}/offer.pdf`, {
        responseType: "blob",
      });
      const url = URL.createObjectURL(r.data as Blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename || "Angebot.pdf";
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 10_000);
    } catch {
      setPanelError(tp("downloadError"));
    } finally {
      setPanelBusy(false);
    }
  }

  // --- send dialog ---
  const [target, setTarget] = useState<OfferInquiry | null>(null);
  const [art, setArt] = useState<Art>("WEG");
  const [units, setUnits] = useState("");
  const [startDate, setStartDate] = useState("");
  const [objectStreet, setObjectStreet] = useState("");
  const [objectPlzCity, setObjectPlzCity] = useState("");
  const [recipientName, setRecipientName] = useState("");
  const [recipientStreet, setRecipientStreet] = useState("");
  const [recipientPlzCity, setRecipientPlzCity] = useState("");
  const [salutation, setSalutation] = useState("");
  const [object1, setObject1] = useState("");
  // Price + end date: prefilled with the computed values (so the Verwalter
  // *sees* them) and overridable. `*Touched` stops the live recompute once the
  // Verwalter has typed their own value.
  const [monthlyFee, setMonthlyFee] = useState("");
  const [endDate, setEndDate] = useState("");
  const [priceTouched, setPriceTouched] = useState(false);
  const [endTouched, setEndTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [dialogError, setDialogError] = useState<string | null>(null);

  function openSend(inq: OfferInquiry) {
    setTarget(inq);
    setDialogError(null);
    const a: Art = inq.art === "MV" ? "MV" : "WEG";
    setArt(a);
    setUnits(inq.units != null ? String(inq.units) : "");
    const startISO = inq.desired_start ?? defaultStartDate();
    setStartDate(startISO);
    const [street, plzCity] = splitGermanAddress(inq.object_address);
    setObjectStreet(street);
    setObjectPlzCity(plzCity);
    setRecipientName(inq.sender_name ?? "");
    setRecipientStreet("");
    setRecipientPlzCity("");
    setSalutation(inq.sender_name ? `Sehr geehrte/r ${inq.sender_name},` : "");
    setObject1(inq.object_address ?? "");
    const cmf = computedMonthlyNet(a, inq.units ?? 0);
    setMonthlyFee(cmf != null ? String(cmf) : "");
    setEndDate(computedEndDate(startISO));
    setPriceTouched(false);
    setEndTouched(false);
  }

  // Keep the price preview in step with units/Art until the Verwalter overrides.
  useEffect(() => {
    if (!target || priceTouched) return;
    const cmf = computedMonthlyNet(art, Number(units));
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setMonthlyFee(cmf != null ? String(cmf) : "");
  }, [art, units, priceTouched, target]);

  // Keep the end date (= start + 4y − 1d) in step with the start until overridden.
  useEffect(() => {
    if (!target || endTouched) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setEndDate(computedEndDate(startDate));
  }, [startDate, endTouched, target]);

  async function submitSend() {
    if (!target) return;
    setBusy(true);
    setDialogError(null);
    try {
      const payload: Record<string, unknown> = {
        art,
        units: Number(units),
        start_date: startDate || undefined,
        end_date: endDate || undefined,
        monthly_fee_net_override: monthlyFee ? Number(monthlyFee) : undefined,
      };
      if (art === "WEG") {
        payload.object_street = objectStreet;
        payload.object_plz_city = objectPlzCity;
      } else {
        payload.recipient_name = recipientName;
        payload.recipient_street = recipientStreet;
        payload.recipient_plz_city = recipientPlzCity;
        payload.salutation = salutation;
        payload.objects = [object1].filter(Boolean);
      }
      await api.post(`/admin/offer-inquiries/${target.id}/send`, payload);
      setTarget(null);
      await load();
    } catch {
      setDialogError(tp("sendError"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Box>
      <Box
        sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", mb: 1 }}
      >
        <Typography variant="h4">{tp("title")}</Typography>
        <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
          <Tooltip title={tp("autoModeHint")}>
            <FormControlLabel
              sx={{ mr: 0 }}
              control={
                <Switch
                  checked={autoMode}
                  onChange={(e) => void toggleAutoMode(e.target.checked)}
                  disabled={autoBusy || loading}
                />
              }
              label={tp("autoMode")}
            />
          </Tooltip>
          <Button onClick={() => void load()} disabled={loading}>
            {tp("refresh")}
          </Button>
        </Box>
      </Box>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        {tp("subtitle")}
      </Typography>

      {autoMode && (
        <Alert severity="info" sx={{ mb: 2 }}>
          {tp("autoModeActive")}
        </Alert>
      )}
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {loading ? (
        <CircularProgress />
      ) : rows.length === 0 ? (
        <Typography color="text.secondary">{tp("empty")}</Typography>
      ) : (
        <>
        <TextField
          size="small"
          fullWidth
          placeholder={tp("searchPlaceholder")}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          sx={{ mb: 2, maxWidth: 420 }}
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
        {visibleRows.length === 0 ? (
          <Typography color="text.secondary">{tp("noMatches")}</Typography>
        ) : (
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell sx={{ width: 40 }} />
              {(
                [
                  ["sender", tp("colSender"), undefined],
                  ["subject", tp("colSubject"), undefined],
                  ["art", tp("colArt"), undefined],
                  ["object", tp("colObject"), undefined],
                  ["units", tp("colUnits"), "right"],
                  ["confidence", tp("colConfidence"), "right"],
                  ["status", tp("colStatus"), undefined],
                  ["lead", tp("colLeadStatus"), undefined],
                ] as [SortKey, string, "right" | undefined][]
              ).map(([key, label, align]) => (
                <TableCell
                  key={key}
                  align={align}
                  sortDirection={sortKey === key ? sortDir : false}
                >
                  <TableSortLabel
                    active={sortKey === key}
                    direction={sortKey === key ? sortDir : "asc"}
                    onClick={() => toggleSort(key)}
                  >
                    {label}
                  </TableSortLabel>
                </TableCell>
              ))}
              <TableCell />
            </TableRow>
          </TableHead>
          <TableBody>
            {visibleRows.map((r) => {
              const open = expandedId === r.id;
              const detail = details[r.id];
              const fieldsDirty =
                !!detail &&
                ((detail.art ?? "") !== editArt ||
                  (detail.object_address ?? "") !== editAddress ||
                  (detail.units != null ? String(detail.units) : "") !== editUnits ||
                  (detail.desired_start ?? "") !== editStart);
              return (
                <Fragment key={r.id}>
                  <TableRow hover>
                    <TableCell sx={{ borderBottom: open ? "none" : undefined }}>
                      <IconButton
                        size="small"
                        aria-label={tp("expandAria")}
                        onClick={() => void toggleExpand(r.id)}
                      >
                        {open ? <KeyboardArrowDownIcon /> : <KeyboardArrowRightIcon />}
                      </IconButton>
                    </TableCell>
                    <TableCell sx={{ borderBottom: open ? "none" : undefined }}>
                      {r.sender_name || r.sender_email}
                      <br />
                      <Typography variant="caption" color="text.secondary">
                        {r.sender_email}
                      </Typography>
                    </TableCell>
                    <TableCell sx={{ borderBottom: open ? "none" : undefined }}>
                      {r.subject}
                    </TableCell>
                    <TableCell sx={{ borderBottom: open ? "none" : undefined }}>
                      {r.art ?? "—"}
                    </TableCell>
                    <TableCell sx={{ borderBottom: open ? "none" : undefined }}>
                      {r.object_address ?? "—"}
                    </TableCell>
                    <TableCell align="right" sx={{ borderBottom: open ? "none" : undefined }}>
                      {r.units ?? "—"}
                    </TableCell>
                    <TableCell align="right" sx={{ borderBottom: open ? "none" : undefined }}>
                      {r.confidence != null ? `${Math.round(r.confidence * 100)}%` : "—"}
                    </TableCell>
                    <TableCell sx={{ borderBottom: open ? "none" : undefined }}>
                      <Chip
                        size="small"
                        label={r.status}
                        color={STATUS_COLOR[r.status] ?? "default"}
                      />
                    </TableCell>
                    <TableCell sx={{ borderBottom: open ? "none" : undefined }}>
                      <Select
                        size="small"
                        variant="standard"
                        value={r.lead_status}
                        onChange={(e) => void updateLeadStatus(r.id, e.target.value)}
                        sx={{ minWidth: 120 }}
                      >
                        {LEAD_STATUSES.map((s) => (
                          <MenuItem key={s} value={s}>
                            {tp(`lead.${s}`)}
                          </MenuItem>
                        ))}
                      </Select>
                    </TableCell>
                    <TableCell
                      align="right"
                      sx={{ borderBottom: open ? "none" : undefined, whiteSpace: "nowrap" }}
                    >
                      {r.status !== "SENT" && r.status !== "IGNORED" && (
                        <Button size="small" variant="outlined" onClick={() => openSend(r)}>
                          {tp("send")}
                        </Button>
                      )}
                      <Tooltip title={tp("deleteAria")}>
                        <span>
                          <IconButton
                            size="small"
                            aria-label={tp("deleteAria")}
                            onClick={() => void deleteInquiry(r.id)}
                            disabled={deleteBusy === r.id}
                            sx={{ ml: 0.5 }}
                          >
                            <DeleteOutlineIcon fontSize="small" />
                          </IconButton>
                        </span>
                      </Tooltip>
                    </TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell sx={{ py: 0, border: 0 }} colSpan={COL_SPAN}>
                      <Collapse in={open} timeout="auto" unmountOnExit>
                        <Box sx={{ py: 2, px: 1 }}>
                          {detailBusy === r.id ? (
                            <CircularProgress size={22} />
                          ) : detail ? (
                            <Stack spacing={2}>
                              {panelError && <Alert severity="error">{panelError}</Alert>}
                              {detail.error && (
                                <Alert severity="error">{detail.error}</Alert>
                              )}
                              <Box>
                                <Typography variant="subtitle2" gutterBottom>
                                  {tp("emailBody")}
                                </Typography>
                                <Box
                                  sx={{
                                    whiteSpace: "pre-wrap",
                                    wordBreak: "break-word",
                                    maxHeight: 320,
                                    overflow: "auto",
                                    bgcolor: "action.hover",
                                    p: 1.5,
                                    borderRadius: 1,
                                    fontSize: "0.85rem",
                                    fontFamily: "ui-monospace, monospace",
                                  }}
                                >
                                  {detail.body.trim() || tp("noEmailBody")}
                                </Box>
                              </Box>
                              <Box>
                                <Typography variant="subtitle2" gutterBottom>
                                  {tp("editTitle")}
                                </Typography>
                                <Stack spacing={1.5}>
                                  <Stack direction="row" spacing={2}>
                                    <TextField
                                      select
                                      size="small"
                                      label={tp("colArt")}
                                      value={editArt}
                                      onChange={(e) => setEditArt(e.target.value)}
                                      sx={{ minWidth: 150 }}
                                    >
                                      <MenuItem value="">{tp("artUnknown")}</MenuItem>
                                      <MenuItem value="WEG">WEG</MenuItem>
                                      <MenuItem value="MV">Mietverwaltung</MenuItem>
                                    </TextField>
                                    <TextField
                                      size="small"
                                      type="number"
                                      label={tp("units")}
                                      value={editUnits}
                                      onChange={(e) => setEditUnits(e.target.value)}
                                      slotProps={{ htmlInput: { min: 1, max: 1000 } }}
                                      sx={{ width: 120 }}
                                    />
                                    <TextField
                                      size="small"
                                      type="date"
                                      label={tp("start")}
                                      value={editStart}
                                      onChange={(e) => setEditStart(e.target.value)}
                                      slotProps={{ inputLabel: { shrink: true } }}
                                    />
                                  </Stack>
                                  <TextField
                                    size="small"
                                    fullWidth
                                    label={tp("fieldObject")}
                                    value={editAddress}
                                    onChange={(e) => setEditAddress(e.target.value)}
                                  />
                                  <Box>
                                    <Button
                                      size="small"
                                      onClick={() => void saveFields(r.id)}
                                      disabled={panelBusy || !fieldsDirty}
                                    >
                                      {tp("fieldsSave")}
                                    </Button>
                                  </Box>
                                </Stack>
                              </Box>
                              <Box>
                                <Typography variant="subtitle2" gutterBottom>
                                  {tp("notes")}
                                </Typography>
                                <TextField
                                  multiline
                                  minRows={2}
                                  fullWidth
                                  size="small"
                                  placeholder={tp("notesPlaceholder")}
                                  value={noteDraft}
                                  onChange={(e) => setNoteDraft(e.target.value)}
                                />
                                <Button
                                  size="small"
                                  sx={{ mt: 1 }}
                                  onClick={() => void saveNote(r.id)}
                                  disabled={panelBusy || noteDraft === (detail.review_note ?? "")}
                                >
                                  {tp("notesSave")}
                                </Button>
                              </Box>
                              <Box
                                sx={{
                                  display: "flex",
                                  flexDirection: "row",
                                  gap: 2,
                                  alignItems: "center",
                                  flexWrap: "wrap",
                                }}
                              >
                                {!!r.generated_offer_filename && (
                                  <Button
                                    size="small"
                                    variant="outlined"
                                    startIcon={<DownloadIcon />}
                                    onClick={() =>
                                      void downloadOffer(r.id, r.generated_offer_filename)
                                    }
                                    disabled={panelBusy}
                                  >
                                    {tp("downloadOffer")}
                                  </Button>
                                )}
                                {r.status === "SENT" && (
                                  <Button
                                    size="small"
                                    variant="outlined"
                                    startIcon={<SendIcon />}
                                    onClick={() => void sendReminder(r.id)}
                                    disabled={panelBusy}
                                  >
                                    {tp("reminder")}
                                  </Button>
                                )}
                                {r.reminder_count > 0 && (
                                  <Typography variant="caption" color="text.secondary">
                                    {tp("reminderSent", {
                                      count: r.reminder_count,
                                      date: formatDateTime(r.last_reminder_at),
                                    })}
                                  </Typography>
                                )}
                              </Box>
                            </Stack>
                          ) : (
                            panelError && <Alert severity="error">{panelError}</Alert>
                          )}
                        </Box>
                      </Collapse>
                    </TableCell>
                  </TableRow>
                </Fragment>
              );
            })}
          </TableBody>
        </Table>
        )}
        </>
      )}

      <Dialog open={target !== null} onClose={() => setTarget(null)} fullWidth maxWidth="sm">
        <DialogTitle>{tp("dialogTitle")}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <ToggleButtonGroup
              exclusive
              color="primary"
              value={art}
              onChange={(_, v) => v && setArt(v as Art)}
            >
              <ToggleButton value="WEG">WEG</ToggleButton>
              <ToggleButton value="MV">Mietverwaltung</ToggleButton>
            </ToggleButtonGroup>
            <Stack direction="row" spacing={2}>
              <TextField
                label={tp("units")}
                type="number"
                value={units}
                onChange={(e) => setUnits(e.target.value)}
                slotProps={{ htmlInput: { min: 1, max: 1000 } }}
                fullWidth
              />
              <TextField
                label={tp("start")}
                type="date"
                value={startDate}
                onChange={(e) => {
                  setStartDate(e.target.value);
                }}
                slotProps={{ inputLabel: { shrink: true } }}
                fullWidth
              />
            </Stack>
            <Stack direction="row" spacing={2}>
              <TextField
                label={tp("priceNet")}
                type="number"
                value={monthlyFee}
                onChange={(e) => {
                  setMonthlyFee(e.target.value);
                  setPriceTouched(true);
                }}
                slotProps={{ htmlInput: { min: 0.01, step: "0.01" } }}
                helperText={
                  monthlyFee
                    ? tp("priceGrossHint", {
                        gross: formatEur(grossFromNet(Number(monthlyFee))),
                      })
                    : undefined
                }
                fullWidth
              />
              <TextField
                label={tp("end")}
                type="date"
                value={endDate}
                onChange={(e) => {
                  setEndDate(e.target.value);
                  setEndTouched(true);
                }}
                slotProps={{ inputLabel: { shrink: true } }}
                fullWidth
              />
            </Stack>
            <Divider />
            {art === "WEG" ? (
              <>
                <TextField
                  label={tp("objectStreet")}
                  value={objectStreet}
                  onChange={(e) => setObjectStreet(e.target.value)}
                  fullWidth
                />
                <TextField
                  label={tp("objectPlzCity")}
                  value={objectPlzCity}
                  onChange={(e) => setObjectPlzCity(e.target.value)}
                  fullWidth
                />
              </>
            ) : (
              <>
                <TextField
                  label={tp("recipientName")}
                  value={recipientName}
                  onChange={(e) => setRecipientName(e.target.value)}
                  fullWidth
                />
                <Stack direction="row" spacing={2}>
                  <TextField
                    label={tp("recipientStreet")}
                    value={recipientStreet}
                    onChange={(e) => setRecipientStreet(e.target.value)}
                    fullWidth
                  />
                  <TextField
                    label={tp("recipientPlzCity")}
                    value={recipientPlzCity}
                    onChange={(e) => setRecipientPlzCity(e.target.value)}
                    fullWidth
                  />
                </Stack>
                <TextField
                  label={tp("salutation")}
                  value={salutation}
                  onChange={(e) => setSalutation(e.target.value)}
                  fullWidth
                />
                <TextField
                  label={tp("object")}
                  value={object1}
                  onChange={(e) => setObject1(e.target.value)}
                  fullWidth
                />
              </>
            )}
            {dialogError && <Alert severity="error">{dialogError}</Alert>}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setTarget(null)}>{tp("cancel")}</Button>
          <Button
            variant="contained"
            onClick={() => void submitSend()}
            disabled={busy}
            startIcon={busy ? <CircularProgress size={18} /> : undefined}
          >
            {tp("sendNow")}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
