/**
 * Portal list of Eigentümerversammlungen for a single property.
 *
 * Mirrors the iOS Versammlungen tab layout — two sections (Geplant /
 * Vergangen), status chip + datetime + location per row, "Protokoll
 * vorhanden" hint when a signed PDF exists. ABGESAGT rows are
 * filtered server-side so they never appear here.
 */

import { useCallback, useEffect, useState } from "react";
import { Link as RouterLink, useParams } from "react-router-dom";
import {
  Alert,
  Box,
  Chip,
  Paper,
  Stack,
  Typography,
} from "@mui/material";
import CalendarIcon from "@mui/icons-material/CalendarMonthOutlined";
import LocationIcon from "@mui/icons-material/LocationOnOutlined";
import PictureAsPdfIcon from "@mui/icons-material/PictureAsPdfOutlined";
import { api } from "@/api/client";
import {
  ASSEMBLY_STATUS_LABELS,
  type AssemblyResponse,
  type AssemblyStatus,
} from "@/api/types";

const STATUS_COLOR: Record<
  AssemblyStatus,
  "default" | "primary" | "success"
> = {
  // ABGESAGT is filtered server-side; we never render it here, so no
  // color mapping needed for it.
  GEPLANT: "default",
  EINGELADEN: "primary",
  ABGEHALTEN: "success",
  ABGESAGT: "default",
};

function StatusChip({ status }: { status: AssemblyStatus }) {
  return (
    <Chip
      size="small"
      label={ASSEMBLY_STATUS_LABELS[status]}
      color={STATUS_COLOR[status]}
      variant={status === "GEPLANT" ? "outlined" : "filled"}
    />
  );
}

function formatDateRange(startIso: string, endIso: string): string {
  const start = new Date(startIso);
  const end = new Date(endIso);
  const sameDay =
    start.getFullYear() === end.getFullYear() &&
    start.getMonth() === end.getMonth() &&
    start.getDate() === end.getDate();
  const date = new Intl.DateTimeFormat("de-DE", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
  const time = new Intl.DateTimeFormat("de-DE", {
    hour: "2-digit",
    minute: "2-digit",
  });
  if (sameDay) {
    return `${date.format(start)}, ${time.format(start)}–${time.format(end)} Uhr`;
  }
  return `${date.format(start)} ${time.format(start)} – ${date.format(end)} ${time.format(end)}`;
}

export function MyAssembliesPage() {
  const { id } = useParams<{ id: string }>();
  const [rows, setRows] = useState<AssemblyResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!id) return;
    setError(null);
    try {
      const r = await api.get<AssemblyResponse[]>(
        `/me/properties/${id}/assemblies`,
      );
      setRows(r.data);
    } catch {
      setError("Versammlungen konnten nicht geladen werden.");
    }
  }, [id]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const upcoming = (rows ?? [])
    .filter((a) => a.status === "GEPLANT" || a.status === "EINGELADEN")
    .sort(
      (a, b) =>
        new Date(a.scheduled_start).getTime() -
        new Date(b.scheduled_start).getTime(),
    );
  const past = (rows ?? [])
    .filter((a) => a.status === "ABGEHALTEN")
    .sort(
      (a, b) =>
        new Date(b.scheduled_start).getTime() -
        new Date(a.scheduled_start).getTime(),
    );

  return (
    <Stack spacing={3}>
      {/* Workspace tabs + AppBar switcher carry navigation + identity
          — no embedded breadcrumb / page title here. */}
      {error && <Alert severity="error">{error}</Alert>}

      {rows === null ? (
        <Typography variant="body2" color="text.secondary">
          Wird geladen…
        </Typography>
      ) : rows.length === 0 ? (
        <Paper variant="outlined" sx={{ p: 3, textAlign: "center" }}>
          <Typography variant="body2" color="text.secondary">
            Sobald die Verwaltung eine Versammlung anlegt, erscheint sie hier.
          </Typography>
        </Paper>
      ) : (
        <Stack spacing={4}>
          {upcoming.length > 0 && (
            <AssemblySection title="Geplant" rows={upcoming} />
          )}
          {past.length > 0 && (
            <AssemblySection title="Vergangen" rows={past} />
          )}
        </Stack>
      )}
    </Stack>
  );
}

function AssemblySection({
  title,
  rows,
}: {
  title: string;
  rows: AssemblyResponse[];
}) {
  return (
    <Box>
      <Typography
        variant="overline"
        color="text.secondary"
        sx={{ display: "block", mb: 1 }}
      >
        {title}
      </Typography>
      <Stack spacing={1.5}>
        {rows.map((a) => (
          <Paper
            key={a.id}
            variant="outlined"
            component={RouterLink}
            to={`/assemblies/${a.id}`}
            sx={{
              p: 2,
              display: "block",
              textDecoration: "none",
              color: "inherit",
              "&:hover": { borderColor: "primary.main" },
            }}
          >
            <Stack
              direction={{ xs: "column", sm: "row" }}
              spacing={2}
              sx={{ justifyContent: "space-between", alignItems: "flex-start" }}
            >
              <Box sx={{ minWidth: 0, flex: 1 }}>
                <Stack direction="row" spacing={1} sx={{ mb: 1, alignItems: "center" }}>
                  <StatusChip status={a.status} />
                  {a.protocol_pdf_url && (
                    <Chip
                      icon={<PictureAsPdfIcon />}
                      size="small"
                      variant="outlined"
                      color="success"
                      label="Protokoll vorhanden"
                    />
                  )}
                </Stack>
                <Typography variant="h6" component="div" gutterBottom>
                  {a.title}
                </Typography>
                <Stack spacing={0.5}>
                  <Stack
                    direction="row"
                    spacing={0.75}
                    sx={{ alignItems: "center" }}
                  >
                    <CalendarIcon
                      fontSize="small"
                      sx={{ color: "text.secondary" }}
                    />
                    <Typography variant="body2" color="text.secondary">
                      {formatDateRange(a.scheduled_start, a.scheduled_end)}
                    </Typography>
                  </Stack>
                  <Stack
                    direction="row"
                    spacing={0.75}
                    sx={{ alignItems: "center" }}
                  >
                    <LocationIcon
                      fontSize="small"
                      sx={{ color: "text.secondary" }}
                    />
                    <Typography variant="body2" color="text.secondary">
                      {a.location}
                    </Typography>
                  </Stack>
                </Stack>
              </Box>
            </Stack>
          </Paper>
        ))}
      </Stack>
    </Box>
  );
}
