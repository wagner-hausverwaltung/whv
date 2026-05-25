import { useEffect, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import {
  Alert,
  Avatar,
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
import HomeWorkOutlinedIcon from "@mui/icons-material/HomeWorkOutlined";
import { useTranslation } from "react-i18next";
import { api, API_BASE_URL } from "@/api/client";
import type { AdminPropertyListItem } from "@/api/types";

export function AdminPropertiesPage() {
  const { t } = useTranslation();
  const [rows, setRows] = useState<AdminPropertyListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<AdminPropertyListItem[]>("/admin/properties")
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
        {t("admin.propertiesPage.title")}
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
                <TableCell sx={{ width: 64 }} />
                <TableCell>{t("admin.propertiesPage.name")}</TableCell>
                <TableCell>{t("admin.propertiesPage.type")}</TableCell>
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
                    component={RouterLink}
                    to={`/admin/properties/${p.id}`}
                    sx={{
                      textDecoration: "none",
                      cursor: "pointer",
                      "& td": { color: "text.primary" },
                    }}
                  >
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
                      <Typography variant="body2" sx={{ fontWeight: 500 }}>
                        {p.name}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      <Typography variant="caption" color="text.secondary">
                        {p.type}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      <Typography variant="caption" color="text.secondary">
                        {addr}
                      </Typography>
                    </TableCell>
                    <TableCell
                      sx={{ fontFamily: "ui-monospace, Menlo, monospace" }}
                    >
                      <Typography
                        variant="caption"
                        color="text.secondary"
                      >
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
