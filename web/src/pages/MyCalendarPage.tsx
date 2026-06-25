/**
 * Property "Kalender" tab (member, read-only — ADR-0018).
 *
 * A month grid with the property's events: ETV dates (highlighted, tap to
 * open the assembly), plus the Winterdienst/Kehrwoche assignments the
 * Verwalter set up. The owner's own assignments are bold ("Ihre Aufgabe").
 */

import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Alert,
  Button,
  Chip,
  IconButton,
  Paper,
  Stack,
  Typography,
} from "@mui/material";
import CalendarMonthIcon from "@mui/icons-material/CalendarMonth";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import { api } from "@/api/client";
import {
  CALENDAR_KIND_COLORS,
  CALENDAR_KIND_LABELS,
  type CalendarEntry,
} from "@/api/types";
import { CalendarMonth } from "@/components/CalendarMonth";
import { useAuth } from "@/auth/AuthContext";
import { useTranslation } from "react-i18next";

function fmtSpan(e: CalendarEntry): string {
  const d = (iso: string) => new Date(iso).toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" });
  return e.ends_on && e.ends_on !== e.starts_on ? `${d(e.starts_on)}–${d(e.ends_on)}` : d(e.starts_on);
}

export function MyCalendarPage() {
  const { id } = useParams<{ id: string }>();
  const { user } = useAuth();
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [entries, setEntries] = useState<CalendarEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!id) return;
    setError(null);
    try {
      const r = await api.get<CalendarEntry[]>(
        `/me/properties/${id}/calendar?year=${year}&month=${month}`,
      );
      setEntries(r.data);
    } catch {
      setError(t("calendar.loadFailed"));
    }
  }, [id, year, month, t]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const shift = (delta: number) => {
    const d = new Date(year, month - 1 + delta, 1);
    setYear(d.getFullYear());
    setMonth(d.getMonth() + 1);
  };

  const onEntry = (e: CalendarEntry) => {
    if (e.kind === "ETV" && e.assembly_id) navigate(`/assemblies/${e.assembly_id}`);
  };

  // Download the whole property calendar as .ics (ETV + Winterdienst/Kehrwoche/
  // Termin) for import into Outlook / Apple Calendar / Google.
  const exportIcs = async () => {
    if (!id) return;
    try {
      const r = await api.get(`/me/properties/${id}/calendar.ics`, { responseType: "blob" });
      const url = URL.createObjectURL(r.data as Blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "kalender.ics";
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch {
      setError(t("calendar.exportFailed"));
    }
  };

  const sorted = [...(entries ?? [])].sort((a, b) => a.starts_on.localeCompare(b.starts_on));
  const monthLabel = new Date(year, month - 1, 1).toLocaleDateString(
    i18n.language.startsWith("en") ? "en-US" : "de-DE",
    { month: "long", year: "numeric" },
  );

  return (
    <Stack spacing={2}>
      {error && <Alert severity="error">{error}</Alert>}

      <Stack direction="row" sx={{ justifyContent: "flex-end" }}>
        <Button size="small" startIcon={<CalendarMonthIcon />} onClick={() => void exportIcs()}>
          {t("calendar.exportIcs")}
        </Button>
      </Stack>

      <Stack direction="row" sx={{ alignItems: "center", justifyContent: "center" }} spacing={2}>
        <IconButton onClick={() => shift(-1)} aria-label={t("calendar.prevMonth")}>
          <ChevronLeftIcon />
        </IconButton>
        <Typography variant="h6" sx={{ minWidth: 160, textAlign: "center" }}>
          {monthLabel}
        </Typography>
        <IconButton onClick={() => shift(1)} aria-label={t("calendar.nextMonth")}>
          <ChevronRightIcon />
        </IconButton>
      </Stack>

      <CalendarMonth
        year={year}
        month={month}
        entries={entries ?? []}
        highlightUserId={user?.id}
        onEntryClick={onEntry}
      />

      {sorted.length > 0 && (
        <Paper variant="outlined" sx={{ p: 2 }}>
          <Stack spacing={1}>
            {sorted.map((e) => {
              const mine = e.assigned_user_id != null && e.assigned_user_id === user?.id;
              return (
                <Stack
                  key={`${e.source}-${e.id}`}
                  direction="row"
                  spacing={1.5}
                  sx={{ alignItems: "center", flexWrap: "wrap" }}
                >
                  <Typography variant="body2" sx={{ minWidth: 92, color: "text.secondary" }}>
                    {fmtSpan(e)}
                  </Typography>
                  <Chip
                    size="small"
                    label={CALENDAR_KIND_LABELS[e.kind]}
                    sx={{
                      bgcolor: `${CALENDAR_KIND_COLORS[e.kind]}22`,
                      color: CALENDAR_KIND_COLORS[e.kind],
                      fontWeight: 600,
                    }}
                    onClick={e.kind === "ETV" ? () => onEntry(e) : undefined}
                  />
                  <Typography variant="body2" sx={{ flex: 1 }}>
                    {e.title}
                    {e.assigned_label ? ` — ${e.assigned_label}` : ""}
                  </Typography>
                  {mine && <Chip size="small" color="primary" label={t("calendar.myTask")} />}
                </Stack>
              );
            })}
          </Stack>
        </Paper>
      )}
    </Stack>
  );
}
