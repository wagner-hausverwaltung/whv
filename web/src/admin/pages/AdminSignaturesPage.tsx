// Admin "Signaturen" tab (ADR-0012). DocuSeal's open-source edition gates
// the headless "PDF → signature" API behind Pro, so instead of driving it
// from the backend we embed DocuSeal's full (free) UI in an iframe: the
// Verwalter uploads a PDF, places fields, picks a recipient and sends —
// all inside DocuSeal, which emails the signer via SES (no portal account).
// On completion DocuSeal calls our webhook, which archives the signed PDF
// into the document store; those completed signatures are listed below.
//
// sign. and admin. share the same site (*.wagner-hausverwaltung.com), so
// DocuSeal's login cookie works inside the frame; Caddy strips DocuSeal's
// X-Frame-Options + sets a frame-ancestors CSP so the admin may embed it.

import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Chip,
  IconButton,
  Link,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
} from "@mui/material";
import DownloadIcon from "@mui/icons-material/DownloadOutlined";
import OpenInNewIcon from "@mui/icons-material/OpenInNewOutlined";
import { useTranslation } from "react-i18next";
import { api, API_BASE_URL, getAccessToken } from "@/api/client";
import type { AdminPropertyListItem, SignatureRequestResponse } from "@/api/types";

// The self-hosted DocuSeal instance (Caddy allows framing it from here).
const DOCUSEAL_URL = "https://sign.wagner-hausverwaltung.com";

const STATUS_COLOR: Record<
  SignatureRequestResponse["status"],
  "default" | "info" | "success" | "error"
> = {
  PENDING: "default",
  SENT: "info",
  COMPLETED: "success",
  FAILED: "error",
};

async function downloadSigned(documentId: string) {
  const token = getAccessToken();
  const res = await fetch(
    `${API_BASE_URL}/admin/documents/${documentId}/file`,
    token ? { headers: { Authorization: `Bearer ${token}` } } : undefined,
  );
  if (!res.ok) return;
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "signiert.pdf";
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function AdminSignaturesPage() {
  const { t } = useTranslation();
  const [rows, setRows] = useState<SignatureRequestResponse[] | null>(null);
  const [properties, setProperties] = useState<AdminPropertyListItem[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [sigRes, propRes] = await Promise.all([
        api.get<SignatureRequestResponse[]>("/admin/signature-requests"),
        api.get<AdminPropertyListItem[]>("/admin/properties"),
      ]);
      setRows(sigRes.data);
      setProperties(propRes.data);
    } catch {
      setError(t("admin.signaturesPage.loadFailed"));
    }
  }, [t]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const propName = (id: string | null) =>
    id ? (properties.find((p) => p.id === id)?.name ?? "—") : "—";

  return (
    <Stack spacing={3}>
      <Stack
        direction="row"
        sx={{ alignItems: "center", justifyContent: "space-between", gap: 2 }}
      >
        <Typography variant="h4" component="h1">
          {t("admin.signaturesPage.title")}
        </Typography>
        <Link
          href={DOCUSEAL_URL}
          target="_blank"
          rel="noopener noreferrer"
          sx={{ display: "inline-flex", alignItems: "center", gap: 0.5 }}
        >
          <OpenInNewIcon fontSize="small" />
          {t("admin.signaturesPage.openInNewTab")}
        </Link>
      </Stack>
      <Typography variant="body2" color="text.secondary">
        {t("admin.signaturesPage.intro")}
      </Typography>

      {error && <Alert severity="error">{error}</Alert>}

      {/* Embedded DocuSeal — create + send signature requests here. */}
      <Box
        component="iframe"
        src={DOCUSEAL_URL}
        title="DocuSeal"
        sx={{
          width: "100%",
          height: "78vh",
          border: 1,
          borderColor: "divider",
          borderRadius: 1,
          bgcolor: "background.paper",
        }}
      />

      <Typography variant="subtitle1" sx={{ fontWeight: 700, mt: 1 }}>
        {t("admin.signaturesPage.completedTitle")}
      </Typography>
      {rows === null ? (
        <Typography variant="body2" color="text.secondary">
          {t("common.loading")}
        </Typography>
      ) : rows.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          {t("admin.signaturesPage.empty")}
        </Typography>
      ) : (
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>{t("admin.signaturesPage.colStatus")}</TableCell>
                <TableCell>{t("admin.signaturesPage.colRecipient")}</TableCell>
                <TableCell>{t("admin.signaturesPage.colDocument")}</TableCell>
                <TableCell>{t("admin.signaturesPage.colProperty")}</TableCell>
                <TableCell>{t("admin.signaturesPage.colCreated")}</TableCell>
                <TableCell align="right">
                  {t("admin.signaturesPage.colSigned")}
                </TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((r) => (
                <TableRow key={r.id} hover>
                  <TableCell>
                    <Chip
                      size="small"
                      color={STATUS_COLOR[r.status]}
                      label={t(`admin.signaturesPage.status.${r.status}`)}
                    />
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2">
                      {r.recipient_name ?? r.recipient_email}
                    </Typography>
                    {r.recipient_name && (
                      <Typography variant="caption" color="text.secondary">
                        {r.recipient_email}
                      </Typography>
                    )}
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2">{r.source_filename}</Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="caption" color="text.secondary">
                      {propName(r.property_id)}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="caption" color="text.secondary">
                      {new Date(r.created_at).toLocaleDateString("de-DE")}
                    </Typography>
                  </TableCell>
                  <TableCell align="right">
                    {r.signed_document_id ? (
                      <Tooltip title={t("admin.signaturesPage.downloadSigned")}>
                        <IconButton
                          size="small"
                          onClick={() => void downloadSigned(r.signed_document_id!)}
                          aria-label={t("admin.signaturesPage.downloadSigned")}
                        >
                          <DownloadIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    ) : (
                      <Typography variant="caption" color="text.disabled">
                        —
                      </Typography>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}
    </Stack>
  );
}
