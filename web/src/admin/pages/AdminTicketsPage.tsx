import { useCallback, useEffect, useState, type MouseEvent } from "react";
import { Link as RouterLink, useNavigate, useSearchParams } from "react-router-dom";
import {
  Alert,
  Box,
  Card,
  CardActionArea,
  CardContent,
  Chip,
  FormControl,
  InputLabel,
  Link,
  ListSubheader,
  MenuItem,
  Select,
  Stack,
  Typography,
} from "@mui/material";
import { useTranslation } from "react-i18next";
import { api } from "@/api/client";
import {
  TICKET_CATEGORY_LABELS,
  TICKET_STATUS_LABELS,
  type TicketCategory,
  type TicketResponse,
  type TicketStatus,
} from "@/api/types";
import { groupedCategories } from "@/lib/ticketCategories";

const STATUSES: TicketStatus[] = [
  "NEU",
  "OFFEN",
  "WARTET_AUF_KUNDE",
  "GESCHLOSSEN",
];

function StatusChip({ status }: { status: TicketStatus }) {
  const color: "success" | "warning" | "default" | "info" =
    status === "GESCHLOSSEN"
      ? "default"
      : status === "WARTET_AUF_KUNDE"
        ? "warning"
        : status === "NEU"
          ? "info"
          : "success";
  return (
    <Chip
      size="small"
      label={TICKET_STATUS_LABELS[status]}
      color={color}
      variant={status === "GESCHLOSSEN" ? "outlined" : "filled"}
    />
  );
}

// 6-char tag = the LAST six hex chars of the UUID — the same "[#xxxxxx]" the
// e-mail subject carries, so a Verwalter can find a ticket by the tag an
// owner quotes. (UUIDv7 prefixes are timestamps and look alike; the tail is random.)
function shortId(id: string): string {
  return id.replace(/-/g, "").slice(-6);
}

interface TileProps {
  ticket: TicketResponse;
}

