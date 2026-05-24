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
}

export type TicketCategory =
  | "SCHADEN"
  | "VERWALTUNG"
  | "HAUSGELD"
  | "SONSTIGES";

export type TicketStatus =
  | "NEU"
  | "OFFEN"
  | "WARTET_AUF_KUNDE"
  | "GESCHLOSSEN";

export type TicketShareScope = "PRIVATE" | "PARTICIPANTS" | "PROPERTY";

export interface TicketMessageResponse {
  id: string;
  ticket_id: string;
  author_email?: string | null;
  author_user_id: string;
  body: string;
  is_internal_note: boolean;
  created_at: string;
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
  created_by_user_id: string;
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

export const TICKET_CATEGORY_LABELS: Record<TicketCategory, string> = {
  SCHADEN: "Schaden",
  VERWALTUNG: "Verwaltung",
  HAUSGELD: "Hausgeld",
  SONSTIGES: "Sonstiges",
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
