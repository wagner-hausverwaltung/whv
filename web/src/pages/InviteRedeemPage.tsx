import { useEffect, useState, type FormEvent } from "react";
import { isAxiosError } from "axios";
import { Link as RouterLink, useNavigate, useSearchParams } from "react-router-dom";
import { Alert, Box, Button, Link, Stack, TextField, Typography } from "@mui/material";
import { api, setTokens } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { AuthShell } from "@/components/AuthShell";
import {
  MIN_PASSWORD_LENGTH,
  PASSWORD_HINT,
  PASSWORD_TOO_SHORT,
  isValidationError,
  passwordError,
} from "@/lib/password";

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
  // 410 = already redeemed. The invitation mail is the only link owners
  // keep, so they reopen it to get back in; that must lead to the login,
  // not to "ask your Hausverwaltung for a new invitation" (B42, 2026-08-26).
  const [alreadyRedeemed, setAlreadyRedeemed] = useState(false);
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
  //
  // The no-code path is handled by the initial state above
  // (`code ? undefined : null`) so this effect doesn't need to call
  // setInfo synchronously — keeps the react-hooks/set-state-in-effect
  // lint happy.
  useEffect(() => {
    if (!code) return;
    let cancelled = false;
    void api
      .get<InviteInfoResponse>(`/auth/invite/${encodeURIComponent(code)}`)
      .then((r) => {
        if (cancelled) return;
        setInfo(r.data);
        setEmail(r.data.email);
        setError(null);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setInfo(null);
        const redeemed = isAxiosError(err) && err.response?.status === 410;
        setAlreadyRedeemed(redeemed);
        setError(
          redeemed
            ? "Diese Einladung haben Sie bereits eingelöst. Melden Sie sich "
              + "einfach mit Ihrer E-Mail-Adresse und Ihrem Passwort an."
            : "Diese Einladung ist nicht (mehr) gültig. Bitte wenden Sie sich "
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
    const invalid = passwordError(password, confirm);
    if (invalid) {
      setError(invalid);
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
    } catch (err) {
      // 422 = the body failed validation (the password rule), NOT a broken
      // invite — saying "invite invalid" here is what stranded owners.
      setError(
        isValidationError(err)
          ? PASSWORD_TOO_SHORT
          : "Einladung ungültig, abgelaufen oder die E-Mail-Adresse passt nicht zur Einladung.",
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
        title={alreadyRedeemed ? "Sie haben bereits ein Konto" : "Einladung einlösen"}
        subtitle={
          alreadyRedeemed
            ? "Diese Einladung wurde schon verwendet."
            : "Bitte verwenden Sie den Link aus Ihrer Einladungs-E-Mail."
        }
      >
        <Stack spacing={2}>
          <Alert severity={alreadyRedeemed ? "info" : "error"} role="alert">
            {error}
          </Alert>
          {/* Always offer the way forward: someone who lands here has no
              other link to the portal in hand. */}
          <Button
            component={RouterLink}
            to="/login"
            variant="contained"
            size="large"
            fullWidth
          >
            Zur Anmeldung
          </Button>
          <Box sx={{ textAlign: "center" }}>
            <Link
              component={RouterLink}
              to="/forgot-password"
              variant="body2"
              underline="hover"
            >
              Passwort vergessen?
            </Link>
          </Box>
        </Stack>
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
