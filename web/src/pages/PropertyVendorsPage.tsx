/**
 * Property "Dienstleister" tab.
 *
 * Lists every firm (Schornsteinfeger, Elektriker, Maler …) that has
 * issued an invoice for the property, with the contactable bits and
 * a recent-invoices list. Aggregated server-side from documents
 * where kind = RECHNUNG, grouped by contact_id.
 *
 * Card layout:
 *   - Collapsed by default: name + summary stats + tap-to-call/mail.
 *   - Expand → recent invoices, each row clickable.
 *   - Click invoice → InvoiceDetailDialog with bookkeeping line items
 *     fetched from Impower's /v2/invoices/{id} on demand.
 *
 * Owners answer "who fixed the boiler last time?" without paging the
 * Verwalter. Click on an invoice to see the bookkeeping breakdown
 * (Primärenergie / Sonstige Reparaturen / …).
 */

import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  IconButton,
  Link as MuiLink,
  Paper,
  Stack,
  Typography,
} from "@mui/material";
import BusinessIcon from "@mui/icons-material/Business";
import PersonIcon from "@mui/icons-material/Person";
import PhoneIcon from "@mui/icons-material/Phone";
import EmailIcon from "@mui/icons-material/MailOutlined";
import DownloadIcon from "@mui/icons-material/Download";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import CloseIcon from "@mui/icons-material/Close";
import { useTranslation } from "react-i18next";
import { api, API_BASE_URL, getAccessToken } from "@/api/client";
import type {
  InvoiceDetailResponse,
  InvoiceLineItemResponse,
  VendorInvoiceSummary,
  VendorSummary,
} from "@/api/types";

