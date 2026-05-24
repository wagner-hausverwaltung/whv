import { useEffect, useState } from "react";
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

  useEffect(() => {
    api
      .get<TicketResponse[]>("/me/tickets")
      // eslint-disable-next-line react-hooks/set-state-in-effect
      .then((r) => setTickets(r.data))
      .catch(() => setError(t("tickets.loadFailed")));
  }, [t]);

  if (error) return <Alert severity="error">{error}</Alert>;
  if (tickets === null) {
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

      {tickets.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          {t("tickets.empty")}
        </Typography>
      ) : (
        <Stack spacing={1.5}>
          {tickets.map((tk) => (
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
