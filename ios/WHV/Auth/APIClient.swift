// Backend HTTP surface. Targets the same /auth/login endpoint the
// React portal uses, so a single set of credentials works across
// both clients.
//
// Scope is deliberately tiny for the scaffold: login + refresh +
// authenticated /me/* style GETs. Phase 2 expands this with PATCH/
// POST/etc. for tickets, announcements, etc. — same shape.

import Foundation

// MARK: - Wire shapes (mirror backend Pydantic models)

struct UserResponse: Codable, Hashable {
    let id: String
    let email: String
    let role: String  // "verwalter" | "eigentuemer" | "mieter" | "beirat" | "dienstleister"
    let organization_id: String
    let contact_id_impower: Int?
    let avatar_url: String?
}

struct TokenResponse: Codable {
    let access_token: String
    let refresh_token: String
    let expires_in: Int
    let user: UserResponse
}

struct LoginRequest: Codable {
    let email: String
    let password: String
}

/// Body for POST /auth/invite/redeem — same shape the React portal
/// sends (see web/src/pages/InviteRedeemPage.tsx), so the same
/// backend handler can serve both clients.
struct InviteRedeemRequest: Codable {
    let code: String
    let email: String
    let password: String
}

/// Response from GET /auth/invite/{code} — lets the registration
/// screen pre-fill the email so the user doesn't have to retype an
/// address already in their inbox. Returning a different email than
/// the invite is the most common cause of "Einladung ungültig" errors;
/// pre-filling eliminates the typo failure mode.
struct InviteInfoResponse: Codable {
    let email: String
    let role: String
    let organization_name: String
    let expires_at: String
}

/// Mirror of backend PropertyResponse. Only the fields the iOS UI
/// actually reads — leaving impower_id/state/etc. out keeps the
/// decoder forward-compatible.
struct PropertyResponse: Codable, Hashable {
    let id: String
    let property_hr_id: String?
    let name: String
    let type: String
    let city: String?
    let street: String?
    let number: String?
    let postal_code: String?
    let image_url: String?
}

/// One contract currently active on a unit. Backend bundles them
/// into UnitResponse.current_contracts so PropertyDetailView can
/// render the role-tagged tenant/owner chip without a second
/// fetch.
struct UnitContractSummary: Codable, Hashable, Identifiable {
    let contract_id: String
    let contract_number: String?
    let type: String        // OWNER / TENANT / PROPERTY_OWNER
    let contact_id: String?
    let contact_label: String?  // server-rendered "Max Mustermann"
    let role: String?
    let start_date: String?     // ISO-8601 date, no time
    let end_date: String?

    // Identity must be unique per (contract × contact): a single
    // owner/tenant contract can carry several joint contacts (e.g.
    // a couple co-owning one unit), so keying on contract_id alone
    // gave two rows the same id — SwiftUI's ForEach then rendered
    // the first contact's chip twice instead of both names.
    var id: String { "\(contract_id)#\(contact_id ?? "—")#\(role ?? "")" }

    /// "Eigentümer" / "Mieter" / "Verwalter (objekt-eigen)"
    /// for the chip label. Falls back to raw `type` if the
    /// backend ever adds a new ContractType.
    var typeLabel: LocalizedStringResource {
        switch type {
        case "OWNER": return "Eigentümer"
        case "TENANT": return "Mieter"
        case "PROPERTY_OWNER": return "Objekteigentümer"
        default: return LocalizedStringResource(stringLiteral: type)
        }
    }
}

/// One Einheit inside a property — mirrors the backend's
/// UnitResponse. PropertyDetailView renders these as a compact
/// table beneath the address card.
struct UnitResponse: Codable, Hashable, Identifiable {
    let id: String
    let unit_hr_id: String?
    let type: String
    let floor: String?
    let position: String?
    let unit_rank: Int?
    let is_owned_by_weg: Bool?
    /// Pydantic v2 emits Decimal as JSON number — Double is enough
    /// precision for the read-only display in PropertyDetailView.
    let voting_share: Double?
    let area_m2: Double?
    /// Heizfläche — heating floor area, often differs from area_m2
    /// (terraces / cellars excluded). Manual-fill on our side since
    /// Impower's REST API doesn't expose the panel. Optional.
    let heated_area_m2: Double?
    /// Personen — registered head-count for cost distribution.
    /// Number, not Int, because Impower allows 0.5 partials.
    let persons: Double?
    let rooms: Double?
    /// Empty array when no contracts are currently active (vacant
    /// or stub). Decoded with a default via custom init so older
    /// payloads (without the field) still parse.
    let current_contracts: [UnitContractSummary]

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        unit_hr_id = try c.decodeIfPresent(String.self, forKey: .unit_hr_id)
        type = try c.decode(String.self, forKey: .type)
        floor = try c.decodeIfPresent(String.self, forKey: .floor)
        position = try c.decodeIfPresent(String.self, forKey: .position)
        unit_rank = try c.decodeIfPresent(Int.self, forKey: .unit_rank)
        is_owned_by_weg = try c.decodeIfPresent(Bool.self, forKey: .is_owned_by_weg)
        voting_share = try c.decodeIfPresent(Double.self, forKey: .voting_share)
        area_m2 = try c.decodeIfPresent(Double.self, forKey: .area_m2)
        heated_area_m2 = try c.decodeIfPresent(Double.self, forKey: .heated_area_m2)
        persons = try c.decodeIfPresent(Double.self, forKey: .persons)
        rooms = try c.decodeIfPresent(Double.self, forKey: .rooms)
        current_contracts = (try? c.decode([UnitContractSummary].self, forKey: .current_contracts)) ?? []
    }

    enum CodingKeys: String, CodingKey {
        case id, unit_hr_id, type, floor, position, unit_rank
        case is_owned_by_weg, voting_share, area_m2, heated_area_m2
        case persons, rooms
        case current_contracts
    }
}

/// One invoice row inside a VendorSummary's recent-history list.
/// The actual PDF is fetched via the existing
/// `/me/documents/{id}/file` endpoint when the user taps the row.
struct VendorInvoiceSummary: Codable, Hashable, Identifiable {
    let id: String
    let name: String
    let issued_date: String?
    /// Pydantic v2 emits Decimal as a JSON number — Double is enough
    /// precision for the rendered amount. May be nil for early-stage
    /// invoices without a parsed total.
    let amount: Double?
}

/// Per-vendor aggregate returned by
/// `GET /me/properties/{id}/vendors`. Drives the Dienstleister
/// section in PropertyDetailView — owners see who's worked on the
/// property and can call/email them back.
struct VendorSummary: Codable, Hashable, Identifiable {
    let contact_id: String
    let name: String
    /// PERSON | COMPANY — drives the row icon (briefcase vs person).
    let kind: String
    let email: String?
    let phone: String?
    let invoice_count: Int
    let total_amount: Double?
    let first_service_date: String?
    let last_service_date: String?
    let recent_invoices: [VendorInvoiceSummary]

    var id: String { contact_id }
}

/// One posting line in an InvoiceDetailResponse. Comes from
/// Impower's `/v2/invoices/{id}.items` — the bookkeeping breakdown
/// owners want to see ("Primärenergie 01.01.-31.12.2025 · 250 €").
struct InvoiceLineItemResponse: Codable, Hashable, Identifiable {
    let account_code: String?
    let account_name: String?
    let booking_text: String?
    let amount: Double?
    let vat_amount: Double?
    let vat_percentage: Double?

    /// Synthetic id — line items don't carry one on the wire and
    /// we need something stable for SwiftUI ForEach. Falls back to
    /// the booking text + amount so the same line in the same
    /// position keeps its identity across re-decodes.
    var id: String {
        "\(account_code ?? "")|\(booking_text ?? "")|\(amount ?? 0)"
    }
}

/// Header + items returned by
/// `GET /me/properties/{property_id}/invoices/{document_id}`.
/// Drives the per-invoice detail sheet on the Dienstleister
/// section of PropertyDetailView.
struct InvoiceDetailResponse: Codable, Hashable {
    let invoice_number: String?
    let issued_date: String?
    let amount: Double?
    /// DRAFT | READY | BOOKED | SCHEDULED | REVERSED.
    let state: String?
    let counterpart_name: String?
    /// Vendor (recipient) IBAN/BIC — "Zum Konto".
    let counterpart_iban: String?
    let counterpart_bic: String?
    /// Property (sender) IBAN/BIC — "Vom Konto".
    let property_iban: String?
    let property_bic: String?
    /// True when Impower generates a bank order for this invoice.
    let order_required: Bool?
    /// Statement text that lands on the bank order.
    let order_statement: String?
    /// Days from booking → bank-order execution.
    let order_day_offset: Int?
    let items: [InvoiceLineItemResponse]
}

/// Detail variant of PropertyResponse — adds the embedded unit
/// list. Returned by GET /me/properties/{id}.
struct PropertyDetailResponse: Codable, Hashable {
    let id: String
    let property_hr_id: String?
    let name: String
    let type: String
    let city: String?
    let street: String?
    let number: String?
    let postal_code: String?
    let image_url: String?
    let units: [UnitResponse]
}

