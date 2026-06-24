// Reusable month-grid calendar (Mo–So). Renders merged CalendarEntry items
// into day cells; shared by the portal (read-only) and admin (clickable to
// add/edit). Pure presentation — the parent owns the year/month + fetching.

import { Box, Stack, Typography } from "@mui/material";
import {
  CALENDAR_KIND_COLORS,
  CALENDAR_KIND_LABELS,
  type CalendarEntry,
} from "@/api/types";

const WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];

function isoDay(year: number, month: number, day: number): string {
  return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

function todayIso(): string {
  const n = new Date();
  return isoDay(n.getFullYear(), n.getMonth() + 1, n.getDate());
}

interface CalendarMonthProps {
  year: number;
  month: number; // 1–12
  entries: CalendarEntry[];
  onDayClick?: (isoDate: string) => void;
  onEntryClick?: (entry: CalendarEntry) => void;
  /// Highlight entries assigned to this user ("your duty").
  highlightUserId?: string | null;
}

export function CalendarMonth({
  year,
  month,
  entries,
  onDayClick,
  onEntryClick,
  highlightUserId,
}: CalendarMonthProps) {
  const daysInMonth = new Date(year, month, 0).getDate();
  // Monday-first leading blanks.
  const firstWeekday = (new Date(year, month - 1, 1).getDay() + 6) % 7;
  const today = todayIso();

  const cells: (number | null)[] = [
    ...Array.from({ length: firstWeekday }, () => null),
    ...Array.from({ length: daysInMonth }, (_, i) => i + 1),
  ];
  while (cells.length % 7 !== 0) cells.push(null);

  const entriesFor = (day: number): CalendarEntry[] => {
    const iso = isoDay(year, month, day);
    return entries.filter((e) => e.starts_on <= iso && (e.ends_on ?? e.starts_on) >= iso);
  };

  return (
    <Box
      sx={{
        display: "grid",
        gridTemplateColumns: "repeat(7, 1fr)",
        border: 1,
        borderColor: "divider",
        borderRadius: 1,
        overflow: "hidden",
      }}
    >
      {WEEKDAYS.map((d) => (
        <Box
          key={d}
          sx={{
            bgcolor: "primary.main",
            color: "primary.contrastText",
            textAlign: "center",
            py: 0.5,
            fontSize: 12,
            fontWeight: 600,
          }}
        >
          {d}
        </Box>
      ))}
      {cells.map((day, idx) => {
        const iso = day ? isoDay(year, month, day) : "";
        const dayEntries = day ? entriesFor(day) : [];
        return (
          <Box
            key={idx}
            onClick={day && onDayClick ? () => onDayClick(iso) : undefined}
            sx={{
              minHeight: 84,
              p: 0.5,
              borderTop: 1,
              borderLeft: idx % 7 === 0 ? 0 : 1,
              borderColor: "divider",
              bgcolor: day ? "background.paper" : "action.hover",
              cursor: day && onDayClick ? "pointer" : "default",
              "&:hover": day && onDayClick ? { bgcolor: "action.hover" } : undefined,
            }}
          >
            {day && (
              <Typography
                variant="caption"
                sx={{
                  fontWeight: iso === today ? 700 : 500,
                  color: iso === today ? "primary.main" : "text.secondary",
                }}
              >
                {day}
              </Typography>
            )}
            <Stack spacing={0.25} sx={{ mt: 0.25 }}>
              {dayEntries.slice(0, 3).map((e) => {
                const mine =
                  highlightUserId != null && e.assigned_user_id === highlightUserId;
                return (
                  <Box
                    key={`${e.source}-${e.id}`}
                    onClick={
                      onEntryClick
                        ? (ev) => {
                            ev.stopPropagation();
                            onEntryClick(e);
                          }
                        : undefined
                    }
                    title={`${CALENDAR_KIND_LABELS[e.kind]}: ${e.title}${
                      e.assigned_label ? ` — ${e.assigned_label}` : ""
                    }`}
                    sx={{
                      px: 0.5,
                      py: 0.1,
                      borderRadius: 0.5,
                      bgcolor: `${CALENDAR_KIND_COLORS[e.kind]}22`,
                      borderLeft: `3px solid ${CALENDAR_KIND_COLORS[e.kind]}`,
                      fontSize: 10,
                      lineHeight: 1.3,
                      whiteSpace: "nowrap",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      cursor: onEntryClick ? "pointer" : "default",
                      fontWeight: mine ? 700 : 400,
                    }}
                  >
                    {e.title}
                  </Box>
                );
              })}
              {dayEntries.length > 3 && (
                <Typography variant="caption" color="text.secondary" sx={{ fontSize: 9 }}>
                  +{dayEntries.length - 3}
                </Typography>
              )}
            </Stack>
          </Box>
        );
      })}
    </Box>
  );
}
