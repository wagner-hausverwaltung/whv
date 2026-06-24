// Owner-facing Vollmacht (ETV proxy) card on the assembly detail (ADR-0017).
// An Eigentümer delegates their vote to a proxy and signs in-app; the signed
// WHV-design PDF is downloadable, and the Vollmacht can be revoked before the
// meeting. Hidden for non-owners by the parent (it only renders this for
// Eigentümer/Beirat).

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import DownloadIcon from "@mui/icons-material/Download";
import HowToVoteIcon from "@mui/icons-material/HowToVote";
import { useTranslation } from "react-i18next";
import { api } from "@/api/client";
import type { VollmachtResponse } from "@/api/types";
import { SignaturePad, type SignaturePadHandle } from "@/components/SignaturePad";

function fmtDate(d: string | null): string {
  if (!d) return "—";
  const parsed = new Date(d);
  return Number.isNaN(parsed.getTime()) ? d : parsed.toLocaleDateString("de-DE");
}

export function VollmachtCard({ assemblyId }: { assemblyId: string }) {
  const { t } = useTranslation();
  const [vollmacht, setVollmacht] = useState<VollmachtResponse | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [proxyName, setProxyName] = useState("");
  const [scopeNote, setScopeNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const padRef = useRef<SignaturePadHandle>(null);

  const load = useCallback(async () => {
    try {
      const r = await api.get<VollmachtResponse>(`/me/assemblies/${assemblyId}/vollmacht`);
      setVollmacht(r.data);
    } catch {
      // 404 = no active Vollmacht yet; any other error also just shows the grant CTA.
      setVollmacht(null);
    } finally {
      setLoaded(true);
    }
  }, [assemblyId]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const grant = async () => {
    if (!proxyName.trim()) {
      setError(t("vollmacht.proxyNameRequired"));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const blob = await padRef.current?.toBlob();
      const fd = new FormData();
      fd.append("proxy_name", proxyName.trim());
      if (scopeNote.trim()) fd.append("scope_note", scopeNote.trim());
      if (blob) fd.append("signature", blob, "signature.png");
      const r = await api.post<VollmachtResponse>(
        `/me/assemblies/${assemblyId}/vollmacht`,
        fd,
      );
      setVollmacht(r.data);
      setDialogOpen(false);
      setProxyName("");
      setScopeNote("");
    } catch (e) {
      const detail =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        t("vollmacht.grantFailed");
      setError(detail);
    } finally {
      setBusy(false);
    }
  };

  const revoke = async () => {
    if (!vollmacht) return;
    setBusy(true);
    try {
      await api.post(`/me/vollmachten/${vollmacht.id}/revoke`);
      await load();
    } catch {
      setError(t("vollmacht.revokeFailed"));
    } finally {
      setBusy(false);
    }
  };

  const download = async () => {
    if (!vollmacht) return;
    const r = await api.get(`/me/vollmachten/${vollmacht.id}/document.pdf`, {
      responseType: "blob",
    });
    const url = URL.createObjectURL(r.data as Blob);
    window.open(url, "_blank", "noopener");
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  };

  if (!loaded) return null;

  const active = vollmacht && vollmacht.status === "SIGNED";

  return (
    <Box>
      <Typography variant="h5" component="h2" sx={{ mb: 2 }}>
        {t("vollmacht.title")}
      </Typography>
      <Paper variant="outlined" sx={{ p: 2 }}>
        {active ? (
          <Stack spacing={1.5}>
            <Stack direction="row" spacing={1} sx={{ alignItems: "center", flexWrap: "wrap" }}>
              <Chip size="small" color="success" icon={<HowToVoteIcon />} label={t("vollmacht.granted")} />
              <Typography variant="body2">
                {t("vollmacht.grantedToPrefix")} <strong>{vollmacht.proxy_name}</strong> · {fmtDate(vollmacht.signed_at)}
              </Typography>
            </Stack>
            {vollmacht.scope_note && (
              <Typography variant="caption" color="text.secondary">
                {t("vollmacht.instructionLabel")}: {vollmacht.scope_note}
              </Typography>
            )}
            <Stack direction="row" spacing={1}>
              <Button size="small" variant="outlined" startIcon={<DownloadIcon />} onClick={() => void download()}>
                {t("vollmacht.downloadPdf")}
              </Button>
              <Button size="small" color="error" onClick={() => void revoke()} disabled={busy}>
                {t("vollmacht.revoke")}
              </Button>
            </Stack>
          </Stack>
        ) : (
          <Stack
            direction={{ xs: "column", sm: "row" }}
            spacing={2}
            sx={{ alignItems: { sm: "center" }, justifyContent: "space-between" }}
          >
            <Stack direction="row" spacing={1.5} sx={{ alignItems: "center" }}>
              <HowToVoteIcon color="primary" />
              <Box>
                <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                  {t("vollmacht.cantAttend")}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {t("vollmacht.cantAttendSub")}
                </Typography>
              </Box>
            </Stack>
            <Button variant="contained" onClick={() => setDialogOpen(true)}>
              {t("vollmacht.grant")}
            </Button>
          </Stack>
        )}
      </Paper>

      <Dialog open={dialogOpen} onClose={() => setDialogOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>{t("vollmacht.grant")}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            {error && <Alert severity="error">{error}</Alert>}
            <TextField
              label={t("vollmacht.proxyPerson")}
              placeholder={t("vollmacht.proxyPlaceholder")}
              value={proxyName}
              onChange={(e) => setProxyName(e.target.value)}
              required
              fullWidth
            />
            <TextField
              label={t("vollmacht.scopeLabel")}
              placeholder={t("vollmacht.scopePlaceholder")}
              value={scopeNote}
              onChange={(e) => setScopeNote(e.target.value)}
              fullWidth
              multiline
              minRows={2}
            />
            <SignaturePad ref={padRef} label={t("vollmacht.signatureLabel")} />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialogOpen(false)} disabled={busy}>
            {t("common.cancel")}
          </Button>
          <Button variant="contained" onClick={() => void grant()} disabled={busy}>
            {busy ? t("vollmacht.granting") : t("vollmacht.signAndGrant")}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