/// Contract context attached to ContactDetailResponse. Answers the
/// "why am I looking at this contact for this property" half of
/// the dialog.
struct ContractContextResponse: Codable, Hashable {
    let id: String
    /// OWNER / TENANT / PROPERTY_OWNER.
    let type: String
    let contract_number: String?
    let name: String?
    let start_date: String?
    let end_date: String?
    let is_vacant: Bool?
    /// Free-text role from contract_contacts (rare).
    let role: String?
}

/// One row of the per-user notification matrix from
/// `/me/notification-settings`. `category` is one of
/// ANNOUNCEMENT / TICKET / ETV_COMMENT / ETV_INVITATION / DOCUMENT.
/// `push` + `email` are mutable so the settings view can toggle them
/// in place before PUT-ing the whole set back.
struct NotificationSetting: Codable, Hashable, Identifiable {
    let category: String
    var push: Bool
    var email: Bool
    var id: String { category }
}

struct NotificationSettingsResponse: Codable, Hashable {
    let items: [NotificationSetting]
}

/// One booking on the owner's Hausgeldkonto. `amount` is signed; the
/// view shows it neutrally.
struct PostingItem: Codable, Hashable {
    let post_date: String?
    let booking_text: String?
    let amount: Double?
}

/// The owner's Hausgeldkonto for a property, from
/// `GET /me/properties/{id}/account`. `account_id` is nil when the
/// owner has no CONTACT account on the property (the view hides the
/// section in that case). `balance` is the signed sum of bookings,
/// shown neutrally as "Saldo".
struct HausgeldAccount: Codable, Hashable {
    let account_id: Int?
    let account_hr_id: String?
    let name: String?
    let balance: Double?
    let bookings: [PostingItem]
}

/// One Mietabrechnung period for an MV-property owner, from
/// `GET /me/properties/{id}/rent-settlements`. `payout` is the amount
/// transferred to the owner; amounts shown as-is (neutral).
struct RentSettlement: Codable, Hashable {
    let period_from: String?
    let period_until: String?
    let due_date: String?
    let rent_income: Double?
    let payout: Double?
    let balance: Double?
    let state: String?
}

/// Full contact card returned by
/// `GET /me/contracts/{contractId}/contacts/{contactId}`. Drives the
/// sheet opened by tapping a contract chip on PropertyDetailView.
/// Mirrors backend `ContactDetailResponse` field-for-field.
struct ContactDetailResponse: Codable, Hashable {
    let id: String
    /// PERSON or COMPANY.
    let kind: String
    // Person
    let salutation: String?
    let title: String?
    let first_name: String?
    let last_name: String?
    let date_of_birth: String?
    // Company
    let company_name: String?
    let vat_id: String?
    let trade_register_number: String?
    // Communications
    let recipient_name: String?
    let mandate_number: String?
    let email: String?
    let phone: String?
    /// PORTAL / EMAIL / WHATSAPP / EPOST.
    let preferred_channel: String
    /// Free-form key/value pairs of extra channels Impower exposes
    /// (e.g. "Mobil Privat": "+49 …"). Decoded as `[String: String]`
    /// — Impower's JSON can carry nested objects but we only render
    /// the leaf string values; non-strings get dropped at decode time
    /// via the custom container below to keep the sheet predictable.
    let additional_contacts: [String: String]?
    // Address
    let city: String?
    let street: String?
    let number: String?
    let postal_code: String?
    let country: String?
    let contract: ContractContextResponse

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        kind = try c.decode(String.self, forKey: .kind)
        salutation = try c.decodeIfPresent(String.self, forKey: .salutation)
        title = try c.decodeIfPresent(String.self, forKey: .title)
        first_name = try c.decodeIfPresent(String.self, forKey: .first_name)
        last_name = try c.decodeIfPresent(String.self, forKey: .last_name)
        date_of_birth = try c.decodeIfPresent(String.self, forKey: .date_of_birth)
        company_name = try c.decodeIfPresent(String.self, forKey: .company_name)
        vat_id = try c.decodeIfPresent(String.self, forKey: .vat_id)
        trade_register_number = try c.decodeIfPresent(String.self, forKey: .trade_register_number)
        recipient_name = try c.decodeIfPresent(String.self, forKey: .recipient_name)
        mandate_number = try c.decodeIfPresent(String.self, forKey: .mandate_number)
        email = try c.decodeIfPresent(String.self, forKey: .email)
        phone = try c.decodeIfPresent(String.self, forKey: .phone)
        preferred_channel = try c.decode(String.self, forKey: .preferred_channel)
        city = try c.decodeIfPresent(String.self, forKey: .city)
        street = try c.decodeIfPresent(String.self, forKey: .street)
        number = try c.decodeIfPresent(String.self, forKey: .number)
        postal_code = try c.decodeIfPresent(String.self, forKey: .postal_code)
        country = try c.decodeIfPresent(String.self, forKey: .country)
        contract = try c.decode(ContractContextResponse.self, forKey: .contract)
        // Drop non-string values silently — Impower occasionally
        // returns numbers / nulls and we'd rather render the rest
        // than fail decoding.
        if let raw = try c.decodeIfPresent([String: AnyCodable].self, forKey: .additional_contacts) {
            additional_contacts = raw.compactMapValues { v in
                if let s = v.value as? String { return s }
                if let n = v.value as? Int { return String(n) }
                if let n = v.value as? Double { return String(n) }
                return nil
            }
        } else {
            additional_contacts = nil
        }
    }

    enum CodingKeys: String, CodingKey {
        case id, kind, salutation, title, first_name, last_name
        case date_of_birth, company_name, vat_id, trade_register_number
        case recipient_name, mandate_number, email, phone
        case preferred_channel, additional_contacts
        case city, street, number, postal_code, country, contract
    }
}

/// Tiny `Any` wrapper for JSON values we only need to inspect, not
/// re-encode. Used by ContactDetailResponse's additional_contacts
/// dictionary so heterogeneous Impower payloads survive decoding.
private struct AnyCodable: Decodable {
    let value: Any?
    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { value = nil; return }
        if let s = try? c.decode(String.self) { value = s; return }
        if let i = try? c.decode(Int.self) { value = i; return }
        if let d = try? c.decode(Double.self) { value = d; return }
        if let b = try? c.decode(Bool.self) { value = b; return }
        value = nil
    }
}

/// POST body for /me/assemblies/{id}/comments. Mirrors
/// CreateAssemblyCommentRequest.
struct CreateAssemblyCommentBody: Codable {
    let body: String
}

/// Empty JSON body for no-payload POSTs (e.g. Vollmacht revoke). The
/// endpoint ignores it; sending `{}` keeps the authedJSON helper happy.
struct EmptyBody: Codable {}

/// Digitale Vollmacht (ETV proxy, ADR-0017). `status` is "SIGNED" |
/// "REVOKED"; `signed_at` is kept as a String (display-only) so it skips
/// the strict ISO-datetime date decoder.
struct VollmachtResponse: Codable, Hashable, Identifiable {
    let id: String
    let assembly_id: String
    let property_id: String
    let principal_user_id: String?
    let principal_name: String
    let proxy_name: String
    let scope_note: String?
    let status: String
    let signed_at: String
    let revoked_at: String?
    let has_pdf: Bool
    let principal_email: String?
}

/// One entry in the merged Liegenschafts-Kalender (ADR-0018) — a stored
/// event or a derived ETV date. `kind` is ETV/WINTERDIENST/KEHRWOCHE/TERMIN;
/// `source` is "event" | "etv". Dates are kept as "YYYY-MM-DD" Strings.
struct CalendarEntry: Codable, Hashable, Identifiable {
    let kind: String
    let source: String
    let id: String
    let title: String
    let starts_on: String
    let ends_on: String?
    let assigned_user_id: String?
    let assigned_label: String?
    let note: String?
    let assembly_id: String?
}

/// Minimal Ticket summary — only the fields the widget feeder
/// reads. The full Mitteilungen / Tickets screens get their own
/// richer types once those tabs land.
/// Wire shape for /me/tickets list rows. Status / category use the
/// real Swift enums so consumers don't deal with stringly-typed
/// values. Unknown status decodes to .neu defensively; unknown
/// category to .sonstigesOther (forward-compat with future server
/// additions). Both decoders surface on this list endpoint.
struct TicketSummary: Codable, Hashable, Identifiable {
    let id: String
    let property_id: String?
    let subject: String
    let status: TicketStatus
    let category: TicketCategory
    let last_message_at: Date
    let created_at: Date
    let closed_at: Date?
    let property_name: String?
    let property_address: String?
    let creator_email: String?

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        property_id = try c.decodeIfPresent(String.self, forKey: .property_id)
        subject = try c.decode(String.self, forKey: .subject)
        // Tolerate unknown status — backend may add NEU/OFFEN-style
        // values we don't know yet.
        if let raw = try? c.decode(String.self, forKey: .status),
           let s = TicketStatus(rawValue: raw) {
            status = s
        } else {
            status = .neu
        }
        if let raw = try? c.decode(String.self, forKey: .category),
           let cat = TicketCategory(rawValue: raw) {
            category = cat
        } else {
            category = .sonstigesOther
        }
        last_message_at = try c.decode(Date.self, forKey: .last_message_at)
        created_at = try c.decode(Date.self, forKey: .created_at)
        closed_at = try c.decodeIfPresent(Date.self, forKey: .closed_at)
        property_name = try c.decodeIfPresent(String.self, forKey: .property_name)
        property_address = try c.decodeIfPresent(String.self, forKey: .property_address)
        creator_email = try c.decodeIfPresent(String.self, forKey: .creator_email)
    }

    enum CodingKeys: String, CodingKey {
        case id, property_id, subject, status, category
        case last_message_at, created_at, closed_at
        case property_name, property_address, creator_email
    }
}

