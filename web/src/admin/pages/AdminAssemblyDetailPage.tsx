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
import DeleteIcon from "@mui/icons-material/DeleteOutlined";
import EditIcon from "@mui/icons-material/EditOutlined";
import SaveIcon from "@mui/icons-material/Save";
import CancelIcon from "@mui/icons-material/Close";
import CloudUploadIcon from "@mui/icons-material/CloudUpload";
import { api } from "@/api/client";
import {
  AGENDA_ITEM_TYPE_LABELS,
  ASSEMBLY_STATUS_LABELS,
  type AgendaItemResponse,
  type AgendaItemType,
  type AgendaItemVoteResult,
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

      <AgendaSection
        assembly={assembly}
        onChanged={(a) => setAssembly(a)}
      />

      <ProtocolSection
        assembly={assembly}
        onChanged={(a) => setAssembly(a)}
      />
    </Stack>
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
  const [start, setStart] = useState(toDtLocal(assembly.scheduled_start));
  const [end, setEnd] = useState(toDtLocal(assembly.scheduled_end));
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const startEdit = () => {
    setTitle(assembly.title);
    setDescription(assembly.description);
    setStatus(assembly.status);
    setLocation(assembly.location);
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
              <Typography variant="h4" component="h1">
                {assembly.title}
              </Typography>
              <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
                <StatusChip status={assembly.status} />
                <Chip
                  size="small"
                  variant="outlined"
                  label={`Ort: ${assembly.location}`}
                />
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
            <AgendaItemRow key={item.id} item={item} onChanged={refresh} />
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

interface AgendaItemRowProps {
  item: AgendaItemResponse;
  onChanged: () => Promise<void>;
}

function AgendaItemRow({ item, onChanged }: AgendaItemRowProps) {
  const [expanded, setExpanded] = useState(false);
  const [voteYes, setVoteYes] = useState(item.vote_yes);
  const [voteNo, setVoteNo] = useState(item.vote_no);
  const [voteAbstain, setVoteAbstain] = useState(item.vote_abstain);
  const [voteResult, setVoteResult] = useState<AgendaItemVoteResult | "">(item.vote_result ?? "");
  const [savingVote, setSavingVote] = useState(false);

  const saveVote = async () => {
    setSavingVote(true);
    try {
      await api.patch(`/admin/agenda-items/${item.id}`, {
        vote_yes: voteYes,
        vote_no: voteNo,
        vote_abstain: voteAbstain,
        vote_result: voteResult || null,
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
          <Stack direction="row" spacing={1} sx={{ mb: 0.5, alignItems: "center" }}>
            <Chip
              size="small"
              variant="outlined"
              label={`TOP ${item.position}`}
            />
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
          <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
            {item.title}
          </Typography>
        </Box>
        <IconButton color="error" onClick={remove} aria-label="TOP löschen">
          <DeleteIcon />
        </IconButton>
      </Box>

      {expanded && (
        <Stack spacing={2} sx={{ mt: 2 }}>
          {item.body && (
            <Typography variant="body2" sx={{ whiteSpace: "pre-wrap", color: "text.secondary" }}>
              {item.body}
            </Typography>
          )}
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
              <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
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
// Protocol upload
// =================================================================

interface ProtocolSectionProps {
  assembly: AssemblyDetailResponse;
  onChanged: (a: AssemblyDetailResponse) => void;
}

function ProtocolSection({ assembly, onChanged }: ProtocolSectionProps) {
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

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
      <Typography variant="h6" sx={{ mb: 2 }}>
        Signiertes Protokoll
      </Typography>
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      <Stack direction="row" spacing={2} sx={{ alignItems: "center", flexWrap: "wrap" }}>
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
            Noch nicht hochgeladen.
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
    </Paper>
  );
}
