import { useEffect, useState } from "react";
import { Link as RouterLink, useParams } from "react-router-dom";
import {
  Alert,
  Box,
  Link,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import { useTranslation } from "react-i18next";
import { api } from "@/api/client";
import type { DocumentResponse } from "@/api/types";

function formatBytes(bytes: number | null): string {
  if (bytes == null) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  let n = bytes;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i++;
  }
  return `${n.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

export function PropertyDocumentsPage() {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();
  const [docs, setDocs] = useState<DocumentResponse[] | null>(null);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    if (!id) return;
    api
      .get<DocumentResponse[]>(`/me/properties/${id}/documents`)
      // eslint-disable-next-line react-hooks/set-state-in-effect
      .then((r) => setDocs(r.data))
      .catch((err) => {
        if (err.response?.status === 404) setNotFound(true);
      });
  }, [id]);

  if (notFound) {
    return (
      <Stack spacing={2}>
        <Alert severity="error">
          Objekt nicht gefunden oder nicht zugänglich.
        </Alert>
        <Link component={RouterLink} to="/" color="text.secondary">
          ← {t("properties.title")}
        </Link>
      </Stack>
    );
  }
  if (docs === null) {
    return (
      <Typography variant="body2" color="text.secondary">
        {t("common.loading")}
      </Typography>
    );
  }

  return (
    <Stack spacing={4}>
      <Box>
        <Link
          component={RouterLink}
          to={`/properties/${id}`}
          color="text.secondary"
          underline="hover"
        >
          ← Objektdetails
        </Link>
      </Box>

      <Box>
        <Typography variant="h4" component="h1" sx={{ fontWeight: 700 }}>
          Dokumente
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
          Datei-Downloads kommen mit dem nächsten Update — derzeit sehen Sie nur
          die Metadaten der vom Hausverwalter hinterlegten Dokumente.
        </Typography>
      </Box>

      {docs.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          Keine Dokumente erfasst.
        </Typography>
      ) : (
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Name</TableCell>
                <TableCell>Art</TableCell>
                <TableCell>Datum</TableCell>
                <TableCell>Größe</TableCell>
                <TableCell>Typ</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {docs.map((d) => (
                <TableRow key={d.id} hover>
                  <TableCell>{d.name}</TableCell>
                  <TableCell>
                    <Typography
                      variant="caption"
                      color="text.secondary"
                      sx={{
                        textTransform: "uppercase",
                        letterSpacing: "0.05em",
                      }}
                    >
                      {d.kind}
                    </Typography>
                  </TableCell>
                  <TableCell>{d.issued_date ?? "—"}</TableCell>
                  <TableCell>{formatBytes(d.size_bytes)}</TableCell>
                  <TableCell>
                    <Typography variant="caption" color="text.secondary">
                      {d.mime_type ?? "—"}
                    </Typography>
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
