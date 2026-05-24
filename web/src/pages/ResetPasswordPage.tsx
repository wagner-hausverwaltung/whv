import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "@/api/client";

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
      <div className="min-h-screen flex items-center justify-center px-4">
        <div className="w-full max-w-sm">
          <h1 className="text-2xl font-bold mb-3">Neues Passwort setzen</h1>
          <p className="flash-error">
            Diese Seite kann nur über den Link aus der Reset-E-Mail aufgerufen
            werden.
          </p>
          <p className="text-center mt-6">
            <Link to="/forgot-password" className="muted hover:underline">
              Neuen Link anfordern
            </Link>
          </p>
        </div>
      </div>
    );
  }

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
      await api.post("/auth/reset-password", {
        token,
        new_password: password,
      });
      navigate("/login?reset=ok", { replace: true });
    } catch {
      setError(
        "Token ungültig, abgelaufen oder bereits eingelöst. Bitte fordern Sie einen neuen an.",
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <h1 className="text-2xl font-bold mb-1 text-slate-900">
          Neues Passwort setzen
        </h1>
        <p className="muted mb-6">
          Mindestens 8 Zeichen. Nach dem Speichern werden alle aktiven
          Sitzungen beendet — Sie müssen sich neu anmelden.
        </p>

        {error && (
          <p className="flash-error mb-4" role="alert">
            {error}
          </p>
        )}

        <form onSubmit={onSubmit} className="space-y-4">
          <div>
            <label htmlFor="password" className="label">
              Neues Passwort
            </label>
            <input
              id="password"
              type="password"
              required
              autoFocus
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
            disabled={submitting}
          >
            {submitting ? "Wird gespeichert…" : "Passwort setzen"}
          </button>
        </form>
      </div>
    </div>
  );
}
