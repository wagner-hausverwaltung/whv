import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TableSortLabel,
  TextField,
  Typography,
} from "@mui/material";
import EventBusyOutlinedIcon from "@mui/icons-material/EventBusyOutlined";
import HomeWorkOutlinedIcon from "@mui/icons-material/HomeWorkOutlined";
import SearchIcon from "@mui/icons-material/Search";
import { useTranslation } from "react-i18next";
import { api } from "@/api/client";
import type { AdminPropertyListItem } from "@/api/types";
import { AuthedAvatar } from "@/components/AuthedImage";

const EUR0 = new Intl.NumberFormat("de-DE", {
  style: "currency",
  currency: "EUR",
  maximumFractionDigits: 0,
});

// Sortable columns. The name already embeds the full address (Impower
// names properties "MV Kornwestheimer Straße 59B, 70439 Stammheim"), so a
// separate address column/sort is redundant — we sort on name + HR-ID only.
type SortKey = "name" | "hrId";
type SortDir = "asc" | "desc";

// Hardcoded management-fee step function of total units (Wagner's
// internal schedule). 1100 € is the base tier; the fee steps up at 140,
// 170 and 250 units and caps at 2000 €.
function salaryForUnits(units: number): number {
  if (units >= 250) return 2000;
  if (units >= 170) return 1500;
  if (units >= 140) return 1250;
  return 1100;
}

function readSortField(p: AdminPropertyListItem, key: SortKey): string | null {
  switch (key) {
    case "name":
      return p.name;
    case "hrId":
      return p.property_hr_id;
  }
}

