import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  MenuItem,
  Stack,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";
import { useTranslation } from "react-i18next";
import { api } from "@/api/client";
import { PropertyInvitesTab } from "@/admin/components/PropertyInvitesTab";
import type {
  AdminContactSearchResult,
  AdminInviteResponse,
  AdminPropertySearchResult,
  CreateInviteRequest,
  UserRole,
} from "@/api/types";

const ROLES: UserRole[] = [
  "verwalter",
  "beirat",
  "eigentuemer",
  "mieter",
  "dienstleister",
];

// Debounce helper — keeps the autocomplete server requests in check without
// pulling in lodash. 250 ms feels snappy without spamming.
function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
     
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

function formatPropertyOption(p: AdminPropertySearchResult): string {
  const tail = [p.property_hr_id, p.city, p.street].filter(Boolean).join(" · ");
  return tail ? `${p.name} — ${tail}` : p.name;
}

export function AdminInviteNewPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  // --- Property picker -------------------------------------------------------
  const [propertyQ, setPropertyQ] = useState("");
  const debouncedPropertyQ = useDebounced(propertyQ, 250);
  const [propertyOptions, setPropertyOptions] = useState<
    AdminPropertySearchResult[]
  >([]);
  // "single" = one contact via the picker (original flow); "property" =
  // the whole Objekt via the bulk tab (same component as Stammdaten →
  // Objekt → Einladungen, so there is exactly one bulk implementation).
  const [mode, setMode] = useState<"single" | "property">("single");
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
        params: { q: debouncedPropertyQ },
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
  }, [debouncedPropertyQ]);

  // --- Contact picker (scoped to picked property) ---------------------------
  const [contactQ, setContactQ] = useState("");
  const debouncedContactQ = useDebounced(contactQ, 250);
  const [contactOptions, setContactOptions] = useState<
    AdminContactSearchResult[]
  >([]);
  const [contact, setContact] = useState<AdminContactSearchResult | null>(null);
  const [contactLoading, setContactLoading] = useState(false);

  useEffect(() => {
    if (!property) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setContactOptions([]);
      setContact(null);
      return;
    }
    let cancelled = false;
     
    setContactLoading(true);
    api
      .get<AdminContactSearchResult[]>(
        `/admin/properties/${property.id}/contacts/search`,
        { params: { q: debouncedContactQ } },
      )
      .then((r) => {
        if (!cancelled) setContactOptions(r.data);
      })
      .catch(() => {
        if (!cancelled) setContactOptions([]);
      })
      .finally(() => {
        if (!cancelled) setContactLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [property, debouncedContactQ]);

  // --- Form state ------------------------------------------------------------
  const [email, setEmail] = useState("");
  const [emailTouched, setEmailTouched] = useState(false);
  const [role, setRole] = useState<UserRole>("eigentuemer");
  const [ttlDays, setTtlDays] = useState(14);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // When the picked contact has an email and the user hasn't typed one yet,
  // auto-fill. This matches the Jinja form's behaviour.
  useEffect(() => {
    if (!contact) return;
    if (emailTouched) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setEmail(contact.email ?? "");
  }, [contact, emailTouched]);

  const emailHint = useMemo(() => {
    if (!contact) return t("admin.inviteNew.emailHint");
    if (contact.email) return t("admin.inviteNew.emailFromImpower");
    return t("admin.inviteNew.emailNoImpower");
  }, [contact, t]);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const body: CreateInviteRequest = {
        email: email.trim().toLowerCase(),
        role,
        ttl_days: ttlDays,
        contact_id_impower: contact?.impower_id ?? null,
      };
      const res = await api.post<AdminInviteResponse>("/admin/invites", body);
      navigate(`/admin/invites?status=pending&created=${res.data.code}`);
    } catch (err: unknown) {
      const detail = (
        err as { response?: { data?: { detail?: string } } }
      ).response?.data?.detail;
      setError(detail ?? t("admin.inviteNew.createFailed"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Stack spacing={3} sx={{ maxWidth: 600 }}>
      <Box>
        <Typography variant="h4" component="h1" gutterBottom>
          {t("admin.inviteNew.title")}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {t("admin.inviteNew.subtitle")}
        </Typography>
      </Box>

      {error && <Alert severity="error">{error}</Alert>}

      <Box component="form" onSubmit={onSubmit}>
        <Stack spacing={2.5}>
          <Box>
            <Typography variant="subtitle2" gutterBottom>
              {t("admin.inviteNew.linkSection")}
            </Typography>
            <Typography
              variant="caption"
              color="text.secondary"
              sx={{ display: "block", mb: 1.5 }}
            >
              {t("admin.inviteNew.linkHint")}
            </Typography>
            <Stack spacing={2}>
              <Autocomplete<AdminPropertySearchResult>
                value={property}
                onChange={(_, v) => {
                  setProperty(v);
                  setContact(null);
                  setContactQ("");
                }}
                inputValue={propertyQ}
                onInputChange={(_, v) => setPropertyQ(v)}
                options={propertyOptions}
                getOptionLabel={formatPropertyOption}
                isOptionEqualToValue={(a, b) => a.id === b.id}
                filterOptions={(x) => x}
                loading={propertyLoading}
                loadingText={t("common.loading")}
                renderInput={(p) => (
                  <TextField
                    {...p}
                    label={t("admin.inviteNew.property")}
                    placeholder={t("admin.inviteNew.propertyPlaceholder")}
                  />
                )}
              />

              {property && (
                <ToggleButtonGroup
                  size="small"
                  exclusive
                  value={mode}
                  onChange={(_, v: "single" | "property" | null) => {
                    if (v) setMode(v);
                  }}
                  aria-label={t("admin.inviteNew.modeLabel")}
                >
                  <ToggleButton value="single">
                    {t("admin.inviteNew.modeSingle")}
                  </ToggleButton>
                  <ToggleButton value="property">
                    {t("admin.inviteNew.modeProperty")}
                  </ToggleButton>
                </ToggleButtonGroup>
              )}

              {property && mode === "property" && (
                <Box sx={{ mt: 1 }}>
                  <Typography
                    variant="caption"
                    color="text.secondary"
                    sx={{ display: "block", mb: 1 }}
                  >
                    {t("admin.inviteNew.modePropertyHint")}
                  </Typography>
                  <PropertyInvitesTab propertyId={property.id} />
                </Box>
              )}

              {mode === "single" && (
              <Autocomplete<AdminContactSearchResult>
                value={contact}
                onChange={(_, v) => setContact(v)}
                inputValue={contactQ}
                onInputChange={(_, v) => setContactQ(v)}
                options={contactOptions}
                getOptionLabel={(c) => c.label}
                isOptionEqualToValue={(a, b) => a.impower_id === b.impower_id}
                filterOptions={(x) => x}
                disabled={!property}
                loading={contactLoading}
                loadingText={t("common.loading")}
                renderInput={(p) => (
                  <TextField
                    {...p}
                    label={t("admin.inviteNew.contact")}
                    placeholder={
                      property
                        ? t("admin.inviteNew.contactPlaceholder")
                        : t("admin.inviteNew.contactRequiresProperty")
                    }
                  />
                )}
                renderOption={(props, opt) => {
                  const { key, ...rest } = props as typeof props & {
                    key: string;
                  };
                  return (
                    <li key={key} {...rest}>
                      <Stack>
                        <Typography variant="body2">{opt.label}</Typography>
                        {opt.email && (
                          <Typography
                            variant="caption"
                            color="text.secondary"
                          >
                            {opt.email} · #{opt.impower_id}
                          </Typography>
                        )}
                      </Stack>
                    </li>
                  );
                }}
              />
              )}
            </Stack>
          </Box>

          {mode === "single" && (
          <>
          <TextField
            label={t("admin.inviteNew.email")}
            type="email"
            required
            value={email}
            onChange={(e) => {
              setEmail(e.target.value);
              setEmailTouched(true);
            }}
            helperText={emailHint}
            fullWidth
          />

          <TextField
            label={t("admin.inviteNew.role")}
            select
            required
            value={role}
            onChange={(e) => setRole(e.target.value as UserRole)}
            fullWidth
          >
            {ROLES.map((r) => (
              <MenuItem key={r} value={r}>
                {r}
              </MenuItem>
            ))}
          </TextField>

          <TextField
            label={t("admin.inviteNew.ttlDays")}
            type="number"
            required
            value={ttlDays}
            onChange={(e) =>
              setTtlDays(Math.max(1, Math.min(90, Number(e.target.value) || 14)))
            }
            slotProps={{ htmlInput: { min: 1, max: 90 } }}
            fullWidth
          />

          <Stack direction="row" spacing={2}>
            <Button
              type="submit"
              variant="contained"
              size="large"
              disabled={submitting || !email}
            >
              {submitting ? t("common.loading") : t("admin.inviteNew.submit")}
            </Button>
            <Button
              variant="outlined"
              size="large"
              onClick={() => navigate("/admin/invites")}
            >
              {t("common.cancel")}
            </Button>
          </Stack>
          </>
          )}
        </Stack>
      </Box>
    </Stack>
  );
}
