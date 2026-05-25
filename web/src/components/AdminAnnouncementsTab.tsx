/**
 * Per-property Mitteilungen list for the admin SPA.
 *
 * Mounts as a tab on /admin/properties/:id alongside Übersicht /
 * Tickets / Dokumente / Firmen. Compose lives in a modal dialog
 * (right column on the list page) — keeps the admin on the list
 * while drafting, since they'll often publish-now or edit during
 * the 10-min buffer and don't need a separate page round-trip.
 *
 * Detail + comment moderation live on /admin/announcements/:id —
 * each row is a clickable link.
 */

import { useCallback, useEffect, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  FormGroup,
  Paper,
  Stack,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import AttachFileIcon from "@mui/icons-material/AttachFile";
import { useTranslation } from "react-i18next";
import { api } from "@/api/client";
import type {
  AdminUnitListItem,
  AnnouncementCreateRequest,
  AnnouncementResponse,
} from "@/api/types";

interface Props {
  propertyId: string;
}

interface StatusBadgeProps {
  row: AnnouncementResponse;
}

function StatusBadge({ row }: StatusBadgeProps) {
  const { t } = useTranslation();
  // Anchor "now" to component mount so the countdown is stable across
  // re-renders of the same list row. Stale by the time the user
  // refreshes the list — acceptable for a chip; not worth a live tick.
  const [mountedAt] = useState(() => Date.now());

  if (row.notification_sent_at) {
    return (
      <Chip
        size="small"
        color="success"
        variant="filled"
        label={t("admin.announcementsTab.statusPublished")}
      />
    );
  }
  const due = new Date(row.scheduled_publish_at).getTime();
  const minutes = Math.max(0, Math.round((due - mountedAt) / 60000));
  const label =
    minutes <= 0
      ? t("admin.announcementsTab.statusImminent")
      : t("admin.announcementsTab.statusInMinutes", { count: minutes });
  return <Chip size="small" color="warning" variant="outlined" label={label} />;
}

// --- Compose dialog --------------------------------------------------------

interface ComposeDialogProps {
  propertyId: string;
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

function ComposeDialog({
  propertyId,
  open,
  onClose,
  onCreated,
}: ComposeDialogProps) {
  const { t } = useTranslation();
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [audEigentuemer, setAudEigentuemer] = useState(true);
  const [audMieter, setAudMieter] = useState(true);
  const [audBeirat, setAudBeirat] = useState(true);
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Per-unit targeting — empty list = property-wide-by-role
  // (default). Picker stays hidden behind the Autocomplete so the
  // admin only sees a "narrowing" affordance when they want one.
  const [units, setUnits] = useState<AdminUnitListItem[]>([]);
  const [selectedUnits, setSelectedUnits] = useState<AdminUnitListItem[]>([]);

  // Load this property's units once when the dialog opens. Filter
  // server-side would be cleaner but /admin/units returns the whole
  // org and we just narrow client-side — fine at v1 scale.
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    void (async () => {
      try {
        const r = await api.get<AdminUnitListItem[]>("/admin/units");
        if (cancelled) return;
        setUnits(r.data.filter((u) => u.property_id === propertyId));
      } catch {
        // Picker stays empty — the admin can still send property-wide.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, propertyId]);

  const reset = () => {
    setTitle("");
    setBody("");
    setAudEigentuemer(true);
    setAudMieter(true);
    setAudBeirat(true);
    setFiles([]);
    setSelectedUnits([]);
    setError(null);
  };

  const handleClose = () => {
    if (busy) return;
    reset();
    onClose();
  };

  const submit = async () => {
    setError(null);
    if (!title.trim()) {
      setError(t("admin.announcementsTab.composeTitleRequired"));
      return;
    }
    if (!(audEigentuemer || audMieter || audBeirat)) {
      setError(t("admin.announcementsTab.composeAudienceRequired"));
      return;
    }
    setBusy(true);
    try {
      const payload: AnnouncementCreateRequest = {
        title: title.trim(),
        body: body,
        audience_eigentuemer: audEigentuemer,
        audience_mieter: audMieter,
        audience_beirat: audBeirat,
        unit_ids: selectedUnits.map((u) => u.id),
      };
      const r = await api.post<AnnouncementResponse>(
        `/admin/properties/${propertyId}/announcements`,
        payload,
      );
      // Upload attachments serially against the new row. Failures here
      // don't roll back the announcement — admin can re-upload from
      // the detail page.
      for (const f of files) {
        const form = new FormData();
        form.append("file", f);
        try {
          await api.post(
            `/admin/announcements/${r.data.id}/attachments`,
            form,
          );
        } catch {
          // Surface but don't abort — partial success is recoverable.
          setError(t("admin.announcementsTab.attachmentFailed", { name: f.name }));
        }
      }
      reset();
      onCreated();
      onClose();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })
        .response?.data?.detail;
      setError(detail ?? t("admin.announcementsTab.composeFailed"));
    } finally {
      setBusy(false);
    }
  };

  const onPickFiles = (e: React.ChangeEvent<HTMLInputElement>) => {
    const picked = e.target.files ? Array.from(e.target.files) : [];
    setFiles((prev) => [...prev, ...picked]);
    // Reset so picking the same file twice fires onChange.
    e.target.value = "";
  };

  const removeFile = (idx: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== idx));
  };

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth>
      <DialogTitle>{t("admin.announcementsTab.composeTitle")}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField
            label={t("admin.announcementsTab.fieldTitle")}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            fullWidth
            autoFocus
            required
          />
          <TextField
            label={t("admin.announcementsTab.fieldBody")}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            fullWidth
            multiline
            minRows={4}
            maxRows={12}
          />
          <Box>
            <Typography variant="body2" color="text.secondary" gutterBottom>
              {t("admin.announcementsTab.audienceLabel")}
            </Typography>
            <FormGroup row>
              <FormControlLabel
                control={
                  <Switch
                    checked={audEigentuemer}
                    onChange={(e) => setAudEigentuemer(e.target.checked)}
                  />
                }
                label={t("admin.announcementsTab.audienceEigentuemer")}
              />
              <FormControlLabel
                control={
                  <Switch
                    checked={audMieter}
                    onChange={(e) => setAudMieter(e.target.checked)}
                  />
                }
                label={t("admin.announcementsTab.audienceMieter")}
              />
              <FormControlLabel
                control={
                  <Switch
                    checked={audBeirat}
                    onChange={(e) => setAudBeirat(e.target.checked)}
                  />
                }
                label={t("admin.announcementsTab.audienceBeirat")}
              />
            </FormGroup>
          </Box>

          <Autocomplete
            multiple
            options={units}
            value={selectedUnits}
            onChange={(_, next) => setSelectedUnits(next)}
            getOptionLabel={(o) =>
              o.unit_hr_id ?? `${o.type} · ${o.floor ?? "—"}`
            }
            isOptionEqualToValue={(a, b) => a.id === b.id}
            renderInput={(params) => (
              <TextField
                {...params}
                label={t("admin.announcementsTab.unitsLabel")}
                placeholder={t("admin.announcementsTab.unitsPlaceholder")}
                helperText={t("admin.announcementsTab.unitsHelper")}
              />
            )}
          />

          <Box>
            <Button
              component="label"
              variant="outlined"
              size="small"
              startIcon={<AttachFileIcon />}
            >
              {t("admin.announcementsTab.addAttachments")}
              <input
                type="file"
                multiple
                hidden
                onChange={onPickFiles}
              />
            </Button>
            {files.length > 0 && (
              <Stack direction="row" spacing={1} sx={{ mt: 1, flexWrap: "wrap" }}>
                {files.map((f, idx) => (
                  <Chip
                    key={`${f.name}-${idx}`}
                    label={`${f.name} (${Math.round(f.size / 1024)} KB)`}
                    onDelete={() => removeFile(idx)}
                    size="small"
                  />
                ))}
              </Stack>
            )}
          </Box>

          <Alert severity="info" variant="outlined">
            {t("admin.announcementsTab.delayHint")}
          </Alert>

          {error && <Alert severity="error">{error}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose} disabled={busy}>
          {t("common.cancel")}
        </Button>
        <Button onClick={submit} variant="contained" disabled={busy}>
          {busy ? t("common.loading") : t("admin.announcementsTab.submit")}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

// --- Main tab content ------------------------------------------------------

export function AdminAnnouncementsTab({ propertyId }: Props) {
  const { t } = useTranslation();
  const [rows, setRows] = useState<AnnouncementResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [composeOpen, setComposeOpen] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      const r = await api.get<AnnouncementResponse[]>(
        `/admin/properties/${propertyId}/announcements`,
      );
      setRows(r.data);
    } catch {
      setError(t("admin.announcementsTab.loadFailed"));
    }
  }, [propertyId, t]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  return (
    <Stack spacing={2}>
      <Box
        sx={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: 1,
        }}
      >
        <Typography variant="h6">
          {t("admin.announcementsTab.title")}
        </Typography>
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          onClick={() => setComposeOpen(true)}
        >
          {t("admin.announcementsTab.newButton")}
        </Button>
      </Box>

      {error && <Alert severity="error">{error}</Alert>}

      {rows === null ? (
        <Typography variant="body2" color="text.secondary">
          {t("common.loading")}
        </Typography>
      ) : rows.length === 0 ? (
        <Paper variant="outlined" sx={{ p: 3, textAlign: "center" }}>
          <Typography variant="body2" color="text.secondary">
            {t("admin.announcementsTab.empty")}
          </Typography>
        </Paper>
      ) : (
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>{t("admin.announcementsTab.colStatus")}</TableCell>
                <TableCell>{t("admin.announcementsTab.colTitle")}</TableCell>
                <TableCell>{t("admin.announcementsTab.colAudience")}</TableCell>
                <TableCell>{t("admin.announcementsTab.colAttachments")}</TableCell>
                <TableCell>{t("admin.announcementsTab.colComments")}</TableCell>
                <TableCell>{t("admin.announcementsTab.colDate")}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((r) => (
                <TableRow
                  key={r.id}
                  hover
                  component={RouterLink}
                  to={`/admin/announcements/${r.id}`}
                  sx={{
                    textDecoration: "none",
                    cursor: "pointer",
                    "& td": { color: "text.primary" },
                  }}
                >
                  <TableCell>
                    <StatusBadge row={r} />
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2" sx={{ fontWeight: 500 }}>
                      {r.title}
                    </Typography>
                    {r.is_edited && (
                      <Typography
                        variant="caption"
                        color="text.secondary"
                        sx={{ display: "block" }}
                      >
                        {t("admin.announcementsTab.edited")}
                      </Typography>
                    )}
                  </TableCell>
                  <TableCell>
                    <Stack
                      direction="row"
                      spacing={0.5}
                      sx={{ flexWrap: "wrap", gap: 0.5 }}
                    >
                      {r.audience_eigentuemer && (
                        <Chip size="small" variant="outlined" label="Eig." />
                      )}
                      {r.audience_mieter && (
                        <Chip size="small" variant="outlined" label="Mieter" />
                      )}
                      {r.audience_beirat && (
                        <Chip size="small" variant="outlined" label="Beirat" />
                      )}
                      {r.unit_ids.length > 0 && (
                        <Chip
                          size="small"
                          color="info"
                          variant="filled"
                          label={t("admin.announcementsTab.unitsChip", {
                            count: r.unit_ids.length,
                          })}
                        />
                      )}
                    </Stack>
                  </TableCell>
                  <TableCell>{r.attachment_count}</TableCell>
                  <TableCell>{r.comment_count}</TableCell>
                  <TableCell>
                    <Typography variant="caption" color="text.secondary">
                      {new Date(
                        r.notification_sent_at ?? r.scheduled_publish_at,
                      ).toLocaleDateString("de-DE")}
                    </Typography>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      <ComposeDialog
        propertyId={propertyId}
        open={composeOpen}
        onClose={() => setComposeOpen(false)}
        onCreated={() => void load()}
      />
    </Stack>
  );
}

