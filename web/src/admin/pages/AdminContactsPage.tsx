import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Chip,
  Link,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TableSortLabel,
  TextField,
  Typography,
} from "@mui/material";
import OpenInNewIcon from "@mui/icons-material/OpenInNew";
import SearchIcon from "@mui/icons-material/Search";
import { useTranslation } from "react-i18next";
import { api } from "@/api/client";
import type { AdminContactListItem } from "@/api/types";
import { impowerContactUrl } from "@/lib/impowerLinks";

// Backend contact_kind enum has just these two values today. Hard-coding
// instead of importing a generated TS enum (we don't ship one) keeps
// the pill row honest about what we actually filter on.
type ContactKindFilter = "" | "PERSON" | "COMPANY";

/// Sortable column keys. Map matches the AdminContactListItem field
/// names — keeping the union small + literal means the comparator
/// switch stays exhaustive at compile time.
type SortKey = "name" | "email" | "phone" | "city" | "impower_id";
type SortDir = "asc" | "desc";

export function AdminContactsPage() {
  const { t } = useTranslation();
  const [rows, setRows] = useState<AdminContactListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // No default filter — the user spec was "no default filter, only when
  // the user clicks on the pill", so the "Alle" pill is the initial state.
  const [kindFilter, setKindFilter] = useState<ContactKindFilter>("");
  // Free-text search across name/email/phone/city/impower_id. Filters
  // client-side because /admin/contacts is already capped at 200 rows;
  // an in-memory pass is snappier than a server round-trip per keystroke.
  const [query, setQuery] = useState("");
  // Sort state. Default asc on name matches the previous sort-by-name
  // implicit ordering server-side, so users don't see things shuffle
  // when they don't touch the sort.
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortDir, setSortDir] = useState<SortDir>("asc");

  useEffect(() => {
    api
      .get<AdminContactListItem[]>("/admin/contacts")
      .then((r) => setRows(r.data))
      .catch(() => setError(t("admin.stammdaten.loadFailed")));
  }, [t]);

  const visibleRows = useMemo(() => {
    if (rows === null) return null;
    let out = rows;
    if (kindFilter) {
      out = out.filter((r) => r.kind === kindFilter);
    }
    const q = query.trim().toLowerCase();
    if (q.length > 0) {
      // Split the query on whitespace so "luis stuttgart" matches a
      // row whose name + city together contain both words. Each token
      // must hit some field — typical "AND across tokens, OR across
      // columns" search semantics that admins expect.
      const tokens = q.split(/\s+/).filter(Boolean);
      out = out.filter((r) => {
        const haystack = [
          r.name,
          r.email,
          r.phone,
          r.city,
          r.impower_id != null ? String(r.impower_id) : null,
        ]
          .filter((s): s is string => !!s)
          .join(" ")
          .toLowerCase();
        return tokens.every((tok) => haystack.includes(tok));
      });
    }
    // Sort copy so we don't mutate state. Localised name compare
    // (de-DE) so umlauts collate correctly — "Ölbach" sorts under O,
    // not Ø.
    const sorted = [...out].sort((a, b) => {
      const av = readSortField(a, sortKey);
      const bv = readSortField(b, sortKey);
      // Nulls last regardless of direction — empty cells at the
      // bottom feels right both asc and desc.
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      let cmp: number;
      if (typeof av === "number" && typeof bv === "number") {
        cmp = av - bv;
      } else {
        cmp = String(av).localeCompare(String(bv), "de-DE", {
          sensitivity: "base",
          numeric: true,
        });
      }
      return sortDir === "asc" ? cmp : -cmp;
    });
    return sorted;
  }, [rows, kindFilter, query, sortKey, sortDir]);

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  };

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

      {/* Search field + filter pills. The search is the headline tool
          because admins typically know who they're looking for; the
          PERSON/COMPANY pills are a coarse secondary cut. */}
      <Stack spacing={1.5}>
        <TextField
          size="small"
          placeholder="Suchen — Name, E-Mail, Telefon, Stadt, Impower-ID"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          sx={{ maxWidth: 480 }}
          slotProps={{
            input: {
              startAdornment: (
                <SearchIcon
                  fontSize="small"
                  sx={{ color: "text.secondary", mr: 1 }}
                />
              ),
            },
          }}
        />
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
      </Stack>

      {visibleRows.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          {query.trim() || kindFilter
            ? "Keine Treffer."
            : t("admin.stammdaten.empty")}
        </Typography>
      ) : (
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <SortableHead
                  label={t("admin.contactsPage.name")}
                  active={sortKey === "name"}
                  dir={sortDir}
                  onClick={() => toggleSort("name")}
                />
                <SortableHead
                  label={t("admin.contactsPage.email")}
                  active={sortKey === "email"}
                  dir={sortDir}
                  onClick={() => toggleSort("email")}
                />
                <SortableHead
                  label={t("admin.contactsPage.phone")}
                  active={sortKey === "phone"}
                  dir={sortDir}
                  onClick={() => toggleSort("phone")}
                />
                <SortableHead
                  label={t("admin.contactsPage.city")}
                  active={sortKey === "city"}
                  dir={sortDir}
                  onClick={() => toggleSort("city")}
                />
                <SortableHead
                  label={t("admin.contactsPage.impowerId")}
                  active={sortKey === "impower_id"}
                  dir={sortDir}
                  onClick={() => toggleSort("impower_id")}
                />
              </TableRow>
            </TableHead>
            <TableBody>
              {visibleRows.map((c) => {
                const impowerHref =
                  c.impower_id != null
                    ? impowerContactUrl(c.kind, c.impower_id)
                    : null;
                return (
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
                      {impowerHref ? (
                        <Link
                          href={impowerHref}
                          target="_blank"
                          rel="noopener noreferrer"
                          underline="hover"
                          sx={{
                            display: "inline-flex",
                            alignItems: "center",
                            gap: 0.5,
                            fontSize: "0.75rem",
                          }}
                          // Stop the row's hover effect from intercepting
                          // the click on big touch targets like iPad.
                          onClick={(e) => e.stopPropagation()}
                        >
                          {c.impower_id}
                          <OpenInNewIcon sx={{ fontSize: 12 }} />
                        </Link>
                      ) : (
                        <Typography variant="caption" color="text.secondary">
                          —
                        </Typography>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
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

function readSortField(
  c: AdminContactListItem,
  key: SortKey,
): string | number | null {
  switch (key) {
    case "name":
      return c.name;
    case "email":
      return c.email;
    case "phone":
      return c.phone;
    case "city":
      return c.city;
    case "impower_id":
      return c.impower_id;
  }
}

/// Header cell wrapped in a TableSortLabel — clicking flips through
/// asc → desc → asc on the same key, or switches the active key with
/// asc as the default. The TableSortLabel's built-in arrow visually
/// indicates direction.
function SortableHead({
  label,
  active,
  dir,
  onClick,
}: {
  label: string;
  active: boolean;
  dir: SortDir;
  onClick: () => void;
}) {
  return (
    <TableCell sortDirection={active ? dir : false}>
      <TableSortLabel
        active={active}
        direction={active ? dir : "asc"}
        onClick={onClick}
      >
        {label}
      </TableSortLabel>
    </TableCell>
  );
}
