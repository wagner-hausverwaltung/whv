// Shape mirrors the backend's Pydantic response models. Kept manually in
// sync — small surface, low churn. If this grows, generate from OpenAPI.

export type UserRole =
  | "verwalter"
  | "beirat"
  | "eigentuemer"
  | "mieter"
  | "dienstleister";

export interface UserResponse {
  id: string;
  email: string;
  role: UserRole;
  organization_id: string;
  contact_id_impower: number | null;
  avatar_url: string | null;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  user: UserResponse;
}

export interface PropertyResponse {
  id: string;
  impower_id: number | null;
  property_hr_id: string | null;
  name: string;
  type: string;
  state: string;
  city: string | null;
  street: string | null;
  number: string | null;
  postal_code: string | null;
  country: string | null;
  image_url: string | null;
}

export interface UnitResponse {
  id: string;
  unit_hr_id: string | null;
  type: string;
  floor: string | null;
  position: string | null;
  area_m2: string | null;
  rooms: number | null;
}

export interface PropertyDetailResponse extends PropertyResponse {
  units: UnitResponse[];
}

export interface DocumentResponse {
  id: string;
  name: string;
  kind: string;
  mime_type: string | null;
  size_bytes: number | null;
  issued_date: string | null;
  amount: string | null;
  // Verwalter-managed tree (Item 6). NULL = sits at the property root
  // (Impower-imported docs and pre-folder uploads land there).
  folder_id?: string | null;
  uploaded_at?: string | null;
  visibility?: string;
}

export interface DocumentFolderResponse {
  id: string;
  property_id: string;
  parent_folder_id: string | null;
  name: string;
  created_at: string;
  updated_at: string;
}

// 32 ticket categories grouped into 7 buckets — see
// backend/app/services/ticket_categories.py for the source of truth
// (group / German label / English label / MUI icon name per value).
export type TicketCategory =
  | "ALLGEMEIN_FRAGE"
  | "ALLGEMEIN_KLINGEL"
  | "ALLGEMEIN_DOKUMENTE"
  | "ALLGEMEIN_ONBOARDING"
  | "ALLGEMEIN_LOB"
  | "ALLGEMEIN_RUECKRUF"
  | "ALLGEMEIN_SCHLUESSEL"
  | "ALLGEMEIN_TELEFONNOTIZ"
  | "BUCHHALTUNG_BANK_SEPA"
  | "BUCHHALTUNG_BETRIEBSKOSTEN"
  | "BUCHHALTUNG_JAHRESABRECHNUNG"
  | "BUCHHALTUNG_BELEGE"
  | "BUCHHALTUNG_ABBUCHUNGEN"
  | "VERTRIEB_BEWERTUNG"
  | "VERTRIEB_BERATUNG"
  | "VERTRIEB_INTERESSE"
  | "MIETER_WECHSEL"
  | "SCHADEN_ALLGEMEIN"
  | "SCHADEN_BAUMANGEL"
  | "SCHADEN_ELEMENTAR"
  | "SCHADEN_FEUER"
  | "SCHADEN_SCHAEDLINGE"
  | "SCHADEN_STROM"
  | "SCHADEN_ABWASSER"
  | "SCHADEN_WASSER"
  | "WEG_ANFRAGE"
  | "WEG_BESCHLUSSANTRAG"
  | "WEG_LEGIONELLEN"
  | "SONSTIGES_DATEN"
  | "SONSTIGES_BESCHLUSSUMSETZUNG"
  | "SONSTIGES_ETV"
  | "SONSTIGES_RELAY"
  | "SONSTIGES_STOERUNG"
  | "SONSTIGES_OTHER";

export type TicketStatus =
  | "NEU"
  | "OFFEN"
  | "WARTET_AUF_KUNDE"
  | "GESCHLOSSEN";

export type TicketShareScope = "PRIVATE" | "PARTICIPANTS" | "PROPERTY";

export interface TicketMessageAttachmentResponse {
  id: string;
  ticket_message_id: string;
  filename: string;
  mime_type: string | null;
  size_bytes: number;
  uploaded_by_user_id: string | null;
  created_at: string;
}

export interface TicketMessageResponse {
  id: string;
  ticket_id: string;
  author_email?: string | null;
  // Now nullable on the wire — inbound-email messages from non-registered
  // senders have NULL author_user_id; external_sender_email on the ticket
  // identifies them.
  author_user_id: string | null;
  body: string;
  is_internal_note: boolean;
  created_at: string;
  // Item 7 — per-message file attachments. Always an array; empty when
  // the message had no files.
  attachments?: TicketMessageAttachmentResponse[];
}

