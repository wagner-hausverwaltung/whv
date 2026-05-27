/**
 * Property "Dienstleister" tab.
 *
 * Lists every firm (Schornsteinfeger, Elektriker, Maler …) that has
 * issued an invoice for the property, with the contactable bits and
 * a recent-invoices list. Aggregated server-side from documents
 * where kind = RECHNUNG, grouped by contact_id.
 *
 * Owners answer the "who fixed the boiler last time?" question
 * without paging the Verwalter. Click on an invoice to download
 * the PDF via the existing /me/documents/{id}/file endpoint.
 */

import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import {
  Alert,
  Box,
  Chip,
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
import { useTranslation } from "react-i18next";
import { api, API_BASE_URL, getAccessToken } from "@/api/client";
import type { VendorInvoiceSummary, VendorSummary } from "@/api/types";

export function PropertyVendorsPage() {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();
  const [vendors, setVendors] = useState<VendorSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

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
          Dienstleister
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
          Firmen, die für diese Liegenschaft gearbeitet haben, mit
          aktuellen Kontaktdaten und Rechnungshistorie.
        </Typography>
      </Box>

      {vendors.length === 0 ? (
        <Paper variant="outlined" sx={{ p: 3 }}>
          <Typography variant="body2" color="text.secondary">
            Noch keine Rechnungen für diese Liegenschaft erfasst.
          </Typography>
        </Paper>
      ) : (
        <Stack spacing={2}>
          {vendors.map((v) => (
            <VendorCard key={v.contact_id} vendor={v} />
          ))}
        </Stack>
      )}
    </Stack>
  );
}

function VendorCard({ vendor }: { vendor: VendorSummary }) {
  const [downloadError, setDownloadError] = useState<string | null>(null);
  return (
    <Paper variant="outlined" sx={{ p: 2.5 }}>
      <Stack spacing={1.5}>
        {/* Header: kind icon + name + last-service badge. */}
        <Stack
          direction="row"
          spacing={1.5}
          sx={{ alignItems: "flex-start", flexWrap: "wrap" }}
        >
          <Box sx={{ pt: 0.5 }}>
            {vendor.kind === "COMPANY" ? (
              <BusinessIcon color="primary" />
            ) : (
              <PersonIcon color="primary" />
            )}
          </Box>
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
              {vendor.name}
            </Typography>
            <Stack
              direction="row"
              spacing={1}
              sx={{ mt: 0.5, flexWrap: "wrap", rowGap: 0.5 }}
            >
              {vendor.last_service_date && (
                <Chip
                  size="small"
                  variant="outlined"
                  label={`Zuletzt am ${formatDate(vendor.last_service_date)}`}
                />
              )}
              <Chip
                size="small"
                variant="outlined"
                label={`${vendor.invoice_count} Rechnung${vendor.invoice_count === 1 ? "" : "en"}`}
              />
              {vendor.total_amount != null && (
                <Chip
                  size="small"
                  variant="outlined"
                  label={`Summe ${formatAmount(vendor.total_amount)} €`}
                />
              )}
            </Stack>
          </Box>
        </Stack>

        {/* Contactable bits. mailto: + tel: launchers — the
            actionable feature owners actually want. */}
        {(vendor.phone || vendor.email) && (
          <Stack direction="row" spacing={2} sx={{ flexWrap: "wrap", rowGap: 1 }}>
            {vendor.phone && (
              <MuiLink
                href={`tel:${vendor.phone.replace(/\s+/g, "")}`}
                underline="hover"
                sx={{ display: "inline-flex", alignItems: "center", gap: 0.5 }}
              >
                <PhoneIcon fontSize="small" />
                {vendor.phone}
              </MuiLink>
            )}
            {vendor.email && (
              <MuiLink
                href={`mailto:${vendor.email}`}
                underline="hover"
                sx={{ display: "inline-flex", alignItems: "center", gap: 0.5 }}
              >
                <EmailIcon fontSize="small" />
                {vendor.email}
              </MuiLink>
            )}
          </Stack>
        )}

        {/* Recent invoices — clickable into the existing document
            downloader. We deliberately re-use the auth-fetch pattern
            from DocumentFoldersPanel rather than a plain <a> so the
            JWT goes along with the request. */}
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
              Letzte Rechnungen
            </Typography>
            <Stack spacing={0.5}>
              {vendor.recent_invoices.map((inv) => (
                <InvoiceRow
                  key={inv.id}
                  invoice={inv}
                  onDownloadError={setDownloadError}
                />
              ))}
            </Stack>
            {downloadError && (
              <Alert severity="error" sx={{ mt: 1 }}>
                {downloadError}
              </Alert>
            )}
          </Box>
        )}
      </Stack>
    </Paper>
  );
}

function InvoiceRow({
  invoice,
  onDownloadError,
}: {
  invoice: VendorInvoiceSummary;
  onDownloadError: (msg: string) => void;
}) {
  const [busy, setBusy] = useState(false);

  const download = async () => {
    setBusy(true);
    try {
      // Same auth-fetch trick DocumentFoldersPanel uses — a plain
      // <a href> can't send our JWT, so we pull the bytes and
      // synthesize a click on a blob URL.
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
      a.download = invoice.name;
      document.body.appendChild(a);
      a.click();
      a.remove();
      // Safari needs a beat before we revoke or the download breaks.
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch {
      onDownloadError("Download fehlgeschlagen.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Stack
      direction="row"
      spacing={1}
      sx={{ alignItems: "center" }}
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
      <IconButton
        size="small"
        onClick={() => void download()}
        disabled={busy}
        aria-label={`Rechnung ${invoice.name} herunterladen`}
      >
        <DownloadIcon fontSize="small" />
      </IconButton>
    </Stack>
  );
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
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
