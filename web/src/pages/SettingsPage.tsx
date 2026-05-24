import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
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
    <Stack spacing={4}>
      <Typography variant="h4" component="h1" sx={{ fontWeight: 700 }}>
        Einstellungen
      </Typography>

      {error && <Alert severity="error">{error}</Alert>}

      <Paper variant="outlined" sx={{ p: 2.5 }}>
        <Typography variant="h6" gutterBottom>
          Konto
        </Typography>
        <Stack spacing={1}>
          <Box>
            <Typography component="span" variant="body2" color="text.secondary">
              E-Mail:{" "}
            </Typography>
            <Typography
              component="span"
              variant="body2"
              sx={{ fontFamily: "ui-monospace, Menlo, monospace" }}
            >
              {user.email}
            </Typography>
          </Box>
          <Box>
            <Typography component="span" variant="body2" color="text.secondary">
              Rolle:{" "}
            </Typography>
            <Typography component="span" variant="body2">
              {user.role}
            </Typography>
          </Box>
          {user.contact_id_impower !== null && (
            <Box>
              <Typography
                component="span"
                variant="body2"
                color="text.secondary"
              >
                Impower-Kontakt-ID:{" "}
              </Typography>
              <Typography
                component="span"
                variant="body2"
                sx={{ fontFamily: "ui-monospace, Menlo, monospace" }}
              >
                {user.contact_id_impower}
              </Typography>
            </Box>
          )}
        </Stack>
      </Paper>

      <Paper variant="outlined" sx={{ p: 2.5 }}>
        <Typography variant="h6" gutterBottom>
          Passwort ändern
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Klicken Sie unten, um eine Reset-E-Mail an{" "}
          <strong>{user.email}</strong> zu senden. Der Link ist 30 Minuten
          gültig und beendet alle aktiven Sitzungen.
        </Typography>
        {pwRequested ? (
          <Alert severity="success">
            ✓ Reset-E-Mail wurde versandt. Bitte prüfen Sie Ihren Posteingang.
          </Alert>
        ) : (
          <Button variant="outlined" onClick={requestPwReset}>
            Reset-E-Mail anfordern
          </Button>
        )}
      </Paper>

      <Paper variant="outlined" sx={{ p: 2.5 }}>
        <Typography variant="h6" gutterBottom>
          Meine Daten exportieren
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          DSGVO Art. 20 — alle zu Ihrem Konto gespeicherten Daten als
          JSON-Datei herunterladen.
        </Typography>
        <Button
          variant="outlined"
          onClick={downloadExport}
          disabled={exporting}
        >
          {exporting ? "Wird vorbereitet…" : "JSON-Export herunterladen"}
        </Button>
      </Paper>

      <Paper
        variant="outlined"
        sx={(theme) => ({
          p: 2.5,
          borderColor:
            theme.palette.mode === "dark"
              ? "rgba(220, 38, 38, 0.4)"
              : "rgba(220, 38, 38, 0.3)",
        })}
      >
        <Typography variant="h6" color="error" gutterBottom>
          Konto löschen
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
          Ihr Konto wird zum Löschen markiert (30-Tage-Wiederherstellungsfenster).
          Alle aktiven Sitzungen werden beendet. Die in Impower hinterlegten
          Stammdaten bleiben unberührt.
        </Typography>
        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 1.5 }}>
          Tippen Sie <strong>LÖSCHEN</strong> in das Feld unten, um zu bestätigen.
        </Typography>
        <Stack spacing={1.5}>
          <TextField
            type="text"
            size="small"
            placeholder="LÖSCHEN"
            value={deleteConfirm}
            onChange={(e) => setDeleteConfirm(e.target.value)}
            sx={{ maxWidth: 280 }}
          />
          <Box>
            <Button
              variant="contained"
              color="error"
              onClick={deleteAccount}
              disabled={deleteConfirm !== "LÖSCHEN" || deleting}
            >
              {deleting ? "Wird gelöscht…" : "Konto unwiderruflich löschen"}
            </Button>
          </Box>
        </Stack>
      </Paper>
    </Stack>
  );
}
