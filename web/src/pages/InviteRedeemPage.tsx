import { useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
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
  // Initial error from URL state (computed once); submission errors overwrite.
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
        <p className="flash-info font-mono text-xs">
          Code: <strong>{code}</strong>
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
          <p className="muted mt-1.5 text-xs">
            Muss mit der E-Mail-Adresse aus der Einladung übereinstimmen.
          </p>
        </div>
        <div>
          <label htmlFor="password" className="label">
            Neues Passwort
          </label>
          <input
            id="password"
            type="password"
            required
            autoComplete="new-password"
            minLength={8}
            className="input"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        <div>
          <label htmlFor="confirm" className="label">
            Passwort bestätigen
          </label>
          <input
            id="confirm"
            type="password"
            required
            autoComplete="new-password"
            minLength={8}
            className="input"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
          />
        </div>
        <button
          type="submit"
          className="btn-primary w-full"
          disabled={submitting || !code}
        >
          {submitting ? "Wird eingelöst…" : "Einladung einlösen + anmelden"}
        </button>
      </form>
    </AuthShell>
  );
}
