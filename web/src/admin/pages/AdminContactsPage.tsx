import { useEffect, useState } from "react";
import {
  Alert,
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
import type { AdminContactListItem } from "@/api/types";

export function AdminContactsPage() {
  const { t } = useTranslation();
  const [rows, setRows] = useState<AdminContactListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<AdminContactListItem[]>("/admin/contacts")
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
        {t("admin.contactsPage.title")}
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
                <TableCell>{t("admin.contactsPage.name")}</TableCell>
                <TableCell>{t("admin.contactsPage.kind")}</TableCell>
                <TableCell>{t("admin.contactsPage.email")}</TableCell>
                <TableCell>{t("admin.contactsPage.phone")}</TableCell>
                <TableCell>{t("admin.contactsPage.city")}</TableCell>
                <TableCell>{t("admin.contactsPage.impowerId")}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((c) => (
                <TableRow key={c.id} hover>
                  <TableCell>
                    <Typography variant="body2" sx={{ fontWeight: 500 }}>
                      {c.name}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="caption" color="text.secondary">
                      {c.kind}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="caption" color="text.secondary">
                      {c.email ?? "—"}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="caption" color="text.secondary">
                      {c.phone ?? "—"}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="caption" color="text.secondary">
                      {c.city ?? "—"}
                    </Typography>
                  </TableCell>
                  <TableCell
                    sx={{ fontFamily: "ui-monospace, Menlo, monospace" }}
                  >
                    <Typography variant="caption" color="text.secondary">
                      {c.impower_id ?? "—"}
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
