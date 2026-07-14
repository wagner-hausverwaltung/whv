import { useState, type FormEvent } from "react";
import { isAxiosError } from "axios";
import { Link as RouterLink } from "react-router-dom";
import { Alert, Box, Button, Link, Stack, TextField } from "@mui/material";
import { api } from "@/api/client";
import { AuthShell } from "@/components/AuthShell";

export function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [formatError, setFormatError] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setFormatError(false);
    try {
      await api.post("/auth/forgot-password", {
        email: email.trim().toLowerCase(),
      });
      setSubmitted(true);
    } catch (err) {
      // 422 = the address is syntactically invalid (typo) — showing the
      // success screen here would promise a mail that can never arrive.
      // Anything else (transport, 5xx) keeps the no-enumeration confirmation.
      if (isAxiosError(err) && err.response?.status === 422) {
        setFormatError(true);
      } else {
        setSubmitted(true);
      }
    } finally {
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
          {formatError && (
            <Alert severity="error">
              Diese E-Mail-Adresse ist ungültig formatiert (z. B. Tippfehler in
              der Domain). Bitte prüfen und erneut senden.
            </Alert>
          )}
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
