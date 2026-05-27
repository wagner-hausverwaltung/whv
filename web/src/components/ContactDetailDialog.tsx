/**
 * Contact-detail dialog reached by clicking a contract chip on the
 * property detail page.
 *
 * Loads `GET /me/contracts/{contractId}/contacts/{contactId}` on
 * open and renders every API-exposed field as a key/value pair —
 * the goal is "see what we have on file", not "edit". Anything the
 * caller can read in this dialog they could already see in the
 * chip's contact_label and the underlying Impower mirror; this just
 * surfaces the address, phone, mandate number etc. that the chip
 * label hides for space.
 *
 * Person vs Company rendering branches on `kind` so we don't show
 * "Vorname: —" on a GmbH or "Handelsregister-Nr.: —" on a person.
 */

import { useEffect, useState } from "react";
import {
  Alert,
  Box,
  Chip,
  Dialog,
  DialogContent,
  DialogTitle,
  Divider,
  IconButton,
  Stack,
  Typography,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import { api } from "@/api/client";
import type { ContactDetailResponse } from "@/api/types";

interface Props {
  open: boolean;
  contractId: string;
  contactId: string;
  /// Pre-rendered name from the chip — shown as the dialog title
  /// while the detail fetch is in flight, so the operator knows
  /// which row they clicked even if the network is slow.
  fallbackLabel: string;
  onClose: () => void;
}

export function ContactDetailDialog({
  open,
  contractId,
  contactId,
  fallbackLabel,
  onClose,
}: Props) {
  const [detail, setDetail] = useState<ContactDetailResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setDetail(null);
    setError(null);
    let cancelled = false;
    void (async () => {
      try {
        const r = await api.get<ContactDetailResponse>(
          `/me/contracts/${contractId}/contacts/${contactId}`,
        );
        if (!cancelled) setDetail(r.data);
      } catch {
        if (!cancelled) setError("Kontaktdaten konnten nicht geladen werden.");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, contractId, contactId]);

  const heading = detail ? renderName(detail) : fallbackLabel;

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle sx={{ pr: 6 }}>
        {heading}
        <IconButton
          onClick={onClose}
          sx={{ position: "absolute", right: 8, top: 8 }}
          aria-label="Schließen"
        >
          <CloseIcon />
        </IconButton>
      </DialogTitle>
      <DialogContent dividers>
        {error && <Alert severity="error">{error}</Alert>}
        {!error && detail === null && (
          <Typography variant="body2" color="text.secondary">
            Lädt …
          </Typography>
        )}
        {detail && <ContactBody detail={detail} />}
      </DialogContent>
    </Dialog>
  );
}

function ContactBody({ detail }: { detail: ContactDetailResponse }) {
  const isCompany = detail.kind === "COMPANY";
  const address = formatAddress(detail);
  return (
    <Stack spacing={2.5}>
      {/* Contract context first — answers "why am I looking at
          this person from this property". */}
      <Section title="Vertrag">
        <ContractContext detail={detail} />
      </Section>

      <Divider />

      {!isCompany && (
        <Section title="Person">
          <Row label="Anrede" value={detail.salutation} />
          <Row label="Titel" value={detail.title} />
          <Row label="Vorname" value={detail.first_name} />
          <Row label="Nachname" value={detail.last_name} />
          <Row label="Geburtsdatum" value={formatDate(detail.date_of_birth)} />
        </Section>
      )}
      {isCompany && (
        <Section title="Unternehmen">
          <Row label="Firma" value={detail.company_name} />
          <Row label="USt-IdNr." value={detail.vat_id} />
          <Row label="Handelsregister-Nr." value={detail.trade_register_number} />
        </Section>
      )}

      <Section title="Kontakt">
        <Row label="E-Mail" value={detail.email} valueAs="email" />
        <Row label="Telefon" value={detail.phone} valueAs="phone" />
        <Row
          label="Bevorzugt"
          value={preferredChannelLabel(detail.preferred_channel)}
        />
        <Row label="Empfänger-Adresse" value={detail.recipient_name} />
        {detail.additional_contacts && (
          <AdditionalContacts data={detail.additional_contacts} />
        )}
      </Section>

      {(address || detail.country) && (
        <Section title="Anschrift">
          {address && (
            <Typography variant="body2" sx={{ whiteSpace: "pre-line" }}>
              {address}
            </Typography>
          )}
        </Section>
      )}

      {detail.mandate_number && (
        <Section title="Mandat">
          <Row label="Mandat-Nr." value={detail.mandate_number} />
        </Section>
      )}
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
  valueAs,
}: {
  label: string;
  value: string | null | undefined;
  valueAs?: "email" | "phone";
}) {
  // We do NOT render rows for null values — a sea of "—" makes the
  // dialog feel empty even when the populated rows are exactly what
  // the user wanted to see. The dialog itself stays compact this way.
  if (value == null || value === "") return null;
  let content: React.ReactNode = value;
  if (valueAs === "email") {
    content = (
      <a href={`mailto:${value}`} style={{ color: "inherit" }}>
        {value}
      </a>
    );
  }
  if (valueAs === "phone") {
    content = (
      <a href={`tel:${value}`} style={{ color: "inherit" }}>
        {value}
      </a>
    );
  }
  return (
    <Stack direction="row" spacing={1.5} sx={{ alignItems: "baseline" }}>
      <Typography
        variant="body2"
        color="text.secondary"
        sx={{ minWidth: 140, flexShrink: 0 }}
      >
        {label}
      </Typography>
      <Typography variant="body2">{content}</Typography>
    </Stack>
  );
}

function ContractContext({ detail }: { detail: ContactDetailResponse }) {
  const c = detail.contract;
  return (
    <>
      <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
        <Chip
          size="small"
          label={contractTypeLabel(c.type)}
          color={contractTypeColor(c.type)}
        />
        {c.contract_number && (
          <Typography
            variant="caption"
            color="text.secondary"
            sx={{ fontFamily: "ui-monospace, Menlo, monospace" }}
          >
            {c.contract_number}
          </Typography>
        )}
      </Stack>
      <Row label="Bezeichnung" value={c.name} />
      <Row label="Beginn" value={formatDate(c.start_date)} />
      <Row label="Ende" value={formatDate(c.end_date)} />
      {c.role && <Row label="Rolle" value={c.role} />}
    </>
  );
}

function AdditionalContacts({
  data,
}: {
  data: Record<string, unknown>;
}) {
  const entries = Object.entries(data).filter(
    ([, v]) => v != null && String(v) !== "",
  );
  if (entries.length === 0) return null;
  return (
    <>
      {entries.map(([k, v]) => (
        <Row key={k} label={k} value={String(v)} />
      ))}
    </>
  );
}

function renderName(d: ContactDetailResponse): string {
  if (d.kind === "COMPANY") return d.company_name ?? "—";
  const parts = [d.title, d.first_name, d.last_name].filter(
    (s) => s && s.length > 0,
  );
  return parts.length > 0 ? parts.join(" ") : "—";
}

function formatAddress(d: ContactDetailResponse): string {
  const line1 = [d.street, d.number].filter(Boolean).join(" ");
  const line2 = [d.postal_code, d.city].filter(Boolean).join(" ");
  return [line1, line2, d.country].filter((s) => s && s.length > 0).join("\n");
}

function formatDate(iso: string | null): string | null {
  if (!iso) return null;
  // Backend gives ISO YYYY-MM-DD; render as German DD.MM.YYYY.
  const [y, m, d] = iso.split("-");
  if (!y || !m || !d) return iso;
  return `${d}.${m}.${y}`;
}

function preferredChannelLabel(c: string): string {
  switch (c) {
    case "PORTAL":
      return "Portal";
    case "EMAIL":
      return "E-Mail";
    case "WHATSAPP":
      return "WhatsApp";
    case "EPOST":
      return "E-Post";
    default:
      return c;
  }
}

function contractTypeLabel(t: string): string {
  switch (t) {
    case "OWNER":
      return "Eigentümer";
    case "TENANT":
      return "Mieter";
    case "PROPERTY_OWNER":
      return "Objekteigentümer";
    default:
      return t;
  }
}

function contractTypeColor(
  t: string,
): "success" | "primary" | "warning" | "default" {
  switch (t) {
    case "OWNER":
      return "success";
    case "TENANT":
      return "primary";
    case "PROPERTY_OWNER":
      return "warning";
    default:
      return "default";
  }
}
