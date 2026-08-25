import { useState, type FormEvent } from "react";
import {
  Link as RouterLink,
  useNavigate,
  useSearchParams,
} from "react-router-dom";
import { Alert, Box, Button, Link, Stack, TextField } from "@mui/material";
import { api } from "@/api/client";
import { AuthShell } from "@/components/AuthShell";
import {
  MIN_PASSWORD_LENGTH,
  PASSWORD_HINT,
  PASSWORD_TOO_SHORT,
  isValidationError,
  passwordError,
} from "@/lib/password";

export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const token = params.get("token") ?? "";

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (!token) {
    return (
      <AuthShell title="Neues Passwort setzen">
        <Alert severity="error">
          Diese Seite kann nur über den Link aus der Reset-E-Mail aufgerufen
          werden.
        </Alert>
        <Box sx={{ textAlign: "center" }}>
          <Link
            component={RouterLink}
            to="/forgot-password"
            color="text.secondary"
            variant="body2"
            underline="hover"
          >
            Neuen Link anfordern
          </Link>
        </Box>
      </AuthShell>
    );
  }

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    const invalid = passwordError(password, confirm);
    if (invalid) {
      setError(invalid);
      return;
    }
    setSubmitting(true);
    try {
      await api.post("/auth/reset-password", {
        token,
        new_password: password,
      });
      navigate("/login?reset=ok", { replace: true });
    } catch (err) {
      // 422 = body validation (the password rule), not a dead token.
      setError(
        isValidationError(err)
          ? PASSWORD_TOO_SHORT
          : "Token ungültig, abgelaufen oder bereits eingelöst. Bitte fordern Sie einen neuen an.",
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AuthShell
      title="Neues Passwort setzen"
      subtitle={`${PASSWORD_HINT} Nach dem Speichern werden alle aktiven Sitzungen beendet.`}
    >
      {error && (
        <Alert severity="error" role="alert">
          {error}
        </Alert>
      )}

      <Box component="form" onSubmit={onSubmit}>
        <Stack spacing={2}>
          <TextField
            id="password"
            type="password"
            label="Neues Passwort"
            required
            autoFocus
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            helperText={PASSWORD_HINT}
            slotProps={{ htmlInput: { minLength: MIN_PASSWORD_LENGTH } }}
            fullWidth
          />
          <TextField
            id="confirm"
            type="password"
            label="Passwort bestätigen"
            required
            autoComplete="new-password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            slotProps={{ htmlInput: { minLength: MIN_PASSWORD_LENGTH } }}
            fullWidth
          />
          <Button
            type="submit"
            variant="contained"
            size="large"
            disabled={submitting}
            fullWidth
          >
            {submitting ? "Wird gespeichert…" : "Passwort setzen"}
          </Button>
        </Stack>
      </Box>
    </AuthShell>
  );
}
