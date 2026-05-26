import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import {
  Alert,
  Box,
  Chip,
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
import type { UnitContractSummary } from "@/api/types";
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
                  <TableCell align="right">m²</TableCell>
                  {/* MEA (Miteigentumsanteile) + currently-active
                      contracts are the master-table-truthy
                      columns: who-pays-how-much + who's-in-it. */}
                  <TableCell align="right">MEA</TableCell>
                  <TableCell align="right">Zimmer</TableCell>
                  <TableCell>Aktuelle Verträge</TableCell>
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
                    <TableCell align="right">
                      {u.area_m2 != null
                        ? u.area_m2.toLocaleString(undefined, {
                            maximumFractionDigits: 1,
                          })
                        : "—"}
                    </TableCell>
                    <TableCell align="right">
                      {u.voting_share != null
                        ? u.voting_share.toLocaleString(undefined, {
                            maximumFractionDigits: 4,
                          })
                        : "—"}
                    </TableCell>
                    <TableCell align="right">
                      {u.rooms != null ? u.rooms : "—"}
                    </TableCell>
                    <TableCell>
                      <ContractChips contracts={u.current_contracts} />
                    </TableCell>
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

/// One chip per role-tagged contract — Eigentümer green, Mieter
/// blue/accent, Objekteigentümer orange. Falls back gracefully
/// when the backend sends `contact_label` null (a contract row
/// without a contact, rare data-hygiene case).
function ContractChips({ contracts }: { contracts: UnitContractSummary[] }) {
  if (contracts.length === 0) {
    return (
      <Typography variant="caption" color="text.secondary">
        leer
      </Typography>
    );
  }
  return (
    <Stack spacing={0.5}>
      {contracts.map((c) => (
        <Stack
          key={c.contract_id + ":" + (c.contact_id ?? "—")}
          direction="row"
          spacing={1}
          sx={{ alignItems: "center" }}
        >
          <Chip
            label={typeLabel(c.type)}
            size="small"
            color={typeColor(c.type)}
            variant="filled"
          />
          <Typography variant="body2">{c.contact_label ?? "—"}</Typography>
        </Stack>
      ))}
    </Stack>
  );
}

function typeLabel(type: string): string {
  switch (type) {
    case "OWNER":
      return "Eigentümer";
    case "TENANT":
      return "Mieter";
    case "PROPERTY_OWNER":
      return "Objekteigentümer";
    default:
      return type;
  }
}

function typeColor(
  type: string,
): "success" | "primary" | "warning" | "default" {
  switch (type) {
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
