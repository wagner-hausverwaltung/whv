import { useCallback, useEffect, useState } from "react";
import { Link as RouterLink, useParams } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Card,
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
  TextField,
  Typography,
} from "@mui/material";
import { useTranslation } from "react-i18next";
import { api, API_BASE_URL } from "@/api/client";
import {
  RESOLUTION_MODE_LABELS,
  RESOLUTION_STATUS_LABELS,
  VOTE_CHOICE_LABELS,
  type ResolutionDetailResponse,
  type ResolutionStatus,
  type VoteChoice,
} from "@/api/types";

function StatusChip({ status }: { status: ResolutionStatus }) {
  const color: "success" | "error" | "info" | "default" =
    status === "ANGENOMMEN"
      ? "success"
      : status === "ABGELEHNT"
        ? "error"
        : status === "OFFEN"
          ? "info"
          : "default";
  return (
    <Chip
      size="small"
      label={RESOLUTION_STATUS_LABELS[status]}
      color={color}
      variant={status === "ENTWURF" || status === "GESCHLOSSEN" ? "outlined" : "filled"}
    />
  );
}

function StatCard({ label, value, color }: { label: string; value: string | number; color?: string }) {
  return (
    <Paper variant="outlined" sx={{ p: 2, textAlign: "center" }}>
      <Typography
        variant="h4"
        sx={{ fontWeight: 700, color: color ?? "inherit", lineHeight: 1, mb: 0.5 }}
      >
        {value}
      </Typography>
      <Typography variant="caption" color="text.secondary">
        {label}
      </Typography>
    </Paper>
  );
}

function VoteCell({ choice }: { choice: VoteChoice }) {
  const color =
    choice === "JA" ? "success.main" : choice === "NEIN" ? "error.main" : "text.secondary";
  return (
    <Typography variant="body2" sx={{ color, fontWeight: 600 }}>
      {VOTE_CHOICE_LABELS[choice]}
    </Typography>
  );
}