export interface TicketParticipantResponse {
  user_id: string;
  email: string;
  added_by_user_id: string;
  added_at: string;
}

export interface TicketResponse {
  id: string;
  property_id: string | null;
  // Nullable: inbound-email tickets from unknown senders have NULL
  // here and identify the sender via `external_sender_email` instead.
  created_by_user_id: string | null;
  assignee_user_id: string | null;
  category: TicketCategory;
  status: TicketStatus;
  share_scope: TicketShareScope;
  subject: string;
  last_message_at: string;
  created_at: string;
  closed_at: string | null;
  // Denormalised join fields populated by list handlers. May be null in
  // single-row responses (post-create) — render falls back to plain text.
  property_name?: string | null;
  property_address?: string | null;
  creator_email?: string | null;
  creator_contact_label?: string | null;
  creator_contact_id_impower?: number | null;
  external_sender_email?: string | null;
}

export interface TicketDetailResponse extends TicketResponse {
  messages: TicketMessageResponse[];
  participants: TicketParticipantResponse[];
}

export const TICKET_SHARE_SCOPE_LABELS: Record<TicketShareScope, string> = {
  PRIVATE: "Privat",
  PARTICIPANTS: "Nur Teilnehmer",
  PROPERTY: "Alle Eigentümer dieses Objekts",
};

// Display labels keyed by category. Kept in sync with the German
// labels from app/services/ticket_categories.py — when adding values
// keep that file and this dict in lockstep. English labels and group
// metadata live in src/lib/ticketCategories.ts.
export const TICKET_CATEGORY_LABELS: Record<TicketCategory, string> = {
  ALLGEMEIN_FRAGE: "Allgemeine Frage / Information",
  ALLGEMEIN_KLINGEL: "Änderung Klingel-/Namensschild",
  ALLGEMEIN_DOKUMENTE: "Anforderung von Dokumenten",
  ALLGEMEIN_ONBOARDING: "Ihr Onboarding zur Hausverwaltung",
  ALLGEMEIN_LOB: "Lob & Kritik",
  ALLGEMEIN_RUECKRUF: "Rückrufbitte",
  ALLGEMEIN_SCHLUESSEL: "Schlüssel-/Schließzylinderbestellung",
  ALLGEMEIN_TELEFONNOTIZ: "Telefonnotiz",
  BUCHHALTUNG_BANK_SEPA: "Änderung der Bankverbindung / SEPA-Lastschriftmandat",
  BUCHHALTUNG_BETRIEBSKOSTEN: "Anfrage zur Betriebskostenabrechnung",
  BUCHHALTUNG_JAHRESABRECHNUNG: "Anfrage zur Jahresabrechnung",
  BUCHHALTUNG_BELEGE: "Belegprüfung",
  BUCHHALTUNG_ABBUCHUNGEN: "Rückfragen zu Abbuchungen",
  VERTRIEB_BEWERTUNG: "Anfrage zur Immobilienbewertung",
  VERTRIEB_BERATUNG: "Beratungsgespräch",
  VERTRIEB_INTERESSE: "Kauf-/Mietinteresse",
  MIETER_WECHSEL: "Mieterwechsel",
  SCHADEN_ALLGEMEIN: "Allgemeine Schadensmeldung",
  SCHADEN_BAUMANGEL: "Baumangel",
  SCHADEN_ELEMENTAR: "Elementarschaden",
  SCHADEN_FEUER: "Feuer-/Brandschaden",
  SCHADEN_SCHAEDLINGE: "Schädlingsbekämpfung",
  SCHADEN_STROM: "Strom-/Elektrikschaden",
  SCHADEN_ABWASSER: "Verstopfung / Rückstau Abwasser",
  SCHADEN_WASSER: "Wasserschaden",
  WEG_ANFRAGE: "Anfrage an die WEG-Verwaltung",
  WEG_BESCHLUSSANTRAG: "Antrag zur Tagesordnung / Beschlussantrag",
  WEG_LEGIONELLEN: "Legionellenprüfung",
  SONSTIGES_DATEN: "Änderung der Daten im Kundenportal",
  SONSTIGES_BESCHLUSSUMSETZUNG: "Beschlussumsetzung",
  SONSTIGES_ETV: "Eigentümerversammlung",
  SONSTIGES_RELAY: "Relay-Meldung",
  SONSTIGES_STOERUNG: "Störung",
  SONSTIGES_OTHER: "Sonstiges",
};

