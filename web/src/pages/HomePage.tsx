import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Link as RouterLink, useNavigate } from "react-router-dom";
import {
  Box,
  Button,
  Card,
  CardContent,
  CardHeader,
  Chip,
  CircularProgress,
  Divider,
  List,
  ListItemButton,
  ListItemText,
  Typography,
} from "@mui/material";
import CampaignIcon from "@mui/icons-material/Campaign";
import ConfirmationNumberIcon from "@mui/icons-material/ConfirmationNumber";
import DescriptionIcon from "@mui/icons-material/Description";
import EventIcon from "@mui/icons-material/Event";
import { useTranslation } from "react-i18next";
import { api } from "@/api/client";
import type {
  AnnouncementResponse,
  AssemblyResponse,
  DocumentResponse,
  PropertyResponse,
  TicketResponse,
} from "@/api/types";
import { getRememberedPropertyId } from "@/lib/activeProperty";

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

function SectionCard({
  icon,
  title,
  seeAllTo,
  isEmpty,
  emptyText,
  children,
}: {
  icon: ReactNode;
  title: string;
  seeAllTo: string | null;
  isEmpty: boolean;
  emptyText: string;
  children: ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <Card variant="outlined" sx={{ flex: 1, minWidth: { xs: "100%", md: 280 }, display: "flex", flexDirection: "column" }}>
      <CardHeader
        avatar={icon}
        title={title}
        titleTypographyProps={{ variant: "h6" }}
        action={
          seeAllTo && (
            <Button size="small" component={RouterLink} to={seeAllTo}>
              {t("home.seeAll")}
            </Button>
          )
        }
      />
      <Divider />
      {isEmpty ? (
        <CardContent>
          <Typography color="text.secondary" variant="body2">
            {emptyText}
          </Typography>
        </CardContent>
      ) : (
        <List dense disablePadding>
          {children}
        </List>
      )}
    </Card>
  );
}

/**
 * Home / dashboard landing — aggregates the active property's Mitteilungen +
 * ETV and the user's open tickets into one overview. Each row jumps to its
 * detail; each card links to the full tab. Property-scoped sections use the
 * remembered active Liegenschaft (or the first one).
 */
