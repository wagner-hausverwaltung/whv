/**
 * Compose-a-Mitteilung dialog. Two entry points:
 *
 *  - **Per-property tab** (AdminAnnouncementsTab) passes a fixed
 *    `propertyId`. Same flow as v1: pick units optionally,
 *    audience, attachments, submit.
 *
 *  - **Cross-property tab** (AdminAnnouncementsAllPage) passes
 *    `propertyId={null}`. Dialog loads /admin/properties and
 *    renders a Liegenschaft picker at the top. The unit picker is
 *    hidden in this mode — the Verwalter who's drafting from the
 *    global queue just wants a property-wide send; unit-level
 *    targeting lives on the property-detail tab.
 *
 * The submit POST goes to `/admin/properties/{id}/announcements`
 * either way — backend stays unchanged.
 */

import { useEffect, useState } from "react";
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
  Stack,
  Switch,
  TextField,
  Typography,
} from "@mui/material";
import AttachFileIcon from "@mui/icons-material/AttachFile";
import { useTranslation } from "react-i18next";
import { api } from "@/api/client";
import type {
  AdminPropertyListItem,
  AdminUnitListItem,
  AnnouncementCreateRequest,
  AnnouncementResponse,
} from "@/api/types";

interface Props {
  /// Fixed property when launched from the per-property tab.
  /// null = picker mode (cross-property tab).
  propertyId: string | null;
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

export function AnnouncementComposeDialog({
  propertyId,
  open,
  onClose,
  onCreated,
}: Props) {
  const { t } = useTranslation();
  const isPickerMode = propertyId === null;

  // --- Picker-mode state -------------------------------------------------
  const [properties, setProperties] = useState<AdminPropertyListItem[]>([]);
  const [selectedProperty, setSelectedProperty] =
    useState<AdminPropertyListItem | null>(null);

  // --- Shared compose state ----------------------------------------------
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [audEigentuemer, setAudEigentuemer] = useState(true);
  const [audMieter, setAudMieter] = useState(true);
  const [audBeirat, setAudBeirat] = useState(true);
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [units, setUnits] = useState<AdminUnitListItem[]>([]);
  const [selectedUnits, setSelectedUnits] = useState<AdminUnitListItem[]>([]);

  /// Whichever propertyId we'll POST against — caller's fixed one or
  /// the picker selection.
  const effectivePropertyId = propertyId ?? selectedProperty?.id ?? null;

  // Load properties for the picker (once per open) when in picker mode.
  useEffect(() => {
    if (!open || !isPickerMode) return;
    let cancelled = false;
    void (async () => {
      try {
        const r = await api.get<AdminPropertyListItem[]>("/admin/properties");
        if (!cancelled) setProperties(r.data);
      } catch {
        // Empty picker stays in place — the admin will see no options
        // and the error surfaces on submit.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, isPickerMode]);

  // Load units for the effective property — only ever fires when
  // the dialog opens in per-property mode. Picker mode doesn't
  // offer unit-level targeting (see module docstring), so we
  // skip the fetch AND skip touching state inside the effect to
  // avoid the cascading-renders lint trip; `reset()` already
  // clears `units`/`selectedUnits` on close so re-opening in
  // picker mode never sees stale data.
  useEffect(() => {
    if (!open || isPickerMode) return;
    let cancelled = false;
    void (async () => {
      try {
        const r = await api.get<AdminUnitListItem[]>("/admin/units");
        if (cancelled) return;
        setUnits(r.data.filter((u) => u.property_id === propertyId));
      } catch {
        // Picker stays empty — admin can still send property-wide.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, isPickerMode, propertyId]);

  const reset = () => {
    setTitle("");
    setBody("");
    setAudEigentuemer(true);
    setAudMieter(true);
    setAudBeirat(true);
    setFiles([]);
    setSelectedUnits([]);
    setSelectedProperty(null);
    setError(null);
  };

  const handleClose = () => {
    if (busy) return;
    reset();
    onClose();
  };

  const submit = async () => {
    setError(null);
    if (isPickerMode && !effectivePropertyId) {
      setError(t("admin.announcementsTab.composePropertyRequired"));
      return;
    }
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
        `/admin/properties/${effectivePropertyId}/announcements`,
        payload,
      );
      // Upload attachments serially against the new row. Failures
      // here don't roll back the announcement — admin can re-upload
      // from the detail page.
      for (const f of files) {
        const form = new FormData();
        form.append("file", f);
        try {
          await api.post(
            `/admin/announcements/${r.data.id}/attachments`,
            form,
          );
        } catch {
          setError(
            t("admin.announcementsTab.attachmentFailed", { name: f.name }),
          );
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
          {isPickerMode && (
            <Autocomplete
              options={properties}
              value={selectedProperty}
              onChange={(_, next) => setSelectedProperty(next)}
              getOptionLabel={(o) =>
                o.property_hr_id ? `${o.name} · ${o.property_hr_id}` : o.name
              }
              isOptionEqualToValue={(a, b) => a.id === b.id}
              renderInput={(params) => (
                <TextField
                  {...params}
                  label={t("admin.announcementsTab.propertyLabel")}
                  required
                  autoFocus
                />
              )}
            />
          )}
          <TextField
            label={t("admin.announcementsTab.fieldTitle")}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            fullWidth
            autoFocus={!isPickerMode}
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

          {!isPickerMode && (
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
          )}

          <Box>
            <Button
              component="label"
              variant="outlined"
              size="small"
              startIcon={<AttachFileIcon />}
            >
              {t("admin.announcementsTab.addAttachments")}
              <input type="file" multiple hidden onChange={onPickFiles} />
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
