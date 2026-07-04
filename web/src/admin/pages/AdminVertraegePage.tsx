// Org-wide Versorgungsverträge board — every property's supply/service
// contracts, soonest-ending first, with a traffic light for expiring ones:
//   red    = ended (without auto-renewal), or the cancellation deadline
//            (Ende − Kündigungsfrist) is within the next 2 months or past
//   orange = ends within the next 6 months, or auto-renewed past its end
//            date (the stored Ende needs updating)
//   green  = comfortable runway
//   grey   = open-ended (no end date)
// Row click opens the property's Verträge tab. All date math is done on
// ISO date STRINGS (YYYY-MM-DD compares lexicographically) — no Date
// objects, so no UTC-vs-local drift and no setMonth overflow.

import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Chip,
  CircularProgress,
  InputAdornment,
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
import SearchIcon from "@mui/icons-material/Search";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import {
  SUPPLIER_CATEGORY_LABELS,
  type SupplierContractCategory,
  type SupplierContractResponse,
} from "@/api/types";
import { fmtContractDate, fmtPrice } from "@/lib/supplierContracts";

type Ampel = "red" | "orange" | "green" | "grey";

const AMPEL_COLOR: Record<Ampel, string> = {
  red: "#e53935",
  orange: "#fb8c00",
  green: "#43a047",
  grey: "#9e9e9e",
};

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
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState<"" | SupplierContractCategory>("");

  useEffect(() => {
    let cancelled = false;
    api
      .get<SupplierContractResponse[]>("/admin/supplier-contracts")
      .then((r) => {
        if (!cancelled) setRows(r.data);
      })
      .catch(() => {
        if (!cancelled) setError(t("admin.vertraegePage.loadError"));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [t]);

  const todayISO = useMemo(() => localTodayISO(), []);

  // Tooltip for the traffic-light dot. Red is split into "deadline coming
  // up" vs "deadline already missed" so an actionable red is recognizable.
  function ampelTitle(c: SupplierContractResponse): string {
    const a = ampelFor(c, todayISO);
    if (a === "grey") return t("admin.vertraegePage.ampelUnbefristet");
    if (a === "green") return t("admin.vertraegePage.ampelLaeuft");
    if (c.end_date && c.end_date < todayISO) {
      return c.auto_renew
        ? t("admin.vertraegePage.ampelVerlaengert")
        : t("admin.vertraegePage.ampelAbgelaufen");
    }
    const deadline = cancellationDeadlineISO(c);
    if (a === "red" && deadline) {
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

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        {t("admin.vertraegePage.title")}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        {t("admin.vertraegePage.subtitle")}
      </Typography>

      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {loading ? (
        <CircularProgress />
      ) : rows.length === 0 ? (
        <Typography color="text.secondary">{t("admin.vertraegePage.empty")}</Typography>
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
          {visible.length === 0 ? (
            <Typography color="text.secondary">
              {t("admin.vertraegePage.noMatches")}
            </Typography>
          ) : (
            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell sx={{ width: 24 }} />
                    <TableCell>{t("admin.vertraegePage.colProperty")}</TableCell>
                    <TableCell>{t("admin.vertraegePage.colCategory")}</TableCell>
                    <TableCell>{t("admin.vertraegePage.colProvider")}</TableCell>
                    <TableCell>{t("admin.vertraegePage.colNumber")}</TableCell>
                    <TableCell>{t("admin.vertraegePage.colMeter")}</TableCell>
                    <TableCell>{t("admin.vertraegePage.colEnd")}</TableCell>
                    <TableCell>{t("admin.vertraegePage.colCancellation")}</TableCell>
                    <TableCell align="right">{t("admin.vertraegePage.colPrice")}</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {visible.map((c) => (
                    <TableRow
                      key={c.id}
                      hover
                      onClick={() =>
                        navigate(`/admin/properties/${c.property_id}?tab=vertraege`)
                      }
                      sx={{ cursor: "pointer" }}
                    >
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
                      <TableCell>{c.property_name ?? "—"}</TableCell>
                      <TableCell>
                        <Chip size="small" label={SUPPLIER_CATEGORY_LABELS[c.category]} />
                      </TableCell>
                      <TableCell>{c.provider_name}</TableCell>
                      <TableCell>{c.contract_number ?? "—"}</TableCell>
                      <TableCell>{c.meter_number ?? "—"}</TableCell>
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
                      <TableCell align="right">{fmtPrice(c)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          )}
        </>
      )}
    </Box>
  );
}
