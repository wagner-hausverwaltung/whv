// Portal owner view (read-only): the Jahresabrechnung progress for the current
// property, as a stage checklist + bar. Edits live in the admin board.
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import RadioButtonUncheckedIcon from "@mui/icons-material/RadioButtonUnchecked";
import {
  Box,
  CircularProgress,
  LinearProgress,
  List,
  ListItem,
  Typography,
} from "@mui/material";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";

import { api } from "@/api/client";

interface Stage {
  code: string;
  label: string;
  done: boolean;
  done_at: string | null;
  note: string | null;
}
interface Progress {
  property_id: string;
  year: number;
  done_count: number;
  total: number;
  stages: Stage[];
}

function fmtDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString("de-DE");
}

export function MyAccountingPage() {
  const { id } = useParams();
  const { t } = useTranslation();
  const [progress, setProgress] = useState<Progress | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.get<Progress>(`/me/properties/${id}/accounting`);
      setProgress(r.data);
    } catch {
      setProgress(null);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  if (loading) return <CircularProgress />;
  if (!progress) return <Typography color="text.secondary">{t("accounting.loadError")}</Typography>;

  const pct = progress.total ? Math.round((progress.done_count / progress.total) * 100) : 0;

  return (
    <Box>
      <Typography variant="h5" gutterBottom>
        {t("accounting.title", { year: progress.year })}
      </Typography>
      <Box sx={{ display: "flex", alignItems: "center", gap: 2, mb: 2 }}>
        <Box sx={{ flex: 1 }}>
          <LinearProgress variant="determinate" value={pct} color="success" />
        </Box>
        <Typography variant="body2" color="text.secondary">
          {progress.done_count}/{progress.total}
        </Typography>
      </Box>
      <List>
        {progress.stages.map((s) => (
          <ListItem key={s.code} alignItems="flex-start" disableGutters>
            {s.done ? (
              <CheckCircleIcon color="success" sx={{ mr: 1.5 }} />
            ) : (
              <RadioButtonUncheckedIcon sx={{ mr: 1.5, color: "text.disabled" }} />
            )}
            <Box>
              <Typography variant="body2">
                {s.code} · {s.label}
              </Typography>
              {s.done && s.done_at && (
                <Typography variant="caption" color="text.secondary">
                  {t("accounting.doneOn", { date: fmtDate(s.done_at) })}
                </Typography>
              )}
              {s.note && (
                <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
                  „{s.note}“
                </Typography>
              )}
            </Box>
          </ListItem>
        ))}
      </List>
      <Typography variant="caption" color="text.secondary">
        {t("accounting.readonly")}
      </Typography>
    </Box>
  );
}
