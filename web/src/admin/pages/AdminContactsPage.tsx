import { useEffect, useMemo, useState } from "react";
import {
  Alert,
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
import { useTranslation } from "react-i18next";
import { api } from "@/api/client";
import type { AdminContactListItem } from "@/api/types";

// Backend contact_kind enum has just these two values today. Hard-coding
// instead of importing a generated TS enum (we don't ship one) keeps
// the pill row honest about what we actually filter on.
type ContactKindFilter = "" | "PERSON" | "COMPANY";

export function AdminContactsPage() {
  const { t } = useTranslation();
  const [rows, setRows] = useState<AdminContactListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // No default filter — the user spec was "no default filter, only when
  // the user clicks on the pill", so the "Alle" pill is the initial state.
  const [kindFilter, setKindFilter] = useState<ContactKindFilter>("");

  useEffect(() => {
    api
      .get<AdminContactListItem[]>("/admin/contacts")
      // eslint-disable-next-line react-hooks/set-state-in-effect
      .then((r) => setRows(r.data))
      .catch(() => setError(t("admin.stammdaten.loadFailed")));
  }, [t]);

  // Filtering is client-side: /admin/contacts already returns up to 200
  // rows in one call, so an in-memory filter is cheaper and snappier
  // than a round-trip per pill click.
  const visibleRows = useMemo(() => {
    if (rows === null) return null;
    if (!kindFilter) return rows;
    return rows.filter((r) => r.kind === kindFilter);
  }, [rows, kindFilter]);

  if (error) return <Alert severity="error">{error}</Alert>;
  if (visibleRows === null) {
    return (
      <Typography variant="body2" color="text.secondary">
        {t("common.loading")}
      </Typography>
    );
  }

  return (
    <Stack spacing={3}>
      <Typography variant="h4" component="h1">
        {t("admin.contactsPage.title")}
      </Typography>

      {/* Filter pills — same visual language as the ticket queue's
          "Status:" strip. Clicking a kind sets the filter; clicking
          "Alle" (or the active pill) clears it. */}
      <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", gap: 1 }}>
        <Typography
          variant="caption"
          color="text.secondary"
          sx={{ alignSelf: "center", mr: 1 }}
        >
          {t("admin.contactsPage.kindFilterLabel")}:
        </Typography>
        <Chip
          label={t("admin.contactsPage.kindAll")}
          color={!kindFilter ? "primary" : "default"}
          variant={!kindFilter ? "filled" : "outlined"}
          onClick={() => setKindFilter("")}
          clickable
        />
        <Chip
          label={t("admin.contactsPage.kindCompany")}
          color={kindFilter === "COMPANY" ? "primary" : "default"}
          variant={kindFilter === "COMPANY" ? "filled" : "outlined"}
          onClick={() =>
            setKindFilter((cur) => (cur === "COMPANY" ? "" : "COMPANY"))
          }
          clickable
        />
        <Chip
          label={t("admin.contactsPage.kindPerson")}
          color={kindFilter === "PERSON" ? "primary" : "default"}
          variant={kindFilter === "PERSON" ? "filled" : "outlined"}
          onClick={() =>
            setKindFilter((cur) => (cur === "PERSON" ? "" : "PERSON"))
          }
          clickable
        />
      </Stack>

      {visibleRows.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          {t("admin.stammdaten.empty")}
        </Typography>
      ) : (
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>{t("admin.contactsPage.name")}</TableCell>
                <TableCell>{t("admin.contactsPage.email")}</TableCell>
                <TableCell>{t("admin.contactsPage.phone")}</TableCell>
                <TableCell>{t("admin.contactsPage.city")}</TableCell>
                <TableCell>{t("admin.contactsPage.impowerId")}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {visibleRows.map((c) => (
                <TableRow key={c.id} hover>
                  <TableCell>
                    <Typography variant="body2" sx={{ fontWeight: 500 }}>
                      {c.name}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="caption" color="text.secondary">
                      {c.email ?? "—"}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="caption" color="text.secondary">
                      {c.phone ?? "—"}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="caption" color="text.secondary">
                      {c.city ?? "—"}
                    </Typography>
                  </TableCell>
                  <TableCell
                    sx={{ fontFamily: "ui-monospace, Menlo, monospace" }}
                  >
                    <Typography variant="caption" color="text.secondary">
                      {c.impower_id ?? "—"}
                    </Typography>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}
      {/* The 200-row limit is enforced server-side on the unfiltered
          response, so the warning still tracks the upstream cap. */}
      {rows !== null && rows.length >= 200 && (
        <Typography variant="caption" color="text.secondary">
          {t("admin.stammdaten.limitNote")}
        </Typography>
      )}
    </Stack>
  );
}
