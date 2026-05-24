import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { api } from "@/api/client";
import {
  TICKET_CATEGORY_LABELS,
  type TicketCategory,
  type TicketDetailResponse,
} from "@/api/types";

const CATEGORIES: TicketCategory[] = [
  "SCHADEN",
  "VERWALTUNG",
  "HAUSGELD",
  "SONSTIGES",
];

export function TicketNewPage() {
  const navigate = useNavigate();
  const [subject, setSubject] = useState("");
  const [category, setCategory] = useState<TicketCategory>("SONSTIGES");
  const [body, setBody] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const res = await api.post<TicketDetailResponse>("/me/tickets", {
        subject: subject.trim(),
        body: body.trim(),
        category,
      });
      navigate(`/tickets/${res.data.id}`, { replace: true });
    } catch {
      setError(
        "Ticket konnte nicht erstellt werden. Bitte prüfen Sie Ihre Eingaben.",
      );
      setSubmitting(false);
    }
  };

  return (
    <Stack spacing={3} sx={{ maxWidth: 600 }}>
      <Box>
        <Typography variant="h4" component="h1" gutterBottom>
          Neues Ticket
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Schildern Sie Ihr Anliegen — wir melden uns über das Portal und per
          E-Mail.
        </Typography>
      </Box>

      {error && <Alert severity="error">{error}</Alert>}

      <Paper variant="outlined" component="form" onSubmit={onSubmit} sx={{ p: 2.5 }}>
        <Stack spacing={2}>
          <TextField
            id="subject"
            label="Betreff"
            required
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            slotProps={{ htmlInput: { minLength: 3, maxLength: 200 } }}
            fullWidth
          />
          <TextField
            id="category"
            label="Kategorie"
            select
            required
            value={category}
            onChange={(e) => setCategory(e.target.value as TicketCategory)}
            fullWidth
          >
            {CATEGORIES.map((c) => (
              <MenuItem key={c} value={c}>
                {TICKET_CATEGORY_LABELS[c]}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            id="body"
            label="Beschreibung"
            required
            multiline
            minRows={8}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            slotProps={{ htmlInput: { minLength: 3, maxLength: 10_000 } }}
            fullWidth
          />
          <Stack direction="row" spacing={2}>
            <Button type="submit" variant="contained" disabled={submitting}>
              {submitting ? "Wird gesendet…" : "Ticket erstellen"}
            </Button>
            <Button
              type="button"
              variant="outlined"
              onClick={() => navigate("/tickets")}
              disabled={submitting}
            >
              Abbrechen
            </Button>
          </Stack>
        </Stack>
      </Paper>
    </Stack>
  );
}