export function AdminResolutionDetailPage() {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();
  const [resolution, setResolution] =
    useState<ResolutionDetailResponse | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [closing, setClosing] = useState(false);
  const [sending, setSending] = useState(false);
  const [sendResult, setSendResult] = useState<{
    sent: number;
    no_email: { owner_contact_id_impower: number; owner_name: string | null }[];
  } | null>(null);
  const [editing, setEditing] = useState(false);
  const [editTitle, setEditTitle] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [savingEdit, setSavingEdit] = useState(false);

  const refresh = useCallback(async () => {
    if (!id) return;
    try {
      const r = await api.get<ResolutionDetailResponse>(
        `/admin/resolutions/${id}`,
      );
      setResolution(r.data);
    } catch (err: unknown) {
      const httpStatus = (err as { response?: { status?: number } }).response
        ?.status;
      if (httpStatus === 404) setNotFound(true);
      else setError(t("admin.resolutionDetail.loadFailed"));
    }
  }, [id, t]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh();
  }, [refresh]);

  const closeNow = async () => {
    if (!id) return;
    if (!window.confirm(t("admin.resolutionDetail.closeConfirm"))) return;
    setClosing(true);
    setError(null);
    try {
      await api.post(`/admin/resolutions/${id}/close`);
      await refresh();
    } catch {
      setError(t("admin.resolutionDetail.actionFailed"));
    } finally {
      setClosing(false);
    }
  };

  const saveEdit = async () => {
    if (!id) return;
    setSavingEdit(true);
    setError(null);
    try {
      await api.patch(`/admin/resolutions/${id}`, {
        title: editTitle,
        description: editDescription,
      });
      await refresh();
      setEditing(false);
    } catch {
      setError(t("admin.resolutionDetail.actionFailed"));
    } finally {
      setSavingEdit(false);
    }
  };

  const sendNow = async () => {
    if (!id) return;
    setSending(true);
    setError(null);
    try {
      const res = await api.post<{
        sent: number;
        no_email: { owner_contact_id_impower: number; owner_name: string | null }[];
      }>(`/admin/resolutions/${id}/send`);
      setSendResult(res.data);
      await refresh();
    } catch {
      setError(t("admin.resolutionDetail.actionFailed"));
    } finally {
      setSending(false);
    }
  };

  if (notFound) {
    return (
      <Stack spacing={2}>
        <Alert severity="error">{t("admin.resolutionDetail.notFound")}</Alert>
        <Link component={RouterLink} to="/admin/resolutions">
          {t("admin.resolutionDetail.back")}
        </Link>
      </Stack>
    );
  }
  if (resolution === null) {
    if (error) return <Alert severity="error">{error}</Alert>;
    return (
      <Typography variant="body2" color="text.secondary">
        {t("common.loading")}
      </Typography>
    );
  }

  const r = resolution;
  const tally = r.tally;
  const isOpen = r.status === "OFFEN";

  return (
    <Stack spacing={3}>
      <Box>
        <Link component={RouterLink} to="/admin/resolutions" color="text.secondary">
          {t("admin.resolutionDetail.back")}
        </Link>
      </Box>

      <Box>
        <Typography variant="h4" component="h1" gutterBottom>
          {r.title}
        </Typography>
        <Stack
          direction="row"
          spacing={1}
          sx={{ alignItems: "center", flexWrap: "wrap", gap: 1, mb: 0.5 }}
        >
          <StatusChip status={r.status} />
          <Typography variant="caption" color="text.secondary">
            · {RESOLUTION_MODE_LABELS[r.mode]} ·{" "}
            {t("admin.resolutionDetail.opens")}{" "}
            {new Date(r.opens_at).toLocaleString("de-DE")} ·{" "}
            {t("admin.resolutionDetail.closes")}{" "}
            {new Date(r.closes_at).toLocaleString("de-DE")}
            {r.decided_at &&
              ` · ${t("admin.resolutionDetail.decided")} ${new Date(
                r.decided_at,
              ).toLocaleString("de-DE")}`}
          </Typography>
        </Stack>
      </Box>

      {error && <Alert severity="error">{error}</Alert>}

      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: {
            xs: "1fr 1fr",
            sm: "repeat(3, 1fr)",
            md: "repeat(6, 1fr)",
          },
          gap: 2,
        }}
      >
        <StatCard
          label={t("admin.resolutionDetail.eligible")}
          value={tally.eligible_voters}
        />
        <StatCard label={t("admin.resolutionDetail.cast")} value={tally.cast} />
        <StatCard
          label={t("admin.resolutionDetail.ja")}
          value={tally.ja}
          color="success.main"
        />
        <StatCard
          label={t("admin.resolutionDetail.nein")}
          value={tally.nein}
          color="error.main"
        />
        <StatCard
          label={t("admin.resolutionDetail.enthaltung")}
          value={tally.enthaltung}
        />
        <StatCard
          label={
            r.mode === "KLASSISCH"
              ? t("admin.resolutionDetail.unanimous")
              : t("admin.resolutionDetail.quorumRequired")
          }
          value={
            r.mode === "KLASSISCH"
              ? tally.unanimous_yes
                ? "✓"
                : "✗"
              : r.required_quorum
          }
        />
      </Box>

      {r.status === "ENTWURF" && (
        <Box>
          {editing ? (
            <Stack spacing={1.5}>
              <TextField
                label={t("admin.resolutionDetail.editTitle")}
                value={editTitle}
                onChange={(e) => setEditTitle(e.target.value)}
                fullWidth
                size="small"
              />
              <TextField
                label={t("admin.resolutionDetail.editDescription")}
                value={editDescription}
                onChange={(e) => setEditDescription(e.target.value)}
                fullWidth
                multiline
                minRows={4}
              />
              <Stack direction="row" spacing={1}>
                <Button
                  variant="contained"
                  onClick={saveEdit}
                  disabled={savingEdit || editTitle.trim().length < 3}
                >
                  {savingEdit ? t("common.loading") : t("admin.resolutionDetail.editSave")}
                </Button>
                <Button onClick={() => setEditing(false)} disabled={savingEdit}>
                  {t("admin.resolutionDetail.editCancel")}
                </Button>
              </Stack>
            </Stack>
          ) : (
            <Button
              variant="outlined"
              onClick={() => {
                setEditTitle(r.title);
                setEditDescription(r.description);
                setEditing(true);
              }}
            >
              {t("admin.resolutionDetail.editAction")}
            </Button>
          )}
        </Box>
      )}

      {(r.status === "ENTWURF" || r.status === "OFFEN") && (
        <Box>
          <Button variant="contained" onClick={sendNow} disabled={sending}>
            {sending ? t("common.loading") : t("admin.resolutionDetail.sendAction")}
          </Button>
          <Typography variant="caption" color="text.secondary" sx={{ ml: 2 }}>
            {t("admin.resolutionDetail.sendHint")}
          </Typography>
          {sendResult && (
            <Alert severity="success" sx={{ mt: 1.5 }}>
              {t("admin.resolutionDetail.sendResult", { sent: sendResult.sent })}
              {sendResult.no_email.length > 0 && (
                <Box sx={{ mt: 1 }}>
                  <Typography variant="body2" sx={{ fontWeight: 600 }}>
                    {t("admin.resolutionDetail.noEmailTitle")}
                  </Typography>
                  <ul style={{ margin: "4px 0 0", paddingLeft: 20 }}>
                    {sendResult.no_email.map((o) => (
                      <li key={o.owner_contact_id_impower}>
                        {o.owner_name ?? `Kontakt ${o.owner_contact_id_impower}`}
                      </li>
                    ))}
                  </ul>
                </Box>
              )}
            </Alert>
          )}
        </Box>
      )}

      {isOpen && (
        <Box>
          <Button
            variant="contained"
            color="secondary"
            onClick={closeNow}
            disabled={closing}
          >
            {closing ? t("common.loading") : t("admin.resolutionDetail.closeAction")}
          </Button>
          <Typography
            variant="caption"
            color="text.secondary"
            sx={{ ml: 2 }}
          >
            {t("admin.resolutionDetail.closeHint")}
          </Typography>
        </Box>
      )}

      {r.result && (
        <Alert severity={r.status === "ANGENOMMEN" ? "success" : "info"}>
          <strong>{t("admin.resolutionDetail.result")}:</strong> {r.result}
          {r.result_pdf_url && (
            <>
              {" · "}
              <Link
                href={`${API_BASE_URL}/admin/resolutions/${r.id}/result.pdf`}
                target="_blank"
                rel="noopener noreferrer"
              >
                {t("admin.resolutionDetail.downloadPdf")}
              </Link>
            </>
          )}
        </Alert>
      )}

      <Card variant="outlined" sx={{ p: 2 }}>
        <Typography variant="subtitle1" gutterBottom>
          {t("admin.resolutionDetail.description")}
        </Typography>
        <Typography variant="body2" sx={{ whiteSpace: "pre-wrap" }}>
          {r.description}
        </Typography>
      </Card>

      <Box>
        <Typography variant="subtitle1" gutterBottom>
          {t("admin.resolutionDetail.votes")} ({r.votes.length})
        </Typography>
        {r.votes.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            {t("admin.resolutionDetail.noVotes")}
          </Typography>
        ) : (
          <TableContainer component={Paper} variant="outlined">
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>{t("admin.resolutionDetail.owner")}</TableCell>
                  <TableCell>{t("admin.resolutionDetail.vote")}</TableCell>
                  <TableCell>{t("admin.resolutionDetail.voted")}</TableCell>
                  <TableCell>{t("admin.resolutionDetail.method")}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {r.votes.map((v) => (
                  <TableRow key={v.id} hover>
                    <TableCell
                      sx={{
                        fontFamily: "ui-monospace, Menlo, monospace",
                      }}
                    >
                      {v.owner_contact_id_impower}
                    </TableCell>
                    <TableCell>
                      <VoteCell choice={v.choice} />
                    </TableCell>
                    <TableCell>
                      <Typography variant="caption" color="text.secondary">
                        {new Date(v.voted_at).toLocaleString("de-DE")}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      <Typography variant="caption" color="text.secondary">
                        {v.signature_method}
                      </Typography>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </Box>

      <BallotsPanel resolutionId={id ?? ""} isOpen={isOpen} onChanged={refresh} />
    </Stack>
  );
}

interface BallotStatusRow {
  owner_contact_id_impower: number;
  owner_name: string | null;
  owner_email: string | null;
  has_voted: boolean;
  choice: VoteChoice | null;
}

/// Per-owner voting status — shows who's voted (and how), flags owners
/// without an email ("ohne E-Mail"), and lets the Verwalter record a
/// postal vote for anyone still open while the resolution is OFFEN.
/// Self-hides until ballots exist (i.e. after "Jetzt versenden").
function BallotsPanel({
  resolutionId,
  isOpen,
  onChanged,
}: {
  resolutionId: string;
  isOpen: boolean;
  onChanged: () => void | Promise<void>;
}) {
  const { t } = useTranslation();
  const [rows, setRows] = useState<BallotStatusRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);

  const load = useCallback(async () => {
    if (!resolutionId) return;
    try {
      const r = await api.get<BallotStatusRow[]>(
        `/admin/resolutions/${resolutionId}/ballots`,
      );
      setRows(r.data);
    } catch {
      setError(t("admin.resolutionDetail.actionFailed"));
    }
  }, [resolutionId, t]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const recordVote = async (owner: number, choice: VoteChoice) => {
    setBusy(owner);
    setError(null);
    try {
      await api.post(`/admin/resolutions/${resolutionId}/manual-vote`, {
        owner_contact_id_impower: owner,
        choice,
      });
      await load();
      await onChanged();
    } catch {
      setError(t("admin.resolutionDetail.actionFailed"));
    } finally {
      setBusy(null);
    }
  };

  if (rows === null || rows.length === 0) return null;

  const choices: VoteChoice[] = ["JA", "NEIN", "ENTHALTUNG"];

  return (
    <Box>
      <Typography variant="subtitle1" gutterBottom>
        {t("admin.resolutionDetail.ballotStatus")} ({rows.length})
      </Typography>
      {error && (
        <Alert severity="error" sx={{ mb: 1 }}>
          {error}
        </Alert>
      )}
      <Paper variant="outlined">
        <Stack divider={<Box sx={{ borderBottom: 1, borderColor: "divider" }} />}>
          {rows.map((b) => (
            <Stack
              key={b.owner_contact_id_impower}
              direction="row"
              spacing={2}
              sx={{ p: 1.5, alignItems: "center", flexWrap: "wrap", gap: 1 }}
            >
              <Box sx={{ flex: 1, minWidth: 160 }}>
                <Typography variant="body2">
                  {b.owner_name ?? `Kontakt ${b.owner_contact_id_impower}`}
                </Typography>
                {b.owner_email ? (
                  <Typography variant="caption" color="text.secondary">
                    {b.owner_email}
                  </Typography>
                ) : (
                  <Chip
                    size="small"
                    color="warning"
                    variant="outlined"
                    label={t("admin.resolutionDetail.noEmailChip")}
                  />
                )}
              </Box>
              {b.has_voted ? (
                <Chip
                  size="small"
                  color="success"
                  label={b.choice ? VOTE_CHOICE_LABELS[b.choice] : "✓"}
                />
              ) : isOpen ? (
                <Stack direction="row" spacing={0.5}>
                  {choices.map((c) => (
                    <Button
                      key={c}
                      size="small"
                      variant="outlined"
                      disabled={busy === b.owner_contact_id_impower}
                      onClick={() => recordVote(b.owner_contact_id_impower, c)}
                    >
                      {VOTE_CHOICE_LABELS[c]}
                    </Button>
                  ))}
                </Stack>
              ) : (
                <Typography variant="caption" color="text.secondary">
                  —
                </Typography>
              )}
            </Stack>
          ))}
        </Stack>
      </Paper>
      {isOpen && (
        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1 }}>
          {t("admin.resolutionDetail.paperVoteHint")}
        </Typography>
      )}
    </Box>
  );
}