export function PropertyVendorsPage() {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();
  const [vendors, setVendors] = useState<VendorSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Picked invoice → opens the InvoiceDetailDialog. Carries enough
  // context (propertyId + document.id + the row metadata) that the
  // dialog can render its header before the fetch returns.
  const [openInvoice, setOpenInvoice] = useState<{
    invoice: VendorInvoiceSummary;
    vendorName: string;
  } | null>(null);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    api
      .get<VendorSummary[]>(`/me/properties/${id}/vendors`)
      .then((r) => {
        if (!cancelled) setVendors(r.data);
      })
      .catch((err) => {
        if (cancelled) return;
        if (err?.response?.status === 404) {
          setError(t("properties.empty"));
        } else {
          setError(t("properties.loadFailed"));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [id, t]);

  if (error) return <Alert severity="error">{error}</Alert>;
  if (vendors === null) {
    return (
      <Typography variant="body2" color="text.secondary">
        {t("common.loading")}
      </Typography>
    );
  }

  return (
    <Stack spacing={3}>
      <Box>
        <Typography variant="h5" component="h2" sx={{ fontWeight: 700 }}>
          {t("properties.vendors.title")}
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
          {t("properties.vendors.intro")}
        </Typography>
      </Box>

      {vendors.length === 0 ? (
        <Paper variant="outlined" sx={{ p: 3 }}>
          <Typography variant="body2" color="text.secondary">
            {t("properties.vendors.empty")}
          </Typography>
        </Paper>
      ) : (
        <Stack spacing={1.5}>
          {vendors.map((v) => (
            <VendorAccordion
              key={v.contact_id}
              vendor={v}
              onInvoiceClick={(invoice) =>
                setOpenInvoice({ invoice, vendorName: v.name })
              }
            />
          ))}
        </Stack>
      )}

      {openInvoice && id && (
        // `key` per invoice id forces a fresh component mount when
        // the user opens a different invoice without closing the
        // dialog first. Internal state (detail / error) reinitialises
        // to its useState default — no setState-in-effect reset
        // needed (which the lint rule flags as a cascading-render
        // risk).
        <InvoiceDetailDialog
          key={openInvoice.invoice.id}
          open
          propertyId={id}
          invoice={openInvoice.invoice}
          vendorName={openInvoice.vendorName}
          onClose={() => setOpenInvoice(null)}
        />
      )}
    </Stack>
  );
}

/// Collapsed-by-default vendor card. Summary header (always shown)
/// + expandable body with contact-action row + recent invoices.
function VendorAccordion({
  vendor,
  onInvoiceClick,
}: {
  vendor: VendorSummary;
  onInvoiceClick: (invoice: VendorInvoiceSummary) => void;
}) {
  const { t } = useTranslation();
  return (
    <Accordion variant="outlined" disableGutters>
      <AccordionSummary
        expandIcon={<ExpandMoreIcon />}
        sx={{
          // Make the header row read as a tight summary even at
          // narrow widths: icon, name, chips wrap if needed.
          "& .MuiAccordionSummary-content": { margin: 0, py: 0.5 },
        }}
      >
        <Stack
          direction="row"
          spacing={1.5}
          sx={{ alignItems: "center", width: "100%", flexWrap: "wrap" }}
        >
          {vendor.kind === "COMPANY" ? (
            <BusinessIcon color="primary" />
          ) : (
            <PersonIcon color="primary" />
          )}
          <Typography variant="subtitle1" sx={{ fontWeight: 600, flex: 1 }}>
            {vendor.name}
          </Typography>
          <Stack
            direction="row"
            spacing={0.5}
            sx={{ flexWrap: "wrap", rowGap: 0.5 }}
          >
            {vendor.last_service_date && (
              <Chip
                size="small"
                variant="outlined"
                label={t("properties.vendors.lastService", {
                  date: formatDate(vendor.last_service_date),
                })}
              />
            )}
            <Chip
              size="small"
              variant="outlined"
              label={t("properties.vendors.invoiceCount", {
                count: vendor.invoice_count,
              })}
            />
            {vendor.total_amount != null && (
              <Chip
                size="small"
                variant="outlined"
                label={`${formatAmount(vendor.total_amount)} € (${new Date().getFullYear()})`}
              />
            )}
          </Stack>
        </Stack>
      </AccordionSummary>
      <AccordionDetails sx={{ pt: 0 }}>
        <Stack spacing={1.5}>
          {/* Contact actions — mailto / tel launchers. Lifted to
              the top of the body because they're the actionable
              thing 80 % of owners come here for. */}
          {(vendor.phone || vendor.email) && (
            <Stack
              direction="row"
              spacing={2}
              sx={{ flexWrap: "wrap", rowGap: 1 }}
            >
              {vendor.phone && (
                <MuiLink
                  href={`tel:${vendor.phone.replace(/\s+/g, "")}`}
                  underline="hover"
                  sx={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 0.5,
                  }}
                >
                  <PhoneIcon fontSize="small" />
                  {vendor.phone}
                </MuiLink>
              )}
              {vendor.email && (
                <MuiLink
                  href={`mailto:${vendor.email}`}
                  underline="hover"
                  sx={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 0.5,
                  }}
                >
                  <EmailIcon fontSize="small" />
                  {vendor.email}
                </MuiLink>
              )}
            </Stack>
          )}

          {vendor.recent_invoices.length > 0 && (
            <Box>
              <Typography
                variant="caption"
                color="text.secondary"
                sx={{
                  textTransform: "uppercase",
                  letterSpacing: 0.5,
                  display: "block",
                  mb: 0.5,
                }}
              >
                {t("properties.vendors.invoicesHeader")}
              </Typography>
              {/* Grouped by year (newest first) so old invoices sit
                  under their own heading instead of mixed into the list. */}
              {groupInvoicesByYear(vendor.recent_invoices).map((group) => (
                <Box key={group.year} sx={{ mb: 0.5 }}>
                  <Typography
                    variant="caption"
                    sx={{
                      fontWeight: 700,
                      color: "text.secondary",
                      display: "block",
                      mt: 1,
                    }}
                  >
                    {group.year || t("properties.vendors.noDate")}
                  </Typography>
                  <Stack divider={<Divider />} spacing={0}>
                    {group.items.map((inv) => (
                      <InvoiceRow
                        key={inv.id}
                        invoice={inv}
                        onClick={() => onInvoiceClick(inv)}
                      />
                    ))}
                  </Stack>
                </Box>
              ))}
            </Box>
          )}
        </Stack>
      </AccordionDetails>
    </Accordion>
  );
}

