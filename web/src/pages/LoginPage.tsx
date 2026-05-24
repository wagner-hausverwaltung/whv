import { useState, type FormEvent } from "react";
import {
  Link,
  useLocation,
  useNavigate,
  useSearchParams,
} from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { AuthShell } from "@/components/AuthShell";

interface LocationState {
  from?: string;
}

export function LoginPage() {
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
    } catch {
      setError("Ungültige E-Mail-Adresse oder Passwort.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AuthShell title="Anmelden" subtitle="Für Eigentümer und Mieter.">
      {justReset && !error && (
        <p className="flash-success">
          ✓ Passwort wurde aktualisiert. Bitte melden Sie sich mit dem neuen
          Passwort an.
        </p>
      )}

      {error && (
        <p className="flash-error" role="alert">
          {error}
        </p>
      )}

      <form onSubmit={onSubmit} className="space-y-4">
        <div>
          <label htmlFor="email" className="label">
            E-Mail-Adresse
          </label>
          <input
            id="email"
            type="email"
            required
            autoFocus
            autoComplete="email"
            className="input"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <div>
          <label htmlFor="password" className="label">
            Passwort
          </label>
          <input
            id="password"
            type="password"
            required
            autoComplete="current-password"
            className="input"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        <button
          type="submit"
          className="btn-primary w-full"
          disabled={submitting}
        >
          {submitting ? "Wird angemeldet…" : "Anmelden"}
        </button>
      </form>

      <p className="text-center">
        <Link to="/forgot-password" className="muted hover:underline">
          Passwort vergessen?
        </Link>
      </p>
    </AuthShell>
  );
}
