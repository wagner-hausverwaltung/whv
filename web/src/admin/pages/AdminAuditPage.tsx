import { useEffect, useState } from "react";
import {
  Alert,
  Box,
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
import { useTranslation } from "react-i18next";
import { api } from "@/api/client";
import type { AdminAuditLogResponse } from "@/api/types";

function formatPayload(payload: Record<string, unknown> | null): string {
  if (!payload) return "—";
  const json = JSON.stringify(payload);
  // Truncate long payloads — click-to-expand can come later.
  return json.length > 140 ? json.slice(0, 137) + "…" : json;
}

export function AdminAuditPage() {
  const { t } = useTranslation();
  const [rows, setRows] = useState<AdminAuditLogResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<AdminAuditLogResponse[]>("/admin/audit-log")
      // eslint-disable-next-line react-hooks/set-state-in-effect
      .then((r) => setRows(r.data))
      .catch(() => setError(t("admin.auditPage.loadFailed")));
  }, [t]);

  return (
    <Stack spacing={3}>
      <Box>
        <Typography variant="h4" component="h1" gutterBottom>
          {t("admin.auditPage.title")}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {t("admin.auditPage.subtitle")}
        </Typography>
      </Box>

      {error && <Alert severity="error">{error}</Alert>}

      {rows === null ? (
        <Typography variant="body2" color="text.secondary">
          {t("common.loading")}
        </Typography>
      ) : rows.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          {t("admin.auditPage.empty")}
        </Typography>
      ) : (
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>{t("admin.auditPage.when")}</TableCell>
                <TableCell>{t("admin.auditPage.actor")}</TableCell>
                <TableCell>{t("admin.auditPage.action")}</TableCell>
                <TableCell>{t("admin.auditPage.target")}</TableCell>
                <TableCell>{t("admin.auditPage.payload")}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((r) => (
                <TableRow key={r.id} hover>
                  <TableCell>
                    <Typography variant="caption" color="text.secondary">
                      {new Date(r.created_at).toLocaleString("de-DE")}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2">
                      {r.actor_email ?? "—"}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Chip
                      label={r.action}
                      size="small"
                      variant="outlined"
                      sx={{
                        fontFamily: "ui-monospace, Menlo, monospace",
                        fontSize: "0.72rem",
                      }}
                    />
                  </TableCell>
                  <TableCell
                    sx={{ fontFamily: "ui-monospace, Menlo, monospace" }}
                  >
                    <Typography variant="caption">
                      {r.target_type ?? "—"}
                      {r.target_id && (
                        <>
                          <br />
                          <Typography
                            component="span"
                            variant="caption"
                            color="text.secondary"
                          >
                            {r.target_id}
                          </Typography>
                        </>
                      )}
                    </Typography>
                  </TableCell>
                  <TableCell
                    sx={{
                      fontFamily: "ui-monospace, Menlo, monospace",
                      fontSize: "0.72rem",
                      maxWidth: 320,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                    }}
                  >
                    {formatPayload(r.payload_json)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}
    </Stack>
  );
}
