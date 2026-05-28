import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Alert,
  Avatar,
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
  Typography,
} from "@mui/material";
import EventBusyOutlinedIcon from "@mui/icons-material/EventBusyOutlined";
import HomeWorkOutlinedIcon from "@mui/icons-material/HomeWorkOutlined";
import { useTranslation } from "react-i18next";
import { api, API_BASE_URL } from "@/api/client";
import type { AdminPropertyListItem } from "@/api/types";

const EUR0 = new Intl.NumberFormat("de-DE", {
  style: "currency",
  currency: "EUR",
  maximumFractionDigits: 0,
});

// Hardcoded management-fee step function of total units (Wagner's
// internal schedule). 1100 € is the base tier; the fee steps up at 140,
// 170 and 250 units and caps at 2000 €.
function salaryForUnits(units: number): number {
  if (units >= 250) return 2000;
  if (units >= 170) return 1500;
  if (units >= 140) return 1250;
  return 1100;
}

export function AdminPropertiesPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [rows, setRows] = useState<AdminPropertyListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Checked property ids → the units/salary summary box sums these.
  const [selected, setSelected] = useState<Set<string>>(new Set());

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

  const totalUnits = useMemo(
    () =>
      (rows ?? [])
        .filter((p) => selected.has(p.id))
        .reduce((sum, p) => sum + (p.units_count ?? 0), 0),
    [rows, selected],
  );

  if (error) return <Alert severity="error">{error}</Alert>;
  if (rows === null) {
    return (
      <Typography variant="body2" color="text.secondary">
        {t("common.loading")}
      </Typography>
    );
  }

  const allSelected = rows.length > 0 && rows.every((p) => selected.has(p.id));
  const someSelected = selected.size > 0 && !allSelected;
  const toggleAll = () =>
    applySelection(allSelected ? new Set() : new Set(rows.map((p) => p.id)));
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

      {rows.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          {t("admin.stammdaten.empty")}
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
                <TableCell>{t("admin.propertiesPage.name")}</TableCell>
                <TableCell>{t("admin.propertiesPage.address")}</TableCell>
                <TableCell>{t("admin.propertiesPage.hrId")}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((p) => {
                const street = [p.street, p.number].filter(Boolean).join(" ");
                const zipCity = [p.postal_code, p.city]
                  .filter(Boolean)
                  .join(" ");
                const addr =
                  [street, zipCity].filter(Boolean).join(" · ") || "—";
                return (
                  <TableRow
                    key={p.id}
                    hover
                    onClick={() => navigate(`/admin/properties/${p.id}`)}
                    sx={{ cursor: "pointer" }}
                  >
                    <TableCell
                      padding="checkbox"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <Checkbox
                        size="small"
                        checked={selected.has(p.id)}
                        onChange={() => toggle(p.id)}
                      />
                    </TableCell>
                    <TableCell sx={{ width: 64 }}>
                      <Avatar
                        variant="rounded"
                        src={
                          p.image_url
                            ? `${API_BASE_URL}${p.image_url}`
                            : undefined
                        }
                        sx={{
                          width: 40,
                          height: 40,
                          bgcolor: "action.hover",
                          color: "text.disabled",
                        }}
                      >
                        <HomeWorkOutlinedIcon fontSize="small" />
                      </Avatar>
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
                    <TableCell>
                      <Typography variant="caption" color="text.secondary">
                        {addr}
                      </Typography>
                    </TableCell>
                    <TableCell
                      sx={{ fontFamily: "ui-monospace, Menlo, monospace" }}
                    >
                      <Typography variant="caption" color="text.secondary">
                        {p.property_hr_id ?? "—"}
                      </Typography>
                    </TableCell>
                  </TableRow>
                );
              })}
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
