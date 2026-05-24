import { useCallback, useEffect, useState } from "react";
import { Link as RouterLink, useSearchParams } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
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
import AddIcon from "@mui/icons-material/Add";
import { useTranslation } from "react-i18next";
import { api } from "@/api/client";
import {
  RESOLUTION_MODE_LABELS,
  RESOLUTION_STATUS_LABELS,
  type ResolutionResponse,
  type ResolutionStatus,
} from "@/api/types";

const STATUSES: ResolutionStatus[] = [
  "ENTWURF",
  "OFFEN",
  "GESCHLOSSEN",
  "ANGENOMMEN",
  "ABGELEHNT",
];

function StatusChip({ status }: { status: ResolutionStatus }) {
  const color: "success" | "error" | "info" | "default" =
    status === "ANGENOMMEN"
      ? "success"
      : status === "ABGELEHNT"
        ? "error"
        : status === "OFFEN"
          ? "info"
          : "default";
  return (
    <Chip
      size="small"
      label={RESOLUTION_STATUS_LABELS[status]}
      color={color}
      variant={status === "ENTWURF" || status === "GESCHLOSSEN" ? "outlined" : "filled"}
    />
  );
}

export function AdminResolutionsPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const statusFilter = (params.get("status") ?? "") as "" | ResolutionStatus;
  const [rows, setRows] = useState<ResolutionResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    setRows(null);
    const url = statusFilter
      ? `/admin/resolutions?status=${encodeURIComponent(statusFilter)}`
      : "/admin/resolutions";
    try {
      const r = await api.get<ResolutionResponse[]>(url);
      setRows(r.data);
    } catch {
      setError(t("admin.resolutionsPage.loadFailed"));
    }
  }, [statusFilter, t]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const setStatus = (next: "" | ResolutionStatus) => {
    setParams(next ? { status: next } : {});
  };

  return (
    <Stack spacing={3}>
      <Box
        sx={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          flexWrap: "wrap",
          gap: 2,
        }}
      >
        <Typography variant="h4" component="h1">
          {t("admin.resolutionsPage.title")}
        </Typography>
        <Button
          component={RouterLink}
          to="/admin/resolutions/new"
          variant="contained"
          startIcon={<AddIcon />}
        >
          {t("admin.resolutionsPage.newButton")}
        </Button>
      </Box>

      <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", gap: 1 }}>
        <Chip
          label={t("admin.resolutionsPage.filterAll")}
          color={!statusFilter ? "primary" : "default"}
          variant={!statusFilter ? "filled" : "outlined"}
          onClick={() => setStatus("")}
          clickable
        />
        {STATUSES.map((s) => (
          <Chip
            key={s}
            label={RESOLUTION_STATUS_LABELS[s]}
            color={statusFilter === s ? "primary" : "default"}
            variant={statusFilter === s ? "filled" : "outlined"}
            onClick={() => setStatus(s)}
            clickable
          />
        ))}
      </Stack>

      {error && <Alert severity="error">{error}</Alert>}

      {rows === null ? (
        <Typography variant="body2" color="text.secondary">
          {t("common.loading")}
        </Typography>
      ) : rows.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          {t("admin.resolutionsPage.empty")}
        </Typography>
      ) : (
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>{t("admin.resolutionsPage.status")}</TableCell>
                <TableCell>{t("admin.resolutionsPage.mode")}</TableCell>
                <TableCell>{t("admin.resolutionsPage.titleCol")}</TableCell>
                <TableCell>{t("admin.resolutionsPage.closesAt")}</TableCell>
                <TableCell>{t("admin.resolutionsPage.created")}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((r) => (
                <TableRow
                  key={r.id}
                  hover
                  component={RouterLink}
                  to={`/admin/resolutions/${r.id}`}
                  sx={{
                    textDecoration: "none",
                    cursor: "pointer",
                    "& td": { color: "text.primary" },
                  }}
                >
                  <TableCell>
                    <StatusChip status={r.status} />
                  </TableCell>
                  <TableCell>
                    <Typography variant="caption" color="text.secondary">
                      {RESOLUTION_MODE_LABELS[r.mode]}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2" sx={{ fontWeight: 500 }}>
                      {r.title}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="caption" color="text.secondary">
                      {new Date(r.closes_at).toLocaleString("de-DE")}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="caption" color="text.secondary">
                      {new Date(r.created_at).toLocaleDateString("de-DE")}
                    </Typography>
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