// Bucket a vendor's invoices by issued-date year, newest year first,
// undated rows last. Undated uses an empty-string key so the caller
// renders a localized "no date" heading (the label can't live here —
// this is a pure helper with no translation context). The backend
// already returns them newest-first, so order within a year is preserved.
function groupInvoicesByYear(
  invoices: VendorInvoiceSummary[],
): { year: string; items: VendorInvoiceSummary[] }[] {
  const byYear = new Map<string, VendorInvoiceSummary[]>();
  for (const inv of invoices) {
    const head = inv.issued_date?.slice(0, 4) ?? "";
    const year = /^\d{4}$/.test(head) ? head : "";
    const bucket = byYear.get(year);
    if (bucket) bucket.push(inv);
    else byYear.set(year, [inv]);
  }
  return [...byYear.entries()]
    .sort(([a], [b]) => {
      if (a === "") return 1;
      if (b === "") return -1;
      return b.localeCompare(a);
    })
    .map(([year, items]) => ({ year, items }));
}

function InvoiceRow({
  invoice,
  onClick,
}: {
  invoice: VendorInvoiceSummary;
  onClick: () => void;
}) {
  const { t } = useTranslation();
  return (
    <Stack
      direction="row"
      spacing={1}
      sx={{
        alignItems: "center",
        py: 1,
        cursor: "pointer",
        "&:hover": { bgcolor: "action.hover" },
        borderRadius: 0.5,
        px: 0.5,
      }}
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onClick();
        }
      }}
    >
      <Box sx={{ flex: 1, minWidth: 0 }}>
        <Typography variant="body2" sx={{ fontWeight: 500 }} noWrap>
          {invoice.name}
        </Typography>
        <Stack direction="row" spacing={1} sx={{ alignItems: "baseline" }}>
          {invoice.issued_date && (
            <Typography variant="caption" color="text.secondary">
              {formatDate(invoice.issued_date)}
            </Typography>
          )}
          {invoice.amount != null && (
            <Typography variant="caption" color="text.secondary">
              · {formatAmount(invoice.amount)} €
            </Typography>
          )}
        </Stack>
      </Box>
      <Typography
        variant="caption"
        color="primary"
        sx={{ textTransform: "uppercase", letterSpacing: 0.5, mr: 1 }}
      >
        {t("properties.vendors.details")}
      </Typography>
    </Stack>
  );
}