export function AdminPropertiesPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [rows, setRows] = useState<AdminPropertyListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Checked property ids → the units/salary summary box sums these.
  const [selected, setSelected] = useState<Set<string>>(new Set());
  // Free-text search over name + HR-ID; the name carries the address, so
  // a ZIP/street query still matches. Client-side because the list is
  // capped at 200 rows — snappier than a round-trip per keystroke.
  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortDir, setSortDir] = useState<SortDir>("asc");

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      api.get<AdminPropertyListItem[]>("/admin/properties"),
      api.get<{ property_ids: string[] }>("/admin/property-selection"),
    ])
      .then(([propsRes, selRes]) => {
        if (cancelled) return;
        const ids = new Set(propsRes.data.map((p) => p.id));
        setRows(propsRes.data);
        // Drop any ids whose property no longer exists.
        setSelected(new Set(selRes.data.property_ids.filter((id) => ids.has(id))));
      })
      .catch(() => {
        if (!cancelled) setError(t("admin.stammdaten.loadFailed"));
      });
    return () => {
      cancelled = true;
    };
  }, [t]);

  // Persist the org-wide selection on every change (last write wins;
  // best-effort — the next change retries, no intrusive error).
  const saveSelection = (ids: string[]) => {
    void api.put("/admin/property-selection", { property_ids: ids }).catch(() => {});
  };
  const applySelection = (next: Set<string>) => {
    setSelected(next);
    saveSelection([...next]);
  };

  // Filtered + sorted view. Summing units below stays on `selected` over
  // the FULL list, so a search never changes the fee total — only what's
  // shown/select-all-able.
  const visibleRows = useMemo(() => {
    const all = rows ?? [];
    const q = query.trim().toLowerCase();
    const tokens = q.split(/\s+/).filter(Boolean);
    const filtered =
      tokens.length === 0
        ? all
        : all.filter((p) => {
            const haystack = [p.name, p.property_hr_id]
              .filter((s): s is string => !!s)
              .join(" ")
              .toLowerCase();
            return tokens.every((tok) => haystack.includes(tok));
          });
    return [...filtered].sort((a, b) => {
      const av = readSortField(a, sortKey);
      const bv = readSortField(b, sortKey);
      // Empty cells sort last in both directions.
      if (!av && !bv) return 0;
      if (!av) return 1;
      if (!bv) return -1;
      const cmp = av.localeCompare(bv, "de-DE", {
        sensitivity: "base",
        numeric: true,
      });
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [rows, query, sortKey, sortDir]);

  const totalUnits = useMemo(
    () =>
      (rows ?? [])
        .filter((p) => selected.has(p.id))
        .reduce((sum, p) => sum + (p.units_count ?? 0), 0),
    [rows, selected],
  );

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  };

  if (error) return <Alert severity="error">{error}</Alert>;
  if (rows === null) {
    return (
      <Typography variant="body2" color="text.secondary">
        {t("common.loading")}
      </Typography>
    );
  }

  // Select-all operates on the VISIBLE rows so it does what you see when a
  // search is active, while preserving selections outside the filter.
  const allSelected =
    visibleRows.length > 0 && visibleRows.every((p) => selected.has(p.id));
  const someSelected = visibleRows.some((p) => selected.has(p.id)) && !allSelected;
  const toggleAll = () => {
    const next = new Set(selected);
    if (allSelected) visibleRows.forEach((p) => next.delete(p.id));
    else visibleRows.forEach((p) => next.add(p.id));
    applySelection(next);
  };
  const toggle = (id: string) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    applySelection(next);
  };

  return (
    <Stack spacing={3}>
      <Typography variant="h4" component="h1">
        {t("admin.propertiesPage.title")}
      </Typography>

      <TextField
        size="small"
        placeholder={t("admin.propertiesPage.search")}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        sx={{ maxWidth: 480 }}
        slotProps={{
          input: {
            startAdornment: (
              <SearchIcon fontSize="small" sx={{ color: "text.secondary", mr: 1 }} />
            ),
          },
        }}
      />

      {/* Selection summary: sum of the checked rows' units + the
          hardcoded management fee for that unit count. */}
      {selected.size > 0 && (
        <Paper
          variant="outlined"
          sx={{
            p: 2,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 2,
            flexWrap: "wrap",
          }}
        >
          <Box>
            <Typography
              variant="overline"
              color="text.secondary"
              sx={{ display: "block", lineHeight: 1.4 }}
            >
              {t("admin.propertiesPage.summaryLabel")}
            </Typography>
            <Typography variant="h5" sx={{ fontWeight: 700 }}>
              {t("admin.propertiesPage.summaryValue", {
                units: totalUnits,
                salary: EUR0.format(salaryForUnits(totalUnits)),
              })}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {t("admin.propertiesPage.summarySelected", {
                count: selected.size,
              })}
            </Typography>
          </Box>
          <Button size="small" onClick={() => applySelection(new Set())}>
            {t("admin.propertiesPage.clearSelection")}
          </Button>
        </Paper>
      )}

      {visibleRows.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          {query.trim()
            ? t("admin.propertiesPage.noMatches")
            : t("admin.stammdaten.empty")}
        </Typography>
      ) : (
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell padding="checkbox">
                  <Checkbox
                    size="small"
                    checked={allSelected}
                    indeterminate={someSelected}
                    onChange={toggleAll}
                  />
                </TableCell>
                <TableCell sx={{ width: 64 }} />
                <TableCell sortDirection={sortKey === "name" ? sortDir : false}>
                  <TableSortLabel
                    active={sortKey === "name"}
                    direction={sortKey === "name" ? sortDir : "asc"}
                    onClick={() => toggleSort("name")}
                  >
                    {t("admin.propertiesPage.name")}
                  </TableSortLabel>
                </TableCell>
                <TableCell sortDirection={sortKey === "hrId" ? sortDir : false}>
                  <TableSortLabel
                    active={sortKey === "hrId"}
                    direction={sortKey === "hrId" ? sortDir : "asc"}
                    onClick={() => toggleSort("hrId")}
                  >
                    {t("admin.propertiesPage.hrId")}
                  </TableSortLabel>
                </TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {visibleRows.map((p) => (
                <TableRow
                  key={p.id}
                  hover
                  onClick={() => navigate(`/admin/properties/${p.id}`)}
                  sx={{ cursor: "pointer" }}
                >
                  <TableCell padding="checkbox" onClick={(e) => e.stopPropagation()}>
                    <Checkbox
                      size="small"
                      checked={selected.has(p.id)}
                      onChange={() => toggle(p.id)}
                    />
                  </TableCell>
                  <TableCell sx={{ width: 64 }}>
                    <AuthedAvatar
                      variant="rounded"
                      relativeUrl={p.image_url}
                      sx={{
                        width: 40,
                        height: 40,
                        bgcolor: "action.hover",
                        color: "text.disabled",
                      }}
                    >
                      <HomeWorkOutlinedIcon fontSize="small" />
                    </AuthedAvatar>
                  </TableCell>
                  <TableCell>
                    <Stack
                      direction="row"
                      spacing={1}
                      sx={{ alignItems: "center", flexWrap: "wrap" }}
                    >
                      <Typography variant="body2" sx={{ fontWeight: 500 }}>
                        {p.name}
                      </Typography>
                      {p.needs_current_year_etv && (
                        <Chip
                          size="small"
                          color="warning"
                          variant="outlined"
                          icon={<EventBusyOutlinedIcon />}
                          label={t("admin.propertiesPage.etvMissing", {
                            year: new Date().getFullYear(),
                          })}
                        />
                      )}
                    </Stack>
                  </TableCell>
                  <TableCell sx={{ fontFamily: "ui-monospace, Menlo, monospace" }}>
                    <Typography variant="caption" color="text.secondary">
                      {p.property_hr_id ?? "—"}
                    </Typography>
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
    </Stack>
  );
}
