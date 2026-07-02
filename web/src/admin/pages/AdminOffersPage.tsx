// Verwalter-only "Angebot erstellen" — fills the WEG/MV offer fields and
// downloads the generated PDF from POST /admin/offers/generate.
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Divider,
  Paper,
  Stack,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";

type Art = "WEG" | "MV";

export function AdminOffersPage() {
  const { t } = useTranslation();
  const [art, setArt] = useState<Art>("WEG");
  const [units, setUnits] = useState("6");
  const [termYears, setTermYears] = useState("4");
  const [startDate, setStartDate] = useState("");
  const [rate, setRate] = useState("");

  // WEG
  const [objectStreet, setObjectStreet] = useState("");
  const [objectPlzCity, setObjectPlzCity] = useState("");

  // MV
  const [recipientName, setRecipientName] = useState("");
  const [recipientStreet, setRecipientStreet] = useState("");
  const [recipientPlzCity, setRecipientPlzCity] = useState("");
  const [salutation, setSalutation] = useState("");
  const [offerDate, setOfferDate] = useState("");
  const [objects, setObjects] = useState(["", "", ""]);
  const [repName, setRepName] = useState("");
  const [repStreet, setRepStreet] = useState("");
  const [repPlzCity, setRepPlzCity] = useState("");

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const tp = (k: string) => t(`admin.offersPage.${k}`);

  async function generate() {
    setBusy(true);
    setError(null);
    try {
      // The rate override is optional — treat 0 / blank / junk as "no
      // override" so the backend's default pricing applies (its schema
      // rejects rate_per_unit_net <= 0).
      const rateNum = Number(rate);
      const payload: Record<string, unknown> = {
        art,
        units: Number(units),
        term_years: Number(termYears),
        start_date: startDate || undefined,
        rate_per_unit_net: Number.isFinite(rateNum) && rateNum > 0 ? rateNum : undefined,
      };
      if (art === "WEG") {
        payload.object_street = objectStreet;
        payload.object_plz_city = objectPlzCity;
      } else {
        payload.recipient_name = recipientName;
        payload.recipient_street = recipientStreet;
        payload.recipient_plz_city = recipientPlzCity;
        payload.salutation = salutation;
        payload.offer_date = offerDate || undefined;
        payload.objects = objects.map((o) => o.trim()).filter(Boolean);
        if (repName) {
          payload.representative_name = repName;
          payload.representative_street = repStreet || undefined;
          payload.representative_plz_city = repPlzCity || undefined;
        }
      }
      const res = await api.post("/admin/offers/generate", payload, {
        responseType: "blob",
      });
      const disposition = String(res.headers["content-disposition"] ?? "");
      const match = disposition.match(/filename="?([^"]+)"?/);
      const filename = match?.[1] ?? `Angebot-${art}.pdf`;
      const url = URL.createObjectURL(res.data as Blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch {
      setError(tp("error"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        {tp("title")}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        {tp("subtitle")}
      </Typography>

      <Paper sx={{ p: 3, maxWidth: 720 }}>
        <Stack spacing={2.5}>
          <ToggleButtonGroup
            exclusive
            color="primary"
            value={art}
            onChange={(_, v) => v && setArt(v as Art)}
            aria-label={tp("art")}
          >
            <ToggleButton value="WEG">{tp("weg")}</ToggleButton>
            <ToggleButton value="MV">{tp("mv")}</ToggleButton>
          </ToggleButtonGroup>

          <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
            <TextField
              label={tp("units")}
              type="number"
              value={units}
              onChange={(e) => setUnits(e.target.value)}
              slotProps={{ htmlInput: { min: 1, max: 1000 } }}
              fullWidth
            />
            <TextField
              label={tp("term")}
              type="number"
              value={termYears}
              onChange={(e) => setTermYears(e.target.value)}
              slotProps={{ htmlInput: { min: 1, max: 10 } }}
              fullWidth
            />
          </Stack>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
            <TextField
              label={tp("start")}
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              helperText={tp("startHint")}
              slotProps={{ inputLabel: { shrink: true } }}
              fullWidth
            />
            <TextField
              label={tp("rate")}
              type="number"
              value={rate}
              onChange={(e) => setRate(e.target.value)}
              helperText={tp("rateHint")}
              slotProps={{ htmlInput: { min: 0 } }}
              fullWidth
            />
          </Stack>

          <Divider />

          {art === "WEG" ? (
            <Stack spacing={2}>
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
            </Stack>
          ) : (
            <Stack spacing={2}>
              <TextField
                label={tp("recipientName")}
                value={recipientName}
                onChange={(e) => setRecipientName(e.target.value)}
                fullWidth
              />
              <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
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
              <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
                <TextField
                  label={tp("salutation")}
                  value={salutation}
                  onChange={(e) => setSalutation(e.target.value)}
                  fullWidth
                />
                <TextField
                  label={tp("offerDate")}
                  type="date"
                  value={offerDate}
                  onChange={(e) => setOfferDate(e.target.value)}
                  slotProps={{ inputLabel: { shrink: true } }}
                  fullWidth
                />
              </Stack>
              <Typography variant="subtitle2">{tp("objectsLabel")}</Typography>
              {objects.map((obj, i) => (
                <TextField
                  key={i}
                  label={`${tp("object")} ${i + 1}`}
                  value={obj}
                  onChange={(e) =>
                    setObjects((prev) => prev.map((o, j) => (j === i ? e.target.value : o)))
                  }
                  fullWidth
                />
              ))}
              <Divider textAlign="left">{tp("representative")}</Divider>
              <TextField
                label={tp("recipientName")}
                value={repName}
                onChange={(e) => setRepName(e.target.value)}
                fullWidth
              />
              <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
                <TextField
                  label={tp("recipientStreet")}
                  value={repStreet}
                  onChange={(e) => setRepStreet(e.target.value)}
                  fullWidth
                />
                <TextField
                  label={tp("recipientPlzCity")}
                  value={repPlzCity}
                  onChange={(e) => setRepPlzCity(e.target.value)}
                  fullWidth
                />
              </Stack>
            </Stack>
          )}

          {error && <Alert severity="error">{error}</Alert>}

          <Box>
            <Button
              variant="contained"
              onClick={generate}
              disabled={busy}
              startIcon={busy ? <CircularProgress size={18} /> : undefined}
            >
              {busy ? tp("generating") : tp("generate")}
            </Button>
          </Box>
        </Stack>
      </Paper>
    </Box>
  );
}
