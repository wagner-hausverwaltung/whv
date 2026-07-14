import { useState, type FormEvent } from "react";
import { isAxiosError } from "axios";
import {
  Link as RouterLink,
  useLocation,
  useNavigate,
  useSearchParams,
} from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Link,
  Stack,
  TextField,
} from "@mui/material";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/auth/AuthContext";
import { AuthShell } from "@/components/AuthShell";

interface LocationState {
  from?: string;
}

export function LoginPage() {
  const { t } = useTranslation();
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [params] = useSearchParams();
  const from = (location.state as LocationState | null)?.from ?? "/";
  const justReset = params.get("reset") === "ok";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email.trim().toLowerCase(), password);
      navigate(from, { replace: true });
    } catch (err) {
      // A 422 means the EMAIL didn't pass validation (typo like a missing
      // ".de") — the password was never even checked. Saying "check email or
      // password" here sends people down a futile password-reset spiral.
      setError(
        isAxiosError(err) && err.response?.status === 422
          ? t("login.invalidEmail")
          : t("login.failed"),
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AuthShell title={t("login.title")} subtitle={t("login.subtitle")}>
      {justReset && !error && (
        <Alert severity="success">
          ✓ Passwort wurde aktualisiert. Bitte melden Sie sich mit dem neuen
          Passwort an.
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
            label={t("login.email")}
            required
            autoFocus
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            fullWidth
          />
          <TextField
            id="password"
            type="password"
            label={t("login.password")}
            required
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            fullWidth
          />
          <Button
            type="submit"
            variant="contained"
            size="large"
            disabled={submitting}
            fullWidth
          >
            {submitting ? t("common.loading") : t("login.submit")}
          </Button>
        </Stack>
      </Box>

      <Box sx={{ textAlign: "center" }}>
        <Link
          component={RouterLink}
          to="/forgot-password"
          color="text.secondary"
          underline="hover"
          variant="body2"
        >
          {t("login.forgot")}
        </Link>
      </Box>
    </AuthShell>
  );
}