function TicketTile({ ticket }: TileProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();

  // Sub-link clicks navigate to contact/property pages instead of opening
  // the ticket. The CardActionArea wraps the whole card, so we have to
  // stopPropagation on the sub-link and route manually.
  const goto = (e: MouseEvent, path: string) => {
    e.preventDefault();
    e.stopPropagation();
    navigate(path);
  };

  const contactLabel =
    ticket.creator_contact_label ??
    ticket.creator_email ??
    ticket.external_sender_email ??
    "—";

  return (
    <Card variant="outlined">
      <CardActionArea
        component={RouterLink}
        to={`/admin/tickets/${ticket.id}`}
        sx={{ display: "block" }}
      >
        <CardContent>
          <Stack
            direction="row"
            sx={{
              justifyContent: "space-between",
              alignItems: "baseline",
              mb: 1,
              gap: 1,
              flexWrap: "wrap",
            }}
          >
            <StatusChip status={ticket.status} />
            <Typography variant="caption" color="text.secondary">
              {new Date(ticket.last_message_at).toLocaleString("de-DE", {
                day: "2-digit",
                month: "2-digit",
                year: "numeric",
                hour: "2-digit",
                minute: "2-digit",
              })}
            </Typography>
          </Stack>

          <Typography
            variant="h6"
            sx={{
              fontSize: "1.05rem",
              fontWeight: 600,
              color: "primary.main",
              mb: 1.5,
            }}
          >
            {ticket.subject}
            <Typography
              component="span"
              variant="body2"
              color="text.secondary"
              sx={{ ml: 1, fontWeight: 400 }}
            >
              (#{shortId(ticket.id)})
            </Typography>
          </Typography>

          <Box
            sx={{
              display: "grid",
              gridTemplateColumns: "auto 1fr",
              columnGap: 1.5,
              rowGap: 0.5,
              alignItems: "baseline",
              fontSize: "0.875rem",
            }}
          >
            <Typography variant="body2" color="text.secondary">
              {t("admin.ticketTile.contact")}
            </Typography>
            <Box>
              {ticket.creator_contact_id_impower != null &&
              ticket.creator_contact_label ? (
                <Link
                  href={`/admin/contacts`}
                  onClick={(e: MouseEvent) =>
                    goto(e, `/admin/contacts`)
                  }
                  underline="hover"
                  color="primary"
                >
                  {ticket.creator_contact_label}
                </Link>
              ) : (
                <Typography variant="body2">{contactLabel}</Typography>
              )}
            </Box>

            <Typography variant="body2" color="text.secondary">
              {t("admin.ticketTile.property")}
            </Typography>
            <Box>
              {ticket.property_id && ticket.property_name ? (
                <Link
                  href={`/admin/properties/${ticket.property_id}`}
                  onClick={(e: MouseEvent) =>
                    goto(e, `/admin/properties/${ticket.property_id}`)
                  }
                  underline="hover"
                  color="primary"
                >
                  {ticket.property_name}
                  {ticket.property_address && `, ${ticket.property_address}`}
                </Link>
              ) : (
                <Typography variant="body2">—</Typography>
              )}
            </Box>
          </Box>

          <Box sx={{ mt: 1 }}>
            <Typography variant="caption" color="text.secondary">
              {TICKET_CATEGORY_LABELS[ticket.category]}
            </Typography>
          </Box>
        </CardContent>
      </CardActionArea>
    </Card>
  );
}

interface AdminTicketsPageProps {
  // Pre-applied property filter for the property-detail Tickets tab. When
  // provided, the page hides its own status/category strips? No — we
  // still surface filters, the property filter is implicit.
  filterPropertyId?: string;
  // Whether to render the H1 + filter chips. The property-detail embed
  // hides them; the standalone /admin/tickets page shows them.
  showHeader?: boolean;
}

export function AdminTicketsPage({
  filterPropertyId,
  showHeader = true,
}: AdminTicketsPageProps = {}) {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const statusFilter = (params.get("status") ?? "") as "" | TicketStatus;
  const categoryFilter = (params.get("category") ?? "") as "" | TicketCategory;
  const [rows, setRows] = useState<TicketResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    setRows(null);
    const qs = new URLSearchParams();
    if (statusFilter) qs.set("status", statusFilter);
    if (categoryFilter) qs.set("category", categoryFilter);
    if (filterPropertyId) qs.set("property_id", filterPropertyId);
    const url =
      qs.toString().length > 0
        ? `/admin/tickets?${qs.toString()}`
        : "/admin/tickets";
    try {
      const r = await api.get<TicketResponse[]>(url);
      setRows(r.data);
    } catch {
      setError(t("admin.ticketsPage.loadFailed"));
    }
  }, [statusFilter, categoryFilter, filterPropertyId, t]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const setStatus = (next: "" | TicketStatus) => {
    const p = new URLSearchParams(params);
    if (next) p.set("status", next);
    else p.delete("status");
    setParams(p);
  };
  const setCategory = (next: "" | TicketCategory) => {
    const p = new URLSearchParams(params);
    if (next) p.set("category", next);
    else p.delete("category");
    setParams(p);
  };

  return (
    <Stack spacing={3}>
      {showHeader && (
        <Typography variant="h4" component="h1">
          {t("admin.ticketsPage.title")}
        </Typography>
      )}

      {showHeader && (
        <Stack spacing={1}>
          <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", gap: 1 }}>
            <Typography
              variant="caption"
              color="text.secondary"
              sx={{ alignSelf: "center", mr: 1 }}
            >
              {t("admin.ticketsPage.status")}:
            </Typography>
            <Chip
              label={t("admin.ticketsPage.filterAll")}
              color={!statusFilter ? "primary" : "default"}
              variant={!statusFilter ? "filled" : "outlined"}
              onClick={() => setStatus("")}
              clickable
            />
            {STATUSES.map((s) => (
              <Chip
                key={s}
                label={TICKET_STATUS_LABELS[s]}
                color={statusFilter === s ? "primary" : "default"}
                variant={statusFilter === s ? "filled" : "outlined"}
                onClick={() => setStatus(s)}
                clickable
              />
            ))}
          </Stack>
          {/* 32 categories → too many chips. Drop into a grouped Select
              and keep the same query-param contract (?category=…). */}
          <FormControl size="small" sx={{ minWidth: 280, maxWidth: 400 }}>
            <InputLabel>{t("admin.ticketsPage.category")}</InputLabel>
            <Select
              value={categoryFilter}
              label={t("admin.ticketsPage.category")}
              onChange={(e) =>
                setCategory(e.target.value as "" | TicketCategory)
              }
            >
              <MenuItem value="">
                <em>{t("admin.ticketsPage.filterAll")}</em>
              </MenuItem>
              {groupedCategories().flatMap(({ group, items }) => [
                <ListSubheader key={`g-${group}`}>{group}</ListSubheader>,
                ...items.map((c) => (
                  <MenuItem key={c} value={c} sx={{ pl: 4 }}>
                    {TICKET_CATEGORY_LABELS[c]}
                  </MenuItem>
                )),
              ])}
            </Select>
          </FormControl>
        </Stack>
      )}

      {error && <Alert severity="error">{error}</Alert>}

      {rows === null ? (
        <Typography variant="body2" color="text.secondary">
          {t("common.loading")}
        </Typography>
      ) : rows.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          {t("admin.ticketsPage.empty")}
        </Typography>
      ) : (
        <Stack spacing={1.5}>
          {rows.map((r) => (
            <TicketTile key={r.id} ticket={r} />
          ))}
        </Stack>
      )}
    </Stack>
  );
}
