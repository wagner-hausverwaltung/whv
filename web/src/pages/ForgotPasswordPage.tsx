import { useState, type FormEvent } from "react";
import { Link as RouterLink } from "react-router-dom";
import { Alert, Box, Button, Link, Stack, TextField } from "@mui/material";
import { api } from "@/api/client";
import { AuthShell } from "@/components/AuthShell";

export function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      await api.post("/auth/forgot-password", {
        email: email.trim().toLowerCase(),
      });
    } catch {
      // /auth/forgot-password always 204s; even on transport failure we show
      // the same confirmation (no enumeration). User can request again.
    } finally {
      setSubmitted(true);
      setSubmitting(false);
    }
  };

  if (submitted) {
    return (
      <AuthShell title="Passwort vergessen">
        <Alert severity="success">
          Falls Ihre E-Mail-Adresse bei uns hinterlegt ist, wurde ein Link zum
          Zurücksetzen versandt. Bitte prüfen Sie Ihren Posteingang (auch
          Spam-Ordner). Der Link ist 30 Minuten gültig.
        </Alert>
        <Box sx={{ textAlign: "center" }}>
          <Link
            component={RouterLink}
            to="/login"
            color="text.secondary"
            variant="body2"
            underline="hover"
          >
            ← Zurück zur Anmeldung
          </Link>
        </Box>
      </AuthShell>
    );
  }

  return (
    <AuthShell
      title="Passwort vergessen"
      subtitle="Aus Sicherheitsgründen erhalten Sie immer die gleiche Bestätigung — unabhängig davon, ob die Adresse bekannt ist."
    >
      <Box component="form" onSubmit={onSubmit}>
        <Stack spacing={2}>
          <TextField
            id="email"
            type="email"
            label="E-Mail-Adresse"
            required
            autoFocus
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            fullWidth
          />
          <Button
            type="submit"
            variant="contained"
            size="large"
            disabled={submitting}
            fullWidth
          >
            {submitting ? "Wird gesendet…" : "Link senden"}
          </Button>
        </Stack>
      </Box>
      <Box sx={{ textAlign: "center" }}>
        <Link
          component={RouterLink}
          to="/login"
          color="text.secondary"
          variant="body2"
          underline="hover"
        >
          Abbrechen
        </Link>
      </Box>
    </AuthShell>
  );
}
