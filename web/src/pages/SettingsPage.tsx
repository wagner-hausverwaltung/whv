import { useRef, useState, type ChangeEvent, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import {
  Alert,
  Avatar,
  Box,
  Button,
  Divider,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import PhotoCameraOutlinedIcon from "@mui/icons-material/PhotoCameraOutlined";
import { api, API_BASE_URL } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { NotificationSettings } from "@/components/NotificationSettings";
import type { UserResponse } from "@/api/types";

// Compact card wrapper + section title, so every block shares the same
// tight rhythm (less padding + smaller heading than the old h6 cards).
function Section({ title, color, children }: { title: string; color?: "error"; children: ReactNode }) {
  return (
    <Paper
      variant="outlined"
      sx={(theme) => ({
        p: 2,
        ...(color === "error" && {
          borderColor:
            theme.palette.mode === "dark"
              ? "rgba(220, 38, 38, 0.4)"
              : "rgba(220, 38, 38, 0.3)",
        }),
      })}
    >
      <Typography
        variant="subtitle1"
        color={color}
        sx={{ fontWeight: 700, mb: 1.5 }}
      >
        {title}
      </Typography>
      {children}
    </Paper>
  );
}

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
    <Stack spacing={2.5} sx={{ maxWidth: 760, mx: "auto", width: "100%" }}>
      <Typography variant="h5" component="h1" sx={{ fontWeight: 700 }}>
        Einstellungen
      </Typography>

      {error && <Alert severity="error">{error}</Alert>}

      {/* Profil & Konto — avatar + identity in one compact row. */}
      <Section title="Profil">
        {avatarError && (
          <Alert severity="error" onClose={() => setAvatarError(null)} sx={{ mb: 1.5 }}>
            {avatarError}
          </Alert>
        )}
        <Stack direction="row" spacing={2} sx={{ alignItems: "center" }}>
          <Avatar
            src={user.avatar_url ? `${API_BASE_URL}${user.avatar_url}` : undefined}
            sx={{
              width: 64,
              height: 64,
              bgcolor: "primary.main",
              color: "primary.contrastText",
              fontSize: "1.25rem",
            }}
          >
            {initialsOf(user.email)}
          </Avatar>
          <Box sx={{ minWidth: 0, flexGrow: 1 }}>
            <Typography
              variant="body2"
              sx={{ fontFamily: "ui-monospace, Menlo, monospace", wordBreak: "break-all" }}
            >
              {user.email}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              Rolle: {user.role}
              {user.contact_id_impower !== null && ` · Impower-ID ${user.contact_id_impower}`}
            </Typography>
            <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
              <Button
                size="small"
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
                  size="small"
                  variant="text"
                  color="inherit"
                  onClick={onAvatarRemove}
                  disabled={avatarBusy}
                >
                  Entfernen
                </Button>
              )}
            </Stack>
          </Box>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            hidden
            onChange={onAvatarChange}
          />
        </Stack>
      </Section>

      {/* Benachrichtigungen — the Push/E-Mail matrix (shared with iOS). */}
      <Section title="Benachrichtigungen">
        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 1.5 }}>
          Wählen Sie je Ereignis, ob Sie per Push (App) und/oder E-Mail
          benachrichtigt werden möchten.
        </Typography>
        <NotificationSettings />
      </Section>

      {/* Sicherheit & Daten — password reset + DSGVO export, two tight rows. */}
      <Section title="Sicherheit & Daten">
        <Stack divider={<Divider flexItem />} spacing={1.5}>
          <Stack
            direction="row"
            spacing={2}
            sx={{ alignItems: "center", justifyContent: "space-between" }}
          >
            <Box sx={{ minWidth: 0 }}>
              <Typography variant="body2" sx={{ fontWeight: 600 }}>
                Passwort ändern
              </Typography>
              <Typography variant="caption" color="text.secondary">
                Reset-Link an {user.email} — 30 Min. gültig, beendet alle Sitzungen.
              </Typography>
            </Box>
            {pwRequested ? (
              <Typography variant="caption" color="success.main" sx={{ flexShrink: 0 }}>
                ✓ E-Mail versandt
              </Typography>
            ) : (
              <Button size="small" variant="outlined" onClick={requestPwReset} sx={{ flexShrink: 0 }}>
                Reset-E-Mail
              </Button>
            )}
          </Stack>
          <Stack
            direction="row"
            spacing={2}
            sx={{ alignItems: "center", justifyContent: "space-between" }}
          >
            <Box sx={{ minWidth: 0 }}>
              <Typography variant="body2" sx={{ fontWeight: 600 }}>
                Meine Daten exportieren
              </Typography>
              <Typography variant="caption" color="text.secondary">
                DSGVO Art. 20 — alle Kontodaten als JSON-Datei.
              </Typography>
            </Box>
            <Button
              size="small"
              variant="outlined"
              onClick={downloadExport}
              disabled={exporting}
              sx={{ flexShrink: 0 }}
            >
              {exporting ? "Wird vorbereitet…" : "JSON-Export"}
            </Button>
          </Stack>
        </Stack>
      </Section>

      {/* Danger zone. */}
      <Section title="Konto löschen" color="error">
        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 1.5 }}>
          Markiert das Konto zum Löschen (30-Tage-Fenster) und beendet alle
          Sitzungen. Die in Impower hinterlegten Stammdaten bleiben unberührt.
          Tippen Sie <strong>LÖSCHEN</strong> zum Bestätigen.
        </Typography>
        <Stack direction="row" spacing={1} sx={{ alignItems: "center", flexWrap: "wrap" }}>
          <TextField
            type="text"
            size="small"
            placeholder="LÖSCHEN"
            value={deleteConfirm}
            onChange={(e) => setDeleteConfirm(e.target.value)}
            sx={{ maxWidth: 200 }}
          />
          <Button
            variant="contained"
            color="error"
            size="small"
            onClick={deleteAccount}
            disabled={deleteConfirm !== "LÖSCHEN" || deleting}
          >
            {deleting ? "Wird gelöscht…" : "Unwiderruflich löschen"}
          </Button>
        </Stack>
      </Section>
    </Stack>
  );
}
