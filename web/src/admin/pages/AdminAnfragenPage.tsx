// Verwalter review queue for inbound anfragen@ inquiries (ADR-0019). Lists
// inquiries with status; for one that needs review, opens a dialog prefilled
// from the LLM extraction so the Verwalter can correct + send the offer.
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";

type Art = "WEG" | "MV";

interface OfferInquiry {
  id: string;
  sender_email: string;
  sender_name: string | null;
  subject: string;
  status: string;
  art: string | null;
  object_address: string | null;
  units: number | null;
  desired_start: string | null;
  confidence: number | null;
  sent_at: string | null;
  created_at: string;
}

const STATUS_COLOR: Record<
  string,
  "default" | "info" | "warning" | "success" | "error"
> = {
  NEW: "default",
  EXTRACTED: "info",
  NEEDS_REVIEW: "warning",
  SENT: "success",
  FAILED: "error",
  IGNORED: "default",
};

export function AdminAnfragenPage() {
  const { t } = useTranslation();
  const tp = (k: string) => t(`admin.anfragenPage.${k}`);

  const [rows, setRows] = useState<OfferInquiry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<OfferInquiry[]>("/admin/offer-inquiries");
      setRows(res.data);
    } catch {
      setError(tp("loadError"));
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  // --- send dialog ---
  const [target, setTarget] = useState<OfferInquiry | null>(null);
  const [art, setArt] = useState<Art>("WEG");
  const [units, setUnits] = useState("");
  const [startDate, setStartDate] = useState("");
  const [objectStreet, setObjectStreet] = useState("");
  const [objectPlzCity, setObjectPlzCity] = useState("");
  const [recipientName, setRecipientName] = useState("");
  const [recipientStreet, setRecipientStreet] = useState("");
  const [recipientPlzCity, setRecipientPlzCity] = useState("");
  const [salutation, setSalutation] = useState("");
  const [object1, setObject1] = useState("");
  const [busy, setBusy] = useState(false);
  const [dialogError, setDialogError] = useState<string | null>(null);

  function openSend(inq: OfferInquiry) {
    setTarget(inq);
    setDialogError(null);
    const a: Art = inq.art === "MV" ? "MV" : "WEG";
    setArt(a);
    setUnits(inq.units != null ? String(inq.units) : "");
    setStartDate(inq.desired_start ?? "");
    setObjectStreet(inq.object_address ?? "");
    setObjectPlzCity("");
    setRecipientName(inq.sender_name ?? "");
    setRecipientStreet("");
    setRecipientPlzCity("");
    setSalutation(inq.sender_name ? `Sehr geehrte/r ${inq.sender_name},` : "");
    setObject1(inq.object_address ?? "");
  }

  async function submitSend() {
    if (!target) return;
    setBusy(true);
    setDialogError(null);
    try {
      const payload: Record<string, unknown> = {
        art,
        units: Number(units),
        start_date: startDate || undefined,
      };
      if (art === "WEG") {
        payload.object_street = objectStreet;
        payload.object_plz_city = objectPlzCity;
      } else {
        payload.recipient_name = recipientName;
        payload.recipient_street = recipientStreet;
        payload.recipient_plz_city = recipientPlzCity;
        payload.salutation = salutation;
        payload.objects = [object1].filter(Boolean);
      }
      await api.post(`/admin/offer-inquiries/${target.id}/send`, payload);
      setTarget(null);
      await load();
    } catch {
      setDialogError(tp("sendError"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Box>
      <Box
        sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", mb: 1 }}
      >
        <Typography variant="h4">{tp("title")}</Typography>
        <Button onClick={() => void load()} disabled={loading}>
          {tp("refresh")}
        </Button>
      </Box>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        {tp("subtitle")}
      </Typography>

      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {loading ? (
        <CircularProgress />
      ) : rows.length === 0 ? (
        <Typography color="text.secondary">{tp("empty")}</Typography>
      ) : (
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>{tp("colSender")}</TableCell>
              <TableCell>{tp("colSubject")}</TableCell>
              <TableCell>{tp("colArt")}</TableCell>
              <TableCell>{tp("colObject")}</TableCell>
              <TableCell align="right">{tp("colUnits")}</TableCell>
              <TableCell align="right">{tp("colConfidence")}</TableCell>
              <TableCell>{tp("colStatus")}</TableCell>
              <TableCell />
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.id} hover>
                <TableCell>
                  {r.sender_name || r.sender_email}
                  <br />
                  <Typography variant="caption" color="text.secondary">
                    {r.sender_email}
                  </Typography>
                </TableCell>
                <TableCell>{r.subject}</TableCell>
                <TableCell>{r.art ?? "—"}</TableCell>
                <TableCell>{r.object_address ?? "—"}</TableCell>
                <TableCell align="right">{r.units ?? "—"}</TableCell>
                <TableCell align="right">
                  {r.confidence != null ? `${Math.round(r.confidence * 100)}%` : "—"}
                </TableCell>
                <TableCell>
                  <Chip
                    size="small"
                    label={r.status}
                    color={STATUS_COLOR[r.status] ?? "default"}
                  />
                </TableCell>
                <TableCell align="right">
                  {r.status !== "SENT" && r.status !== "IGNORED" && (
                    <Button size="small" variant="outlined" onClick={() => openSend(r)}>
                      {tp("send")}
                    </Button>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      <Dialog open={target !== null} onClose={() => setTarget(null)} fullWidth maxWidth="sm">
        <DialogTitle>{tp("dialogTitle")}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <ToggleButtonGroup
              exclusive
              color="primary"
              value={art}
              onChange={(_, v) => v && setArt(v as Art)}
            >
              <ToggleButton value="WEG">WEG</ToggleButton>
              <ToggleButton value="MV">Mietverwaltung</ToggleButton>
            </ToggleButtonGroup>
            <Stack direction="row" spacing={2}>
              <TextField
                label={tp("units")}
                type="number"
                value={units}
                onChange={(e) => setUnits(e.target.value)}
                slotProps={{ htmlInput: { min: 1, max: 1000 } }}
                fullWidth
              />
              <TextField
                label={tp("start")}
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                slotProps={{ inputLabel: { shrink: true } }}
                fullWidth
              />
            </Stack>
            <Divider />
            {art === "WEG" ? (
              <>
                <TextField
                  label={tp("objectStreet")}
                  value={objectStreet}
                  onChange={(e) => setObjectStreet(e.target.value)}
                  fullWidth
                />
                <TextField
                  label={tp("objectPlzCity")}
                  value={objectPlzCity}
                  onChange={(e) => setObjectPlzCity(e.target.value)}
                  fullWidth
                />
              </>
            ) : (
              <>
                <TextField
                  label={tp("recipientName")}
                  value={recipientName}
                  onChange={(e) => setRecipientName(e.target.value)}
                  fullWidth
                />
                <Stack direction="row" spacing={2}>
                  <TextField
                    label={tp("recipientStreet")}
                    value={recipientStreet}
                    onChange={(e) => setRecipientStreet(e.target.value)}
                    fullWidth
                  />
                  <TextField
                    label={tp("recipientPlzCity")}
                    value={recipientPlzCity}
                    onChange={(e) => setRecipientPlzCity(e.target.value)}
                    fullWidth
                  />
                </Stack>
                <TextField
                  label={tp("salutation")}
                  value={salutation}
                  onChange={(e) => setSalutation(e.target.value)}
                  fullWidth
                />
                <TextField
                  label={tp("object")}
                  value={object1}
                  onChange={(e) => setObject1(e.target.value)}
                  fullWidth
                />
              </>
            )}
            {dialogError && <Alert severity="error">{dialogError}</Alert>}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setTarget(null)}>{tp("cancel")}</Button>
          <Button
            variant="contained"
            onClick={() => void submitSend()}
            disabled={busy}
            startIcon={busy ? <CircularProgress size={18} /> : undefined}
          >
            {tp("sendNow")}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