/// Dialog opened by tapping an invoice row. Loads
/// `/me/properties/{id}/invoices/{document_id}` which fetches the
/// Impower invoice on demand and returns the bookkeeping line items
/// (account name + booking text + VAT). Download button reuses the
/// existing `/me/documents/{id}/file` flow.
function InvoiceDetailDialog({
  open,
  propertyId,
  invoice,
  vendorName,
  onClose,
}: {
  open: boolean;
  propertyId: string;
  invoice: VendorInvoiceSummary;
  vendorName: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [detail, setDetail] = useState<InvoiceDetailResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);

  useEffect(() => {
    // Per-invoice key on the parent (PropertyVendorsPage) forces a
    // remount when invoice.id changes — that's where the state
    // reset lives. This effect only kicks the fetch.
    if (!open) return;
    let cancelled = false;
    void (async () => {
      try {
        const r = await api.get<InvoiceDetailResponse>(
          `/me/properties/${propertyId}/invoices/${invoice.id}`,
        );
        if (!cancelled) setDetail(r.data);
      } catch (err: unknown) {
        if (cancelled) return;
        const detailMsg = (
          err as { response?: { data?: { detail?: string } } }
        ).response?.data?.detail;
        setError(detailMsg ?? t("properties.vendors.loadFailed"));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, propertyId, invoice.id, t]);

  const downloadPdf = async () => {
    setDownloadError(null);
    setDownloading(true);
    try {
      const token = getAccessToken();
      const res = await fetch(
        `${API_BASE_URL}/me/documents/${invoice.id}/file`,
        token ? { headers: { Authorization: `Bearer ${token}` } } : undefined,
      );
      if (!res.ok) throw new Error(`${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = invoice.name + ".pdf";
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch {
      setDownloadError(t("properties.vendors.downloadFailed"));
    } finally {
      setDownloading(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle sx={{ pr: 6 }}>
        {t("properties.vendors.sectionInvoice")}
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.25 }}>
          {vendorName}
        </Typography>
        <IconButton
          onClick={onClose}
          sx={{ position: "absolute", right: 8, top: 8 }}
          aria-label={t("properties.vendors.close")}
        >
          <CloseIcon />
        </IconButton>
      </DialogTitle>
      <DialogContent dividers>
        {error && <Alert severity="error">{error}</Alert>}
        {!error && detail === null && (
          <Typography variant="body2" color="text.secondary">
            {t("properties.vendors.loading")}
          </Typography>
        )}
        {detail && <InvoiceBody detail={detail} fallback={invoice} />}
        {downloadError && (
          <Alert severity="error" sx={{ mt: 1.5 }}>
            {downloadError}
          </Alert>
        )}
      </DialogContent>
      <DialogActions>
        <MuiLink
          component="button"
          underline="hover"
          onClick={() => void downloadPdf()}
          disabled={downloading}
          sx={{
            display: "inline-flex",
            alignItems: "center",
            gap: 0.5,
            mr: "auto",
            ml: 2,
          }}
        >
          <DownloadIcon fontSize="small" />
          {downloading
            ? t("properties.vendors.loading")
            : t("properties.vendors.downloadPdf")}
        </MuiLink>
      </DialogActions>
    </Dialog>
  );
}

function InvoiceBody({
  detail,
  fallback,
}: {
  detail: InvoiceDetailResponse;
  fallback: VendorInvoiceSummary;
}) {
  const { t } = useTranslation();
  // Falls back to the row metadata when the Impower detail came
  // back without that field — keeps the header useful even on
  // partial fetches.
  const date = detail.issued_date ?? fallback.issued_date;
  const amount = detail.amount ?? fallback.amount;

  return (
    <Stack spacing={2.5}>
      <Section title={t("properties.vendors.sectionInvoice")}>
        <Row
          label={t("properties.vendors.invoiceNo")}
          value={detail.invoice_number}
        />
        <Row label={t("properties.vendors.date")} value={formatDate(date)} />
        <Row
          label={t("properties.vendors.amount")}
          value={
            amount != null ? `${formatAmount(amount)} €` : null
          }
        />
        <Stack
          direction="row"
          spacing={1}
          sx={{ alignItems: "center", flexWrap: "wrap" }}
        >
          <Typography
            variant="body2"
            color="text.secondary"
            sx={{ minWidth: 130, flexShrink: 0 }}
          >
            {t("properties.vendors.status")}
          </Typography>
          {detail.state ? (
            <Chip
              size="small"
              label={invoiceStateLabel(detail.state)}
              color={invoiceStateColor(detail.state)}
              variant="filled"
            />
          ) : (
            <Typography variant="body2">—</Typography>
          )}
          {/* Treat "BOOKED + orderRequired=true" as the strongest
              signal we have that the bill has been queued for the
              bank. Impower doesn't expose execution-time data
              (DS19 / TS01 status codes) on the public API, so this
              is the cleanest "an Bank übermittelt" indicator we
              can give the owner. */}
          {detail.state === "BOOKED" && detail.order_required && (
            <Chip
              size="small"
              label={t("properties.vendors.sentToBank")}
              color="success"
              variant="outlined"
            />
          )}
        </Stack>
        {detail.order_statement && (
          <Row
            label={t("properties.vendors.purpose")}
            value={detail.order_statement}
          />
        )}
        {detail.order_day_offset != null &&
          detail.order_required && (
            <Row
              label={t("properties.vendors.execution")}
              value={
                detail.order_day_offset === 0
                  ? t("properties.vendors.executionImmediate")
                  : t("properties.vendors.executionOffset", {
                      days: detail.order_day_offset,
                    })
              }
            />
          )}
      </Section>

      {(detail.counterpart_iban ||
        detail.counterpart_bic ||
        detail.property_iban ||
        detail.property_bic) && (
        <Section title={t("properties.vendors.sectionBank")}>
          {detail.property_iban && (
            <Row
              label={t("properties.vendors.fromIban")}
              value={detail.property_iban}
            />
          )}
          {detail.property_bic && (
            <Row
              label={t("properties.vendors.fromBic")}
              value={detail.property_bic}
            />
          )}
          {detail.counterpart_iban && (
            <Row
              label={t("properties.vendors.toIban")}
              value={detail.counterpart_iban}
            />
          )}
          {detail.counterpart_bic && (
            <Row
              label={t("properties.vendors.toBic")}
              value={detail.counterpart_bic}
            />
          )}
        </Section>
      )}

      <Section title={t("properties.vendors.sectionBookings")}>
        {detail.items.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            {t("properties.vendors.noBookings")}
          </Typography>
        ) : (
          <Stack divider={<Divider />} spacing={0}>
            {detail.items.map((item, idx) => (
              <LineItemRow key={idx} item={item} />
            ))}
          </Stack>
        )}
      </Section>

      {/* Honest note: Impower's public REST API doesn't expose the
          actual bank-order execution history (BankOrderDataDto /
          EbicsOrderMonitoringDto) per invoice. We surface what's
          available (state + orderRequired + statement); the
          "actually settled" detail can only come once Impower
          opens those endpoints or we mirror bank statements. */}
      <Typography
        variant="caption"
        color="text.secondary"
        sx={{ fontStyle: "italic" }}
      >
        {t("properties.vendors.apiNote")}
      </Typography>
    </Stack>
  );
}

/// Maps Impower's invoice-state enum to the German labels owners
/// see in the dialog header. The raw enum stays on the wire so
/// audits / future ETL can match exactly what Impower has.
function invoiceStateLabel(state: string): string {
  switch (state) {
    case "DRAFT":
      return "Entwurf";
    case "READY":
      return "Bereit";
    case "BOOKED":
      return "Gebucht";
    case "SCHEDULED":
      return "Geplant";
    case "REVERSED":
      return "Storniert";
    default:
      return state;
  }
}

function invoiceStateColor(
  state: string,
): "default" | "primary" | "success" | "warning" | "error" {
  switch (state) {
    case "DRAFT":
      return "warning";
    case "READY":
      return "primary";
    case "BOOKED":
      return "success";
    case "SCHEDULED":
      return "default";
    case "REVERSED":
      return "error";
    default:
      return "default";
  }
}

function LineItemRow({ item }: { item: InvoiceLineItemResponse }) {
  const { t } = useTranslation();
  return (
    <Stack spacing={0.5} sx={{ py: 1 }}>
      <Stack
        direction="row"
        spacing={1}
        sx={{ alignItems: "baseline", flexWrap: "wrap" }}
      >
        <Typography variant="body2" sx={{ fontWeight: 600, flex: 1 }}>
          {item.account_name ?? t("properties.vendors.lineItemFallback")}
        </Typography>
        {item.amount != null && (
          <Typography variant="body2" sx={{ fontWeight: 600 }}>
            {formatAmount(item.amount)} €
          </Typography>
        )}
      </Stack>
      {item.booking_text && (
        <Typography variant="caption" color="text.secondary">
          {item.booking_text}
        </Typography>
      )}
      <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap" }}>
        {item.account_code && (
          <Typography variant="caption" color="text.disabled">
            {t("properties.vendors.account")} {item.account_code}
          </Typography>
        )}
        {item.vat_percentage != null && (
          <Typography variant="caption" color="text.disabled">
            {t("properties.vendors.vat")} {formatPercent(item.vat_percentage)} %
            {item.vat_amount != null && ` · ${formatAmount(item.vat_amount)} €`}
          </Typography>
        )}
      </Stack>
    </Stack>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <Box>
      <Typography
        variant="overline"
        color="text.secondary"
        sx={{ letterSpacing: "0.08em", display: "block", mb: 1 }}
      >
        {title}
      </Typography>
      <Stack spacing={0.75}>{children}</Stack>
    </Box>
  );
}

function Row({
  label,
  value,
}: {
  label: string;
  value: string | null | undefined;
}) {
  if (value == null || value === "") return null;
  return (
    <Stack direction="row" spacing={1.5} sx={{ alignItems: "baseline" }}>
      <Typography
        variant="body2"
        color="text.secondary"
        sx={{ minWidth: 130, flexShrink: 0 }}
      >
        {label}
      </Typography>
      <Typography variant="body2">{value}</Typography>
    </Stack>
  );
}

function formatDate(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const [y, m, d] = iso.split("-");
  if (!y || !m || !d) return iso;
  return `${d}.${m}.${y}`;
}

function formatAmount(v: number | string): string {
  const n = typeof v === "string" ? Number(v) : v;
  if (!Number.isFinite(n)) return String(v);
  return n.toLocaleString("de-DE", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function formatPercent(v: number | string): string {
  const n = typeof v === "string" ? Number(v) : v;
  if (!Number.isFinite(n)) return String(v);
  // Drop trailing zeros: "19" not "19.00".
  return n
    .toLocaleString("de-DE", {
      minimumFractionDigits: 0,
      maximumFractionDigits: 2,
    });
}
