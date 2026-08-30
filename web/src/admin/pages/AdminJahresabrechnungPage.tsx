// Admin board (Verwalter): the cross-property Jahresabrechnung matrix —
// properties × stages A–I — the digital cabinet door. Click a cell to tick a
// stage. The portal owner view (MyAccountingPage) is the read-only counterpart.
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import RadioButtonUncheckedIcon from "@mui/icons-material/RadioButtonUnchecked";
import {
  Alert,
  Box,
  CircularProgress,
  IconButton,
  MenuItem,
  Select,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
} from "@mui/material";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import { WithheldDocumentsCard } from "@/admin/components/WithheldDocumentsCard";

interface Stage {
  code: string;
  label: string;
  done: boolean;
  done_at: string | null;
  note: string | null;
}
interface BoardRow {
  property_id: string;
  property_name: string;
  year: number;
  done_count: number;
  total: number;
  stages: Stage[];
}
interface Progress {
  property_id: string;
  done_count: number;
  total: number;
  stages: Stage[];
}

const CODES = ["A", "B", "C", "D", "E", "F", "G", "H", "I"];

export function AdminJahresabrechnungPage() {
  const { t } = useTranslation();
  const thisYear = new Date().getFullYear();
  const [year, setYear] = useState(thisYear - 1);
  const [rows, setRows] = useState<BoardRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await api.get<BoardRow[]>(`/admin/accounting?year=${year}`);
      setRows(r.data);
    } catch {
      setError(t("accounting.loadError"));
    } finally {
      setLoading(false);
    }
  }, [year, t]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  // Stage labels for the header tooltips (all rows share the same 9).
  const labels: Record<string, string> = {};
  for (const s of rows[0]?.stages ?? []) labels[s.code] = s.label;

  async function toggle(row: BoardRow, stage: Stage) {
    const key = `${row.property_id}:${stage.code}`;
    setBusy(key);
    setError(null);
    try {
      const r = await api.put<Progress>(
        `/admin/properties/${row.property_id}/accounting/${year}/stages/${stage.code}`,
        { done: !stage.done },
      );
      setRows((rs) =>
        rs.map((x) =>
          x.property_id === row.property_id
            ? { ...x, stages: r.data.stages, done_count: r.data.done_count }
            : x,
        ),
      );
    } catch {
      setError(t("accounting.saveError"));
    } finally {
      setBusy(null);
    }
  }

  return (
    <Box>
      <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", mb: 1 }}>
        <Typography variant="h4">{t("accounting.boardTitle")}</Typography>
        <Select
          size="small"
          value={year}
          onChange={(e) => setYear(Number(e.target.value))}
        >
          {[thisYear, thisYear - 1, thisYear - 2, thisYear - 3].map((y) => (
            <MenuItem key={y} value={y}>
              {y}
            </MenuItem>
          ))}
        </Select>
      </Box>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        {t("accounting.boardSubtitle")}
      </Typography>
      <WithheldDocumentsCard />
      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}
      {loading ? (
        <CircularProgress />
      ) : rows.length === 0 ? (
        <Typography color="text.secondary">{t("accounting.empty")}</Typography>
      ) : (
        <Box sx={{ overflowX: "auto" }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>{t("accounting.colProperty")}</TableCell>
                <TableCell align="center">{t("accounting.colProgress")}</TableCell>
                {CODES.map((c) => (
                  <TableCell key={c} align="center">
                    <Tooltip title={labels[c] ?? c}>
                      <span>{c}</span>
                    </Tooltip>
                  </TableCell>
                ))}
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.property_id} hover>
                  <TableCell>{row.property_name}</TableCell>
                  <TableCell align="center">
                    <Typography variant="body2" sx={{ fontWeight: 500 }}>
                      {row.done_count}/{row.total}
                    </Typography>
                  </TableCell>
                  {row.stages.map((s) => {
                    const key = `${row.property_id}:${s.code}`;
                    return (
                      <TableCell key={s.code} align="center" sx={{ p: 0.25 }}>
                        {busy === key ? (
                          <CircularProgress size={18} />
                        ) : (
                          <Tooltip title={`${s.code} · ${labels[s.code] ?? ""}`}>
                            <IconButton size="small" onClick={() => void toggle(row, s)}>
                              {s.done ? (
                                <CheckCircleIcon fontSize="small" color="success" />
                              ) : (
                                <RadioButtonUncheckedIcon
                                  fontSize="small"
                                  sx={{ color: "text.disabled" }}
                                />
                              )}
                            </IconButton>
                          </Tooltip>
                        )}
                      </TableCell>
                    );
                  })}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Box>
      )}
    </Box>
  );
}
