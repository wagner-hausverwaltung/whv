// Einladungen tab on the admin property detail.
//
// Lists every contact linked to the property via active contracts +
// their account/invite status, with per-row "Einladen" / "Erneut
// senden" buttons + a top-level "Alle einladen" that picks every
// row eligible for an invite.
//
// "Eligible" = the row's status chip is anything except a green
// "Konto vorhanden" (i.e. PENDING + EXPIRED + NEVER_INVITED counts;
// SKIPPED_NO_EMAIL is also skipped server-side so the button silently
// gives up on those).

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import GroupAddIcon from "@mui/icons-material/GroupAdd";
import MailOutlineIcon from "@mui/icons-material/MailOutline";
import { api } from "@/api/client";

interface AdminPropertyContactInviteInfo {
  code: string;
  expires_at: string;
  created_at: string;
}

interface AdminPropertyContactResponse {
  contact_id: string;
  impower_id: number | null;
  name: string;
  email: string | null;
  contract_type: string;
  suggested_role: string;
  has_user_account: boolean;
  pending_invite: AdminPropertyContactInviteInfo | null;
  last_invited_at: string | null;
}

type BulkOutcomeStatus =
  | "sent"
  | "resent"
  | "skipped_account_exists"
  | "skipped_no_email"
  | "skipped_no_role"
  | "failed";

interface BulkInviteOutcome {
  contact_id: string;
  status: BulkOutcomeStatus;
  code: string | null;
  email: string | null;
  reason: string | null;
}

interface PropertyInvitesTabProps {
  propertyId: string;
}

function StatusChip({ contact }: { contact: AdminPropertyContactResponse }) {
  if (contact.has_user_account) {
    return <Chip size="small" color="success" label="Konto vorhanden" />;
  }
  if (contact.pending_invite) {
    const exp = new Date(contact.pending_invite.expires_at);
    return (
      <Chip
        size="small"
        color="warning"
        label={`Eingeladen · läuft ab ${exp.toLocaleDateString("de-DE")}`}
      />
    );
  }
  if (contact.last_invited_at) {
    return <Chip size="small" variant="outlined" color="default" label="Abgelaufen" />;
  }
  return <Chip size="small" variant="outlined" color="default" label="Noch nicht eingeladen" />;
}

function OutcomeChip({ status }: { status: BulkOutcomeStatus }) {
  const map: Record<BulkOutcomeStatus, { label: string; color: "success" | "warning" | "default" | "error" }> = {
    sent: { label: "Gesendet", color: "success" },
    resent: { label: "Erneut gesendet", color: "success" },
    skipped_account_exists: { label: "Konto existiert", color: "default" },
    skipped_no_email: { label: "Keine E-Mail", color: "default" },
    skipped_no_role: { label: "Keine Rolle", color: "default" },
    failed: { label: "Fehlgeschlagen", color: "error" },
  };
  const { label, color } = map[status];
  return <Chip size="small" color={color} label={label} />;
}

