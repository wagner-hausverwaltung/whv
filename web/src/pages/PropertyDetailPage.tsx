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
import {
  propertyHasOwnershipShares,
  propertyTypeLabel,
} from "@/lib/propertyType";
import { ContactDetailDialog } from "@/components/ContactDetailDialog";

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

/// Click target for the contact-detail dialog. We carry the
/// contract+contact pair plus the chip's rendered label so the
/// dialog title can populate before the network round-trip finishes.
interface ContactDialogTarget {
  contractId: string;
  contactId: string;
  fallbackLabel: string;
}

export function PropertyDetailPage() {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();
  const [prop, setProp] = useState<PropertyDetailResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  /// Null = dialog closed. Set by ContractChips when the user clicks
  /// a row; cleared on dialog dismiss.
  const [contactDialog, setContactDialog] = useState<ContactDialogTarget | null>(
    null,
  );

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

  // Hide the unit-type column when every Einheit has the same kind —
  // a column of repeated "APARTMENT" cells is dead weight. Mixed-use
  // properties (APARTMENT + PARKING + COMMERCIAL) keep the column.
  const distinctUnitTypes = new Set(prop.units.map((u) => u.type));
  const showUnitTypeColumn = distinctUnitTypes.size > 1;

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
          {t("properties.detail.stammdaten")}
        </Typography>
        <Stack spacing={1}>
          {address && (
            <Row label={`${t("properties.detail.address")}:`} value={address} />
          )}
          {/* Render the human label (WEG / MV / SEV) — the raw
              OWNER/RENTAL/STRATA enum from Impower is opaque to
              owners and the prop.name already carries the same
              prefix, so showing "OWNER" beside "WEG …" looks
              broken. Status row was removed: the portal is filtered
              to state == "READY" upstream, so showing "Status:
              READY" everywhere is noise. */}
          <Row
            label={`${t("properties.detail.type")}:`}
            value={propertyTypeLabel(prop.type)}
          />
        </Stack>
      </Paper>

      <Box>
        <Typography
          variant="overline"
          color="text.secondary"
          sx={{ letterSpacing: "0.08em", display: "block", mb: 1.5 }}
        >
          {t("properties.detail.units")} ({prop.units.length})
        </Typography>
        {prop.units.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            {t("properties.detail.noUnits")}
          </Typography>
        ) : (
          <TableContainer component={Paper} variant="outlined">
            <Table size="small">
              <TableHead>
                {/* MEA (Miteigentumsanteile) only makes sense on
                    WEG / SEV (ownership) properties — for MV
                    rentals Mieter have no Anteile, so hiding the
                    column keeps the table honest. The other three
                    distribution-key columns (Fläche / Heizfläche /
                    Personen) are universal so they're always
                    rendered, with "—" when the row is blank. */}
                <TableRow>
                  <TableCell>{t("properties.detail.colName")}</TableCell>
                  {showUnitTypeColumn && (
                    <TableCell>{t("properties.detail.colType")}</TableCell>
                  )}
                  <TableCell>{t("properties.detail.colFloor")}</TableCell>
                  <TableCell>{t("properties.detail.colPosition")}</TableCell>
                  <TableCell align="right">
                    {t("properties.detail.colArea")}
                  </TableCell>
                  <TableCell align="right">
                    {t("properties.detail.colHeated")}
                  </TableCell>
                  <TableCell align="right">
                    {t("properties.detail.colPersons")}
                  </TableCell>
                  {propertyHasOwnershipShares(prop.type) && (
                    <TableCell align="right">MEA</TableCell>
                  )}
                  <TableCell align="right">
                    {t("properties.detail.colRooms")}
                  </TableCell>
                  <TableCell>{t("properties.detail.colContracts")}</TableCell>
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
                    {showUnitTypeColumn && <TableCell>{u.type}</TableCell>}
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
                      {u.heated_area_m2 != null
                        ? u.heated_area_m2.toLocaleString(undefined, {
                            maximumFractionDigits: 1,
                          })
                        : "—"}
                    </TableCell>
                    <TableCell align="right">
                      {u.persons != null
                        ? u.persons.toLocaleString(undefined, {
                            maximumFractionDigits: 1,
                          })
                        : "—"}
                    </TableCell>
                    {propertyHasOwnershipShares(prop.type) && (
                      <TableCell align="right">
                        {u.voting_share != null
                          ? u.voting_share.toLocaleString(undefined, {
                              maximumFractionDigits: 4,
                            })
                          : "—"}
                      </TableCell>
                    )}
                    <TableCell align="right">
                      {u.rooms != null ? u.rooms : "—"}
                    </TableCell>
                    <TableCell>
                      <ContractChips
                        contracts={u.current_contracts}
                        onContactClick={setContactDialog}
                      />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </Box>

      {/* One dialog instance for the whole page — opening another
          contact remounts via the contact-id key so internal state
          (detail / error) resets to its useState default. Avoids
          synchronous setState-in-effect resets the lint rule flags. */}
      {contactDialog && (
        <ContactDetailDialog
          key={contactDialog.contactId}
          open
          contractId={contactDialog.contractId}
          contactId={contactDialog.contactId}
          fallbackLabel={contactDialog.fallbackLabel}
          onClose={() => setContactDialog(null)}
        />
      )}
    </Stack>
  );
}

