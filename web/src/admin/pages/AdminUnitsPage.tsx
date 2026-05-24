import { useEffect, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import {
  Alert,
  Link,
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
import { useTranslation } from "react-i18next";
import { api } from "@/api/client";
import type { AdminUnitListItem } from "@/api/types";

export function AdminUnitsPage() {
  const { t } = useTranslation();
  const [rows, setRows] = useState<AdminUnitListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<AdminUnitListItem[]>("/admin/units")
      // eslint-disable-next-line react-hooks/set-state-in-effect
      .then((r) => setRows(r.data))
      .catch(() => setError(t("admin.stammdaten.loadFailed")));
  }, [t]);

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
                <TableCell align="right">
                  {t("admin.unitsPage.area")}
                </TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((u) => (
                <TableRow key={u.id} hover>
                  <TableCell>
                    <Link
                      component={RouterLink}
                      to={`/admin/properties/${u.property_id}`}
                      underline="hover"
                      sx={{ fontWeight: 500 }}
                    >
                      {u.property_name}
                    </Link>
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
                    {u.area_m2 != null
                      ? u.area_m2.toLocaleString("de-DE", {
                          minimumFractionDigits: 2,
                          maximumFractionDigits: 2,
                        })
                      : "—"}
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
