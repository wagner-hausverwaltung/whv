import { useEffect, useMemo, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Card,
  CardActionArea,
  CardContent,
  Chip,
  Stack,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import { useTranslation } from "react-i18next";
import { api } from "@/api/client";
import {
  TICKET_CATEGORY_LABELS,
  TICKET_STATUS_LABELS,
  type TicketResponse,
  type TicketStatus,
} from "@/api/types";

/** Filter pill state. "open" = anything NOT closed (NEU, OFFEN,
 *  WARTET_AUF_KUNDE) — usually what a user actually wants to see on
 *  "My tickets". Stays in component state (no URL param) because
 *  it's a quick toggle, not deep-linkable. */
type TicketFilter = "all" | "open";

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

export function TicketListPage() {
  const { t } = useTranslation();
  const [tickets, setTickets] = useState<TicketResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<TicketFilter>("open");

  useEffect(() => {
    api
      .get<TicketResponse[]>("/me/tickets")
      // eslint-disable-next-line react-hooks/set-state-in-effect
      .then((r) => setTickets(r.data))
      .catch(() => setError(t("tickets.loadFailed")));
  }, [t]);

  // Client-side filter — /me/tickets already returns every ticket the
  // user can see (capped by the server), so toggling pills is instant.
  const visibleTickets = useMemo(() => {
    if (tickets === null) return null;
    if (filter === "open") {
      return tickets.filter((tk) => tk.status !== "GESCHLOSSEN");
    }
    return tickets;
  }, [tickets, filter]);
  const closedCount = useMemo(
    () =>
      tickets
        ? tickets.filter((tk) => tk.status === "GESCHLOSSEN").length
        : 0,
    [tickets],
  );

  if (error) return <Alert severity="error">{error}</Alert>;
  if (tickets === null || visibleTickets === null) {
    return (
      <Typography variant="body2" color="text.secondary">
        {t("common.loading")}
      </Typography>
    );
  }

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
          {t("tickets.title")}
        </Typography>
        <Button
          component={RouterLink}
          to="/tickets/new"
          variant="contained"
          startIcon={<AddIcon />}
        >
          {t("tickets.newButton")}
        </Button>
      </Box>

      {/* Filter pills — copy the admin queue's visual language so the
          two surfaces stay coherent. "Offen" is the default; flip to
          "Alle" to see closed tickets too. */}
      {tickets.length > 0 && (
        <Stack
          direction="row"
          spacing={1}
          sx={{ flexWrap: "wrap", gap: 1, alignItems: "center" }}
        >
          <Typography
            variant="caption"
            color="text.secondary"
            sx={{ mr: 1 }}
          >
            {t("tickets.filterLabel")}:
          </Typography>
          <Chip
            label={t("tickets.filterOpen")}
            color={filter === "open" ? "primary" : "default"}
            variant={filter === "open" ? "filled" : "outlined"}
            onClick={() => setFilter("open")}
            clickable
          />
          <Chip
            label={`${t("tickets.filterAll")} (${tickets.length})`}
            color={filter === "all" ? "primary" : "default"}
            variant={filter === "all" ? "filled" : "outlined"}
            onClick={() => setFilter("all")}
            clickable
          />
          {filter === "open" && closedCount > 0 && (
            <Typography variant="caption" color="text.secondary">
              {t("tickets.closedHidden", { count: closedCount })}
            </Typography>
          )}
        </Stack>
      )}

      {visibleTickets.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          {tickets.length === 0
            ? t("tickets.empty")
            : t("tickets.noneForFilter")}
        </Typography>
      ) : (
        <Stack spacing={1.5}>
          {visibleTickets.map((tk) => (
            <Card key={tk.id} variant="outlined">
              <CardActionArea
                component={RouterLink}
                to={`/tickets/${tk.id}`}
                sx={{ display: "block" }}
              >
                <CardContent>
                  <Stack
                    direction="row"
                    sx={{
                      justifyContent: "space-between",
                      alignItems: "flex-start",
                      gap: 2,
                    }}
                  >
                    <Box sx={{ minWidth: 0, flex: 1 }}>
                      <Typography
                        variant="body1"
                        sx={{ fontWeight: 500, mb: 0.5 }}
                      >
                        {tk.subject}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {TICKET_CATEGORY_LABELS[tk.category]} ·{" "}
                        {t("tickets.lastActivity")}{" "}
                        {new Date(tk.last_message_at).toLocaleString("de-DE")}
                      </Typography>
                    </Box>
                    <StatusChip status={tk.status} />
                  </Stack>
                </CardContent>
              </CardActionArea>
            </Card>
          ))}
        </Stack>
      )}
    </Stack>
  );
}