/// One chip per role-tagged contract — Eigentümer green, Mieter
/// blue/accent, Objekteigentümer orange. Falls back gracefully
/// when the backend sends `contact_label` null (a contract row
/// without a contact, rare data-hygiene case).
///
/// Rows where we have a contact_id are clickable — clicking
/// surfaces the ContactDetailDialog via the page-level callback.
/// Rows without a contact_id (rare) stay as static text so we don't
/// open a dialog that can't load.
function ContractChips({
  contracts,
  onContactClick,
}: {
  contracts: UnitContractSummary[];
  onContactClick: (target: ContactDialogTarget) => void;
}) {
  const { t } = useTranslation();
  if (contracts.length === 0) {
    return (
      <Typography variant="caption" color="text.secondary">
        {t("properties.detail.contractsEmpty")}
      </Typography>
    );
  }
  return (
    <Stack spacing={0.5}>
      {contracts.map((c) => {
        const label = c.contact_label ?? "—";
        const clickable = c.contact_id != null;
        const body = (
          <Stack
            direction="row"
            spacing={1}
            sx={{
              alignItems: "center",
              // Visual affordance for clickability — text underline
              // on hover, default cursor when not clickable.
              cursor: clickable ? "pointer" : "default",
              "&:hover .contact-label": clickable
                ? { textDecoration: "underline" }
                : undefined,
              // The whole row is the hit target; widen vertical
              // padding so finger-tapping on touch devices is
              // forgiving without changing visual rhythm.
              py: 0.25,
            }}
          >
            <Chip
              label={typeLabel(c.type)}
              size="small"
              color={typeColor(c.type)}
              variant="filled"
            />
            <Typography variant="body2" className="contact-label">
              {label}
            </Typography>
          </Stack>
        );
        if (!clickable) {
          return (
            <Box key={c.contract_id + ":none"}>{body}</Box>
          );
        }
        return (
          <Box
            key={c.contract_id + ":" + c.contact_id}
            role="button"
            tabIndex={0}
            onClick={() =>
              onContactClick({
                contractId: c.contract_id,
                contactId: c.contact_id!,
                fallbackLabel: label,
              })
            }
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onContactClick({
                  contractId: c.contract_id,
                  contactId: c.contact_id!,
                  fallbackLabel: label,
                });
              }
            }}
            // Keyboard focus ring — MUI's Button would do this for
            // us but it'd over-style the row; we want it to read
            // as plain text with a hover hint.
            sx={{
              borderRadius: 0.5,
              "&:focus-visible": {
                outline: "2px solid",
                outlineColor: "primary.main",
                outlineOffset: 2,
              },
            }}
          >
            {body}
          </Box>
        );
      })}
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
