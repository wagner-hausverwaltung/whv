import { useEffect, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import {
  Alert,
  Chip,
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
import type { AdminContractListItem } from "@/api/types";

export function AdminContractsPage() {
  const { t } = useTranslation();
  const [rows, setRows] = useState<AdminContractListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<AdminContractListItem[]>("/admin/contracts")
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
        {t("admin.contractsPage.title")}
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
                <TableCell>{t("admin.contractsPage.property")}</TableCell>
                <TableCell>{t("admin.contractsPage.type")}</TableCell>
                <TableCell>{t("admin.contractsPage.number")}</TableCell>
                <TableCell>{t("admin.contractsPage.name")}</TableCell>
                <TableCell>{t("admin.contractsPage.start")}</TableCell>
                <TableCell>{t("admin.contractsPage.end")}</TableCell>
                <TableCell>{t("admin.contractsPage.vacant")}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((c) => (
                <TableRow key={c.id} hover>
                  <TableCell>
                    <Link
                      component={RouterLink}
                      to={`/admin/properties/${c.property_id}`}
                      underline="hover"
                      sx={{ fontWeight: 500 }}
                    >
                      {c.property_name}
                    </Link>
                  </TableCell>
                  <TableCell>
                    <Typography variant="caption" color="text.secondary">
                      {c.type}
                    </Typography>
                  </TableCell>
                  <TableCell
                    sx={{ fontFamily: "ui-monospace, Menlo, monospace" }}
                  >
                    {c.contract_number ?? "—"}
                  </TableCell>
                  <TableCell>
                    <Typography variant="caption" color="text.secondary">
                      {c.name ?? "—"}
                    </Typography>
                  </TableCell>
                  <TableCell>{c.start_date ?? "—"}</TableCell>
                  <TableCell>{c.end_date ?? "—"}</TableCell>
                  <TableCell>
                    {c.is_vacant === true ? (
                      <Chip size="small" label="●" color="warning" />
                    ) : (
                      "—"
                    )}
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
