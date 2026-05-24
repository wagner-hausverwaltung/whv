import { useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Alert, Box, Button, Stack, TextField, Typography } from "@mui/material";
import { api, setTokens } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { AuthShell } from "@/components/AuthShell";

export function InviteRedeemPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { refreshMe } = useAuth();
  const code = params.get("code") ?? "";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(
    code ? null : "Kein Einladungscode in der URL.",
  );
  const [submitting, setSubmitting] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (password !== confirm) {
      setError("Passwörter stimmen nicht überein.");
      return;
    }
    if (password.length < 8) {
      setError("Passwort muss mindestens 8 Zeichen lang sein.");
      return;
    }
    setSubmitting(true);
    try {
      const res = await api.post("/auth/invite/redeem", {
        code,
        email: email.trim().toLowerCase(),
        password,
      });
      setTokens(res.data.access_token, res.data.refresh_token);
      await refreshMe();
      navigate("/", { replace: true });
    } catch {
      setError(
        "Einladung ungültig, abgelaufen oder die E-Mail-Adresse passt nicht zur Einladung.",
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AuthShell
      title="Einladung einlösen"
      subtitle="Legen Sie Ihr Passwort fest, um sich künftig im WHV-Portal anzumelden."
    >
      {code && (
        <Alert severity="info" icon={false}>
          <Typography
            variant="caption"
            sx={{ fontFamily: "ui-monospace, Menlo, monospace" }}
          >
            Code: <strong>{code}</strong>
          </Typography>
        </Alert>
      )}

      {error && (
        <Alert severity="error" role="alert">
          {error}
        </Alert>
      )}

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
            helperText="Muss mit der E-Mail-Adresse aus der Einladung übereinstimmen."
            fullWidth
          />
          <TextField
            id="password"
            type="password"
            label="Neues Passwort"
            required
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            slotProps={{ htmlInput: { minLength: 8 } }}
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
            slotProps={{ htmlInput: { minLength: 8 } }}
            fullWidth
          />
          <Button
            type="submit"
            variant="contained"
            size="large"
            disabled={submitting || !code}
            fullWidth
          >
            {submitting ? "Wird eingelöst…" : "Einladung einlösen + anmelden"}
          </Button>
        </Stack>
      </Box>
    </AuthShell>
  );
}