export function HomePage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [propertyId, setPropertyId] = useState<string | null>(null);
  const [announcements, setAnnouncements] = useState<AnnouncementResponse[]>([]);
  const [assemblies, setAssemblies] = useState<AssemblyResponse[]>([]);
  const [tickets, setTickets] = useState<TicketResponse[]>([]);
  const [documents, setDocuments] = useState<DocumentResponse[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const properties = (await api.get<PropertyResponse[]>("/me/properties")).data;
      const remembered = getRememberedPropertyId();
      const pid =
        properties.find((p) => p.id === remembered)?.id ?? properties[0]?.id ?? null;
      const empty = { data: [] as never[] };
      const [ann, asm, tks, docs] = await Promise.all([
        pid ? api.get<AnnouncementResponse[]>(`/me/properties/${pid}/announcements`) : empty,
        pid ? api.get<AssemblyResponse[]>(`/me/properties/${pid}/assemblies`) : empty,
        api.get<TicketResponse[]>("/me/tickets"),
        pid ? api.get<DocumentResponse[]>(`/me/properties/${pid}/documents`) : empty,
      ]);
      setPropertyId(pid);
      setAnnouncements(ann.data as AnnouncementResponse[]);
      setAssemblies(asm.data as AssemblyResponse[]);
      setTickets(tks.data as TicketResponse[]);
      setDocuments(docs.data as DocumentResponse[]);
    } catch {
      // Cards fall back to their empty state on a transient failure.
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const openDocument = async (documentId: string) => {
    try {
      const res = await api.get<Blob>(`/me/documents/${documentId}/file`, {
        responseType: "blob",
      });
      const objectUrl = URL.createObjectURL(res.data);
      window.open(objectUrl, "_blank", "noopener");
      setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
    } catch {
      // Best-effort open; a failure just doesn't open the tab.
    }
  };

  const publishedAnnouncements = [...announcements]
    .filter((a) => a.notification_sent_at)
    .sort((a, b) => b.scheduled_publish_at.localeCompare(a.scheduled_publish_at))
    .slice(0, 5);
  const recentAssemblies = [...assemblies]
    .sort((a, b) => b.scheduled_start.localeCompare(a.scheduled_start))
    .slice(0, 5);
  const openTickets = [...tickets]
    .filter((tk) => tk.status !== "GESCHLOSSEN")
    .sort((a, b) => b.last_message_at.localeCompare(a.last_message_at))
    .slice(0, 5);
  const latestDocuments = [...documents]
    .sort((a, b) =>
      (b.issued_date ?? b.uploaded_at ?? "").localeCompare(a.issued_date ?? a.uploaded_at ?? ""),
    )
    .slice(0, 5);

  if (loading) {
    return (
      <Box sx={{ display: "flex", justifyContent: "center", py: 8 }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box>
      <Typography variant="h4" sx={{ fontWeight: 700, mb: 0.5 }}>
        {t("home.title")}
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 3 }}>
        {t("home.subtitle")}
      </Typography>

      <Box
        sx={{
          display: "flex",
          flexDirection: { xs: "column", md: "row" },
          flexWrap: "wrap",
          gap: 2,
          alignItems: "stretch",
        }}
      >
        <SectionCard
          icon={<CampaignIcon color="primary" />}
          title={t("home.announcements")}
          seeAllTo={propertyId ? `/properties/${propertyId}/announcements` : null}
          isEmpty={publishedAnnouncements.length === 0}
          emptyText={t("home.noAnnouncements")}
        >
          {publishedAnnouncements.map((a) => (
            <ListItemButton key={a.id} onClick={() => navigate(`/announcements/${a.id}`)}>
              <ListItemText primary={a.title} secondary={fmtDate(a.scheduled_publish_at)} />
            </ListItemButton>
          ))}
        </SectionCard>

        <SectionCard
          icon={<EventIcon color="primary" />}
          title={t("home.etv")}
          seeAllTo={propertyId ? `/properties/${propertyId}/assemblies` : null}
          isEmpty={recentAssemblies.length === 0}
          emptyText={t("home.noEtv")}
        >
          {recentAssemblies.map((a) => (
            <ListItemButton key={a.id} onClick={() => navigate(`/assemblies/${a.id}`)}>
              <ListItemText
                primary={a.title}
                secondary={`${fmtDate(a.scheduled_start)}${a.location ? ` · ${a.location}` : ""}`}
              />
            </ListItemButton>
          ))}
        </SectionCard>

        <SectionCard
          icon={<ConfirmationNumberIcon color="primary" />}
          title={t("home.tickets")}
          seeAllTo="/tickets"
          isEmpty={openTickets.length === 0}
          emptyText={t("home.noTickets")}
        >
          {openTickets.map((tk) => (
            <ListItemButton key={tk.id} onClick={() => navigate(`/tickets/${tk.id}`)}>
              <ListItemText primary={tk.subject} secondary={fmtDate(tk.last_message_at)} />
              <Chip size="small" label={tk.status} sx={{ ml: 1 }} />
            </ListItemButton>
          ))}
        </SectionCard>

        <SectionCard
          icon={<DescriptionIcon color="primary" />}
          title={t("home.documents")}
          seeAllTo={propertyId ? `/properties/${propertyId}/documents` : null}
          isEmpty={latestDocuments.length === 0}
          emptyText={t("home.noDocuments")}
        >
          {latestDocuments.map((doc) => (
            <ListItemButton key={doc.id} onClick={() => void openDocument(doc.id)}>
              <ListItemText
                primary={doc.name}
                secondary={doc.issued_date ? fmtDate(doc.issued_date) : doc.kind}
              />
            </ListItemButton>
          ))}
        </SectionCard>
      </Box>
    </Box>
  );
}
