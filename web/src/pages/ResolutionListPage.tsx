import { useEffect, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import {
  Alert,
  Box,
  Card,
  CardActionArea,
  CardContent,
  Chip,
  Stack,
  Typography,
} from "@mui/material";
import { useTranslation } from "react-i18next";
import { api } from "@/api/client";
import {
  RESOLUTION_MODE_LABELS,
  RESOLUTION_STATUS_LABELS,
  type ResolutionResponse,
  type ResolutionStatus,
} from "@/api/types";

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

export function ResolutionListPage() {
  const { t } = useTranslation();
  const [rows, setRows] = useState<ResolutionResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<ResolutionResponse[]>("/me/resolutions")
       
      .then((r) => setRows(r.data))
      .catch(() => setError("Beschlüsse konnten nicht geladen werden."));
  }, []);

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
      <Box>
        <Typography variant="h4" component="h1" gutterBottom>
          {t("resolutions.title")}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {t("resolutions.subtitle")}
        </Typography>
      </Box>

      {rows.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          {t("resolutions.empty")}
        </Typography>
      ) : (
        <Stack spacing={1.5}>
          {rows.map((r) => (
            <Card key={r.id} variant="outlined">
              <CardActionArea
                component={RouterLink}
                to={`/resolutions/${r.id}`}
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
                        {r.title}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {RESOLUTION_MODE_LABELS[r.mode]} ·{" "}
                        {t("resolutions.deadline")}{" "}
                        {new Date(r.closes_at).toLocaleString("de-DE")}
                      </Typography>
                    </Box>
                    <StatusChip status={r.status} />
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