export const TICKET_STATUS_LABELS: Record<TicketStatus, string> = {
  NEU: "Neu",
  OFFEN: "Offen",
  WARTET_AUF_KUNDE: "Wartet auf Antwort",
  GESCHLOSSEN: "Geschlossen",
};

// --- Umlaufbeschluss (circular resolution) ----------------------------------

export type ResolutionMode = "KLASSISCH" | "MEHRHEITS";

export type ResolutionStatus =
  | "ENTWURF"
  | "OFFEN"
  | "GESCHLOSSEN"
  | "ANGENOMMEN"
  | "ABGELEHNT";

export type VoteChoice = "JA" | "NEIN" | "ENTHALTUNG";

export interface ResolutionTally {
  eligible_voters: number;
  cast: number;
  ja: number;
  nein: number;
  enthaltung: number;
  quorum_met: boolean;
  unanimous_yes: boolean;
}

export interface VoteResponse {
  id: string;
  resolution_id: string;
  owner_contact_id_impower: number;
  choice: VoteChoice;
  voted_at: string;
  signature_method: string;
}

export interface ResolutionResponse {
  id: string;
  property_id: string;
  title: string;
  mode: ResolutionMode;
  status: ResolutionStatus;
  opens_at: string;
  closes_at: string;
  required_quorum: number;
  decided_at: string | null;
  created_at: string;
}

export interface ResolutionDetailResponse extends ResolutionResponse {
  description: string;
  pdf_url: string | null;
  result_pdf_url: string | null;
  result: string | null;
  tally: ResolutionTally;
  votes: VoteResponse[];
  my_vote: VoteResponse | null;
  am_eligible: boolean;
}

export const RESOLUTION_STATUS_LABELS: Record<ResolutionStatus, string> = {
  ENTWURF: "Entwurf",
  OFFEN: "Abstimmung läuft",
  GESCHLOSSEN: "Geschlossen",
  ANGENOMMEN: "Angenommen",
  ABGELEHNT: "Abgelehnt",
};

// =============================================================
// Eigentümerversammlung (ETV) — in-person assembly + agenda
// =============================================================

export type AssemblyStatus =
  | "GEPLANT"
  | "EINGELADEN"
  | "ABGEHALTEN"
  | "ABGESAGT";

export type AgendaItemType = "INFORMATION" | "BESCHLUSS" | "DISKUSSION";

export type AgendaItemVoteResult = "ANGENOMMEN" | "ABGELEHNT";

// Stimmrecht — which voting basis applied. UI shows human-friendly
// labels via VOTING_BASIS_LABELS.
export type AgendaItemVotingBasis = "KOPF" | "MEA" | "OBJEKT";

export const VOTING_BASIS_LABELS: Record<AgendaItemVotingBasis, string> = {
  KOPF: "Kopfprinzip",
  MEA: "Anteilsprinzip (MEA)",
  OBJEKT: "Objektprinzip (Einheiten)",
};

export interface DiscussionEntryResponse {
  id: string;
  agenda_item_id: string;
  position: number;
  speaker_label: string;
  content: string;
  created_at: string;
}

export interface AgendaItemResponse {
  id: string;
  assembly_id: string;
  position: number;
  type: AgendaItemType;
  title: string;
  body: string;
  beschluss_text: string | null;
  vote_yes: number;
  vote_no: number;
  vote_abstain: number;
  vote_required_quorum: number | null;
  vote_result: AgendaItemVoteResult | null;
  voting_basis: AgendaItemVotingBasis | null;
  present_count: number | null;
  discussion: DiscussionEntryResponse[];
}

export interface AssemblyResponse {
  id: string;
  property_id: string;
  property_name: string | null;
  property_hr_id: string | null;
  title: string;
  status: AssemblyStatus;
  scheduled_start: string;
  scheduled_end: string;
  actual_start: string | null;
  actual_end: string | null;
  location: string;
  teams_meeting_url: string | null;
  invitation_pdf_url: string | null;
  invitation_uploaded_at: string | null;
  protocol_pdf_url: string | null;
  protocol_uploaded_at: string | null;
  auto_extracted_at: string | null;
  protocol_extracted_at: string | null;
  verified_at: string | null;
  protocol_verified_at: string | null;
  created_at: string;
}