struct AnnouncementSummary: Codable, Hashable, Identifiable {
    let id: String
    let property_id: String
    let title: String
    let body: String
    let scheduled_publish_at: Date
    let notification_sent_at: Date?
    let property_name: String?
}

/// POST body for /me/announcements/{id}/comments. Mirrors backend's
/// AnnouncementCommentCreateRequest.
struct CreateAnnouncementCommentBody: Codable {
    let body: String
}

/// POST body for /me/tickets. Mirrors backend's TicketCreateRequest.
struct CreateTicketBody: Codable {
    let subject: String
    let body: String
    let category: String
    let property_id: String?
    let share_scope: String
}

/// POST body for /me/tickets/{id}/messages. Only the body field is
/// surfaced today — owners can't post internal notes (the server
/// silently coerces is_internal_note to false on /me/*).
struct CreateTicketMessageBody: Codable {
    let body: String
}

/// POST body for /auth/refresh. Single field — the backend swaps it
/// for a new access+refresh pair plus the user envelope.
struct RefreshRequest: Codable {
    let refresh_token: String
}

// MARK: - Errors

// MARK: - Assistant (ADR-0013)

/// One source citation in an assistant answer. Mirrors the backend
/// AssistantQueryResponse.sources entries. Backend de-dupes by document,
/// so `document_id` is a stable Identifiable id for the chip list.
struct AssistantCitation: Codable, Hashable, Identifiable {
    // The [index] the answer cited — shown on the chip so the inline [n] maps to it.
    let index: Int
    let document_id: String
    let page: Int?
    let source_kind: String?
    let contact_name: String?
    // ADR-0013 §4: "document" → open via /me/documents/{id}/file; a master-data
    // card like "dienstleister" has no file (contact_id/property_id locate the
    // entity). Optional so a newer client tolerates an older backend that
    // omits them (decodes to nil → treated as a document).
    let source_type: String?
    let contact_id: String?
    let property_id: String?
    // index is unique per answer (each cited [n] is distinct) — use it as the
    // Identifiable id so ForEach stays stable even if two cites share a doc.
    var id: Int { index }
    var isMasterData: Bool { (source_type ?? "document") != "document" }
}

struct AssistantQueryResponse: Codable {
    let answer: String
    let abstained: Bool
    let sources: [AssistantCitation]
}

struct AssistantHistoryTurn: Codable {
    let role: String  // "user" | "assistant"
    let content: String
}

struct AssistantQueryRequest: Codable {
    let question: String
    let history: [AssistantHistoryTurn]
    let property_id: String?
    let conversation_id: String?
}

enum APIError: Error, LocalizedError {
    case invalidURL
    case network(Error)
    case http(status: Int, detail: String?)
    case decoding(Error)
    case unauthorized
    /// Mutating API call attempted while demo mode is active.
    /// Surfaces as a friendly message in any composer that tries
    /// to write (POST comment / new ticket / etc.).
    case demoReadOnly
    /// The meter-reading submit endpoint soft-blocked an implausible
    /// value (HTTP 409). The backend's structured `detail` carries a
    /// German `message`, a machine `code` (below_last / unusual_high /
    /// unusual_low), and the last/new values. The reading flow catches
    /// this distinctly to offer "Trotzdem speichern" (resubmit with
    /// `force: true`) instead of treating it as a hard error.
    case implausibleReading(message: String, code: String, lastValue: Double?, newValue: Double?)

    var errorDescription: String? {
        switch self {
        case .invalidURL:
            return "Ungültige URL"
        case .network(let err):
            return "Netzwerkfehler: \(err.localizedDescription)"
        case .http(let status, let detail):
            if let detail = detail, !detail.isEmpty {
                return detail
            }
            return "Server antwortete mit Status \(status)."
        case .decoding:
            return "Antwort konnte nicht ausgewertet werden."
        case .unauthorized:
            return "E-Mail oder Passwort ungültig."
        case .demoReadOnly:
            return String(localized: "Im Demo-Modus nicht verfügbar.")
        case .implausibleReading(let message, _, _, _):
            return message
        }
    }
}

// MARK: - Client

/// Async URLSession-based client for the WHV backend.
///
/// `baseURL` is build-config driven: Debug builds (Xcode / simulator)
/// target staging; Release builds (TestFlight / App Store) target prod.
/// Pass an explicit `baseURL` to the init to override (tests / demo).
struct APIClient {
    static let stagingBaseURL = URL(string: "https://staging.api.wagner-hausverwaltung.com")!
    static let prodBaseURL = URL(string: "https://api.wagner-hausverwaltung.com")!

    /// Debug → staging, Release → prod.
    #if DEBUG
    static let defaultBaseURL = stagingBaseURL
    static let portalForgotPasswordURL = URL(
        string: "https://staging.portal.wagner-hausverwaltung.com/forgot-password")!
    #else
    static let defaultBaseURL = prodBaseURL
    static let portalForgotPasswordURL = URL(
        string: "https://portal.wagner-hausverwaltung.com/forgot-password")!
    #endif

    let baseURL: URL
    let session: URLSession
    /// Pulls the current access token at request time (not init time)
    /// so a fresh sign-in is picked up by long-lived APIClient
    /// instances without rebuilding them. Returns nil when no user
    /// is signed in; authed endpoints surface that as `.unauthorized`.
    let tokenProvider: () -> String?
    /// Reads the refresh token (same lifetime as the access token,
    /// also in Keychain). Used by the 401 retry path to swap an
    /// expired access token for a fresh one before bouncing the user
    /// to LoginView.
    let refreshTokenProvider: () -> String?
    /// Called when /auth/refresh returns a new token pair so the
    /// AuthStore-backed Keychain entries stay in lockstep with what
    /// the client is using on retried requests.
    let onTokenRefreshed: ((TokenResponse) -> Void)?

    init(
        baseURL: URL = APIClient.defaultBaseURL,
        session: URLSession = .shared,
        tokenProvider: @escaping () -> String? = APIClient.defaultTokenProvider,
        refreshTokenProvider: @escaping () -> String? = APIClient.defaultRefreshTokenProvider,
        onTokenRefreshed: ((TokenResponse) -> Void)? = APIClient.defaultOnTokenRefreshed
    ) {
        self.baseURL = baseURL
        self.session = session
        self.tokenProvider = tokenProvider
        self.refreshTokenProvider = refreshTokenProvider
        self.onTokenRefreshed = onTokenRefreshed
    }

    /// Default: read `access_token` out of the shared Keychain. Same
    /// key AuthStore writes to. Keeping this static so the type can
    /// be constructed without dependency injection — picks up the
    /// token at call time.
    static func defaultTokenProvider() -> String? {
        Keychain().read("access_token")
    }

    static func defaultRefreshTokenProvider() -> String? {
        Keychain().read("refresh_token")
    }

    /// Default: persist the refreshed pair to Keychain so every
    /// subsequent request (across stores, across APIClient instances)
    /// picks up the new access token without a second refresh.
    /// AuthStore wraps this to also update its @Published `user`.
    static func defaultOnTokenRefreshed(_ tokens: TokenResponse) {
        let kc = Keychain()
        try? kc.write(tokens.access_token, for: "access_token")
        try? kc.write(tokens.refresh_token, for: "refresh_token")
    }

