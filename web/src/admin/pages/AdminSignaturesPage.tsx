// Admin "Signaturen" tab (ADR-0012): send a PDF out for digital
// signature via DocuSeal (recipient gets an SES email, no portal
// account) and track status. Ships gated — creating returns 503 until
// the DocuSeal instance + env are configured, which we surface plainly.

import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  MenuItem,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import DownloadIcon from "@mui/icons-material/DownloadOutlined";
import UploadFileIcon from "@mui/icons-material/UploadFileOutlined";
import { useTranslation } from "react-i18next";
import { api, API_BASE_URL, getAccessToken } from "@/api/client";
import type { AdminPropertyListItem, SignatureRequestResponse } from "@/api/types";

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
  const [dialogOpen, setDialogOpen] = useState(false);

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
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          onClick={() => setDialogOpen(true)}
        >
          {t("admin.signaturesPage.new")}
        </Button>
      </Stack>
      <Typography variant="body2" color="text.secondary">
        {t("admin.signaturesPage.intro")}
      </Typography>

      {error && <Alert severity="error">{error}</Alert>}

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

      {dialogOpen && (
        <NewSignatureDialog
          properties={properties}
          onClose={() => setDialogOpen(false)}
          onCreated={() => {
            setDialogOpen(false);
            void load();
          }}
        />
      )}
    </Stack>
  );
}

function NewSignatureDialog({
  properties,
  onClose,
  onCreated,
}: {
  properties: AdminPropertyListItem[];
  onClose: () => void;
  onCreated: () => void;
}) {
  const { t } = useTranslation();
  const [file, setFile] = useState<File | null>(null);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [propertyId, setPropertyId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSubmit = file !== null && /\S+@\S+\.\S+/.test(email.trim());

  const submit = async () => {
    if (!canSubmit || !file) return;
    setBusy(true);
    setError(null);
    try {
      const params = new URLSearchParams({ recipient_email: email.trim() });
      if (name.trim()) params.set("recipient_name", name.trim());
      if (propertyId) params.set("property_id", propertyId);
      const form = new FormData();
      form.append("file", file);
      await api.post(`/admin/signature-requests?${params.toString()}`, form);
      onCreated();
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } }).response?.status;
      const detail = (err as { response?: { data?: { detail?: string } } })
        .response?.data?.detail;
      setError(
        status === 503
          ? t("admin.signaturesPage.notConfigured")
          : (detail ?? t("admin.signaturesPage.createFailed")),
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>{t("admin.signaturesPage.new")}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {error && <Alert severity="error">{error}</Alert>}
          <Button component="label" variant="outlined" startIcon={<UploadFileIcon />}>
            {file ? file.name : t("admin.signaturesPage.choosePdf")}
            <input
              hidden
              type="file"
              accept="application/pdf,.pdf"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </Button>
          <TextField
            label={t("admin.signaturesPage.recipientEmail")}
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            fullWidth
          />
          <TextField
            label={t("admin.signaturesPage.recipientName")}
            value={name}
            onChange={(e) => setName(e.target.value)}
            fullWidth
          />
          <TextField
            select
            label={t("admin.signaturesPage.property")}
            value={propertyId}
            onChange={(e) => setPropertyId(e.target.value)}
            fullWidth
          >
            <MenuItem value="">
              <em>{t("admin.signaturesPage.noProperty")}</em>
            </MenuItem>
            {properties.map((p) => (
              <MenuItem key={p.id} value={p.id}>
                {p.name}
              </MenuItem>
            ))}
          </TextField>
          <Typography variant="caption" color="text.secondary">
            {t("admin.signaturesPage.dialogHint")}
          </Typography>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={busy}>
          {t("common.cancel")}
        </Button>
        <Button
          variant="contained"
          onClick={() => void submit()}
          disabled={!canSubmit || busy}
        >
          {t("admin.signaturesPage.send")}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
