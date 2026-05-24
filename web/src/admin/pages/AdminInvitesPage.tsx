import { useCallback, useEffect, useState } from "react";
import { Link as RouterLink, useSearchParams } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Chip,
  IconButton,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutlineOutlined";
import { useTranslation } from "react-i18next";
import { api } from "@/api/client";
import {
  INVITE_STATUS_LABELS,
  type AdminInviteResponse,
  type InviteStatus,
} from "@/api/types";

const FILTERS: { value: "" | InviteStatus; key: string }[] = [
  { value: "", key: "filterAll" },
  { value: "pending", key: "filterPending" },
  { value: "consumed", key: "filterConsumed" },
  { value: "expired", key: "filterExpired" },
];

function StatusChip({ status }: { status: InviteStatus }) {
  const color: "success" | "default" | "error" =
    status === "pending"
      ? "success"
      : status === "consumed"
        ? "default"
        : "error";
  return (
    <Chip
      size="small"
      label={INVITE_STATUS_LABELS[status]}
      color={color}
      variant={status === "consumed" ? "outlined" : "filled"}
    />
  );
}

export function AdminInvitesPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const filter = (params.get("status") ?? "") as "" | InviteStatus;
  const [rows, setRows] = useState<AdminInviteResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    setRows(null);
    try {
      const url = filter
        ? `/admin/invites?status=${encodeURIComponent(filter)}`
        : "/admin/invites";
      const r = await api.get<AdminInviteResponse[]>(url);
      setRows(r.data);
    } catch {
      setError(t("admin.invitesPage.loadFailed"));
    }
  }, [filter, t]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const setFilter = (next: "" | InviteStatus) => {
    setParams(next ? { status: next } : {});
  };

  const revoke = async (code: string) => {
    if (!window.confirm(t("admin.invitesPage.revokeConfirm"))) return;
    try {
      await api.delete(`/admin/invites/${code}`);
      await load();
    } catch {
      setError(t("admin.invitesPage.revokeFailed"));
    }
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
          {t("admin.invitesPage.title")}
        </Typography>
        <Button
          component={RouterLink}
          to="/admin/invites/new"
          variant="contained"
          startIcon={<AddIcon />}
        >
          {t("admin.invitesPage.newButton")}
        </Button>
      </Box>

      <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", gap: 1 }}>
        {FILTERS.map((f) => (
          <Chip
            key={f.value || "all"}
            label={t(`admin.invitesPage.${f.key}`)}
            color={filter === f.value ? "primary" : "default"}
            variant={filter === f.value ? "filled" : "outlined"}
            onClick={() => setFilter(f.value)}
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
          {t("admin.invitesPage.empty")}
        </Typography>
      ) : (
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>{t("admin.invitesPage.code")}</TableCell>
                <TableCell>{t("admin.invitesPage.email")}</TableCell>
                <TableCell>{t("admin.invitesPage.role")}</TableCell>
                <TableCell>{t("admin.invitesPage.impowerId")}</TableCell>
                <TableCell>{t("admin.invitesPage.expiresAt")}</TableCell>
                <TableCell>{t("admin.invitesPage.status")}</TableCell>
                <TableCell align="right">
                  {t("admin.invitesPage.actions")}
                </TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((r) => (
                <TableRow key={r.code} hover>
                  <TableCell
                    sx={{ fontFamily: "ui-monospace, Menlo, monospace" }}
                  >
                    {r.code}
                  </TableCell>
                  <TableCell>{r.email}</TableCell>
                  <TableCell>
                    <Typography variant="caption" color="text.secondary">
                      {r.role}
                    </Typography>
                  </TableCell>
                  <TableCell
                    sx={{ fontFamily: "ui-monospace, Menlo, monospace" }}
                  >
                    {r.contact_id_impower ?? "—"}
                  </TableCell>
                  <TableCell>
                    <Typography variant="caption" color="text.secondary">
                      {new Date(r.expires_at).toLocaleDateString("de-DE")}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <StatusChip status={r.status} />
                  </TableCell>
                  <TableCell align="right">
                    {r.status === "pending" && (
                      <Tooltip title={t("admin.invitesPage.revoke")}>
                        <IconButton
                          size="small"
                          onClick={() => revoke(r.code)}
                          aria-label={t("admin.invitesPage.revoke")}
                        >
                          <DeleteOutlineIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    )}
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
