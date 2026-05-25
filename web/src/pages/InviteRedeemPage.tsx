import { useEffect, useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Alert, Box, Button, Link, Stack, TextField, Typography } from "@mui/material";
import { api, setTokens } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { AuthShell } from "@/components/AuthShell";

interface InviteInfoResponse {
  email: string;
  role: string;
  organization_name: string;
  expires_at: string;
}

export function InviteRedeemPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { refreshMe } = useAuth();
  const code = params.get("code") ?? "";

  // Three states for the invite lookup:
  //   undefined → still loading
  //   null      → lookup failed (no code, 404, expired, consumed)
  //   InviteInfo → success, email pre-filled + locked
  const [info, setInfo] = useState<InviteInfoResponse | null | undefined>(
    code ? undefined : null,
  );
  const [emailEditable, setEmailEditable] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(
    code ? null : "Kein Einladungscode in der URL.",
  );
  const [submitting, setSubmitting] = useState(false);

  // Look up the invite once on mount so we can pre-fill the email
  // field. Mirrors the iOS RegistrationView flow — the user shouldn't
  // be asked to re-type something already in their inbox; doing so
  // invites typo-induced "Einladung ungültig" failures.
  useEffect(() => {
    if (!code) {
      setInfo(null);
      return;
    }
    let cancelled = false;
    void api
      .get<InviteInfoResponse>(`/auth/invite/${encodeURIComponent(code)}`)
      .then((r) => {
        if (cancelled) return;
        setInfo(r.data);
        setEmail(r.data.email);
        setError(null);
      })
      .catch(() => {
        if (cancelled) return;
        setInfo(null);
        setError(
          "Diese Einladung ist nicht (mehr) gültig. Bitte wenden Sie sich "
            + "an Ihre Hausverwaltung für eine neue Einladung.",
        );
      });
    return () => {
      cancelled = true;
    };
  }, [code]);

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

  // No code in URL or invite lookup failed → terminal error state.
  // Don't render the form; the user has nothing to do here.
  if (info === null) {
    return (
      <AuthShell
        title="Einladung einlösen"
        subtitle="Bitte verwenden Sie den Link aus Ihrer Einladungs-E-Mail."
      >
        <Alert severity="error" role="alert">
          {error}
        </Alert>
      </AuthShell>
    );
  }

  // Lookup pending — show a quiet placeholder so the form doesn't
  // flicker between "blank email" and "pre-filled email".
  if (info === undefined) {
    return (
      <AuthShell
        title="Einladung einlösen"
        subtitle="Einladung wird geprüft…"
      >
        <Typography variant="body2" color="text.secondary">
          Einen Moment bitte.
        </Typography>
      </AuthShell>
    );
  }

  return (
    <AuthShell
      title="Einladung einlösen"
      subtitle={`Legen Sie Ihr Passwort fest, um sich künftig im WHV-Portal anzumelden. Einladung von ${info.organization_name}.`}
    >
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
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            disabled={!emailEditable}
            helperText={
              emailEditable
                ? "Achtung: Die Adresse muss mit jener aus der Einladung übereinstimmen."
                : "Aus der Einladung übernommen."
            }
            fullWidth
          />
          {!emailEditable && (
            <Box sx={{ mt: -1 }}>
              <Link
                component="button"
                type="button"
                variant="caption"
                onClick={() => setEmailEditable(true)}
              >
                Andere E-Mail verwenden?
              </Link>
            </Box>
          )}
          <TextField
            id="password"
            type="password"
            label="Neues Passwort"
            required
            autoFocus
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