    /// JSONDecoder used by every authenticated GET. Backend serialises
    /// timestamps as ISO8601 with timezone, sometimes with fractional
    /// seconds (Pydantic v2 includes microseconds). Fall through both
    /// formats so we don't fail to decode microsecond-bearing rows.
    static let jsonDecoder: JSONDecoder = {
        let decoder = JSONDecoder()
        let withFractional = ISO8601DateFormatter()
        withFractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let plain = ISO8601DateFormatter()
        plain.formatOptions = [.withInternetDateTime]
        decoder.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            let str = try container.decode(String.self)
            if let d = withFractional.date(from: str) { return d }
            if let d = plain.date(from: str) { return d }
            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "Invalid ISO8601 date: \(str)"
            )
        }
        return decoder
    }()

    // MARK: Auth

    /// Exchange (email, password) for tokens. Email is lowercased
    /// + trimmed before the call, matching the portal's behaviour
    /// (the backend is case-insensitive on lookup but we want both
    /// clients writing the same canonical form for any logging /
    /// debug stations to compare cleanly).
    func login(email: String, password: String) async throws -> TokenResponse {
        let body = LoginRequest(
            email: email.trimmingCharacters(in: .whitespacesAndNewlines).lowercased(),
            password: password
        )
        var request = URLRequest(url: baseURL.appending(path: "/auth/login"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.httpBody = try JSONEncoder().encode(body)

        let (data, response) = try await performWithMapping(request)

        if let http = response as? HTTPURLResponse, http.statusCode == 401 {
            throw APIError.unauthorized
        }
        try Self.throwIfNotOK(response: response, data: data)
        return try Self.decode(TokenResponse.self, from: data)
    }

    /// Look up an invite by code so the registration screen can
    /// pre-fill the email field as read-only. 404 covers
    /// not-found / expired / consumed — the client just shows the
    /// same "invite no longer valid" error in all three cases.
    func fetchInviteInfo(code: String) async throws -> InviteInfoResponse {
        let trimmed = code.trimmingCharacters(in: .whitespacesAndNewlines)
        // Path-component encoding for safety with stray characters.
        var components = URLComponents(
            url: baseURL.appending(path: "/auth/invite/").appending(path: trimmed),
            resolvingAgainstBaseURL: false
        )
        // appending(path:) already percent-encodes; URLComponents wrap
        // is just for symmetry with other helpers. Build the URL
        // directly to avoid a nil-unwrap.
        components?.path = "/auth/invite/\(trimmed)"
        let url = components?.url(relativeTo: baseURL) ?? baseURL.appending(path: "/auth/invite/\(trimmed)")
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        let (data, response) = try await performWithMapping(request)
        try Self.throwIfNotOK(response: response, data: data)
        return try Self.decode(InviteInfoResponse.self, from: data)
    }

    /// Redeem an invite code (POST /auth/invite/redeem). Returns the
    /// same TokenResponse as /auth/login — the backend creates the
    /// user, sets the password, and issues a fresh JWT pair in one
    /// step. No separate "activate account" follow-up needed.
    ///
    /// 400/409 from the backend bubble up as APIError.http with the
    /// FastAPI `detail` string so the registration screen can show
    /// "Einladung abgelaufen", "E-Mail-Adresse passt nicht", etc.
    /// verbatim — same UX the portal gets.
    func redeemInvite(
        code: String,
        email: String,
        password: String
    ) async throws -> TokenResponse {
        let body = InviteRedeemRequest(
            code: code.trimmingCharacters(in: .whitespacesAndNewlines),
            email: email.trimmingCharacters(in: .whitespacesAndNewlines).lowercased(),
            password: password
        )
        var request = URLRequest(url: baseURL.appending(path: "/auth/invite/redeem"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.httpBody = try JSONEncoder().encode(body)

        let (data, response) = try await performWithMapping(request)
        try Self.throwIfNotOK(response: response, data: data)
        return try Self.decode(TokenResponse.self, from: data)
    }

    /// Trade a refresh token for a fresh access+refresh pair. Called
    /// by the 401 retry path, AND by AuthStore on cold start when it
    /// wants to revalidate stale credentials before the user starts
    /// tapping. 401 here means "refresh token has been revoked or
    /// is too old" — the caller should sign out.
    func refresh(refreshToken: String) async throws -> TokenResponse {
        var request = URLRequest(url: baseURL.appending(path: "/auth/refresh"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.httpBody = try JSONEncoder().encode(RefreshRequest(refresh_token: refreshToken))
        let (data, response) = try await performWithMapping(request)
        if let http = response as? HTTPURLResponse, http.statusCode == 401 {
            throw APIError.unauthorized
        }
        try Self.throwIfNotOK(response: response, data: data)
        return try Self.decode(TokenResponse.self, from: data)
    }

    // MARK: - /me (authed)

    /// GET /me — the current user envelope. AuthStore hits this on
    /// cold start to detect a server-revoked session.
    func getMe() async throws -> UserResponse {
        try await authedGET("/me")
    }

    // MARK: Activity feed (unified "what's new")

    /// GET /me/activity?limit={limit} — the unified, server-sorted
    /// activity feed (most urgent first) that drives the Home/Lock
    /// Screen widget. Read-only; demo mode short-circuits to a small
    /// canned set so the widget still renders in the screenshot/demo
    /// loop without touching the network. `limit` defaults to 10 —
    /// enough to fill the systemLarge family with headroom.
    func getMyActivity(limit: Int = 10) async throws -> [ActivityItem] {
        if DemoFlag.isActive {
            return await DemoStore.shared.activity(limit: limit)
        }
        return try await authedGET("/me/activity?limit=\(limit)")
    }

    // MARK: Anfragen / Angebote (Verwalter-only, ADR-0019)

    /// GET /admin/offer-inquiries — inbound anfragen@ inquiries (newest first).
    func listOfferInquiries() async throws -> [OfferInquirySummary] {
        if DemoFlag.isActive { return [] }
        return try await authedGET("/admin/offer-inquiries")
    }

    func getOfferInquiry(id: String) async throws -> OfferInquiryDetail {
        try await authedGET("/admin/offer-inquiries/\(id)")
    }

    func getOfferAutoMode() async throws -> Bool {
        if DemoFlag.isActive { return false }
        let r: OfferSettingsResp = try await authedGET("/admin/offer-settings")
        return r.auto_send_enabled
    }

    func setOfferAutoMode(_ enabled: Bool) async throws -> Bool {
        if DemoFlag.isActive { throw APIError.demoReadOnly }
        let r: OfferSettingsResp = try await authedJSON(
            "/admin/offer-settings", method: "PUT", body: OfferSettingsBody(auto_send_enabled: enabled)
        )
        return r.auto_send_enabled
    }

    /// PUT lead-status returns the lean summary (no body/note); decode as such.
    func setOfferLeadStatus(id: String, status: String) async throws -> OfferInquirySummary {
        if DemoFlag.isActive { throw APIError.demoReadOnly }
        return try await authedJSON(
            "/admin/offer-inquiries/\(id)/lead-status", method: "PUT",
            body: OfferLeadStatusBody(lead_status: status)
        )
    }

    func setOfferNote(id: String, note: String?) async throws -> OfferInquiryDetail {
        if DemoFlag.isActive { throw APIError.demoReadOnly }
        return try await authedJSON(
            "/admin/offer-inquiries/\(id)/note", method: "PUT", body: OfferNoteBody(review_note: note)
        )
    }

    func setOfferFields(id: String, body: OfferFieldsBody) async throws -> OfferInquiryDetail {
        if DemoFlag.isActive { throw APIError.demoReadOnly }
        return try await authedJSON("/admin/offer-inquiries/\(id)/fields", method: "PUT", body: body)
    }

    func sendOfferReminder(id: String) async throws -> OfferInquiryDetail {
        if DemoFlag.isActive { throw APIError.demoReadOnly }
        return try await authedJSON(
            "/admin/offer-inquiries/\(id)/reminder", method: "POST", body: EmptyJSONBody()
        )
    }

    /// POST send returns the lean summary (status now SENT).
    func sendOffer(id: String, body: OfferGenerateBody) async throws -> OfferInquirySummary {
        if DemoFlag.isActive { throw APIError.demoReadOnly }
        return try await authedJSON("/admin/offer-inquiries/\(id)/send", method: "POST", body: body)
    }

    /// GET offer.pdf → local file URL for QuickLook (regenerated server-side).
    func downloadOffer(id: String, filename: String) async throws -> URL {
        if DemoFlag.isActive { throw APIError.demoReadOnly }
        return try await authedDownload("/admin/offer-inquiries/\(id)/offer.pdf", saveAs: filename)
    }

    // MARK: Assistant (ADR-0013)

    /// POST /assistant/query — ask the RAG document assistant. The backend
    /// resolves the caller's ACL scope from the JWT, so we send only the
    /// question. 503 (assistant disabled server-side) surfaces as
    /// APIError.http(status: 503, …); demo mode short-circuits read-only.
    func askAssistant(
        question: String,
        history: [AssistantHistoryTurn] = [],
        propertyId: String? = nil,
        conversationId: String? = nil
    ) async throws -> AssistantQueryResponse {
        if DemoFlag.isActive { throw APIError.demoReadOnly }
        return try await authedJSON(
            "/assistant/query",
            method: "POST",
            body: AssistantQueryRequest(
                question: question,
                history: history,
                property_id: propertyId,
                conversation_id: conversationId
            )
        )
    }

    /// GET /me/documents/{id}/file → local file URL for QuickLook. The
    /// backend re-checks access, so a citation can't open a document the
    /// caller can't see. RAG-indexed documents are always PDFs (ingestion
    /// only handles PDF), so the .pdf suffix picks the right QL renderer.
    func downloadDocument(id: String) async throws -> URL {
        if DemoFlag.isActive { throw APIError.demoReadOnly }
        return try await authedDownload("/me/documents/\(id)/file", saveAs: "dokument-\(id).pdf")
    }

    /// GET /me/properties — list properties visible to the signed-in
    /// user. Verwalter sees all org properties; owners see only
    /// properties they're a contact on. Short-circuits to the demo
    /// seed when demo mode is active.
    func getMyProperties() async throws -> [PropertyResponse] {
        if DemoFlag.isActive {
            return await DemoStore.shared.properties
        }
        return try await authedGET("/me/properties")
    }

    /// GET /me/properties/{id} — full detail with the units list.
    /// Used by PropertyDetailView (§8.3). Short-circuits to a demo
    /// stub when active so the demo user sees their seed property's
    /// detail page populated.
    func getMyPropertyDetail(id: String) async throws -> PropertyDetailResponse {
        if DemoFlag.isActive {
            if let p = await DemoStore.shared.properties.first(where: { $0.id == id }) {
                return PropertyDetailResponse(
                    id: p.id,
                    property_hr_id: p.property_hr_id,
                    name: p.name,
                    type: p.type,
                    city: p.city,
                    street: p.street,
                    number: p.number,
                    postal_code: p.postal_code,
                    image_url: p.image_url,
                    units: await DemoStore.shared.units(for: id)
                )
            }
            throw APIError.http(status: 404, detail: "Demo: nicht gefunden")
        }
        return try await authedGET("/me/properties/\(id)")
    }

    /// GET /me/properties/{id}/documents — the property's documents the
    /// signed-in owner may see (row-scope applied server-side). Demo: empty.
    func getMyPropertyDocuments(propertyId: String) async throws -> [DocumentResponse] {
        if DemoFlag.isActive { return [] }
        return try await authedGET("/me/properties/\(propertyId)/documents")
    }

    /// GET /me/properties/{id}/vendors — aggregate of every invoice
    /// document on the property keyed by vendor contact. Drives the
    /// Dienstleister section on PropertyDetailView. Demo mode hands
    /// back an empty list rather than synthesising fake plumbers.
    func getMyPropertyVendors(propertyId: String) async throws -> [VendorSummary] {
        if DemoFlag.isActive {
            return await DemoStore.shared.vendors(for: propertyId)
        }
        return try await authedGET("/me/properties/\(propertyId)/vendors")
    }

    /// GET /me/properties/{property_id}/invoices/{document_id} —
    /// per-invoice detail with bookkeeping line items, drives the
    /// VendorInvoiceDetailSheet opened by tapping a row in the
    /// Dienstleister section. Backend fetches from Impower on demand
    /// (5-min TTL cache). Demo mode throws so the sheet can render
    /// "Buchungsdetails im Demo nicht verfügbar" rather than fake
    /// line items.
    func getMyInvoiceDetail(
        propertyId: String, documentId: String
    ) async throws -> InvoiceDetailResponse {
        if DemoFlag.isActive { throw APIError.demoReadOnly }
        return try await authedGET(
            "/me/properties/\(propertyId)/invoices/\(documentId)"
        )
    }

    /// GET /me/properties/{id}/account — the caller's own Hausgeldkonto
    /// (balance + booking history), pulled live from Impower. 404 for
    /// users without a personal account (Verwalter). Demo mode has no
    /// real account, so it throws demoReadOnly and the section hides.
    func getMyAccount(propertyId: String) async throws -> HausgeldAccount {
        if DemoFlag.isActive { throw APIError.demoReadOnly }
        return try await authedGET("/me/properties/\(propertyId)/account")
    }

    /// GET /me/properties/{id}/rent-settlements — MV-property owner
    /// Mietabrechnung (payout statements per period). Empty for WEG
    /// properties / tenants. Demo: empty.
    func getMyRentSettlements(propertyId: String) async throws -> [RentSettlement] {
        if DemoFlag.isActive { return [] }
        return try await authedGET("/me/properties/\(propertyId)/rent-settlements")
    }

    /// GET /me/contracts/{contractId}/contacts/{contactId} —
    /// drives the contact-detail sheet opened by tapping a contract
    /// chip on PropertyDetailView. Returns the full mirror of the
    /// contact + the contract context that wires them to the
    /// property. Demo mode synthesises a minimal stub from the chip's
    /// contact_label so the sheet still renders with something.
    func getMyContractContact(
        contractId: String,
        contactId: String,
        fallbackLabel: String,
        contractType: String
    ) async throws -> ContactDetailResponse {
        if DemoFlag.isActive {
            // Reconstruct just enough to populate the sheet — name
            // splits on the first space (good enough for "Max
            // Mustermann"); company labels (Acme GmbH) fall through
            // to last_name which is the visible field anyway.
            let parts = fallbackLabel.split(separator: " ", maxSplits: 1)
            let first = parts.count > 1 ? String(parts[0]) : nil
            let last = parts.count > 1 ? String(parts[1]) : fallbackLabel
            let payload: [String: Any] = [
                "id": contactId,
                "kind": "PERSON",
                "first_name": first as Any,
                "last_name": last as Any,
                "preferred_channel": "EMAIL",
                "contract": [
                    "id": contractId,
                    "type": contractType,
                ],
            ]
            let data = try JSONSerialization.data(withJSONObject: payload)
            return try JSONDecoder().decode(ContactDetailResponse.self, from: data)
        }
        return try await authedGET("/me/contracts/\(contractId)/contacts/\(contactId)")
    }

    /// GET /me/export → tmp file URL with the DSGVO Art. 20 JSON
    /// dump (profile + sessions metadata + audit entries). Caller
    /// presents via ShareLink so the user can save / mail it.
    /// Demo mode can't materialise a server-signed export, so the
    /// call throws `demoReadOnly` — the Datenschutz UI surfaces
    /// "Im Demo-Modus nicht verfügbar." rather than a tmp-file 401.
    func exportMyData() async throws -> URL {
        if DemoFlag.isActive { throw APIError.demoReadOnly }
        let stamp = ISO8601DateFormatter().string(from: Date())
            .replacingOccurrences(of: ":", with: "-")
        return try await authedDownload(
            "/me/export",
            saveAs: "whv-data-export-\(stamp).json"
        )
    }

    /// DELETE /me — soft-deletes the user, revokes every active
    /// session, writes an audit row. Caller signs out cleanly on
    /// success (the JWT is now backed by a revoked session so any
    /// next request would 401 anyway).
    /// Demo mode: there's no real backend account to delete, so the
    /// call returns a no-op success. The caller's existing
    /// post-success path (signOut + deactivate demo) still runs,
    /// which is exactly what the user wants — "delete" in demo is
    /// indistinguishable from "exit demo" because there's nothing
    /// persistent to remove.
    func deleteMyAccount() async throws {
        if DemoFlag.isActive { return }
        guard let token = tokenProvider() else { throw APIError.unauthorized }
        var request = URLRequest(url: baseURL.appending(path: "/me"))
        request.httpMethod = "DELETE"
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        let (data, response) = try await performWithMapping(request)
        try Self.throwIfNotOK(response: response, data: data)
    }

    /// POST /me/devices — register this device's APNs token for push.
    /// `environment` is "SANDBOX" for Debug/Xcode installs,
    /// "PRODUCTION" for TestFlight / App Store; the backend routes
    /// to the matching APNs host. Demo mode no-ops (no real token,
    /// no backend session to attach it to). 204 → no body to decode.
    func registerDevice(apnsToken: String, environment: String) async throws {
        if DemoFlag.isActive { return }
        guard let token = tokenProvider() else { throw APIError.unauthorized }
        var request = URLRequest(url: baseURL.appending(path: "/me/devices"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.httpBody = try JSONSerialization.data(withJSONObject: [
            "apns_token": apnsToken,
            "environment": environment,
        ])
        let (data, response) = try await performWithMapping(request)
        try Self.throwIfNotOK(response: response, data: data)
    }

    /// DELETE /me/devices/{token} — drop the token on sign-out so a
    /// signed-out phone stops receiving the previous user's pushes.
    /// Best-effort: errors are swallowed by the caller (sign-out
    /// shouldn't block on a notification-bookkeeping call).
    func unregisterDevice(apnsToken: String) async throws {
        if DemoFlag.isActive { return }
        guard let token = tokenProvider() else { throw APIError.unauthorized }
        // Percent-encode the token for the path segment (it's hex so
        // usually safe, but defensive).
        let encoded =
            apnsToken.addingPercentEncoding(withAllowedCharacters: .alphanumerics) ?? apnsToken
        var request = URLRequest(url: baseURL.appending(path: "/me/devices/\(encoded)"))
        request.httpMethod = "DELETE"
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        let (data, response) = try await performWithMapping(request)
        try Self.throwIfNotOK(response: response, data: data)
    }

    /// All-on default — mirrors the backend's opt-out semantics so the
    /// matrix renders correctly in demo mode (no backend account).
    static let defaultNotificationSettings: [NotificationSetting] = [
        NotificationSetting(category: "ANNOUNCEMENT", push: true, email: true),
        NotificationSetting(category: "TICKET", push: true, email: true),
        NotificationSetting(category: "ETV_COMMENT", push: true, email: true),
        NotificationSetting(category: "ETV_INVITATION", push: true, email: true),
        NotificationSetting(category: "DOCUMENT", push: true, email: true),
        NotificationSetting(category: "INVOICE", push: true, email: true),
        NotificationSetting(category: "PLAN_ADJUSTMENT", push: true, email: true),
    ]

    /// GET /me/notification-settings → the caller's full Push/E-Mail
    /// matrix (defaults filled server-side). Demo mode returns the
    /// all-on default so the UI still renders.
    func getNotificationSettings() async throws -> [NotificationSetting] {
        if DemoFlag.isActive { return Self.defaultNotificationSettings }
        let resp: NotificationSettingsResponse = try await authedGET("/me/notification-settings")
        return resp.items
    }

    /// PUT /me/notification-settings — persist the whole matrix; the
    /// backend returns the re-read effective set. Demo mode echoes the
    /// input back (nothing to persist).
    func updateNotificationSettings(
        _ items: [NotificationSetting]
    ) async throws -> [NotificationSetting] {
        if DemoFlag.isActive { return items }
        guard let token = tokenProvider() else { throw APIError.unauthorized }
        let body = try JSONEncoder().encode(NotificationSettingsResponse(items: items))
        let url = baseURL.appending(path: "/me/notification-settings")
        do {
            let (data, response) = try await sendAuthed(
                url: url, method: "PUT", body: body, token: token)
            try Self.throwIfNotOK(response: response, data: data)
            return try Self.decodeAuthed(NotificationSettingsResponse.self, from: data).items
        } catch APIError.unauthorized {
            let fresh = try await refreshOrThrow()
            let (data, response) = try await sendAuthed(
                url: url, method: "PUT", body: body, token: fresh)
            try Self.throwIfNotOK(response: response, data: data)
            return try Self.decodeAuthed(NotificationSettingsResponse.self, from: data).items
        }
    }

    /// GET /me/assemblies/{id}/protocol → local file URL. Streams the
    /// PDF into the caller's temporary directory under a stable name
    /// (one file per assembly) so re-opens hit the same path. The
    /// returned URL is suitable for QLPreviewController.
    func downloadAssemblyProtocol(id: String) async throws -> URL {
        try await authedDownload(
            "/me/assemblies/\(id)/protocol",
            saveAs: "protokoll-\(id).pdf"
        )
    }

    /// GET /me/agenda-items/{itemId}/attachments/{attId}/download
    /// → local file URL. Used by AssemblyDetailView to feed
    /// QLPreviewController when an attendee taps an attachment chip.
    /// Filename preserves the original so QuickLook picks the right
    /// renderer (PDF preview vs image viewer vs office handoff).
    func downloadAgendaAttachment(
        agendaItemId: String,
        attachmentId: String,
        filename: String
    ) async throws -> URL {
        if DemoFlag.isActive { throw APIError.demoReadOnly }
        // Sanitise the filename — the backend renders the
        // Content-Disposition header but we re-use the original on
        // disk so the share-sheet / Files app show the right name.
        let safe = filename
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: ":", with: "_")
        return try await authedDownload(
            "/me/agenda-items/\(agendaItemId)/attachments/\(attachmentId)/download",
            saveAs: "\(attachmentId)-\(safe)"
        )
    }

    // MARK: - ETV (authed)

    /// GET /me/properties/{id}/assemblies — list-shape assemblies for
    /// one property. Filters out ABGESAGT server-side.
    func listMyAssemblies(propertyId: String) async throws -> [AssemblySummary] {
        if DemoFlag.isActive {
            return await DemoStore.shared.assemblies(for: propertyId)
        }
        return try await authedGET("/me/properties/\(propertyId)/assemblies")
    }

    /// GET /me/assemblies/{id} — full detail with agenda items +
    /// discussion. Comments are a separate endpoint.
    func getAssemblyDetail(id: String) async throws -> Assembly {
        if DemoFlag.isActive {
            guard let a = await DemoStore.shared.assemblyDetail(id: id) else {
                throw APIError.http(status: 404, detail: "Demo: nicht gefunden")
            }
            return a
        }
        return try await authedGET("/me/assemblies/\(id)")
    }

    /// GET /me/resolutions — Umlaufbeschlüsse on the caller's owned properties.
    /// The endpoint returns all of them; we filter to the active Liegenschaft
    /// (mirrors how the assemblies list is property-scoped). Read-only.
    func listMyResolutions(propertyId: String) async throws -> [ResolutionSummary] {
        if DemoFlag.isActive {
            return await DemoStore.shared.resolutions(for: propertyId)
        }
        let all: [ResolutionSummary] = try await authedGET("/me/resolutions")
        return all.filter { $0.property_id == propertyId }
    }

    /// GET /me/resolutions/{id} — full Beschluss detail with tally + my vote.
    func getResolutionDetail(id: String) async throws -> ResolutionDetail {
        if DemoFlag.isActive {
            guard let r = await DemoStore.shared.resolutionDetail(id: id) else {
                throw APIError.http(status: 404, detail: "Demo: nicht gefunden")
            }
            return r
        }
        return try await authedGET("/me/resolutions/\(id)")
    }

    /// GET /me/resolutions/{id}/result.pdf → local file URL for QuickLook.
    /// Only the Ergebnis-PDF is owner-downloadable (mirrors the portal; the
    /// Beschlusstext itself is shown inline).
    func downloadResolutionResultPDF(id: String) async throws -> URL {
        if DemoFlag.isActive { throw APIError.demoReadOnly }
        return try await authedDownload(
            "/me/resolutions/\(id)/result.pdf", saveAs: "beschluss-ergebnis-\(id).pdf"
        )
    }

    /// GET /me/assemblies/{id}/comments — ordered chronologically.
    func listAssemblyComments(assemblyId: String) async throws -> [AssemblyComment] {
        if DemoFlag.isActive {
            return await DemoStore.shared.comments(for: assemblyId)
        }
        return try await authedGET("/me/assemblies/\(assemblyId)/comments")
    }

    /// POST /me/assemblies/{id}/comments — append a new Q&A entry.
    /// Server fans out an email to every Verwalter + prior commenter.
    func postAssemblyComment(
        assemblyId: String,
        body: String
    ) async throws -> AssemblyComment {
        if DemoFlag.isActive { throw APIError.demoReadOnly }
        return try await authedJSON(
            "/me/assemblies/\(assemblyId)/comments",
            method: "POST",
            body: CreateAssemblyCommentBody(body: body)
        )
    }

    // MARK: - Vollmacht (ETV proxy, ADR-0017)

    /// GET /me/assemblies/{id}/vollmacht — my active Vollmacht, or nil when
    /// none exists yet (the endpoint 404s in that case).
    func getMyVollmacht(assemblyId: String) async throws -> VollmachtResponse? {
        if DemoFlag.isActive { return nil }
        do {
            let v: VollmachtResponse = try await authedGET("/me/assemblies/\(assemblyId)/vollmacht")
            return v
        } catch APIError.http(let status, _) where status == 404 {
            return nil
        }
    }

    /// POST /me/assemblies/{id}/vollmacht — grant + sign (multipart). The PNG
    /// is the owner's drawn signature, composited into the PDF server-side.
    func createVollmacht(
        assemblyId: String,
        proxyName: String,
        scopeNote: String?,
        signaturePNG: Data?
    ) async throws -> VollmachtResponse {
        if DemoFlag.isActive { throw APIError.demoReadOnly }
        var fields = ["proxy_name": proxyName]
        if let scopeNote, !scopeNote.isEmpty { fields["scope_note"] = scopeNote }
        return try await authedMultipart(
            "/me/assemblies/\(assemblyId)/vollmacht",
            fields: fields,
            fileField: signaturePNG == nil ? nil : "signature",
            fileData: signaturePNG,
            fileName: "signature.png",
            mimeType: "image/png"
        )
    }

    /// POST /me/vollmachten/{id}/revoke — withdraw before the meeting.
    func revokeVollmacht(id: String) async throws -> VollmachtResponse {
        if DemoFlag.isActive { throw APIError.demoReadOnly }
        return try await authedJSON(
            "/me/vollmachten/\(id)/revoke", method: "POST", body: EmptyBody()
        )
    }

    /// GET /me/vollmachten/{id}/document.pdf → local file URL for QuickLook.
    func downloadVollmacht(id: String) async throws -> URL {
        if DemoFlag.isActive { throw APIError.demoReadOnly }
        return try await authedDownload(
            "/me/vollmachten/\(id)/document.pdf", saveAs: "vollmacht-\(id).pdf"
        )
    }

    // MARK: - Liegenschafts-Kalender (ADR-0018, read-only)

    /// GET /me/properties/{id}/calendar?year&month — merged month view
    /// (events + derived ETV dates). Demo mode has none.
    func getCalendar(propertyId: String, year: Int, month: Int) async throws -> [CalendarEntry] {
        if DemoFlag.isActive { return [] }
        return try await authedGET("/me/properties/\(propertyId)/calendar?year=\(year)&month=\(month)")
    }

    /// GET /me/properties/{id}/calendar.ics → tmp file URL with the whole
    /// property calendar (ETV + Winterdienst/Kehrwoche/Termin) for sharing
    /// into Outlook / Apple Calendar.
    func downloadCalendarIcs(propertyId: String) async throws -> URL {
        try await authedDownload(
            "/me/properties/\(propertyId)/calendar.ics", saveAs: "kalender.ics")
    }

    // MARK: - Tickets

    /// GET /me/tickets — every ticket the caller can see. Sorted
    /// newest-active first by the server.
    func listMyTickets() async throws -> [TicketSummary] {
        if DemoFlag.isActive {
            return await DemoStore.shared.tickets
        }
        return try await authedGET("/me/tickets")
    }

    /// GET /me/tickets?status=OFFEN — used by the dynamic widget to
    /// surface "X open tickets" + the newest one. Stays separate
    /// from listMyTickets so the widget snapshot is cheap.
    func listMyOpenTickets() async throws -> [TicketSummary] {
        if DemoFlag.isActive {
            return await DemoStore.shared.openTickets()
        }
        return try await authedGET("/me/tickets?status=OFFEN")
    }

    /// GET /me/tickets/{id} — full thread + participants.
    func getMyTicket(id: String) async throws -> TicketDetail {
        if DemoFlag.isActive {
            guard let t = await DemoStore.shared.ticketDetail(id: id) else {
                throw APIError.http(status: 404, detail: "Demo: nicht gefunden")
            }
            return t
        }
        return try await authedGET("/me/tickets/\(id)")
    }

    /// POST /me/tickets — open a new ticket. `propertyId` is optional;
    /// `share_scope` defaults to PRIVATE matching the backend.
    func createMyTicket(
        subject: String,
        body: String,
        category: TicketCategory,
        propertyId: String?
    ) async throws -> TicketDetail {
        if DemoFlag.isActive { throw APIError.demoReadOnly }
        return try await authedJSON(
            "/me/tickets",
            method: "POST",
            body: CreateTicketBody(
                subject: subject,
                body: body,
                category: category.rawValue,
                property_id: propertyId,
                share_scope: "PRIVATE"
            )
        )
    }

    /// POST /me/tickets/{id}/messages — append a reply to the thread.
    func postMyTicketMessage(
        ticketId: String,
        body: String
    ) async throws -> TicketMessage {
        if DemoFlag.isActive { throw APIError.demoReadOnly }
        return try await authedJSON(
            "/me/tickets/\(ticketId)/messages",
            method: "POST",
            body: CreateTicketMessageBody(body: body)
        )
    }

    /// GET /me/tickets/{id}/attachments/{aid}/file → local file URL
    /// suitable for QuickLook. Same authed-binary pattern as
    /// announcement attachments + protocol PDFs.
    func downloadTicketAttachment(
        ticketId: String,
        attachmentId: String,
        filename: String
    ) async throws -> URL {
        let safe = filename
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "\\", with: "_")
            .replacingOccurrences(of: "..", with: "_")
        return try await authedDownload(
            "/me/tickets/\(ticketId)/attachments/\(attachmentId)/file",
            saveAs: "ticket-att-\(attachmentId)-\(safe)"
        )
    }

    /// GET /me/properties/{id}/announcements — used by the dynamic
    /// widget to surface the newest published announcement.
    func listMyAnnouncementsForProperty(_ propertyId: String) async throws -> [AnnouncementSummary] {
        if DemoFlag.isActive {
            return await DemoStore.shared.announcements(for: propertyId)
        }
        return try await authedGET("/me/properties/\(propertyId)/announcements")
    }

    /// GET /me/announcements/{id} — full detail with attachments +
    /// comments embedded.
    func getAnnouncementDetail(id: String) async throws -> AnnouncementDetail {
        if DemoFlag.isActive {
            guard let a = await DemoStore.shared.announcementDetail(id: id) else {
                throw APIError.http(status: 404, detail: "Demo: nicht gefunden")
            }
            return a
        }
        return try await authedGET("/me/announcements/\(id)")
    }

    /// POST /me/announcements/{id}/comments — append a comment.
    /// Server fans out an email notification to Verwalter + thread.
    func postAnnouncementComment(
        announcementId: String,
        body: String
    ) async throws -> AnnouncementComment {
        if DemoFlag.isActive { throw APIError.demoReadOnly }
        return try await authedJSON(
            "/me/announcements/\(announcementId)/comments",
            method: "POST",
            body: CreateAnnouncementCommentBody(body: body)
        )
    }

    /// GET /me/announcements/{id}/attachments/{aid}/download → local
    /// file URL. Same auth-gated streaming path as the protocol PDF.
    func downloadAnnouncementAttachment(
        announcementId: String,
        attachmentId: String,
        filename: String
    ) async throws -> URL {
        // Slug the filename so a "/" or weird character in the
        // server-provided name doesn't escape the tmp directory.
        let safe = filename
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "\\", with: "_")
            .replacingOccurrences(of: "..", with: "_")
        let target = "att-\(attachmentId)-\(safe)"
        return try await authedDownload(
            "/me/announcements/\(announcementId)/attachments/\(attachmentId)/download",
            saveAs: target
        )
    }

    // MARK: - Zähler (meters)

    /// GET /me/properties/{id}/meters — active meters the caller may
    /// report on. Demo mode has no meters → empty list.
    func listMeters(propertyId: String) async throws -> [MeterSummary] {
        if DemoFlag.isActive { return [] }
        return try await authedGET("/me/properties/\(propertyId)/meters")
    }

    /// GET /me/meters/{id}/readings — reading history, newest first.
    func listMeterReadings(meterId: String) async throws -> [MeterReadingItem] {
        if DemoFlag.isActive { return [] }
        return try await authedGET("/me/meters/\(meterId)/readings")
    }

    /// POST /me/meters/{id}/readings/ocr — upload a meter photo, get a
    /// suggested value back. Never fatal server-side (unconfigured provider
    /// or unreadable photo → empty suggestion), so the UI just falls back
    /// to manual entry.
    func ocrMeterPhoto(meterId: String, imageData: Data) async throws -> MeterOCRResult {
        if DemoFlag.isActive { throw APIError.demoReadOnly }
        return try await authedMultipart(
            "/me/meters/\(meterId)/readings/ocr",
            fields: [:],
            fileField: "photo",
            fileData: imageData
        )
    }

    /// POST /me/meters/{id}/readings — submit a reading, optionally with a
    /// photo. `source` is "OCR" when the value came from a photo, "MANUAL"
    /// otherwise.
    ///
    /// `force` overrides the backend's plausibility soft-block: a normal
    /// submit (`force: false`) that looks implausible (below the last
    /// Zählerstand, or consumption wildly off) returns 409, which
    /// `throwIfNotOK` surfaces as `APIError.implausibleReading`. Re-calling
    /// with `force: true` creates the reading despite the warning. The flag
    /// rides along as a plain multipart text field, so it applies whether or
    /// not a photo is attached.
    func submitMeterReading(
        meterId: String,
        value: String,
        readOn: String,
        note: String?,
        source: String,
        imageData: Data?,
        force: Bool = false
    ) async throws -> MeterReadingItem {
        if DemoFlag.isActive { throw APIError.demoReadOnly }
        var fields = [
            "value": value,
            "read_on": readOn,
            "source": source,
            "force": force ? "true" : "false",
        ]
        if let note, !note.isEmpty { fields["note"] = note }
        return try await authedMultipart(
            "/me/meters/\(meterId)/readings",
            fields: fields,
            fileField: imageData == nil ? nil : "photo",
            fileData: imageData
        )
    }

    // MARK: - Authed images

    /// Fetch raw image bytes for an auth-gated image path (e.g. the
    /// property hero photo at `/admin/property-images/{id}.png`, which is
    /// JWT-protected — a plain AsyncImage would 401). `path` is the
    /// relative `image_url` the API returns; we prepend `baseURL` and send
    /// the same Bearer token + one-shot 401-refresh-retry the JSON helpers
    /// use. Returns the body bytes; the caller turns them into a UIImage.
    func fetchImageData(path: String) async throws -> Data {
        guard let token = tokenProvider() else { throw APIError.unauthorized }
        let url = Self.requestURL(baseURL, path)
        do {
            let (data, response) = try await sendAuthed(url: url, method: "GET", body: nil, token: token)
            try Self.throwIfNotOK(response: response, data: data)
            return data
        } catch APIError.unauthorized {
            let fresh = try await refreshOrThrow()
            let (data, response) = try await sendAuthed(url: url, method: "GET", body: nil, token: fresh)
            try Self.throwIfNotOK(response: response, data: data)
            return data
        }
    }

    // MARK: - Plumbing

    /// Generic authed JSON GET. The path is relative to baseURL and
    /// must already be URL-encoded. Returns a decoded T or throws an
    /// APIError that the caller surfaces to the UI verbatim.
    ///
    /// One-shot 401 retry: if the access token has expired but the
    /// refresh token is still valid, /auth/refresh trades it for a
    /// new pair and we replay the original request. A second 401
    /// (or a refresh-side 401) bubbles up as `.unauthorized` so the
    /// app can sign out.
    /// Build a request URL from a path that may carry a query string.
    /// `URL.appending(path:)` percent-encodes "?" *into the path* (swallowing
    /// the whole query → a 404), so split the query off and set it separately.
    static func requestURL(_ base: URL, _ path: String) -> URL {
        guard let qi = path.firstIndex(of: "?") else { return base.appending(path: path) }
        let bare = base.appending(path: String(path[..<qi]))
        guard var comps = URLComponents(url: bare, resolvingAgainstBaseURL: false) else {
            return base.appending(path: path)
        }
        comps.percentEncodedQuery = String(path[path.index(after: qi)...])
        return comps.url ?? base.appending(path: path)
    }

    private func authedGET<T: Decodable>(_ path: String) async throws -> T {
        guard let token = tokenProvider() else { throw APIError.unauthorized }
        let url = Self.requestURL(baseURL, path)
        do {
            let (data, response) = try await sendAuthed(url: url, method: "GET", body: nil, token: token)
            try Self.throwIfNotOK(response: response, data: data)
            return try Self.decodeAuthed(T.self, from: data)
        } catch APIError.unauthorized {
            let fresh = try await refreshOrThrow()
            let (data, response) = try await sendAuthed(url: url, method: "GET", body: nil, token: fresh)
            try Self.throwIfNotOK(response: response, data: data)
            return try Self.decodeAuthed(T.self, from: data)
        }
    }

    /// Generic authed JSON POST/PATCH with a Codable body. Same
    /// one-shot 401 retry semantics as `authedGET`.
    private func authedJSON<T: Decodable, B: Encodable>(
        _ path: String,
        method: String,
        body: B
    ) async throws -> T {
        guard let token = tokenProvider() else { throw APIError.unauthorized }
        let url = Self.requestURL(baseURL, path)
        let encoded = try JSONEncoder().encode(body)
        do {
            let (data, response) = try await sendAuthed(url: url, method: method, body: encoded, token: token)
            try Self.throwIfNotOK(response: response, data: data)
            return try Self.decodeAuthed(T.self, from: data)
        } catch APIError.unauthorized {
            let fresh = try await refreshOrThrow()
            let (data, response) = try await sendAuthed(url: url, method: method, body: encoded, token: fresh)
            try Self.throwIfNotOK(response: response, data: data)
            return try Self.decodeAuthed(T.self, from: data)
        }
    }

    /// Authenticated multipart/form-data POST (photo + text fields). Same
    /// one-shot 401-refresh-retry as the JSON helpers. Used by the meter
    /// reading + OCR endpoints, which take an UploadFile + Form fields.
    private func authedMultipart<T: Decodable>(
        _ path: String,
        fields: [String: String],
        fileField: String? = nil,
        fileData: Data? = nil,
        fileName: String = "foto.jpg",
        mimeType: String = "image/jpeg"
    ) async throws -> T {
        guard let token = tokenProvider() else { throw APIError.unauthorized }
        let url = Self.requestURL(baseURL, path)
        let boundary = "whv-\(UUID().uuidString)"
        let body = Self.multipartBody(
            boundary: boundary,
            fields: fields,
            fileField: fileField,
            fileData: fileData,
            fileName: fileName,
            mimeType: mimeType
        )

        func send(_ tok: String) async throws -> (Data, URLResponse) {
            var request = URLRequest(url: url)
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Accept")
            request.setValue("Bearer \(tok)", forHTTPHeaderField: "Authorization")
            request.setValue(
                "multipart/form-data; boundary=\(boundary)",
                forHTTPHeaderField: "Content-Type"
            )
            request.httpBody = body
            let (data, response) = try await performWithMapping(request)
            if let http = response as? HTTPURLResponse, http.statusCode == 401 {
                throw APIError.unauthorized
            }
            return (data, response)
        }

        do {
            let (data, response) = try await send(token)
            try Self.throwIfNotOK(response: response, data: data)
            return try Self.decodeAuthed(T.self, from: data)
        } catch APIError.unauthorized {
            let fresh = try await refreshOrThrow()
            let (data, response) = try await send(fresh)
            try Self.throwIfNotOK(response: response, data: data)
            return try Self.decodeAuthed(T.self, from: data)
        }
    }

    /// Assemble a multipart/form-data body: text fields first, then an
    /// optional single file part.
    private static func multipartBody(
        boundary: String,
        fields: [String: String],
        fileField: String?,
        fileData: Data?,
        fileName: String,
        mimeType: String
    ) -> Data {
        var body = Data()
        func appendString(_ s: String) {
            if let d = s.data(using: .utf8) { body.append(d) }
        }
        for (key, value) in fields {
            appendString("--\(boundary)\r\n")
            appendString("Content-Disposition: form-data; name=\"\(key)\"\r\n\r\n")
            appendString("\(value)\r\n")
        }
        if let fileField, let fileData {
            appendString("--\(boundary)\r\n")
            appendString(
                "Content-Disposition: form-data; name=\"\(fileField)\"; filename=\"\(fileName)\"\r\n"
            )
            appendString("Content-Type: \(mimeType)\r\n\r\n")
            body.append(fileData)
            appendString("\r\n")
        }
        appendString("--\(boundary)--\r\n")
        return body
    }

    /// Authenticated binary download. Writes the body to
    /// `tmp/{saveAs}` and returns the URL. Same 401-refresh-retry
    /// path as the JSON helpers — QuickLook surfaces the file the
    /// user finally sees.
    private func authedDownload(_ path: String, saveAs filename: String) async throws -> URL {
        guard let token = tokenProvider() else { throw APIError.unauthorized }
        let url = Self.requestURL(baseURL, path)
        let result: (Data, URLResponse)
        do {
            let r = try await sendAuthed(url: url, method: "GET", body: nil, token: token)
            try Self.throwIfNotOK(response: r.1, data: r.0)
            result = r
        } catch APIError.unauthorized {
            let fresh = try await refreshOrThrow()
            let r = try await sendAuthed(url: url, method: "GET", body: nil, token: fresh)
            try Self.throwIfNotOK(response: r.1, data: r.0)
            result = r
        }
        let dest = FileManager.default.temporaryDirectory.appendingPathComponent(filename)
        // Replace any older copy — same assembly id reuses the path,
        // and a stale file is worse than re-downloading.
        try? FileManager.default.removeItem(at: dest)
        try result.0.write(to: dest)
        return dest
    }

    /// Send a single authed request. Returns body+response or throws
    /// `.unauthorized` immediately on 401 (so the caller can decide
    /// whether to refresh). Other non-2xx statuses leave the
    /// status-code check to the caller (so download paths can
    /// reuse this helper without double-throwing).
    private func sendAuthed(
        url: URL,
        method: String,
        body: Data?,
        token: String
    ) async throws -> (Data, URLResponse) {
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        if let body {
            request.httpBody = body
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        let (data, response) = try await performWithMapping(request)
        if let http = response as? HTTPURLResponse, http.statusCode == 401 {
            throw APIError.unauthorized
        }
        return (data, response)
    }

    /// Pull the refresh token, hit /auth/refresh, persist the new
    /// pair via `onTokenRefreshed`, and hand back the new access
    /// token. Any failure bubbles up as `.unauthorized` so the
    /// caller can give up and sign out.
    private func refreshOrThrow() async throws -> String {
        guard let rt = refreshTokenProvider() else { throw APIError.unauthorized }
        let pair = try await refresh(refreshToken: rt)
        onTokenRefreshed?(pair)
        return pair.access_token
    }

    /// Same as `decode` but routes through the ISO8601-aware decoder
    /// so datetime fields round-trip correctly. Login/refresh don't
    /// need it — their bodies are plain strings + ints.
    private static func decodeAuthed<T: Decodable>(_ type: T.Type, from data: Data) throws -> T {
        do {
            return try Self.jsonDecoder.decode(type, from: data)
        } catch {
            throw APIError.decoding(error)
        }
    }

    private func performWithMapping(_ request: URLRequest) async throws -> (Data, URLResponse) {
        do {
            return try await session.data(for: request)
        } catch {
            throw APIError.network(error)
        }
    }

    private static func throwIfNotOK(response: URLResponse, data: Data) throws {
        guard let http = response as? HTTPURLResponse else { return }
        guard !(200...299).contains(http.statusCode) else { return }
        // 401 collapses to a single error case so the UI can react
        // generically (sign-out + bounce to LoginView). 403 stays a
        // generic .http for now — same screens shouldn't usually
        // see one once auth is correct.
        if http.statusCode == 401 {
            throw APIError.unauthorized
        }
        // Backend uses FastAPI's `{detail: "..."}` for 4xx. Pull
        // the human-readable message out so the UI can surface it
        // verbatim — easier debugging than a numeric status code.
        let parsed = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        // The meter-reading submit endpoint soft-blocks an implausible
        // value with a 409 whose `detail` is a STRUCTURED object
        // ({code, message, last_value, new_value}) rather than a plain
        // string. Surface it as a typed error so the reading flow can
        // offer "Trotzdem speichern" (force) instead of a dead-end alert.
        if http.statusCode == 409,
            let structured = parsed?["detail"] as? [String: Any],
            let code = structured["code"] as? String,
            let message = structured["message"] as? String
        {
            // last_value / new_value arrive as JSON numbers — a whole
            // number bridges to NSNumber (not Double), so go via NSNumber
            // to accept both 42 and 42.5 (and null → nil).
            func numeric(_ key: String) -> Double? {
                (structured[key] as? NSNumber)?.doubleValue
            }
            throw APIError.implausibleReading(
                message: message,
                code: code,
                lastValue: numeric("last_value"),
                newValue: numeric("new_value")
            )
        }
        let detail = parsed?["detail"] as? String
        throw APIError.http(status: http.statusCode, detail: detail)
    }

    private static func decode<T: Decodable>(_ type: T.Type, from data: Data) throws -> T {
        do {
            return try JSONDecoder().decode(type, from: data)
        } catch {
            throw APIError.decoding(error)
        }
    }
}
