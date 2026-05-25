import { useRef, useState, type ChangeEvent } from "react";
import { useNavigate } from "react-router-dom";
import {
  Alert,
  Avatar,
  Box,
  Button,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import PhotoCameraOutlinedIcon from "@mui/icons-material/PhotoCameraOutlined";
import { api, API_BASE_URL } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import type { UserResponse } from "@/api/types";

function initialsOf(email: string): string {
  const local = email.split("@")[0] ?? email;
  const parts = local
    .split(/[._\s-]+/)
    .filter(Boolean)
    .slice(0, 2);
  if (parts.length === 0) return "?";
  return parts.map((p) => p[0]?.toUpperCase() ?? "").join("") || "?";
}

export function SettingsPage() {
  const { user, logout, refreshMe } = useAuth();
  const navigate = useNavigate();

  const [pwRequested, setPwRequested] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Avatar errors live inline next to the Profilbild section, separate
  // from the page-level `error` (which covers password reset / export /
  // delete-account). Keeps the upload feedback in the user's eye-line.
  const [avatarError, setAvatarError] = useState<string | null>(null);
  const [avatarBusy, setAvatarBusy] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  if (!user) return null;

  const onPickAvatar = () => fileInputRef.current?.click();

  const onAvatarChange = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setAvatarError(null);
    setAvatarBusy(true);
    try {
      const form = new FormData();
      form.append("file", file);
      // The api-client interceptor drops Content-Type when the body is
      // FormData so the browser can attach the correct multipart boundary.
      await api.put<UserResponse>("/me/avatar", form);
      await refreshMe();
    } catch (err: unknown) {
      const detail = (
        err as { response?: { data?: { detail?: string } } }
      ).response?.data?.detail;
      const status = (err as { response?: { status?: number } }).response
        ?.status;
      // Surface the server's reason verbatim when we got one — backend
      // already prefixes German user-facing copy ("Ungültige Bilddatei: …",
      // "Avatar darf höchstens 4 MB groß sein.", etc.). Fall back to the
      // generic line only when there's no body (network error / CORS).
      const fallback =
        status === 413
          ? "Bild zu groß. Bitte verkleinern und erneut versuchen."
          : "Bild konnte nicht hochgeladen werden. Bitte JPEG, PNG oder WebP wählen.";
      setAvatarError(detail ?? fallback);
    } finally {
      setAvatarBusy(false);
      // Reset the input so picking the same file again re-triggers onChange.
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const onAvatarRemove = async () => {
    setAvatarError(null);
    setAvatarBusy(true);
    try {
      await api.delete("/me/avatar");
      await refreshMe();
    } catch {
      setAvatarError("Bild konnte nicht entfernt werden.");
    } finally {
      setAvatarBusy(false);
    }
  };

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
          Profilbild
        </Typography>
        {avatarError && (
          <Alert
            severity="error"
            onClose={() => setAvatarError(null)}
            sx={{ mb: 2 }}
          >
            {avatarError}
          </Alert>
        )}
        <Stack direction="row" spacing={3} sx={{ alignItems: "center" }}>
          <Avatar
            src={
              user.avatar_url ? `${API_BASE_URL}${user.avatar_url}` : undefined
            }
            sx={{
              width: 80,
              height: 80,
              bgcolor: "primary.main",
              color: "primary.contrastText",
              fontSize: "1.5rem",
            }}
          >
            {initialsOf(user.email)}
          </Avatar>
          <Stack spacing={1}>
            <Typography variant="body2" color="text.secondary">
              JPEG, PNG oder WebP, max. 4 MB. Wir verkleinern automatisch auf
              256×256.
            </Typography>
            <Stack direction="row" spacing={1}>
              <Button
                variant="outlined"
                startIcon={<PhotoCameraOutlinedIcon />}
                onClick={onPickAvatar}
                disabled={avatarBusy}
              >
                {avatarBusy
                  ? "Wird verarbeitet…"
                  : user.avatar_url
                    ? "Bild ändern"
                    : "Bild hochladen"}
              </Button>
              {user.avatar_url && (
                <Button
                  variant="text"
                  color="inherit"
                  onClick={onAvatarRemove}
                  disabled={avatarBusy}
                >
                  Entfernen
                </Button>
              )}
            </Stack>
            <input
              ref={fileInputRef}
              type="file"
              // Broaden the picker hint to image/* so iPhone HEIC/HEIF
              // shows up too. We still only persist what Pillow can
              // decode server-side — if a HEIC slips through, the
              // backend returns "Ungültige Bilddatei: …" which now
              // renders in the inline Alert above.
              accept="image/*"
              hidden
              onChange={onAvatarChange}
            />
          </Stack>
        </Stack>
      </Paper>

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
