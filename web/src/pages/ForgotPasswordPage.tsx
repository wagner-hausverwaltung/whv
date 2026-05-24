import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "@/api/client";
import { AuthShell } from "@/components/AuthShell";

export function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      await api.post("/auth/forgot-password", {
        email: email.trim().toLowerCase(),
      });
    } catch {
      // /auth/forgot-password always 204s; even on transport failure we show
      // the same confirmation (no enumeration). User can request again.
    } finally {
      setSubmitted(true);
      setSubmitting(false);
    }
  };

  if (submitted) {
    return (
      <AuthShell title="Passwort vergessen">
        <p className="flash-success">
          Falls Ihre E-Mail-Adresse bei uns hinterlegt ist, wurde ein Link zum
          Zurücksetzen versandt. Bitte prüfen Sie Ihren Posteingang (auch
          Spam-Ordner). Der Link ist 30 Minuten gültig.
        </p>
        <p className="text-center">
          <Link to="/login" className="muted hover:underline">
            ← Zurück zur Anmeldung
          </Link>
        </p>
      </AuthShell>
    );
  }

  return (
    <AuthShell
      title="Passwort vergessen"
      subtitle="Aus Sicherheitsgründen erhalten Sie immer die gleiche Bestätigung — unabhängig davon, ob die Adresse bekannt ist."
    >
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
      </form>
      <p className="text-center">
        <Link to="/login" className="muted hover:underline">
          Abbrechen
        </Link>
      </p>
    </AuthShell>
  );
}
