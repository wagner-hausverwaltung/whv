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
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";
import DownloadIcon from "@mui/icons-material/Download";
import HowToVoteIcon from "@mui/icons-material/HowToVote";
import { useTranslation } from "react-i18next";
import { api } from "@/api/client";
import type {
  AgendaItemResponse,
  VollmachtResponse,
  VollmachtVoteInstruction,
} from "@/api/types";
import { SignaturePad, type SignaturePadHandle } from "@/components/SignaturePad";

function fmtDate(d: string | null): string {
  if (!d) return "—";
  const parsed = new Date(d);
  return Number.isNaN(parsed.getTime()) ? d : parsed.toLocaleDateString("de-DE");
}

const INSTRUCTION_KEYS: VollmachtVoteInstruction[] = ["JA", "NEIN", "ENTHALTUNG"];

export function VollmachtCard({
  assemblyId,
  agendaItems = [],
}: {
  assemblyId: string;
  agendaItems?: AgendaItemResponse[];
}) {
  const { t } = useTranslation();
  const [vollmacht, setVollmacht] = useState<VollmachtResponse | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [proxyName, setProxyName] = useState("");
  const [scopeNote, setScopeNote] = useState("");
  // Per-TOP Weisungen — owner request: bind the proxy item by item instead of
  // only via free text. Unset = proxy votes freely on that TOP.
  const [instructions, setInstructions] = useState<
    Record<string, VollmachtVoteInstruction | undefined>
  >({});
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

  const votableItems = agendaItems.filter((i) => i.type === "BESCHLUSS");

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
      const chosen = votableItems
        .filter((i) => instructions[i.id])
        .map((i) => ({ agenda_item_id: i.id, instruction: instructions[i.id] }));
      if (chosen.length > 0) fd.append("voting_instructions", JSON.stringify(chosen));
      if (blob) fd.append("signature", blob, "signature.png");
      const r = await api.post<VollmachtResponse>(
        `/me/assemblies/${assemblyId}/vollmacht`,
        fd,
      );
      setVollmacht(r.data);
      setDialogOpen(false);
      setProxyName("");
      setScopeNote("");
      setInstructions({});
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
    // Anchor + download (the pattern every other download here uses) —
    // window.open() AFTER an await is killed by iOS Safari's popup blocker,
    // which is why "PDF herunterladen" silently did nothing on iPhone
    // (owner feedback 07/2026; the request itself returned 200 each time).
    const url = URL.createObjectURL(r.data as Blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `Vollmacht-${vollmacht.proxy_name || "WHV"}.pdf`.replace(/[/\\?%*:|"<>]/g, "-");
    document.body.appendChild(a);
    a.click();
    a.remove();
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
            {vollmacht.voting_instructions?.length > 0 && (
              <Box>
                <Typography variant="caption" color="text.secondary">
                  {t("vollmacht.perTopTitle")}
                </Typography>
                <Stack spacing={0.25} sx={{ mt: 0.5 }}>
                  {vollmacht.voting_instructions.map((i) => (
                    <Typography key={i.agenda_item_id} variant="caption">
                      <strong>TOP {i.position}</strong> {i.title} —{" "}
                      {t(`vollmacht.vote.${i.instruction}`)}
                    </Typography>
                  ))}
                </Stack>
              </Box>
            )}
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
            {votableItems.length > 0 && (
              <Box>
                <Typography variant="subtitle2">{t("vollmacht.perTopTitle")}</Typography>
                <Typography variant="caption" color="text.secondary">
                  {t("vollmacht.perTopHint")}
                </Typography>
                <Stack spacing={1.5} sx={{ mt: 1.5 }}>
                  {votableItems.map((item) => (
                    <Box key={item.id}>
                      <Typography variant="body2" sx={{ mb: 0.5 }}>
                        <strong>TOP {item.position}</strong> {item.title}
                      </Typography>
                      <ToggleButtonGroup
                        exclusive
                        size="small"
                        value={instructions[item.id] ?? null}
                        onChange={(_, v) =>
                          setInstructions((prev) => ({
                            ...prev,
                            [item.id]: (v as VollmachtVoteInstruction | null) ?? undefined,
                          }))
                        }
                        sx={{ flexWrap: "wrap" }}
                      >
                        {INSTRUCTION_KEYS.map((key) => (
                          <ToggleButton key={key} value={key}>
                            {t(`vollmacht.vote.${key}`)}
                          </ToggleButton>
                        ))}
                      </ToggleButtonGroup>
                    </Box>
                  ))}
                </Stack>
              </Box>
            )}
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
