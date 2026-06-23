// Eigentümerversammlung detail — single page covering the entire
// lifecycle: edit header, build Tagesordnung, record discussion +
// vote tallies, upload signed protocol.
//
// Layout (top → bottom):
//   - Breadcrumb / back link
//   - Header card: title + status + start/end + location, "Bearbeiten"
//     toggles inline edit on those fields
//   - Tagesordnung: ordered list of agenda items. Each row is
//     expandable; expanded shows body + (BESCHLUSS only) tally fields +
//     discussion entries. Inline "TOP hinzufügen" composer at the bottom.
//   - Signed-protocol upload + download

import { useCallback, useEffect, useMemo, useState, type ChangeEvent } from "react";
import { Link as RouterLink, useNavigate, useParams } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  IconButton,
  Link,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import AddTaskOutlinedIcon from "@mui/icons-material/AddTaskOutlined";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import DeleteIcon from "@mui/icons-material/DeleteOutlined";
import EditIcon from "@mui/icons-material/EditOutlined";
import SaveIcon from "@mui/icons-material/Save";
import AttachFileIcon from "@mui/icons-material/AttachFile";
import CancelIcon from "@mui/icons-material/Close";
import CloudUploadIcon from "@mui/icons-material/CloudUpload";
import DownloadIcon from "@mui/icons-material/DownloadOutlined";
import PictureAsPdfIcon from "@mui/icons-material/PictureAsPdfOutlined";
import HistoryEduIcon from "@mui/icons-material/HistoryEduOutlined";
import VideocamIcon from "@mui/icons-material/Videocam";
import { api } from "@/api/client";
import { AssemblyComments } from "@/pages/AssemblyComments";
import {
  AGENDA_ITEM_TYPE_LABELS,
  ASSEMBLY_STATUS_LABELS,
  type AgendaItemResponse,
  type AgendaItemType,
  type AgendaItemVoteResult,
  type AgendaItemVotingBasis,
  type AssemblyDetailResponse,
  type AssemblyStatus,
} from "@/api/types";

const STATUS_OPTIONS: AssemblyStatus[] = [
  "GEPLANT",
  "EINGELADEN",
  "ABGEHALTEN",
  "ABGESAGT",
];
const AGENDA_TYPES: AgendaItemType[] = ["INFORMATION", "BESCHLUSS", "DISKUSSION"];

function toDtLocal(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => n.toString().padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function StatusChip({ status }: { status: AssemblyStatus }) {
  const color =
    status === "ABGEHALTEN"
      ? "success"
      : status === "EINGELADEN"
        ? "primary"
        : status === "ABGESAGT"
          ? "error"
          : "default";
  return (
    <Chip
      size="small"
      label={ASSEMBLY_STATUS_LABELS[status]}
      color={color as "default" | "primary" | "success" | "error"}
    />
  );
}

export function AdminAssemblyDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [assembly, setAssembly] = useState<AssemblyDetailResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!id) return;
    setError(null);
    try {
      const r = await api.get<AssemblyDetailResponse>(`/admin/assemblies/${id}`);
      setAssembly(r.data);
    } catch {
      setError("Versammlung konnte nicht geladen werden.");
    }
  }, [id]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  if (!id) return null;

  if (error) {
    return (
      <Stack spacing={2}>
        <Link component={RouterLink} to="/admin/assemblies">
          ← Zurück zur Übersicht
        </Link>
        <Alert severity="error">{error}</Alert>
      </Stack>
    );
  }
  if (!assembly) {
    return (
      <Typography variant="body2" color="text.secondary">
        Wird geladen…
      </Typography>
    );
  }

  return (
    <Stack spacing={3}>
      <Link component={RouterLink} to="/admin/assemblies" color="text.secondary">
        ← Zurück zur Übersicht
      </Link>

      <AssemblyHeader
        assembly={assembly}
        onChanged={(a) => setAssembly(a)}
        onDeleted={() => navigate("/admin/assemblies")}
      />

      <InvitationSection
        assembly={assembly}
        onChanged={(a) => setAssembly(a)}
      />

      <AgendaSection
        assembly={assembly}
        onChanged={(a) => setAssembly(a)}
      />

      <ProtocolSignatureSection assembly={assembly} />

      <ProtocolSection
        assembly={assembly}
        onChanged={(a) => setAssembly(a)}
      />

      {/* Verwalter participates in the Q&A from the same surface
          they edit the assembly on — fewer tabs to bounce between. */}
      <AssemblyComments assemblyId={assembly.id} />
    </Stack>
  );
}

// =================================================================
// Versammlungsprotokoll PDF (WHV design) + send-for-signature
// =================================================================

// Minimal shape of /admin/properties/{id}/contacts — just the fields
// needed to prefill the signer (full type lives in PropertyInvitesTab).
interface OwnerContactRow {
  name: string;
  email: string | null;
  suggested_role: string;
}