export interface AssemblyDetailResponse extends AssemblyResponse {
  description: string;
  agenda_pdf_url: string | null;
  agenda_items: AgendaItemResponse[];
}

export interface AssemblyCommentResponse {
  id: string;
  assembly_id: string;
  author_user_id: string;
  author_label: string;
  author_role: string;
  body: string;
  created_at: string;
  edited_at: string | null;
}

export const ASSEMBLY_STATUS_LABELS: Record<AssemblyStatus, string> = {
  GEPLANT: "Geplant",
  EINGELADEN: "Eingeladen",
  ABGEHALTEN: "Abgehalten",
  ABGESAGT: "Abgesagt",
};

export const AGENDA_ITEM_TYPE_LABELS: Record<AgendaItemType, string> = {
  INFORMATION: "Information",
  BESCHLUSS: "Beschluss",
  DISKUSSION: "Diskussion",
};

// =============================================================

export const RESOLUTION_MODE_LABELS: Record<ResolutionMode, string> = {
  KLASSISCH: "Allstimmigkeit (§23 Abs. 3)",
  MEHRHEITS: "Mehrheits-Umlaufbeschluss",
};

export const VOTE_CHOICE_LABELS: Record<VoteChoice, string> = {
  JA: "JA",
  NEIN: "NEIN",
  ENTHALTUNG: "Enthaltung",
};

// --- Admin: invites + pickers ------------------------------------------------

export type InviteStatus = "pending" | "consumed" | "expired";

export interface AdminInviteResponse {
  code: string;
  email: string;
  role: UserRole;
  contact_id_impower: number | null;
  scope_json: Record<string, unknown> | null;
  expires_at: string;
  consumed_at: string | null;
  created_by: string | null;
  created_at: string;
  status: InviteStatus;
  email_message_id: string | null;
}

export interface AdminPropertySearchResult {
  id: string;
  name: string;
  property_hr_id: string | null;
  city: string | null;
  street: string | null;
}

export interface AdminContactSearchResult {
  impower_id: number;
  label: string;
  email: string | null;
}

export interface CreateInviteRequest {
  email: string;
  role: UserRole;
  contact_id_impower?: number | null;
  ttl_days?: number;
}

export const INVITE_STATUS_LABELS: Record<InviteStatus, string> = {
  pending: "Offen",
  consumed: "Eingelöst",
  expired: "Abgelaufen",
};

export interface AdminPropertyDetailResponse {
  id: string;
  name: string;
  impower_id: number | null;
  property_hr_id: string | null;
  type: string;
  state: string;
  city: string | null;
  street: string | null;
  number: string | null;
  postal_code: string | null;
  country: string | null;
  image_url: string | null;
  units_count: number;
  contracts_count: number;
  contacts_count: number;
  open_tickets_count: number;
  open_resolutions_count: number;
  invoice_companies_count: number;
}

export interface AdminPropertyCompanyResponse {
  contact_id: string;
  impower_id: number | null;
  name: string;
  email: string | null;
  phone: string | null;
  invoice_count: number;
  total_amount: number | null;
  most_recent_invoice_at: string | null;
}

export interface AdminPropertyListItem {
  id: string;
  name: string;
  property_hr_id: string | null;
  type: string;
  state: string;
  city: string | null;
  street: string | null;
  number: string | null;
  postal_code: string | null;
  image_url: string | null;
}

export interface AdminUnitListItem {
  id: string;
  unit_hr_id: string | null;
  type: string;
  floor: string | null;
  position: string | null;
  area_m2: number | null;
  property_id: string;
  property_name: string;
}

export interface AdminContractListItem {
  id: string;
  type: string;
  contract_number: string | null;
  name: string | null;
  start_date: string | null;
  end_date: string | null;
  is_vacant: boolean | null;
  property_id: string;
  property_name: string;
}

export interface AdminContactListItem {
  id: string;
  impower_id: number | null;
  kind: string;
  name: string;
  email: string | null;
  phone: string | null;
  city: string | null;
}

export interface AdminAuditLogResponse {
  id: string;
  actor_user_id: string | null;
  actor_email: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  payload_json: Record<string, unknown> | null;
  created_at: string;
}

