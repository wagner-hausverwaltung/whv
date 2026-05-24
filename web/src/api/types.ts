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

export interface TicketMessageResponse {
  id: string;
  ticket_id: string;
  author_user_id: string;
  body: string;
  is_internal_note: boolean;
  created_at: string;
}

export interface TicketResponse {
  id: string;
  property_id: string | null;
  created_by_user_id: string;
  assignee_user_id: string | null;
  category: TicketCategory;
  status: TicketStatus;
  subject: string;
  last_message_at: string;
  created_at: string;
  closed_at: string | null;
}

export interface TicketDetailResponse extends TicketResponse {
  messages: TicketMessageResponse[];
}

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