function ProtocolSignatureSection({ assembly }: { assembly: AssemblyDetailResponse }) {
  const [error, setError] = useState<string | null>(null);
  const [sendOpen, setSendOpen] = useState(false);

  const openPdf = async () => {
    // Authed fetch → blob → new tab (a plain <a href> would 401, the
    // browser doesn't attach the JWT header). Mirrors the invitation
    // download below.
    setError(null);
    try {
      const r = await api.get(`/admin/assemblies/${assembly.id}/document.pdf`, {
        responseType: "blob",
      });
      const url = URL.createObjectURL(r.data as Blob);
      window.open(url, "_blank", "noopener,noreferrer");
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch {
      setError("PDF konnte nicht erstellt werden.");
    }
  };

  return (
    <Paper sx={{ p: 3 }}>
      <Typography variant="h6" sx={{ mb: 1 }}>
        Versammlungsprotokoll (WHV-Design)
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Erzeugt aus Tagesordnung und Details ein gebrandetes PDF — auch für
        Mietverwaltungen, für die Impower keine ETV anlegt. Optional direkt an
        eine Eigentümerin / einen Eigentümer zur digitalen Unterschrift senden.
      </Typography>
      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
        <Button
          variant="outlined"
          startIcon={<PictureAsPdfIcon />}
          onClick={() => void openPdf()}
        >
          PDF-Export
        </Button>
        <Button
          variant="contained"
          startIcon={<HistoryEduIcon />}
          onClick={() => setSendOpen(true)}
        >
          Zur Unterschrift senden
        </Button>
      </Stack>
      {sendOpen && (
        <SendForSignatureDialog assembly={assembly} onClose={() => setSendOpen(false)} />
      )}
    </Paper>
  );
}

function SendForSignatureDialog({
  assembly,
  onClose,
}: {
  assembly: AssemblyDetailResponse;
  onClose: () => void;
}) {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sentTo, setSentTo] = useState<string | null>(null);

  // Best-effort prefill from the property's first owner contact; the
  // field stays editable and a failed fetch just leaves it blank.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const r = await api.get<OwnerContactRow[]>(
          `/admin/properties/${assembly.property_id}/contacts`,
        );
        const owner = r.data.find((c) => c.suggested_role === "EIGENTUEMER" && c.email);
        if (!cancelled && owner?.email) {
          setEmail(owner.email);
          setName(owner.name);
        }
      } catch {
        /* prefill is optional */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [assembly.property_id]);

  const canSubmit = /\S+@\S+\.\S+/.test(email.trim());

  const submit = async () => {
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    try {
      await api.post(`/admin/assemblies/${assembly.id}/signature-request`, {
        recipient_email: email.trim(),
        recipient_name: name.trim() || null,
      });
      setSentTo(email.trim());
    } catch (e) {
      // Surface the backend's German detail (e.g. 503 "Signatur-Dienst ist
      // nicht konfiguriert." until DocuSeal is provisioned).
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data
        ?.detail;
      setError(detail ?? "Die Anfrage konnte nicht gesendet werden.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Protokoll zur Unterschrift senden</DialogTitle>
      <DialogContent>
        {sentTo ? (
          <Alert severity="success" sx={{ mt: 1 }}>
            Das Protokoll wurde an {sentTo} zur digitalen Unterschrift gesendet. Den
            Status sehen Sie im Bereich Signaturen.
          </Alert>
        ) : (
          <Stack spacing={2} sx={{ mt: 1 }}>
            {error && <Alert severity="error">{error}</Alert>}
            <TextField
              label="E-Mail der Empfängerin / des Empfängers"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              fullWidth
              required
            />
            <TextField
              label="Name (optional)"
              value={name}
              onChange={(e) => setName(e.target.value)}
              fullWidth
            />
            <Typography variant="caption" color="text.secondary">
              Das gebrandete Versammlungsprotokoll wird erzeugt und per E-Mail über
              DocuSeal zur Unterschrift versendet — ein Portal-Konto ist dafür nicht
              nötig.
            </Typography>
          </Stack>
        )}
      </DialogContent>
      <DialogActions>
        {sentTo ? (
          <Button onClick={onClose}>Schließen</Button>
        ) : (
          <>
            <Button onClick={onClose} disabled={busy}>
              Abbrechen
            </Button>
            <Button variant="contained" onClick={() => void submit()} disabled={!canSubmit || busy}>
              Senden
            </Button>
          </>
        )}
      </DialogActions>
    </Dialog>
  );
}

// =================================================================
// Header — read view + inline edit
// =================================================================

interface HeaderProps {
  assembly: AssemblyDetailResponse;
  onChanged: (a: AssemblyDetailResponse) => void;
  onDeleted: () => void;
}

function AssemblyHeader({ assembly, onChanged, onDeleted }: HeaderProps) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(assembly.title);
  const [description, setDescription] = useState(assembly.description);
  const [status, setStatus] = useState<AssemblyStatus>(assembly.status);
  const [location, setLocation] = useState(assembly.location);
  const [teamsUrl, setTeamsUrl] = useState(assembly.teams_meeting_url ?? "");
  const [start, setStart] = useState(toDtLocal(assembly.scheduled_start));
  const [end, setEnd] = useState(toDtLocal(assembly.scheduled_end));
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const startEdit = () => {
    setTitle(assembly.title);
    setDescription(assembly.description);
    setStatus(assembly.status);
    setLocation(assembly.location);
    setTeamsUrl(assembly.teams_meeting_url ?? "");
    setStart(toDtLocal(assembly.scheduled_start));
    setEnd(toDtLocal(assembly.scheduled_end));
    setEditing(true);
    setError(null);
  };

  const save = async () => {
    setError(null);
    setSubmitting(true);
    try {
      const r = await api.patch<AssemblyDetailResponse>(
        `/admin/assemblies/${assembly.id}`,
        {
          title,
          description,
          status,
          location,
          // Empty string clears the URL via the backend's validator.
          teams_meeting_url: teamsUrl.trim(),
          scheduled_start: new Date(start).toISOString(),
          scheduled_end: new Date(end).toISOString(),
        },
      );
      onChanged(r.data);
      setEditing(false);
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Speichern fehlgeschlagen.";
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  };

  const remove = async () => {
    if (
      !window.confirm(
        "Versammlung löschen? Sie wird auf dem Portal nicht mehr angezeigt.",
      )
    )
      return;
    try {
      await api.delete(`/admin/assemblies/${assembly.id}`);
      onDeleted();
    } catch {
      setError("Löschen fehlgeschlagen.");
    }
  };

  return (
    <Paper sx={{ p: 3 }} variant="outlined">
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      {!editing ? (
        <Stack spacing={1.5}>
          <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 2 }}>
            <Box>
              {assembly.property_name && (
                <Typography
                  variant="overline"
                  color="text.secondary"
                  sx={{ letterSpacing: 0.5, display: "block", mb: 0.5 }}
                >
                  {assembly.property_name}
                  {assembly.property_hr_id && (
                    <Box
                      component="span"
                      sx={{
                        ml: 1,
                        fontFamily: "ui-monospace, Menlo, monospace",
                        opacity: 0.7,
                      }}
                    >
                      {assembly.property_hr_id}
                    </Box>
                  )}
                </Typography>
              )}
              <Typography variant="h4" component="h1">
                {assembly.title}
              </Typography>
              <Stack
                direction="row"
                spacing={1}
                sx={{ mt: 1, flexWrap: "wrap", rowGap: 1 }}
              >
                <StatusChip status={assembly.status} />
                <Chip
                  size="small"
                  variant="outlined"
                  label={`Ort: ${assembly.location}`}
                />
                {assembly.teams_meeting_url && (
                  <Chip
                    size="small"
                    variant="filled"
                    icon={<VideocamIcon />}
                    label="Teams-Link gesetzt"
                    sx={{
                      bgcolor: "#4B53BC",
                      color: "#fff",
                      "& .MuiChip-icon": { color: "#fff" },
                    }}
                  />
                )}
              </Stack>
            </Box>
            <Stack direction="row" spacing={1}>
              <Button startIcon={<EditIcon />} onClick={startEdit}>
                Bearbeiten
              </Button>
              <IconButton color="error" onClick={remove} aria-label="Löschen">
                <DeleteIcon />
              </IconButton>
            </Stack>
          </Box>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={3}>
            <DetailField
              label="Geplanter Beginn"
              value={new Date(assembly.scheduled_start).toLocaleString("de-DE")}
            />
            <DetailField
              label="Geplantes Ende"
              value={new Date(assembly.scheduled_end).toLocaleString("de-DE")}
            />
          </Stack>
          {assembly.description && (
            <Typography variant="body2" sx={{ whiteSpace: "pre-wrap", color: "text.secondary" }}>
              {assembly.description}
            </Typography>
          )}
        </Stack>
      ) : (
        <Stack spacing={2}>
          <TextField
            label="Titel"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
            fullWidth
          />
          <TextField
            label="Status"
            select
            value={status}
            onChange={(e) => setStatus(e.target.value as AssemblyStatus)}
            fullWidth
          >
            {STATUS_OPTIONS.map((s) => (
              <MenuItem key={s} value={s}>
                {ASSEMBLY_STATUS_LABELS[s]}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            label="Ort"
            value={location}
            onChange={(e) => setLocation(e.target.value)}
            required
            fullWidth
          />
          <TextField
            label="Microsoft-Teams-Link"
            value={teamsUrl}
            onChange={(e) => setTeamsUrl(e.target.value)}
            helperText={
              teamsUrl
                ? "Eigentümer sehen einen 'Teams-Meeting beitreten'-Button auf der Versammlungs-Detailseite."
                : "Wenn die Versammlung hybrid stattfindet, hier den Teams-Link einfügen. Leer lassen für reine Präsenzversammlung."
            }
            placeholder="https://teams.microsoft.com/l/meetup-join/…"
            fullWidth
          />
          <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
            <TextField
              label="Beginn"
              type="datetime-local"
              value={start}
              onChange={(e) => setStart(e.target.value)}
              required
              fullWidth
              slotProps={{ inputLabel: { shrink: true } }}
            />
            <TextField
              label="Ende"
              type="datetime-local"
              value={end}
              onChange={(e) => setEnd(e.target.value)}
              required
              fullWidth
              slotProps={{ inputLabel: { shrink: true } }}
            />
          </Stack>
          <TextField
            label="Beschreibung"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            multiline
            minRows={3}
            fullWidth
          />
          <Stack direction="row" spacing={1}>
            <Button variant="contained" startIcon={<SaveIcon />} onClick={save} disabled={submitting}>
              {submitting ? "Speichern…" : "Speichern"}
            </Button>
            <Button startIcon={<CancelIcon />} onClick={() => setEditing(false)} disabled={submitting}>
              Abbrechen
            </Button>
          </Stack>
        </Stack>
      )}
    </Paper>
  );
}

function DetailField({ label, value }: { label: string; value: string }) {
  return (
    <Box>
      <Typography variant="caption" color="text.secondary" sx={{ textTransform: "uppercase", letterSpacing: 0.5 }}>
        {label}
      </Typography>
      <Typography variant="body2">{value}</Typography>
    </Box>
  );
}

// =================================================================
// Agenda items + discussion
// =================================================================

interface AgendaSectionProps {
  assembly: AssemblyDetailResponse;
  onChanged: (a: AssemblyDetailResponse) => void;
}

function AgendaSection({ assembly, onChanged }: AgendaSectionProps) {
  const refresh = useCallback(async () => {
    const r = await api.get<AssemblyDetailResponse>(`/admin/assemblies/${assembly.id}`);
    onChanged(r.data);
  }, [assembly.id, onChanged]);

  return (
    <Paper sx={{ p: 3 }} variant="outlined">
      <Typography variant="h6" sx={{ mb: 2 }}>
        Tagesordnung
      </Typography>
      <Stack spacing={2}>
        {assembly.agenda_items.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            Noch keine TOPs angelegt.
          </Typography>
        ) : (
          assembly.agenda_items.map((item) => (
            <AgendaItemRow
              key={item.id}
              item={item}
              propertyId={assembly.property_id}
              assemblyTitle={assembly.title}
              onChanged={refresh}
            />
          ))
        )}
        <Divider />
        <NewAgendaItemRow
          assemblyId={assembly.id}
          nextPosition={(assembly.agenda_items.at(-1)?.position ?? 0) + 1}
          onCreated={refresh}
        />
      </Stack>
    </Paper>
  );
}

// Pre-filled "Aufgabe erstellen" dialog: turns an ETV agenda point into
// a Ticket (category SONSTIGES_ETV, internal/PRIVATE) via the standard
// ticket flow — which already notifies the Verwalter team. Mounted only
// while open so the fields initialise fresh from the agenda item.
function CreateTaskFromAgendaDialog({
  item,
  propertyId,
  assemblyTitle,
  onClose,
}: {
  item: AgendaItemResponse;
  propertyId: string;
  assemblyTitle: string;
  onClose: () => void;
}) {
  const navigate = useNavigate();
  const [subject, setSubject] = useState(() => item.title.slice(0, 200));
  const [body, setBody] = useState(() =>
    item.body.trim()
      ? item.body
      : `Aufgabe aus der Eigentümerversammlung "${assemblyTitle}", Tagesordnungspunkt "${item.title}".`,
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [createdId, setCreatedId] = useState<string | null>(null);

  const canSubmit = subject.trim().length >= 3 && body.trim().length >= 3;

  const submit = async () => {
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.post<{ id: string }>("/me/tickets", {
        subject: subject.trim(),
        body: body.trim(),
        category: "SONSTIGES_ETV",
        property_id: propertyId,
        share_scope: "PRIVATE",
      });
      setCreatedId(r.data.id);
    } catch {
      setError("Aufgabe konnte nicht erstellt werden.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Aufgabe aus Tagesordnungspunkt</DialogTitle>
      <DialogContent>
        {createdId ? (
          <Alert severity="success" sx={{ mt: 1 }}>
            Aufgabe wurde erstellt und das Verwalter-Team benachrichtigt.
          </Alert>
        ) : (
          <Stack spacing={2} sx={{ mt: 1 }}>
            {error && <Alert severity="error">{error}</Alert>}
            <TextField
              label="Betreff"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              fullWidth
              required
              slotProps={{ htmlInput: { maxLength: 200 } }}
            />
            <TextField
              label="Beschreibung"
              value={body}
              onChange={(e) => setBody(e.target.value)}
              fullWidth
              required
              multiline
              minRows={4}
            />
            <Typography variant="caption" color="text.secondary">
              Wird als internes Ticket (Kategorie "Eigentümerversammlung")
              angelegt und an das Verwalter-Team gemeldet.
            </Typography>
          </Stack>
        )}
      </DialogContent>
      <DialogActions>
        {createdId ? (
          <>
            <Button onClick={onClose}>Schließen</Button>
            <Button
              variant="contained"
              onClick={() => navigate(`/admin/tickets/${createdId}`)}
            >
              Zur Aufgabe
            </Button>
          </>
        ) : (
          <>
            <Button onClick={onClose} disabled={busy}>
              Abbrechen
            </Button>
            <Button
              variant="contained"
              onClick={() => void submit()}
              disabled={!canSubmit || busy}
            >
              Aufgabe erstellen
            </Button>
          </>
        )}
      </DialogActions>
    </Dialog>
  );
}

interface AgendaItemRowProps {
  item: AgendaItemResponse;
  propertyId: string;
  assemblyTitle: string;
  onChanged: () => Promise<void>;
}

function AgendaItemRow({
  item,
  propertyId,
  assemblyTitle,
  onChanged,
}: AgendaItemRowProps) {
  const [expanded, setExpanded] = useState(false);
  const [taskOpen, setTaskOpen] = useState(false);
  const [voteYes, setVoteYes] = useState(item.vote_yes);
  const [voteNo, setVoteNo] = useState(item.vote_no);
  const [voteAbstain, setVoteAbstain] = useState(item.vote_abstain);
  const [voteResult, setVoteResult] = useState<AgendaItemVoteResult | "">(item.vote_result ?? "");
  const [votingBasis, setVotingBasis] = useState<AgendaItemVotingBasis | "">(
    item.voting_basis ?? "",
  );
  const [presentCount, setPresentCount] = useState<string>(
    item.present_count !== null ? String(item.present_count) : "",
  );
  const [savingVote, setSavingVote] = useState(false);

  const saveVote = async () => {
    setSavingVote(true);
    try {
      const parsedPresent = presentCount.trim();
      await api.patch(`/admin/agenda-items/${item.id}`, {
        vote_yes: voteYes,
        vote_no: voteNo,
        vote_abstain: voteAbstain,
        vote_result: voteResult || null,
        voting_basis: votingBasis || null,
        present_count: parsedPresent ? parseInt(parsedPresent, 10) : null,
      });
      await onChanged();
    } finally {
      setSavingVote(false);
    }
  };

  const remove = async () => {
    if (!window.confirm("TOP löschen?")) return;
    await api.delete(`/admin/agenda-items/${item.id}`);
    await onChanged();
  };

  const total = item.vote_yes + item.vote_no + item.vote_abstain;

  return (
    <Box
      sx={{
        border: "1px solid",
        borderColor: "divider",
        borderRadius: 1,
        p: 2,
        bgcolor: "background.default",
      }}
    >
      <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 2 }}>
        <Box sx={{ cursor: "pointer", flexGrow: 1 }} onClick={() => setExpanded((v) => !v)}>
          <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
            {item.title}
          </Typography>
          {/* Chips under the heading — title already carries the
              TOP number, so a separate position chip is redundant. */}
          <Stack direction="row" spacing={1} sx={{ mt: 0.5, alignItems: "center" }}>
            <Chip
              size="small"
              label={AGENDA_ITEM_TYPE_LABELS[item.type]}
              color={item.type === "BESCHLUSS" ? "primary" : "default"}
              variant={item.type === "BESCHLUSS" ? "filled" : "outlined"}
            />
            {item.vote_result && (
              <Chip
                size="small"
                label={item.vote_result}
                color={item.vote_result === "ANGENOMMEN" ? "success" : "error"}
              />
            )}
          </Stack>
        </Box>
        <Stack
          direction="row"
          spacing={1}
          sx={{ flexShrink: 0, alignItems: "center" }}
        >
          <Button
            size="small"
            variant="outlined"
            startIcon={<AddTaskOutlinedIcon />}
            onClick={() => setTaskOpen(true)}
          >
            Aufgabe erstellen
          </Button>
          <IconButton color="error" onClick={remove} aria-label="TOP löschen">
            <DeleteIcon />
          </IconButton>
        </Stack>
      </Box>

      {taskOpen && (
        <CreateTaskFromAgendaDialog
          item={item}
          propertyId={propertyId}
          assemblyTitle={assemblyTitle}
          onClose={() => setTaskOpen(false)}
        />
      )}

      {expanded && (
        <Stack spacing={2} sx={{ mt: 2 }}>
          {item.body && (
            <Typography variant="body2" sx={{ whiteSpace: "pre-wrap", color: "text.secondary" }}>
              {item.body}
            </Typography>
          )}
          <AgendaItemAttachmentsEditor item={item} onChanged={onChanged} />

          {item.beschluss_text && (
            <Box
              sx={{
                p: 2,
                bgcolor: "action.hover",
                borderLeft: 3,
                borderLeftColor: "primary.main",
              }}
            >
              <Typography variant="caption" color="text.secondary" sx={{ textTransform: "uppercase" }}>
                Beschlusstext
              </Typography>
              <Typography variant="body2" sx={{ whiteSpace: "pre-wrap", mt: 0.5 }}>
                {item.beschluss_text}
              </Typography>
            </Box>
          )}

          {item.type === "BESCHLUSS" && (
            <Box>
              <Typography variant="caption" color="text.secondary" sx={{ textTransform: "uppercase" }}>
                Abstimmungsergebnis ({total} Stimmen)
              </Typography>
              <Stack
                direction="row"
                spacing={1}
                sx={{ mt: 1, flexWrap: "wrap", rowGap: 1, alignItems: "flex-start" }}
              >
                <TextField
                  label="Stimmrecht"
                  select
                  size="small"
                  value={votingBasis}
                  onChange={(e) =>
                    setVotingBasis(e.target.value as AgendaItemVotingBasis | "")
                  }
                  sx={{ minWidth: 180 }}
                >
                  <MenuItem value="">—</MenuItem>
                  <MenuItem value="KOPF">Kopfprinzip</MenuItem>
                  <MenuItem value="MEA">Anteilsprinzip (MEA)</MenuItem>
                  <MenuItem value="OBJEKT">Objektprinzip (Einheiten)</MenuItem>
                </TextField>
                <TextField
                  label="Anwesend"
                  type="number"
                  size="small"
                  value={presentCount}
                  onChange={(e) => setPresentCount(e.target.value)}
                  sx={{ width: 110 }}
                  placeholder=""
                  slotProps={{ htmlInput: { min: 0 } }}
                />
                <TextField
                  label="Ja"
                  type="number"
                  size="small"
                  value={voteYes}
                  onChange={(e) => setVoteYes(parseInt(e.target.value || "0", 10))}
                  sx={{ width: 90 }}
                />
                <TextField
                  label="Nein"
                  type="number"
                  size="small"
                  value={voteNo}
                  onChange={(e) => setVoteNo(parseInt(e.target.value || "0", 10))}
                  sx={{ width: 90 }}
                />
                <TextField
                  label="Enth."
                  type="number"
                  size="small"
                  value={voteAbstain}
                  onChange={(e) => setVoteAbstain(parseInt(e.target.value || "0", 10))}
                  sx={{ width: 90 }}
                />
                <TextField
                  label="Ergebnis"
                  select
                  size="small"
                  value={voteResult}
                  onChange={(e) => setVoteResult(e.target.value as AgendaItemVoteResult | "")}
                  sx={{ minWidth: 140 }}
                >
                  <MenuItem value="">—</MenuItem>
                  <MenuItem value="ANGENOMMEN">Angenommen</MenuItem>
                  <MenuItem value="ABGELEHNT">Abgelehnt</MenuItem>
                </TextField>
                <Button variant="outlined" size="small" onClick={saveVote} disabled={savingVote}>
                  Speichern
                </Button>
              </Stack>
            </Box>
          )}

          <DiscussionSection item={item} onChanged={onChanged} />
        </Stack>
      )}
    </Box>
  );
}

/// Verwalter-side editor for the per-TOP attachments. Upload via a
/// hidden file input → POST as multipart → reload the parent so the
/// new chip appears. Delete via a small × icon on each chip. The
/// portal + iOS sides render these same attachments inline next to
/// the TOP body.
function AgendaItemAttachmentsEditor({
  item,
  onChanged,
}: {
  item: AgendaItemResponse;
  onChanged: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const upload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = ""; // re-allow same-file selection after this run
    if (!file) return;
    setError(null);
    setBusy(true);
    try {
      const form = new FormData();
      form.append("upload", file);
      await api.post(
        `/admin/agenda-items/${item.id}/attachments`,
        form,
      );
      await onChanged();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })
        .response?.data?.detail;
      setError(detail ?? "Upload fehlgeschlagen.");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (attId: string) => {
    if (!window.confirm("Anhang löschen?")) return;
    setBusy(true);
    setError(null);
    try {
      await api.delete(
        `/admin/agenda-items/${item.id}/attachments/${attId}`,
      );
      await onChanged();
    } catch {
      setError("Löschen fehlgeschlagen.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Box>
      <Stack
        direction="row"
        spacing={1}
        sx={{ alignItems: "center", mb: 1 }}
      >
        <Typography
          variant="caption"
          color="text.secondary"
          sx={{ textTransform: "uppercase", letterSpacing: 0.5 }}
        >
          Anhänge
        </Typography>
        <Button
          component="label"
          size="small"
          variant="outlined"
          startIcon={<AttachFileIcon />}
          disabled={busy}
        >
          Hochladen
          <input
            type="file"
            hidden
            onChange={upload}
            // The backend allow-list governs accepted types but we
            // hint to the OS picker so users see PDFs first.
            accept=".pdf,.doc,.docx,.xls,.xlsx,.png,.jpg,.jpeg,.heic"
          />
        </Button>
      </Stack>
      {error && (
        <Alert severity="error" sx={{ mb: 1 }}>
          {error}
        </Alert>
      )}
      {item.attachments.length === 0 ? (
        <Typography variant="caption" color="text.secondary">
          Noch keine Anhänge zu diesem TOP.
        </Typography>
      ) : (
        <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", gap: 1 }}>
          {item.attachments.map((att) => (
            <Chip
              key={att.id}
              icon={<PictureAsPdfIcon />}
              label={att.filename}
              variant="outlined"
              onDelete={() => void remove(att.id)}
              disabled={busy}
            />
          ))}
        </Stack>
      )}
    </Box>
  );
}

function DiscussionSection({
  item,
  onChanged,
}: {
  item: AgendaItemResponse;
  onChanged: () => Promise<void>;
}) {
  const [speaker, setSpeaker] = useState("");
  const [content, setContent] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const nextPosition = (item.discussion.at(-1)?.position ?? 0) + 1;

  const add = async () => {
    if (!speaker.trim() || !content.trim()) return;
    setSubmitting(true);
    try {
      await api.post(`/admin/agenda-items/${item.id}/discussion`, {
        position: nextPosition,
        speaker_label: speaker.trim(),
        content: content.trim(),
      });
      setSpeaker("");
      setContent("");
      await onChanged();
    } finally {
      setSubmitting(false);
    }
  };

  const remove = async (entryId: string) => {
    if (!window.confirm("Eintrag löschen?")) return;
    await api.delete(`/admin/discussion/${entryId}`);
    await onChanged();
  };

  return (
    <Box>
      <Typography variant="caption" color="text.secondary" sx={{ textTransform: "uppercase" }}>
        Diskussion
      </Typography>
      <Stack spacing={1} sx={{ mt: 1 }}>
        {item.discussion.map((d) => (
          <Box
            key={d.id}
            sx={{
              p: 1.5,
              borderRadius: 1,
              bgcolor: "background.paper",
              border: "1px dashed",
              borderColor: "divider",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "flex-start",
              gap: 1,
            }}
          >
            <Box>
              <Typography variant="caption" color="text.secondary">
                {d.speaker_label}
              </Typography>
              <Typography variant="body2" sx={{ whiteSpace: "pre-wrap" }}>
                {d.content}
              </Typography>
            </Box>
            <IconButton size="small" onClick={() => remove(d.id)} aria-label="Eintrag löschen">
              <DeleteIcon fontSize="small" />
            </IconButton>
          </Box>
        ))}
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ alignItems: "center" }}>
          <TextField
            label="Sprecher:in"
            size="small"
            value={speaker}
            onChange={(e) => setSpeaker(e.target.value)}
            placeholder="z. B. Herr Müller (Wo. 4)"
            sx={{ minWidth: 220 }}
          />
          <TextField
            label="Wortbeitrag"
            size="small"
            value={content}
            onChange={(e) => setContent(e.target.value)}
            fullWidth
            multiline
          />
          <Button onClick={add} startIcon={<AddIcon />} size="small" disabled={submitting}>
            Hinzufügen
          </Button>
        </Stack>
      </Stack>
    </Box>
  );
}

interface NewAgendaItemRowProps {
  assemblyId: string;
  nextPosition: number;
  onCreated: () => Promise<void>;
}

function NewAgendaItemRow({ assemblyId, nextPosition, onCreated }: NewAgendaItemRowProps) {
  const [type, setType] = useState<AgendaItemType>("INFORMATION");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [beschlussText, setBeschlussText] = useState("");
  const [quorum, setQuorum] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const canSubmit = useMemo(
    () => title.trim().length > 0 && !submitting,
    [title, submitting],
  );

  const submit = async () => {
    if (!canSubmit) return;
    setError(null);
    setSubmitting(true);
    try {
      const payload: Record<string, unknown> = {
        position: nextPosition,
        type,
        title: title.trim(),
        body: body.trim(),
      };
      if (type === "BESCHLUSS") {
        if (beschlussText.trim()) payload.beschluss_text = beschlussText.trim();
        if (quorum.trim()) payload.vote_required_quorum = parseInt(quorum, 10);
      }
      await api.post(`/admin/assemblies/${assemblyId}/agenda-items`, payload);
      setTitle("");
      setBody("");
      setBeschlussText("");
      setQuorum("");
      setType("INFORMATION");
      await onCreated();
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "TOP konnte nicht hinzugefügt werden.";
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Box sx={{ p: 2, bgcolor: "background.default", borderRadius: 1 }}>
      <Stack spacing={1.5}>
        <Typography variant="caption" color="text.secondary" sx={{ textTransform: "uppercase" }}>
          Neuer TOP (Position {nextPosition})
        </Typography>
        {error && <Alert severity="error">{error}</Alert>}
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
          <TextField
            label="Typ"
            select
            size="small"
            value={type}
            onChange={(e) => setType(e.target.value as AgendaItemType)}
            sx={{ minWidth: 160 }}
          >
            {AGENDA_TYPES.map((tp) => (
              <MenuItem key={tp} value={tp}>
                {AGENDA_ITEM_TYPE_LABELS[tp]}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            label="Titel"
            size="small"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            fullWidth
            required
          />
        </Stack>
        <TextField
          label="Kontext / Beschreibung"
          size="small"
          value={body}
          onChange={(e) => setBody(e.target.value)}
          multiline
          minRows={2}
          fullWidth
        />
        {type === "BESCHLUSS" && (
          <>
            <TextField
              label="Beschlusstext"
              size="small"
              value={beschlussText}
              onChange={(e) => setBeschlussText(e.target.value)}
              multiline
              minRows={2}
              fullWidth
              helperText="Wird wortgetreu im Protokoll abgedruckt."
            />
            <TextField
              label="Quorum (optional)"
              type="number"
              size="small"
              value={quorum}
              onChange={(e) => setQuorum(e.target.value)}
              sx={{ width: 200 }}
            />
          </>
        )}
        <Box sx={{ display: "flex", justifyContent: "flex-end" }}>
          <Button
            startIcon={<AddIcon />}
            variant="contained"
            size="small"
            onClick={submit}
            disabled={!canSubmit}
          >
            {submitting ? "Wird hinzugefügt…" : "TOP hinzufügen"}
          </Button>
        </Box>
      </Stack>
    </Box>
  );
}

// =================================================================
// Invitation upload + LLM extraction polling
// =================================================================

interface InvitationSectionProps {
  assembly: AssemblyDetailResponse;
  onChanged: (a: AssemblyDetailResponse) => void;
}

function InvitationSection({ assembly, onChanged }: InvitationSectionProps) {
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [verifying, setVerifying] = useState(false);
  // Polling state: true while we expect auto_extracted_at to flip
  // after a fresh upload. Cleared once the timestamp lands OR the
  // user navigates away.
  const [polling, setPolling] = useState(false);

  // Poll the assembly every 3s after upload until auto_extracted_at
  // (or verified_at — though that won't happen during this flow)
  // populates. Single-page, single-purpose effect — clear on unmount.
  useEffect(() => {
    if (!polling) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const r = await api.get<AssemblyDetailResponse>(
          `/admin/assemblies/${assembly.id}`,
        );
        if (cancelled) return;
        if (r.data.auto_extracted_at) {
          setPolling(false);
          onChanged(r.data);
        } else {
          // Keep refreshing the assembly's invitation_uploaded_at
          // so the timestamp under the chip stays current even
          // before extraction finishes.
          onChanged(r.data);
        }
      } catch {
        /* swallow — try again on next tick */
      }
    };
    const handle = window.setInterval(tick, 3000);
    void tick();
    return () => {
      cancelled = true;
      window.clearInterval(handle);
    };
    // assembly.id is the only thing that changes between assemblies;
    // intentionally NOT depending on the whole assembly so the
    // interval doesn't get torn down + recreated on each refresh.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [polling, assembly.id]);

  const onFile = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setError(null);
    setUploading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      await api.post(`/admin/assemblies/${assembly.id}/invitation`, form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      const r = await api.get<AssemblyDetailResponse>(
        `/admin/assemblies/${assembly.id}`,
      );
      onChanged(r.data);
      // Auto-extracted gets cleared by the upload endpoint; we now
      // wait for the Celery task to refill it.
      setPolling(true);
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Upload fehlgeschlagen.";
      setError(msg);
    } finally {
      setUploading(false);
      // Allow re-uploading the same file
      e.target.value = "";
    }
  };

  const onDelete = async () => {
    if (!confirm("Einladungs-PDF wirklich löschen?")) return;
    setError(null);
    try {
      await api.delete(`/admin/assemblies/${assembly.id}/invitation`);
      const r = await api.get<AssemblyDetailResponse>(
        `/admin/assemblies/${assembly.id}`,
      );
      onChanged(r.data);
      setPolling(false);
    } catch {
      setError("Löschen fehlgeschlagen.");
    }
  };

  const onVerify = async () => {
    setError(null);
    setVerifying(true);
    try {
      // Default kind=invitation matches what this button has always
      // done: lock the invitation-derived fields. The protocol
      // section has its own confirm button that passes kind=protocol.
      const r = await api.post<AssemblyDetailResponse>(
        `/admin/assemblies/${assembly.id}/verify?kind=invitation`,
      );
      onChanged(r.data);
    } catch {
      setError("Bestätigung fehlgeschlagen.");
    } finally {
      setVerifying(false);
    }
  };

  const openPdf = async () => {
    // Fetch + blob + window.open. A plain <a href> would silently
    // 401 because /me/assemblies/{id}/invitation requires the JWT
    // from the Authorization header — the browser doesn't attach
    // it to anchor clicks. Revoke after a minute so the new tab
    // has time to load the bytes.
    setError(null);
    try {
      const r = await api.get(`/me/assemblies/${assembly.id}/invitation`, {
        responseType: "blob",
      });
      const url = URL.createObjectURL(r.data as Blob);
      window.open(url, "_blank", "noopener,noreferrer");
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch {
      setError("PDF konnte nicht geöffnet werden.");
    }
  };

  const needsReview = Boolean(
    assembly.auto_extracted_at && !assembly.verified_at,
  );

  return (
    <Paper sx={{ p: 3 }} variant="outlined">
      <Stack
        direction="row"
        spacing={1}
        sx={{ alignItems: "center", mb: 2, flexWrap: "wrap" }}
      >
        <Typography variant="h6">Einladung (PDF)</Typography>
        {needsReview && (
          <Chip
            color="warning"
            size="small"
            icon={<AutoAwesomeIcon />}
            label="KI-extrahiert · bitte prüfen"
          />
        )}
        {assembly.verified_at && (
          <Chip
            color="success"
            size="small"
            icon={<CheckCircleIcon />}
            label={`Bestätigt am ${new Date(
              assembly.verified_at,
            ).toLocaleDateString("de-DE")}`}
          />
        )}
      </Stack>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      <Stack spacing={2}>
        <Stack
          direction="row"
          spacing={2}
          sx={{ alignItems: "center", flexWrap: "wrap" }}
        >
          {assembly.invitation_pdf_url ? (
            <Stack spacing={0.5}>
              <Chip color="success" size="small" label="Hochgeladen" />
              {assembly.invitation_uploaded_at && (
                <Typography variant="caption" color="text.secondary">
                  am{" "}
                  {new Date(
                    assembly.invitation_uploaded_at,
                  ).toLocaleString("de-DE")}
                </Typography>
              )}
            </Stack>
          ) : (
            <Typography variant="body2" color="text.secondary">
              Noch nicht hochgeladen. Beim Hochladen extrahiert die KI Datum,
              Ort und Tagesordnung automatisch.
            </Typography>
          )}
          <Button
            component="label"
            variant="contained"
            startIcon={<CloudUploadIcon />}
            disabled={uploading}
          >
            {uploading
              ? "Wird hochgeladen…"
              : assembly.invitation_pdf_url
                ? "Einladung ersetzen"
                : "Einladung hochladen"}
            <input
              type="file"
              accept="application/pdf"
              hidden
              onChange={onFile}
            />
          </Button>
          {assembly.invitation_pdf_url && (
            <>
              <Button
                variant="outlined"
                startIcon={<DownloadIcon />}
                onClick={openPdf}
              >
                PDF öffnen
              </Button>
              <Button
                variant="outlined"
                color="error"
                startIcon={<DeleteIcon />}
                onClick={onDelete}
              >
                Löschen
              </Button>
            </>
          )}
        </Stack>

        {polling && (
          <Alert severity="info" icon={<AutoAwesomeIcon />}>
            KI extrahiert die Versammlungsdetails aus der PDF…
            Sobald sie fertig ist, erscheinen die Felder oben.
          </Alert>
        )}

        {needsReview && (
          <Stack
            direction="row"
            spacing={2}
            sx={{
              alignItems: "center",
              flexWrap: "wrap",
              p: 2,
              bgcolor: "warning.main",
              borderRadius: 1,
              color: "warning.contrastText",
            }}
          >
            <Typography variant="body2" sx={{ flex: 1, minWidth: 200 }}>
              Bitte Datum, Ort und Tagesordnung prüfen, dann bestätigen.
              Erst danach gilt die Versammlung für Eigentümer als
              verifiziert.
            </Typography>
            <Button
              variant="contained"
              color="success"
              onClick={onVerify}
              disabled={verifying}
              startIcon={<CheckCircleIcon />}
            >
              {verifying ? "Wird bestätigt…" : "Daten bestätigen"}
            </Button>
          </Stack>
        )}
      </Stack>
    </Paper>
  );
}


// =================================================================
// Protocol upload
// =================================================================

interface ProtocolSectionProps {
  assembly: AssemblyDetailResponse;
  onChanged: (a: AssemblyDetailResponse) => void;
}

function ProtocolSection({ assembly, onChanged }: ProtocolSectionProps) {
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [verifying, setVerifying] = useState(false);
  // Polls /admin/assemblies/:id every 3s after upload until
  // protocol_extracted_at lands (LLM merges Beschluss outcomes +
  // Diskussion). Cleared once the timestamp shows up.
  const [polling, setPolling] = useState(false);

  const onVerifyProtocol = async () => {
    setError(null);
    setVerifying(true);
    try {
      const r = await api.post<AssemblyDetailResponse>(
        `/admin/assemblies/${assembly.id}/verify?kind=protocol`,
      );
      onChanged(r.data);
    } catch {
      setError("Bestätigung fehlgeschlagen.");
    } finally {
      setVerifying(false);
    }
  };

  const openProtocol = async () => {
    // Authed fetch → blob → new tab (a plain <a href> would 401 — the
    // browser doesn't attach the JWT). Mirrors the invitation openPdf.
    setError(null);
    try {
      const r = await api.get(`/me/assemblies/${assembly.id}/protocol`, {
        responseType: "blob",
      });
      const url = URL.createObjectURL(r.data as Blob);
      window.open(url, "_blank", "noopener,noreferrer");
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch {
      setError("Protokoll konnte nicht geöffnet werden.");
    }
  };

  const protocolNeedsReview = Boolean(
    assembly.protocol_extracted_at && !assembly.protocol_verified_at,
  );

  useEffect(() => {
    if (!polling) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const r = await api.get<AssemblyDetailResponse>(
          `/admin/assemblies/${assembly.id}`,
        );
        if (cancelled) return;
        if (r.data.protocol_extracted_at) {
          setPolling(false);
        }
        onChanged(r.data);
      } catch {
        /* swallow — try again next tick */
      }
    };
    const handle = window.setInterval(tick, 3000);
    void tick();
    return () => {
      cancelled = true;
      window.clearInterval(handle);
    };
    // assembly.id is the only stable dep here; the whole assembly
    // object updates as the polling refreshes, which would otherwise
    // tear down + recreate the interval each tick.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [polling, assembly.id]);

  const onFile = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setError(null);
    setUploading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      await api.post(`/admin/assemblies/${assembly.id}/protocol`, form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      const r = await api.get<AssemblyDetailResponse>(`/admin/assemblies/${assembly.id}`);
      onChanged(r.data);
      setPolling(true);
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Upload fehlgeschlagen.";
      setError(msg);
    } finally {
      setUploading(false);
      // Allow re-uploading the same file
      e.target.value = "";
    }
  };

  return (
    <Paper sx={{ p: 3 }} variant="outlined">
      <Stack
        direction="row"
        spacing={1}
        sx={{ alignItems: "center", mb: 2, flexWrap: "wrap" }}
      >
        <Typography variant="h6">Signiertes Protokoll</Typography>
        {protocolNeedsReview && (
          <Chip
            color="warning"
            size="small"
            icon={<AutoAwesomeIcon />}
            label="KI-extrahiert · bitte prüfen"
          />
        )}
        {assembly.protocol_verified_at && (
          <Chip
            color="success"
            size="small"
            icon={<CheckCircleIcon />}
            label={`Bestätigt am ${new Date(
              assembly.protocol_verified_at,
            ).toLocaleDateString("de-DE")}`}
          />
        )}
      </Stack>
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      <Stack spacing={2}>
        <Stack
          direction="row"
          spacing={2}
          sx={{ alignItems: "center", flexWrap: "wrap" }}
        >
          {assembly.protocol_pdf_url ? (
            <Stack spacing={0.5}>
              <Chip color="success" size="small" label="Hochgeladen" />
              {assembly.protocol_uploaded_at && (
                <Typography variant="caption" color="text.secondary">
                  am {new Date(assembly.protocol_uploaded_at).toLocaleString("de-DE")}
                </Typography>
              )}
            </Stack>
          ) : (
            <Typography variant="body2" color="text.secondary">
              Noch nicht hochgeladen. Nach dem Upload extrahiert die KI
              Beschluss-Ergebnisse, Stimm-Tallies und die Diskussion und
              verschmilzt sie mit der bestehenden Tagesordnung.
            </Typography>
          )}
          {assembly.protocol_pdf_url && (
            <Button
              variant="outlined"
              startIcon={<DownloadIcon />}
              onClick={() => void openProtocol()}
            >
              Herunterladen
            </Button>
          )}
          <Button
            component="label"
            variant="contained"
            startIcon={<CloudUploadIcon />}
            disabled={uploading}
          >
            {uploading
              ? "Wird hochgeladen…"
              : assembly.protocol_pdf_url
                ? "Protokoll ersetzen"
                : "Protokoll hochladen"}
            <input
              type="file"
              accept="application/pdf"
              hidden
              onChange={onFile}
            />
          </Button>
        </Stack>

        {polling && (
          <Alert severity="info" icon={<AutoAwesomeIcon />}>
            KI extrahiert Beschluss-Ergebnisse + Diskussion aus dem
            Protokoll… Sobald sie fertig ist, sind die Tally-Felder
            und die Diskussionseinträge in der Tagesordnung oben
            befüllt.
          </Alert>
        )}

        {protocolNeedsReview && (
          <Stack
            direction="row"
            spacing={2}
            sx={{
              alignItems: "center",
              flexWrap: "wrap",
              p: 2,
              bgcolor: "warning.main",
              borderRadius: 1,
              color: "warning.contrastText",
            }}
          >
            <Typography variant="body2" sx={{ flex: 1, minWidth: 200 }}>
              Bitte Stimm-Tallies und Diskussion prüfen, dann
              bestätigen. Re-Upload des Protokolls löst die KI erneut
              aus; nach Bestätigung sind die Felder gesperrt.
            </Typography>
            <Button
              variant="contained"
              color="success"
              onClick={onVerifyProtocol}
              disabled={verifying}
              startIcon={<CheckCircleIcon />}
            >
              {verifying ? "Wird bestätigt…" : "Protokoll bestätigen"}
            </Button>
          </Stack>
        )}
      </Stack>
    </Paper>
  );
}
