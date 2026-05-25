import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import {
  Alert,
  Box,
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
import type { PropertyDetailResponse } from "@/api/types";

/**
 * Details tab inside PropertyWorkspace.
 *
 * Renders the property's Stammdaten + Einheiten. The previous
 * standalone version also showed breadcrumbs, a page title, and a
 * bottom row of "Dokumente / Mitteilungen / Versammlungen ansehen"
 * buttons — all three are now redundant: the workspace tabs above
 * carry navigation, the AppBar switcher carries identity, and the
 * page title is implicit in the active tab.
 */

function Row({ label, value }: { label: string; value: string }) {
  return (
    <Stack direction="row" spacing={1.5} sx={{ alignItems: "baseline" }}>
      <Typography
        variant="body2"
        color="text.secondary"
        sx={{ minWidth: 80, flexShrink: 0 }}
      >
        {label}
      </Typography>
      <Typography variant="body2">{value}</Typography>
    </Stack>
  );
}

export function PropertyDetailPage() {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();
  const [prop, setProp] = useState<PropertyDetailResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    if (!id) return;
    api
      .get<PropertyDetailResponse>(`/me/properties/${id}`)
      // eslint-disable-next-line react-hooks/set-state-in-effect
      .then((r) => setProp(r.data))
      .catch((err) => {
        if (err.response?.status === 404) setNotFound(true);
        else setError(t("properties.loadFailed"));
      });
  }, [id, t]);

  if (notFound) {
    return <Alert severity="error">{t("properties.empty")}</Alert>;
  }
  if (error) return <Alert severity="error">{error}</Alert>;
  if (!prop) {
    return (
      <Typography variant="body2" color="text.secondary">
        {t("common.loading")}
      </Typography>
    );
  }

  const address = [
    [prop.street, prop.number].filter(Boolean).join(" "),
    [prop.postal_code, prop.city].filter(Boolean).join(" "),
    prop.country,
  ]
    .filter(Boolean)
    .join(", ");

  return (
    <Stack spacing={3}>
      <Box>
        <Typography variant="h5" component="h2" sx={{ fontWeight: 700 }}>
          {prop.name}
        </Typography>
        {prop.property_hr_id && (
          <Typography
            variant="caption"
            color="text.secondary"
            sx={{ fontFamily: "ui-monospace, Menlo, monospace" }}
          >
            {prop.property_hr_id}
          </Typography>
        )}
      </Box>

      <Paper variant="outlined" sx={{ p: 2.5 }}>
        <Typography
          variant="overline"
          color="text.secondary"
          sx={{ letterSpacing: "0.08em", display: "block", mb: 1.5 }}
        >
          Stammdaten
        </Typography>
        <Stack spacing={1}>
          {address && <Row label="Adresse:" value={address} />}
          <Row label="Typ:" value={prop.type} />
          <Row label="Status:" value={prop.state} />
        </Stack>
      </Paper>

      <Box>
        <Typography
          variant="overline"
          color="text.secondary"
          sx={{ letterSpacing: "0.08em", display: "block", mb: 1.5 }}
        >
          Einheiten ({prop.units.length})
        </Typography>
        {prop.units.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            Keine Einheiten erfasst.
          </Typography>
        ) : (
          <TableContainer component={Paper} variant="outlined">
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Bezeichnung</TableCell>
                  <TableCell>Typ</TableCell>
                  <TableCell>Etage</TableCell>
                  <TableCell>Lage</TableCell>
                  <TableCell>m²</TableCell>
                  <TableCell>Zimmer</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {prop.units.map((u) => (
                  <TableRow key={u.id} hover>
                    <TableCell
                      sx={{ fontFamily: "ui-monospace, Menlo, monospace" }}
                    >
                      {u.unit_hr_id ?? "—"}
                    </TableCell>
                    <TableCell>{u.type}</TableCell>
                    <TableCell>{u.floor ?? "—"}</TableCell>
                    <TableCell>{u.position ?? "—"}</TableCell>
                    <TableCell>{u.area_m2 ?? "—"}</TableCell>
                    <TableCell>{u.rooms ?? "—"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </Box>
    </Stack>
  );
}
