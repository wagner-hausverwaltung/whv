import {
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type FormEvent,
} from "react";
import {
  Alert,
  Box,
  Breadcrumbs,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  Link,
  List,
  ListItem,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  ListSubheader,
  Paper,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import CreateNewFolderOutlinedIcon from "@mui/icons-material/CreateNewFolderOutlined";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutlineOutlined";
import DescriptionOutlinedIcon from "@mui/icons-material/DescriptionOutlined";
import DownloadOutlinedIcon from "@mui/icons-material/DownloadOutlined";
import FolderOutlinedIcon from "@mui/icons-material/FolderOutlined";
import UploadFileOutlinedIcon from "@mui/icons-material/UploadFileOutlined";
import { useTranslation } from "react-i18next";
import { api, API_BASE_URL, getAccessToken } from "@/api/client";
import type {
  DocumentFolderResponse,
  DocumentResponse,
} from "@/api/types";

interface DocumentFoldersPanelProps {
  propertyId: string;
  /** Admin (Verwalter) gets create/upload/delete controls; portal users
   *  see a read-only tree. The component swaps endpoint paths between
   *  /admin/* and /me/* based on this flag. */
  mode: "admin" | "portal";
  /** Optional unit lookup so unit-scoped docs can show "Einheit W01"
   *  rather than the generic "Einheit" badge. Pass `[{id, unit_hr_id}]`
   *  from the property detail. Missing entries fall back to the generic
   *  label — useful when the caller can't see the unit. */
  units?: { id: string; unit_hr_id: string | null }[];
}

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

// Per-class chip colour so the document tree is scannable at a glance.
// Keys are the backend DocumentKind enum values; unknown kinds fall
// back to a neutral chip.
const KIND_COLOR: Record<
  string,
  "default" | "primary" | "secondary" | "success" | "info" | "warning"
> = {
  RECHNUNG: "warning",
  JAHRESABRECHNUNG: "info",
  WIRTSCHAFTSPLAN: "info",
  PROTOKOLL: "success",
  VERTRAG: "primary",
  UMLAUFBESCHLUSS: "secondary",
  HAUSORDNUNG: "default",
  SONSTIGES: "default",
};

function kindColor(kind: string): (typeof KIND_COLOR)[string] {
  return KIND_COLOR[kind] ?? "default";
}

// Year bucket for grouping — issued date wins, upload time is the
// fallback (Impower imports don't always carry an issued date). Empty
// string == "no date" so the caller renders a localized heading.
function docYearKey(d: DocumentResponse): string {
  const head = (d.issued_date ?? d.uploaded_at ?? "").slice(0, 4);
  return /^\d{4}$/.test(head) ? head : "";
}

const EUR = new Intl.NumberFormat("de-DE", {
  style: "currency",
  currency: "EUR",
});

function formatDocAmount(amount: string | null | undefined): string | null {
  if (!amount) return null;
  const n = Number(amount);
  return Number.isFinite(n) ? EUR.format(n) : null;
}

/** Shared Verwalter-managed document explorer used by both the admin
 *  property-detail page (full CRUD) and the portal PropertyDocumentsPage
 *  (read-only). Renders a folder tree as breadcrumbs + a flat list of
 *  the current folder's children — easier to grok than an always-on
 *  recursive sidebar, and good enough for the trees we expect (dozens,
 *  not thousands, of folders per property).
 *
 *  Downloads run through an authenticated FileResponse endpoint (NOT
 *  StaticFiles), so we open them via a temporary blob URL rather than
 *  a bare `<a href>` — that way the Authorization header travels with
 *  the request instead of getting stripped by the browser.
 */
export function DocumentFoldersPanel({
  propertyId,
  mode,
  units,
}: DocumentFoldersPanelProps) {
  const { t } = useTranslation();
  const [folders, setFolders] = useState<DocumentFolderResponse[]>([]);
  const [docs, setDocs] = useState<DocumentResponse[]>([]);
  // currentFolderId === null means "property root" — the implicit
  // unnamed top-level folder. Same convention as folder_id on docs.
  const [currentFolderId, setCurrentFolderId] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busyError, setBusyError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // New-folder dialog state. Kept local so the parent doesn't need to
  // know about modal plumbing.
  const [newFolderOpen, setNewFolderOpen] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");

  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const folderBase = mode === "admin" ? "/admin" : "/me";

  // Map unit_id → label for the row-scope chips. Built once per render
  // of the units list; small enough that re-creating each render is
  // cheaper than memoising. Falls back to the generic "Einheit" badge
  // when the doc references a unit the caller can't see (a property
  // member who isn't on that unit's contract — though in that case the
  // visibility filter on the server should have hidden the doc anyway).
  const unitLabelById = new Map<string, string | null>(
    (units ?? []).map((u) => [u.id, u.unit_hr_id]),
  );
  const scopeChip = (d: DocumentResponse): { label: string } | null => {
    if (d.contact_id) return { label: t("documents.scopePersonal") };
    if (d.contract_id) return { label: t("documents.scopeContract") };
    if (d.unit_id) {
      const name = unitLabelById.get(d.unit_id);
      return {
        label: name
          ? t("documents.scopeUnitNamed", { name })
          : t("documents.scopeUnit"),
      };
    }
    return null;
  };

  // Invoice "name" from Impower is just the bare document number, which
  // reads as a meaningless ID in the list. For RECHNUNG docs lead with
  // the amount (the recognisable bit) and keep the number as context.
  const docTitle = (d: DocumentResponse): string => {
    if (d.kind === "RECHNUNG") {
      const amount = formatDocAmount(d.amount);
      if (amount) return d.name ? `${amount} · ${d.name}` : amount;
    }
    return d.name;
  };

  const refresh = useCallback(async () => {
    setLoadError(null);
    try {
      const [folderRes, docRes] = await Promise.all([
        api.get<DocumentFolderResponse[]>(
          `${folderBase}/properties/${propertyId}/folders`,
        ),
        api.get<DocumentResponse[]>(
          `${folderBase}/properties/${propertyId}/documents`,
        ),
      ]);
      setFolders(folderRes.data);
      setDocs(docRes.data);
    } catch {
      setLoadError(t("documents.loadFailed"));
    }
  }, [folderBase, propertyId, t]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh();
  }, [refresh]);

  // Build the breadcrumb trail from the current folder back to root.
  // O(depth) per render; trees stay shallow in practice, so no memo.
  const trail = useMemo(() => {
    const byId = new Map(folders.map((f) => [f.id, f]));
    const chain: DocumentFolderResponse[] = [];
    let cursor: string | null = currentFolderId;
    const visited = new Set<string>();
    while (cursor !== null) {
      const f = byId.get(cursor);
      if (!f || visited.has(f.id)) break;
      visited.add(f.id);
      chain.unshift(f);
      cursor = f.parent_folder_id;
    }
    return chain;
  }, [folders, currentFolderId]);

  const childFolders = useMemo(
    () =>
      folders
        .filter((f) => f.parent_folder_id === currentFolderId)
        .sort((a, b) => a.name.localeCompare(b.name, "de")),
    [folders, currentFolderId],
  );
  const docsHere = useMemo(
    () =>
      docs
        .filter((d) => (d.folder_id ?? null) === currentFolderId)
        .sort((a, b) => {
          // Newest-first by issued_date when present, falling back to
          // upload time (the impower import doesn't always have a date).
          const ad = a.issued_date ?? a.uploaded_at ?? "";
          const bd = b.issued_date ?? b.uploaded_at ?? "";
          return bd.localeCompare(ad) || a.name.localeCompare(b.name);
        }),
    [docs, currentFolderId],
  );

  // Tag each doc with a year header when the year changes (docsHere is
  // already sorted newest-first), so the list groups by year without a
  // separate data structure. header === null means "same year as the
  // row above"; "" is the undated bucket (rendered as a localized label).
  // Derived from the previous row (not a mutable accumulator) so the
  // React Compiler doesn't flag a reassignment during render.
  const docRows = useMemo(
    () =>
      docsHere.map((d, idx) => {
        const year = docYearKey(d);
        const prevYear = idx > 0 ? docYearKey(docsHere[idx - 1]!) : null;
        return { doc: d, header: year !== prevYear ? year : null };
      }),
    [docsHere],
  );

  const createFolder = async (e: FormEvent) => {
    e.preventDefault();
    if (mode !== "admin") return;
    const name = newFolderName.trim();
    if (!name) return;
    setBusy(true);
    setBusyError(null);
    try {
      await api.post(`/admin/properties/${propertyId}/folders`, {
        name,
        parent_folder_id: currentFolderId,
      });
      setNewFolderName("");
      setNewFolderOpen(false);
      await refresh();
    } catch (err: unknown) {
      const detail = (
        err as { response?: { data?: { detail?: string } } }
      ).response?.data?.detail;
      setBusyError(detail ?? t("documents.folderCreateFailed"));
    } finally {
      setBusy(false);
    }
  };

  const deleteFolder = async (folderId: string) => {
    if (mode !== "admin") return;
    if (!window.confirm(t("documents.folderDeleteConfirm"))) return;
    setBusy(true);
    setBusyError(null);
    try {
      await api.delete(`/admin/folders/${folderId}`);
      await refresh();
    } catch (err: unknown) {
      const detail = (
        err as { response?: { data?: { detail?: string } } }
      ).response?.data?.detail;
      setBusyError(detail ?? t("documents.folderDeleteFailed"));
    } finally {
      setBusy(false);
    }
  };

  const uploadDoc = async (e: ChangeEvent<HTMLInputElement>) => {
    if (mode !== "admin") return;
    const file = e.target.files?.[0];
    if (!file) return;
    setBusy(true);
    setBusyError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const params = new URLSearchParams();
      if (currentFolderId) params.set("folder_id", currentFolderId);
      // The api client strips Content-Type for FormData automatically.
      await api.post(
        `/admin/properties/${propertyId}/documents?${params.toString()}`,
        form,
      );
      await refresh();
    } catch (err: unknown) {
      const detail = (
        err as { response?: { data?: { detail?: string } } }
      ).response?.data?.detail;
      setBusyError(detail ?? t("documents.uploadFailed"));
    } finally {
      setBusy(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const deleteDoc = async (docId: string) => {
    if (mode !== "admin") return;
    if (!window.confirm(t("documents.docDeleteConfirm"))) return;
    setBusy(true);
    setBusyError(null);
    try {
      await api.delete(`/admin/documents/${docId}`);
      await refresh();
    } catch {
      setBusyError(t("documents.docDeleteFailed"));
    } finally {
      setBusy(false);
    }
  };

  const downloadDoc = async (d: DocumentResponse) => {
    // Authenticated download — can't use a plain `<a href>` because the
    // browser won't attach our JWT. Pull the bytes via fetch then synthesize
    // a click on a temporary blob URL.
    const base = mode === "admin" ? "/admin" : "/me";
    const token = getAccessToken();
    try {
      const res = await fetch(
        `${API_BASE_URL}${base}/documents/${d.id}/file`,
        token ? { headers: { Authorization: `Bearer ${token}` } } : undefined,
      );
      if (!res.ok) throw new Error(`${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = d.name;
      document.body.appendChild(a);
      a.click();
      a.remove();
      // Tiny delay so Safari finishes the download before the URL dies.
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch {
      setBusyError(t("documents.downloadFailed"));
    }
  };

  return (
    <Stack spacing={2}>
      <Stack
        direction="row"
        sx={{
          alignItems: "center",
          gap: 1.5,
          flexWrap: "wrap",
          minHeight: 36,
        }}
      >
        <Breadcrumbs sx={{ flex: 1, minWidth: 0 }}>
          <Link
            component="button"
            type="button"
            color={currentFolderId === null ? "text.primary" : "text.secondary"}
            underline={currentFolderId === null ? "none" : "hover"}
            onClick={() => setCurrentFolderId(null)}
          >
            <Stack direction="row" sx={{ alignItems: "center", gap: 0.5 }}>
              <FolderOutlinedIcon fontSize="small" />
              {t("documents.rootCrumb")}
            </Stack>
          </Link>
          {trail.map((f, i) => {
            const isLast = i === trail.length - 1;
            return (
              <Link
                key={f.id}
                component="button"
                type="button"
                color={isLast ? "text.primary" : "text.secondary"}
                underline={isLast ? "none" : "hover"}
                onClick={() => setCurrentFolderId(f.id)}
              >
                {f.name}
              </Link>
            );
          })}
        </Breadcrumbs>

        {mode === "admin" && (
          <Stack direction="row" spacing={1}>
            <Button
              variant="outlined"
              size="small"
              startIcon={<CreateNewFolderOutlinedIcon />}
              onClick={() => setNewFolderOpen(true)}
              disabled={busy}
            >
              {t("documents.newFolder")}
            </Button>
            <Button
              variant="contained"
              size="small"
              startIcon={<UploadFileOutlinedIcon />}
              onClick={() => fileInputRef.current?.click()}
              disabled={busy}
            >
              {t("documents.upload")}
            </Button>
            <input
              ref={fileInputRef}
              type="file"
              hidden
              accept=".pdf,.doc,.docx,.xls,.xlsx,.odt,.ods,.txt,.csv,application/pdf"
              onChange={uploadDoc}
            />
          </Stack>
        )}
      </Stack>

      {loadError && <Alert severity="error">{loadError}</Alert>}
      {busyError && (
        <Alert severity="error" onClose={() => setBusyError(null)}>
          {busyError}
        </Alert>
      )}

      <Paper variant="outlined">
        {childFolders.length === 0 && docsHere.length === 0 ? (
          <Box sx={{ p: 3, textAlign: "center" }}>
            <Typography variant="body2" color="text.secondary">
              {t("documents.empty")}
            </Typography>
          </Box>
        ) : (
          <List disablePadding>
            {childFolders.map((f, i) => (
              <ListItem
                key={f.id}
                disablePadding
                divider={
                  i < childFolders.length - 1 || docsHere.length > 0
                }
                secondaryAction={
                  mode === "admin" ? (
                    <Tooltip title={t("documents.folderDelete")}>
                      <IconButton
                        edge="end"
                        size="small"
                        onClick={(e) => {
                          e.stopPropagation();
                          void deleteFolder(f.id);
                        }}
                        aria-label={t("documents.folderDelete")}
                      >
                        <DeleteOutlineIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  ) : null
                }
              >
                <ListItemButton onClick={() => setCurrentFolderId(f.id)}>
                  <ListItemIcon sx={{ minWidth: 40 }}>
                    <FolderOutlinedIcon color="primary" />
                  </ListItemIcon>
                  <ListItemText
                    primary={
                      <Typography variant="body2" sx={{ fontWeight: 500 }}>
                        {f.name}
                      </Typography>
                    }
                  />
                </ListItemButton>
              </ListItem>
            ))}
            {docRows.map(({ doc: d, header }, i) => (
              <Fragment key={d.id}>
                {header !== null && (
                  <ListSubheader
                    disableSticky
                    sx={{
                      bgcolor: "transparent",
                      lineHeight: 2.2,
                      fontWeight: 700,
                      letterSpacing: 0.5,
                      color: "text.secondary",
                    }}
                  >
                    {header || t("documents.noDate")}
                  </ListSubheader>
                )}
                <ListItem
                  disablePadding
                  divider={i < docRows.length - 1}
                  secondaryAction={
                    /* Always render a visible Download affordance — the
                       whole row is also clickable but the icon makes
                       the action discoverable. Admins additionally get
                       a Delete icon to the right of it. The stopPropagation
                       on each button keeps the row-level onClick from
                       firing twice. */
                    <Stack direction="row" spacing={0.5}>
                      <Tooltip title={t("documents.docDownload")}>
                        <IconButton
                          edge="end"
                          size="small"
                          onClick={(e) => {
                            e.stopPropagation();
                            void downloadDoc(d);
                          }}
                          aria-label={t("documents.docDownload")}
                        >
                          <DownloadOutlinedIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                      {mode === "admin" && (
                        <Tooltip title={t("documents.docDelete")}>
                          <IconButton
                            edge="end"
                            size="small"
                            onClick={(e) => {
                              e.stopPropagation();
                              void deleteDoc(d.id);
                            }}
                            aria-label={t("documents.docDelete")}
                          >
                            <DeleteOutlineIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                      )}
                    </Stack>
                  }
                >
                  <ListItemButton onClick={() => void downloadDoc(d)}>
                    <ListItemIcon sx={{ minWidth: 40 }}>
                      <DescriptionOutlinedIcon color="action" />
                    </ListItemIcon>
                    <ListItemText
                      primary={
                        <Stack
                          direction="row"
                          sx={{
                            alignItems: "center",
                            gap: 1,
                            flexWrap: "wrap",
                          }}
                        >
                          {/* Class pill (Rechnung / Protokoll / …) so the
                              document type is obvious at a glance. */}
                          <Chip
                            size="small"
                            color={kindColor(d.kind)}
                            label={t(`documents.kind.${d.kind}`, {
                              defaultValue: d.kind,
                            })}
                          />
                          <Typography variant="body2">{docTitle(d)}</Typography>
                          {(() => {
                            const chip = scopeChip(d);
                            return chip ? (
                              <Chip
                                size="small"
                                variant="outlined"
                                label={chip.label}
                              />
                            ) : null;
                          })()}
                        </Stack>
                      }
                      secondary={
                        <Typography
                          variant="caption"
                          color="text.secondary"
                          component="span"
                        >
                          {formatBytes(d.size_bytes)}
                          {d.issued_date ? ` · ${d.issued_date}` : ""}
                        </Typography>
                      }
                    />
                  </ListItemButton>
                </ListItem>
              </Fragment>
            ))}
          </List>
        )}
      </Paper>

      <Dialog
        open={newFolderOpen}
        onClose={() => setNewFolderOpen(false)}
        maxWidth="xs"
        fullWidth
      >
        <Box component="form" onSubmit={createFolder}>
          <DialogTitle>{t("documents.newFolder")}</DialogTitle>
          <DialogContent>
            <TextField
              autoFocus
              fullWidth
              label={t("documents.folderName")}
              value={newFolderName}
              onChange={(e) => setNewFolderName(e.target.value)}
              required
              slotProps={{ htmlInput: { maxLength: 200 } }}
              sx={{ mt: 1 }}
            />
            <Typography
              variant="caption"
              color="text.secondary"
              sx={{ display: "block", mt: 1 }}
            >
              {currentFolderId === null
                ? t("documents.creatingUnderRoot")
                : t("documents.creatingUnder", {
                    name: trail[trail.length - 1]?.name ?? "",
                  })}
            </Typography>
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setNewFolderOpen(false)}>
              {t("common.cancel")}
            </Button>
            <Button
              type="submit"
              variant="contained"
              disabled={busy || !newFolderName.trim()}
            >
              {t("documents.create")}
            </Button>
          </DialogActions>
        </Box>
      </Dialog>
    </Stack>
  );
}
