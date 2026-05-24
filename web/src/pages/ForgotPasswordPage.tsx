import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "@/api/client";

export function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      // /auth/forgot-password always returns 204 (no enumeration). We just
      // show the confirmation page regardless.
      await api.post("/auth/forgot-password", { email: email.trim().toLowerCase() });
    } catch {
      // Network failure aside, swallow and show the same confirmation —
      // the user can request again if no email arrives.
    } finally {
      setSubmitted(true);
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <h1 className="text-2xl font-bold mb-1 text-slate-900">
          Passwort vergessen
        </h1>

        {submitted ? (
          <>
            <p className="flash-success mt-6">
              Falls Ihre E-Mail-Adresse bei uns hinterlegt ist, wurde ein
              Link zum Zurücksetzen versandt. Bitte prüfen Sie Ihren
              Posteingang (auch Spam-Ordner). Der Link ist 30 Minuten gültig.
            </p>
            <p className="text-center mt-6">
              <Link to="/login" className="muted hover:underline">
                ← Zurück zur Anmeldung
              </Link>
            </p>
          </>
        ) : (
          <>
            <p className="muted mb-6">
              Geben Sie Ihre E-Mail-Adresse ein. Aus Sicherheitsgründen
              erhalten Sie immer die gleiche Bestätigung — unabhängig davon,
              ob die Adresse bekannt ist.
            </p>
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
              <button
                type="submit"
                className="btn-primary w-full"
                disabled={submitting}
              >
                {submitting ? "Wird gesendet…" : "Link senden"}
              </button>
              <p className="text-center">
                <Link to="/login" className="muted hover:underline">
                  Abbrechen
                </Link>
              </p>
            </form>
          </>
        )}
      </div>
    </div>
  );
}
