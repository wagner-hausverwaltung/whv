import { useCallback, useEffect, useState } from "react";
import { Link as RouterLink, useSearchParams } from "react-router-dom";
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
import {
  TICKET_CATEGORY_LABELS,
  TICKET_STATUS_LABELS,
  type TicketCategory,
  type TicketResponse,
  type TicketStatus,
} from "@/api/types";

const STATUSES: TicketStatus[] = [
  "NEU",
  "OFFEN",
  "WARTET_AUF_KUNDE",
  "GESCHLOSSEN",
];

const CATEGORIES: TicketCategory[] = [
  "SCHADEN",
  "VERWALTUNG",
  "HAUSGELD",
  "SONSTIGES",
];

function StatusChip({ status }: { status: TicketStatus }) {
  const color: "success" | "warning" | "default" | "info" =
    status === "GESCHLOSSEN"
      ? "default"
      : status === "WARTET_AUF_KUNDE"
        ? "warning"
        : status === "NEU"
          ? "info"
          : "success";
  return (
    <Chip
      size="small"
      label={TICKET_STATUS_LABELS[status]}
      color={color}
      variant={status === "GESCHLOSSEN" ? "outlined" : "filled"}
    />
  );
}

export function AdminTicketsPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const statusFilter = (params.get("status") ?? "") as "" | TicketStatus;
  const categoryFilter = (params.get("category") ?? "") as "" | TicketCategory;
  const [rows, setRows] = useState<TicketResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    setRows(null);
    const qs = new URLSearchParams();
    if (statusFilter) qs.set("status", statusFilter);
    if (categoryFilter) qs.set("category", categoryFilter);
    const url =
      qs.toString().length > 0
        ? `/admin/tickets?${qs.toString()}`
        : "/admin/tickets";
    try {
      const r = await api.get<TicketResponse[]>(url);
      setRows(r.data);
    } catch {
      setError(t("admin.ticketsPage.loadFailed"));
    }
  }, [statusFilter, categoryFilter, t]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const setStatus = (next: "" | TicketStatus) => {
    const p = new URLSearchParams(params);
    if (next) p.set("status", next);
    else p.delete("status");
    setParams(p);
  };
  const setCategory = (next: "" | TicketCategory) => {
    const p = new URLSearchParams(params);
    if (next) p.set("category", next);
    else p.delete("category");
    setParams(p);
  };

  return (
    <Stack spacing={3}>
      <Typography variant="h4" component="h1">
        {t("admin.ticketsPage.title")}
      </Typography>

      <Stack spacing={1}>
        <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", gap: 1 }}>
          <Typography
            variant="caption"
            color="text.secondary"
            sx={{ alignSelf: "center", mr: 1 }}
          >
            {t("admin.ticketsPage.status")}:
          </Typography>
          <Chip
            label={t("admin.ticketsPage.filterAll")}
            color={!statusFilter ? "primary" : "default"}
            variant={!statusFilter ? "filled" : "outlined"}
            onClick={() => setStatus("")}
            clickable
          />
          {STATUSES.map((s) => (
            <Chip
              key={s}
              label={TICKET_STATUS_LABELS[s]}
              color={statusFilter === s ? "primary" : "default"}
              variant={statusFilter === s ? "filled" : "outlined"}
              onClick={() => setStatus(s)}
              clickable
            />
          ))}
        </Stack>
        <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", gap: 1 }}>
          <Typography
            variant="caption"
            color="text.secondary"
            sx={{ alignSelf: "center", mr: 1 }}
          >
            {t("admin.ticketsPage.category")}:
          </Typography>
          <Chip
            label={t("admin.ticketsPage.filterAll")}
            color={!categoryFilter ? "primary" : "default"}
            variant={!categoryFilter ? "filled" : "outlined"}
            onClick={() => setCategory("")}
            clickable
          />
          {CATEGORIES.map((c) => (
            <Chip
              key={c}
              label={TICKET_CATEGORY_LABELS[c]}
              color={categoryFilter === c ? "primary" : "default"}
              variant={categoryFilter === c ? "filled" : "outlined"}
              onClick={() => setCategory(c)}
              clickable
            />
          ))}
        </Stack>
      </Stack>

      {error && <Alert severity="error">{error}</Alert>}

      {rows === null ? (
        <Typography variant="body2" color="text.secondary">
          {t("common.loading")}
        </Typography>
      ) : rows.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          {t("admin.ticketsPage.empty")}
        </Typography>
      ) : (
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>{t("admin.ticketsPage.status")}</TableCell>
                <TableCell>{t("admin.ticketsPage.category")}</TableCell>
                <TableCell>{t("admin.ticketsPage.subject")}</TableCell>
                <TableCell>{t("admin.ticketsPage.lastActivity")}</TableCell>
                <TableCell>{t("admin.ticketsPage.created")}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((r) => (
                <TableRow
                  key={r.id}
                  hover
                  component={RouterLink}
                  to={`/admin/tickets/${r.id}`}
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
                      {TICKET_CATEGORY_LABELS[r.category]}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2" sx={{ fontWeight: 500 }}>
                      {r.subject}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="caption" color="text.secondary">
                      {new Date(r.last_message_at).toLocaleString("de-DE")}
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
      {rows && rows.length === 200 && (
        <Box>
          <Typography variant="caption" color="text.secondary">
            Anzeige der neuesten 200 Tickets nach letzter Aktivität.
          </Typography>
        </Box>
      )}
    </Stack>
  );
}