// --- Announcements (Mitteilungen) -------------------------------------------
//
// Mirrors app/schemas/announcement.py. The owner + admin shapes are
// identical on the wire — admin reads see hidden comments in the
// comments[] list with is_hidden=true, owner reads have them filtered
// out server-side.

export interface AnnouncementAttachmentResponse {
  id: string;
  announcement_id: string;
  filename: string;
  mime_type: string | null;
  size_bytes: number;
  uploaded_by_user_id: string | null;
  created_at: string;
}

export interface AnnouncementCommentResponse {
  id: string;
  announcement_id: string;
  author_user_id: string;
  author_email: string | null;
  body: string;
  created_at: string;
  updated_at: string;
  // NULL until the author has edited the comment at least once.
  // Portal renders a "bearbeitet" indicator when set.
  edited_at: string | null;
  is_hidden: boolean;
  hidden_at: string | null;
  hidden_by_user_id: string | null;
  hidden_reason: string | null;
}

export interface AnnouncementResponse {
  id: string;
  organization_id: string;
  property_id: string;
  created_by_user_id: string;
  title: string;
  body: string;
  audience_eigentuemer: boolean;
  audience_mieter: boolean;
  audience_beirat: boolean;
  created_at: string;
  updated_at: string;
  scheduled_publish_at: string;
  // Null while unpublished. Doubles as the "is published" flag.
  notification_sent_at: string | null;
  // Denormalised fields populated by the backend handler.
  property_name: string | null;
  creator_email: string | null;
  is_edited: boolean;
  attachment_count: number;
  comment_count: number;
  // Optional per-unit narrowing. Empty = property-wide-by-role
  // (default). Non-empty = recipients are intersected with users
  // on contracts for these units.
  unit_ids: string[];
  // Per-Mitteilung recipient overrides. Empty = pure auto-resolution.
  excluded_user_ids: string[];
  extra_emails: string[];
}

export interface AnnouncementDetailResponse extends AnnouncementResponse {
  attachments: AnnouncementAttachmentResponse[];
  comments: AnnouncementCommentResponse[];
}

export interface AnnouncementCreateRequest {
  title: string;
  body: string;
  audience_eigentuemer: boolean;
  audience_mieter: boolean;
  audience_beirat: boolean;
  // Optional per-unit narrowing. Empty = property-wide-by-role.
  unit_ids: string[];
}

export interface AnnouncementUpdateRequest {
  title?: string;
  body?: string;
  audience_eigentuemer?: boolean;
  audience_mieter?: boolean;
  audience_beirat?: boolean;
  // null = leave existing unit rows alone; explicit list (incl. [])
  // replaces the entire set (PUT-style on the collection).
  unit_ids?: string[];
  // Recipient overrides — same PUT-style semantics.
  excluded_user_ids?: string[];
  extra_emails?: string[];
}

export interface AnnouncementSendAttemptResponse {
  id: string;
  announcement_id: string;
  recipient_email: string;
  recipient_user_id: string | null;
  // "SUCCESS" | "FAILED"
  status: string;
  error_message: string | null;
  // Stable category for SPA branching:
  // "rate_limited" | "no_api_key" | "upstream" | null
  error_code: string | null;
  attempted_at: string;
}

export interface RecipientPreviewItem {
  // "AUTO_USER" — resolved via audience + unit filter
  // "EXTRA_EMAIL" — admin-added free-text email (no user account)
  kind: string;
  email: string;
  user_id: string | null;
  user_role: string | null;
  // True only for AUTO_USER rows the admin has unchecked.
  // EXTRA_EMAIL rows are always included by definition.
  excluded: boolean;
}

export interface RecipientPreviewResponse {
  items: RecipientPreviewItem[];
  active_emails: string[];
}

export interface AnnouncementResendSummary {
  attempted: number;
  succeeded: number;
  failed: number;
  error_message_examples: string[];
  // Most-frequent FAILED error_code in this pass — drives the
  // friendlier SPA copy (e.g. "Tageslimit erreicht" for rate_limited).
  dominant_error_code: string | null;
}

export interface AnnouncementCommentVersionResponse {
  id: string;
  comment_id: string;
  body: string;
  author_user_id: string;
  // ISO 8601 timestamp of when this body was *replaced*. The current
  // (live) body lives on the parent AnnouncementCommentResponse and
  // its replacement time is `edited_at`.
  recorded_at: string;
}
