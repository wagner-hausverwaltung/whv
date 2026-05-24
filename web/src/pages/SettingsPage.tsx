import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";

export function SettingsPage() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const [pwRequested, setPwRequested] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!user) return null;

  const requestPwReset = async () => {
    setError(null);
    try {
      await api.post("/auth/forgot-password", { email: user.email });
      setPwRequested(true);
    } catch {
      setError("Anforderung fehlgeschlagen. Bitte später erneut versuchen.");
    }
  };

  const downloadExport = async () => {
    setError(null);
    setExporting(true);
    try {
      const res = await api.get("/me/export", { responseType: "blob" });
      const blob = new Blob([res.data], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `whv-export-${user.email}-${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch {
      setError("Export fehlgeschlagen.");
    } finally {
      setExporting(false);
    }
  };

  const deleteAccount = async () => {
    if (deleteConfirm !== "LÖSCHEN") return;
    setError(null);
    setDeleting(true);
    try {
      await api.delete("/me");
      await logout();
      navigate("/login", { replace: true });
    } catch {
      setError("Löschen fehlgeschlagen.");
      setDeleting(false);
    }
  };

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-bold text-slate-900">Einstellungen</h1>

      {error && <p className="flash-error">{error}</p>}

      <section className="card space-y-2">
        <h2 className="font-semibold">Konto</h2>
        <p>
          <span className="muted">E-Mail: </span>
          <span className="font-mono text-sm">{user.email}</span>
        </p>
        <p>
          <span className="muted">Rolle: </span>
          {user.role}
        </p>
        {user.contact_id_impower !== null && (
          <p>
            <span className="muted">Impower-Kontakt-ID: </span>
            <span className="font-mono text-sm">{user.contact_id_impower}</span>
          </p>
        )}
      </section>

      <section className="card space-y-3">
        <h2 className="font-semibold">Passwort ändern</h2>
        <p className="muted">
          Klicken Sie unten, um eine Reset-E-Mail an{" "}
          <strong>{user.email}</strong> zu senden. Der Link ist 30 Minuten
          gültig und beendet alle aktiven Sitzungen.
        </p>
        {pwRequested ? (
          <p className="flash-success">
            ✓ Reset-E-Mail wurde versandt. Bitte prüfen Sie Ihren Posteingang.
          </p>
        ) : (
          <button
            type="button"
            className="btn-secondary"
            onClick={requestPwReset}
          >
            Reset-E-Mail anfordern
          </button>
        )}
      </section>

      <section className="card space-y-3">
        <h2 className="font-semibold">Meine Daten exportieren</h2>
        <p className="muted">
          DSGVO Art. 20 — alle zu Ihrem Konto gespeicherten Daten als
          JSON-Datei herunterladen.
        </p>
        <button
          type="button"
          className="btn-secondary"
          onClick={downloadExport}
          disabled={exporting}
        >
          {exporting ? "Wird vorbereitet…" : "JSON-Export herunterladen"}
        </button>
      </section>

      <section className="card-danger space-y-3">
        <h2 className="font-display font-semibold text-red-700">Konto löschen</h2>
        <p className="muted">
          Ihr Konto wird zum Löschen markiert (30-Tage-Wiederherstellungsfenster).
          Alle aktiven Sitzungen werden beendet. Die in Impower hinterlegten
          Stammdaten bleiben unberührt.
        </p>
        <p className="muted text-xs">
          Tippen Sie <strong>LÖSCHEN</strong> in das Feld unten, um zu bestätigen.
        </p>
        <input
          type="text"
          className="input max-w-xs"
          placeholder="LÖSCHEN"
          value={deleteConfirm}
          onChange={(e) => setDeleteConfirm(e.target.value)}
        />
        <button
          type="button"
          className="btn-danger"
          onClick={deleteAccount}
          disabled={deleteConfirm !== "LÖSCHEN" || deleting}
        >
          {deleting ? "Wird gelöscht…" : "Konto unwiderruflich löschen"}
        </button>
      </section>
    </div>
  );
}
