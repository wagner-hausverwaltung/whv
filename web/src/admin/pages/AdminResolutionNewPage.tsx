import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { useTranslation } from "react-i18next";
import { api } from "@/api/client";
import type {
  AdminPropertySearchResult,
  ResolutionDetailResponse,
  ResolutionMode,
} from "@/api/types";

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
     
    const tm = setTimeout(() => setV(value), ms);
    return () => clearTimeout(tm);
  }, [value, ms]);
  return v;
}

function formatProperty(p: AdminPropertySearchResult): string {
  const tail = [p.property_hr_id, p.city, p.street].filter(Boolean).join(" · ");
  return tail ? `${p.name} — ${tail}` : p.name;
}

// `datetime-local` posts a value without timezone. We treat it as UTC for
// the backend (matching the Jinja form's behaviour) so the round-trip stays
// predictable across hosts and operator browsers.
function localIso(dt: Date): string {
  const pad = (n: number) => `${n}`.padStart(2, "0");
  return (
    `${dt.getFullYear()}-${pad(dt.getMonth() + 1)}-${pad(dt.getDate())}` +
    `T${pad(dt.getHours())}:${pad(dt.getMinutes())}`
  );
}

function defaultDates(): { opens: string; closes: string } {
  const now = new Date();
  const closes = new Date(now);
  closes.setDate(closes.getDate() + 7);
  closes.setHours(23, 59, 0, 0);
  return { opens: localIso(now), closes: localIso(closes) };
}

export function AdminResolutionNewPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  // Property picker --------------------------------------------------------
  const [propertyQ, setPropertyQ] = useState("");
  const debouncedQ = useDebounced(propertyQ, 250);
  const [propertyOptions, setPropertyOptions] = useState<
    AdminPropertySearchResult[]
  >([]);
  const [property, setProperty] = useState<AdminPropertySearchResult | null>(
    null,
  );
  const [propertyLoading, setPropertyLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPropertyLoading(true);
    api
      .get<AdminPropertySearchResult[]>("/admin/properties/search", {
        params: { q: debouncedQ },
      })
      .then((r) => {
        if (!cancelled) setPropertyOptions(r.data);
      })
      .catch(() => {
        if (!cancelled) setPropertyOptions([]);
      })
      .finally(() => {
        if (!cancelled) setPropertyLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [debouncedQ]);

  // Form state -------------------------------------------------------------
  const initial = defaultDates();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [opensAt, setOpensAt] = useState(initial.opens);
  const [closesAt, setClosesAt] = useState(initial.closes);
  const [mode, setMode] = useState<ResolutionMode>("KLASSISCH");
  const [requiredQuorum, setRequiredQuorum] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!property) return;
    setError(null);
    setSubmitting(true);
    try {
      const body = {
        property_id: property.id,
        title: title.trim(),
        description: description.trim(),
        mode,
        opens_at: new Date(`${opensAt}Z`).toISOString(),
        closes_at: new Date(`${closesAt}Z`).toISOString(),
        required_quorum: requiredQuorum,
      };
      const res = await api.post<ResolutionDetailResponse>(
        "/admin/resolutions",
        body,
      );
      navigate(`/admin/resolutions/${res.data.id}`);
    } catch (err: unknown) {
      const detail = (
        err as { response?: { data?: { detail?: string } } }
      ).response?.data?.detail;
      setError(detail ?? t("admin.resolutionNew.createFailed"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Stack spacing={3} sx={{ maxWidth: 700 }}>
      <Box>
        <Typography variant="h4" component="h1" gutterBottom>
          {t("admin.resolutionNew.title")}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {t("admin.resolutionNew.subtitle")}
        </Typography>
      </Box>

      {error && <Alert severity="error">{error}</Alert>}

      <Box component="form" onSubmit={onSubmit}>
        <Stack spacing={2.5}>
          <Autocomplete<AdminPropertySearchResult>
            value={property}
            onChange={(_, v) => setProperty(v)}
            inputValue={propertyQ}
            onInputChange={(_, v) => setPropertyQ(v)}
            options={propertyOptions}
            getOptionLabel={formatProperty}
            isOptionEqualToValue={(a, b) => a.id === b.id}
            filterOptions={(x) => x}
            loading={propertyLoading}
            loadingText={t("common.loading")}
            renderInput={(p) => (
              <TextField
                {...p}
                label={t("admin.resolutionNew.property")}
                placeholder={t("admin.resolutionNew.propertyPlaceholder")}
                required
              />
            )}
          />

          <TextField
            label={t("admin.resolutionNew.titleField")}
            placeholder={t("admin.resolutionNew.titlePlaceholder")}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
            slotProps={{ htmlInput: { minLength: 3, maxLength: 300 } }}
            fullWidth
          />

          <TextField
            label={t("admin.resolutionNew.description")}
            placeholder={t("admin.resolutionNew.descriptionPlaceholder")}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            required
            multiline
            minRows={6}
            slotProps={{ htmlInput: { minLength: 3, maxLength: 50000 } }}
            fullWidth
          />

          <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
            <TextField
              label={t("admin.resolutionNew.opensAt")}
              type="datetime-local"
              value={opensAt}
              onChange={(e) => setOpensAt(e.target.value)}
              required
              fullWidth
              slotProps={{ inputLabel: { shrink: true } }}
            />
            <TextField
              label={t("admin.resolutionNew.closesAt")}
              type="datetime-local"
              value={closesAt}
              onChange={(e) => setClosesAt(e.target.value)}
              required
              fullWidth
              slotProps={{ inputLabel: { shrink: true } }}
            />
          </Stack>

          <TextField
            label={t("admin.resolutionNew.mode")}
            select
            value={mode}
            onChange={(e) => setMode(e.target.value as ResolutionMode)}
            required
            helperText={t("admin.resolutionNew.modeHelp")}
            fullWidth
          >
            <MenuItem value="KLASSISCH">
              {t("admin.resolutionNew.modeKlassisch")}
            </MenuItem>
            <MenuItem value="MEHRHEITS">
              {t("admin.resolutionNew.modeMehrheits")}
            </MenuItem>
          </TextField>

          <TextField
            label={t("admin.resolutionNew.quorum")}
            type="number"
            value={requiredQuorum}
            onChange={(e) =>
              setRequiredQuorum(Math.max(0, Number(e.target.value) || 0))
            }
            helperText={t("admin.resolutionNew.quorumHelp")}
            slotProps={{ htmlInput: { min: 0 } }}
            disabled={mode === "KLASSISCH"}
            fullWidth
          />

          <Stack direction="row" spacing={2}>
            <Button
              type="submit"
              variant="contained"
              size="large"
              disabled={submitting || !property || !title.trim() || !description.trim()}
            >
              {submitting ? t("common.loading") : t("admin.resolutionNew.submit")}
            </Button>
            <Button
              variant="outlined"
              size="large"
              onClick={() => navigate("/admin/resolutions")}
            >
              {t("common.cancel")}
            </Button>
          </Stack>
        </Stack>
      </Box>
    </Stack>
  );
}
