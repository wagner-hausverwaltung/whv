import { Fragment, useEffect, useState } from "react";
import { Alert, Box, CircularProgress, Switch, Typography } from "@mui/material";
import { api } from "@/api/client";
import type {
  NotificationCategory,
  NotificationSetting,
  NotificationSettingsResponse,
} from "@/api/types";

// Render order + German labels. Mirrors the backend's category enum.
const ORDER: NotificationCategory[] = [
  "ANNOUNCEMENT",
  "TICKET",
  "ETV_COMMENT",
  "ETV_INVITATION",
  "DOCUMENT",
  "INVOICE",
];

const LABELS: Record<NotificationCategory, string> = {
  ANNOUNCEMENT: "Mitteilungen / News",
  TICKET: "Anliegen / Tickets",
  ETV_COMMENT: "ETV-Kommentare",
  ETV_INVITATION: "ETV-Einladungen",
  DOCUMENT: "Neue Dokumente",
  INVOICE: "Rechnungen",
};

/// Compact Push / E-Mail matrix backed by GET/PUT
/// /me/notification-settings. Optimistic: each toggle updates local
/// state immediately and PUTs the full set; on failure it reverts and
/// shows an inline error. The same endpoint drives the iOS settings,
/// so a change here follows the user to their phone.
export function NotificationSettings() {
  const [items, setItems] = useState<NotificationSetting[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .get<NotificationSettingsResponse>("/me/notification-settings")
      .then((r) => {
        if (!cancelled) setItems(r.data.items);
      })
      .catch(() => {
        if (!cancelled)
          setError("Benachrichtigungs-Einstellungen konnten nicht geladen werden.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const toggle = async (
    category: NotificationCategory,
    channel: "push" | "email",
    value: boolean,
  ) => {
    if (!items) return;
    const prev = items;
    const next = items.map((i) =>
      i.category === category ? { ...i, [channel]: value } : i,
    );
    setItems(next); // optimistic
    setError(null);
    try {
      const r = await api.put<NotificationSettingsResponse>(
        "/me/notification-settings",
        { items: next },
      );
      setItems(r.data.items);
    } catch {
      setItems(prev); // revert
      setError("Speichern fehlgeschlagen. Bitte erneut versuchen.");
    }
  };

  if (items === null && !error) {
    return <CircularProgress size={20} />;
  }

  const byCat = new Map((items ?? []).map((i) => [i.category, i] as const));

  return (
    <Box>
      {error && (
        <Alert severity="error" sx={{ mb: 1.5 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: "1fr 64px 64px",
          alignItems: "center",
          rowGap: 0.25,
        }}
      >
        <Box />
        <Typography variant="caption" color="text.secondary" sx={{ textAlign: "center" }}>
          Push
        </Typography>
        <Typography variant="caption" color="text.secondary" sx={{ textAlign: "center" }}>
          E-Mail
        </Typography>
        {ORDER.map((cat) => {
          const it = byCat.get(cat);
          if (!it) return null;
          return (
            <Fragment key={cat}>
              <Typography variant="body2">{LABELS[cat]}</Typography>
              <Box sx={{ textAlign: "center" }}>
                <Switch
                  size="small"
                  checked={it.push}
                  onChange={(e) => toggle(cat, "push", e.target.checked)}
                  slotProps={{ input: { "aria-label": `${LABELS[cat]} Push` } }}
                />
              </Box>
              <Box sx={{ textAlign: "center" }}>
                <Switch
                  size="small"
                  checked={it.email}
                  onChange={(e) => toggle(cat, "email", e.target.checked)}
                  slotProps={{ input: { "aria-label": `${LABELS[cat]} E-Mail` } }}
                />
              </Box>
            </Fragment>
          );
        })}
      </Box>
    </Box>
  );
}