export function PropertyInvitesTab({ propertyId }: PropertyInvitesTabProps) {
  const [rows, setRows] = useState<AdminPropertyContactResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [outcomes, setOutcomes] = useState<Record<string, BulkOutcomeStatus>>({});
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const load = useCallback(async () => {
    setError(null);
    try {
      const r = await api.get<AdminPropertyContactResponse[]>(
        `/admin/properties/${propertyId}/contacts`,
      );
      setRows(r.data);
    } catch {
      setError("Kontakte konnten nicht geladen werden.");
    }
  }, [propertyId]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const eligibleIds = useMemo(() => {
    if (!rows) return [] as string[];
    return rows
      .filter((r) => !r.has_user_account && r.email)
      .map((r) => r.contact_id);
  }, [rows]);

  const allSelected =
    eligibleIds.length > 0 && eligibleIds.every((id) => selected.has(id));

  const toggleAll = () => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (allSelected) {
        eligibleIds.forEach((id) => next.delete(id));
      } else {
        eligibleIds.forEach((id) => next.add(id));
      }
      return next;
    });
  };

  const toggleRow = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const invite = async (contactIds: string[]) => {
    if (contactIds.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.post<{ outcomes: BulkInviteOutcome[] }>(
        `/admin/properties/${propertyId}/invites/bulk`,
        { contact_ids: contactIds, ttl_days: 14 },
      );
      const next: Record<string, BulkOutcomeStatus> = { ...outcomes };
      for (const o of r.data.outcomes) {
        next[o.contact_id] = o.status;
      }
      setOutcomes(next);
      setSelected(new Set());
      await load();
    } catch {
      setError("Einladungen konnten nicht versendet werden.");
    } finally {
      setBusy(false);
    }
  };

  if (rows === null) {
    return (
      <Typography variant="body2" color="text.secondary">
        Lade Kontakte…
      </Typography>
    );
  }

  return (
    <Stack spacing={2}>
      {error && <Alert severity="error">{error}</Alert>}

      <Stack
        direction="row"
        spacing={1}
        sx={{ alignItems: "center", flexWrap: "wrap" }}
      >
        <Typography variant="body2" color="text.secondary" sx={{ flex: 1 }}>
          {rows.length} Kontakte aus aktiven Verträgen · {eligibleIds.length}
          {" "}einladbar
        </Typography>
        <Button
          variant="outlined"
          startIcon={<MailOutlineIcon />}
          disabled={busy || selected.size === 0}
          onClick={() => invite(Array.from(selected))}
        >
          Auswahl einladen ({selected.size})
        </Button>
        <Button
          variant="contained"
          startIcon={<GroupAddIcon />}
          disabled={busy || eligibleIds.length === 0}
          onClick={() => invite(eligibleIds)}
        >
          {busy ? "Wird gesendet…" : `Alle einladen (${eligibleIds.length})`}
        </Button>
      </Stack>

      <TableContainer component={Box} variant="outlined" sx={{ border: 1, borderColor: "divider", borderRadius: 1 }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell padding="checkbox">
                <Checkbox
                  size="small"
                  checked={allSelected}
                  indeterminate={
                    selected.size > 0 && !allSelected
                  }
                  onChange={toggleAll}
                  disabled={eligibleIds.length === 0}
                />
              </TableCell>
              <TableCell>Name</TableCell>
              <TableCell>E-Mail</TableCell>
              <TableCell>Vertrag</TableCell>
              <TableCell>Status</TableCell>
              <TableCell align="right">Aktion</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((c) => {
              const eligible = !c.has_user_account && !!c.email;
              const outcome = outcomes[c.contact_id];
              return (
                <TableRow key={c.contact_id} hover>
                  <TableCell padding="checkbox">
                    <Checkbox
                      size="small"
                      checked={selected.has(c.contact_id)}
                      onChange={() => toggleRow(c.contact_id)}
                      disabled={!eligible}
                    />
                  </TableCell>
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
                      {c.contract_type}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Stack direction="row" spacing={0.5} sx={{ alignItems: "center", flexWrap: "wrap", rowGap: 0.5 }}>
                      <StatusChip contact={c} />
                      {outcome && <OutcomeChip status={outcome} />}
                    </Stack>
                  </TableCell>
                  <TableCell align="right">
                    {eligible && (
                      <Button
                        size="small"
                        variant="text"
                        disabled={busy}
                        onClick={() => invite([c.contact_id])}
                      >
                        {c.pending_invite ? "Erneut senden" : "Einladen"}
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              );
            })}
            {rows.length === 0 && (
              <TableRow>
                <TableCell colSpan={6}>
                  <Typography variant="body2" color="text.secondary" sx={{ p: 2 }}>
                    Keine Kontakte über aktive Verträge verknüpft.
                  </Typography>
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </TableContainer>
    </Stack>
  );
}
