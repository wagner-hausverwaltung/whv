// Zurückgehaltene Abrechnungsdokumente (B42-Vorfall, 2026-08-29): Impower
// exportiert Hausgeldabrechnungen/Wirtschaftspläne auch als Entwurf — ohne
// Marker. Der Sync hält diese Arten deshalb zurück, bis der Verwalter sie
// hier freigibt; erst die Freigabe macht sie im Portal sichtbar und stößt
// die "Neues Dokument"-Mail an. Lebt auf der Jahresabrechnungs-Seite, weil
// die Freigabe der letzte Schritt dieser Pipeline ist.
import { Alert, Box, Button, Chip, CircularProgress, Typography } from "@mui/material";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";

interface WithheldDoc {
  id: string;
  name: string;
  kind: string;
  property_id: string | null;
  property_name: string | null;
  unit_hr_id: string | null;
  amount: string | null;
  issued_date: string | null;
  created_at: string;
}

export function WithheldDocumentsCard() {
  const { t } = useTranslation();
  const [docs, setDocs] = useState<WithheldDoc[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [releasedNote, setReleasedNote] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await api.get<WithheldDoc[]>("/admin/documents/withheld");
      setDocs(r.data);
    } catch {
      setError(t("accounting.withheldLoadError"));
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  const groups = useMemo(() => {
    const byProp = new Map<string, { name: string; docs: WithheldDoc[] }>();
    for (const d of docs ?? []) {
      const key = d.property_id ?? "-";
      const g = byProp.get(key) ?? { name: d.property_name ?? "—", docs: [] };
      g.docs.push(d);
      byProp.set(key, g);
    }
    return [...byProp.entries()];
  }, [docs]);

  async function release(ids: string[], busyKey: string) {
    setBusy(busyKey);
    setError(null);
    setReleasedNote(null);
    try {
      const r = await api.post<{ released: number; notified_documents: number }>(
        "/admin/documents/release",
        { document_ids: ids },
      );
      setReleasedNote(t("accounting.withheldReleased", { count: r.data.released }));
      await load();
    } catch {
      setError(t("accounting.withheldReleaseError"));
    } finally {
      setBusy(null);
    }
  }

  // Nothing pending and never errored → no card at all; the common case
  // stays quiet.
  if (docs !== null && docs.length === 0 && !releasedNote && !error) return null;

  return (
    <Box sx={{ mb: 3, p: 2, border: 1, borderColor: "warning.light", borderRadius: 2 }}>
      <Typography variant="h6" sx={{ mb: 0.5 }}>
        {t("accounting.withheldTitle")}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
        {t("accounting.withheldSubtitle")}
      </Typography>
      {error && (
        <Alert severity="error" sx={{ mb: 1.5 }}>
          {error}
        </Alert>
      )}
      {releasedNote && (
        <Alert severity="success" sx={{ mb: 1.5 }}>
          {releasedNote}
        </Alert>
      )}
      {docs === null ? (
        <CircularProgress size={20} />
      ) : (
        groups.map(([propId, g]) => (
          <Box key={propId} sx={{ mb: 2 }}>
            <Box sx={{ display: "flex", alignItems: "center", gap: 1, mb: 0.75 }}>
              <Typography variant="subtitle2">{g.name}</Typography>
              <Chip size="small" label={g.docs.length} />
              <Button
                size="small"
                variant="contained"
                disabled={busy !== null}
                onClick={() =>
                  void release(
                    g.docs.map((d) => d.id),
                    `prop:${propId}`,
                  )
                }
              >
                {busy === `prop:${propId}` ? (
                  <CircularProgress size={16} />
                ) : (
                  t("accounting.withheldReleaseAll")
                )}
              </Button>
            </Box>
            {g.docs.map((d) => (
              <Box
                key={d.id}
                sx={{ display: "flex", alignItems: "center", gap: 1, pl: 1, py: 0.25 }}
              >
                <Typography variant="body2" sx={{ flex: 1, minWidth: 0 }} noWrap title={d.name}>
                  {d.name}
                </Typography>
                <Button
                  size="small"
                  disabled={busy !== null}
                  onClick={() => void release([d.id], d.id)}
                >
                  {busy === d.id ? <CircularProgress size={14} /> : t("accounting.withheldRelease")}
                </Button>
              </Box>
            ))}
          </Box>
        ))
      )}
    </Box>
  );
}
