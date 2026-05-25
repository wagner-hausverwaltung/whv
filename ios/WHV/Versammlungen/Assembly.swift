// Eigentümerversammlung models — mirror the backend's Pydantic
// AssemblyResponse + AgendaItemResponse + DiscussionEntryResponse
// shapes (backend/app/schemas/etv.py).
//
// Decoding from the live API is wired up in EtvService; for now the
// VersammlungenTab consumes baked-in demo data so the iOS app
// renders something meaningful even before a real account is signed
// in. Phase 2.1 flips VersammlungenStore from demo to live without
// changing the views.

import Foundation

enum AssemblyStatus: String, Codable, CaseIterable {
    case geplant = "GEPLANT"
    case eingeladen = "EINGELADEN"
    case abgehalten = "ABGEHALTEN"
    case abgesagt = "ABGESAGT"

    var label: String {
        switch self {
        case .geplant: return "Geplant"
        case .eingeladen: return "Eingeladen"
        case .abgehalten: return "Abgehalten"
        case .abgesagt: return "Abgesagt"
        }
    }

    /// True if this status counts as "upcoming" in the owner queue.
    /// ABGESAGT is filtered out entirely on the owner endpoint, so we
    /// only need to distinguish upcoming (GEPLANT / EINGELADEN) from
    /// past (ABGEHALTEN) for grouping.
    var isUpcoming: Bool {
        self == .geplant || self == .eingeladen
    }
}

enum AgendaItemType: String, Codable {
    case information = "INFORMATION"
    case beschluss = "BESCHLUSS"
    case diskussion = "DISKUSSION"

    var label: String {
        switch self {
        case .information: return "Information"
        case .beschluss: return "Beschluss"
        case .diskussion: return "Diskussion"
        }
    }
}

enum AgendaItemVoteResult: String, Codable {
    case angenommen = "ANGENOMMEN"
    case abgelehnt = "ABGELEHNT"

    var label: String {
        switch self {
        case .angenommen: return "Angenommen"
        case .abgelehnt: return "Abgelehnt"
        }
    }
}

/// WEG-Recht: which counting rule governs the vote.
/// KOPF — one owner one vote (Kopfprinzip).
/// MEA  — Miteigentumsanteile, the share-based default in most WEGs.
/// OBJEKT — one vote per Einheit (Objektprinzip).
enum AgendaItemVotingBasis: String, Codable {
    case kopf = "KOPF"
    case mea = "MEA"
    case objekt = "OBJEKT"

    var label: String {
        switch self {
        case .kopf: return "Kopfprinzip"
        case .mea: return "MEA"
        case .objekt: return "Objektprinzip"
        }
    }
}

/// Role of the comment author. Backend denormalises the role onto
/// the comment so we can badge Verwalter / Beirat without a second
/// fetch. Unknown values decode as `.unknown` rather than failing
/// (forward-compatible with future roles).
enum AssemblyAuthorRole: String, Codable {
    case verwalter
    case eigentuemer
    case mieter
    case beirat
    case dienstleister
    case unknown

    init(from decoder: Decoder) throws {
        let raw = try decoder.singleValueContainer().decode(String.self)
        self = AssemblyAuthorRole(rawValue: raw.lowercased()) ?? .unknown
    }

    var label: String {
        switch self {
        case .verwalter: return "Verwalter"
        case .eigentuemer: return "Eigentümer"
        case .mieter: return "Mieter"
        case .beirat: return "Beirat"
        case .dienstleister: return "Dienstleister"
        case .unknown: return ""
        }
    }
}

struct DiscussionEntry: Codable, Identifiable, Hashable {
    let id: String
    let position: Int
    let speaker_label: String
    let content: String
}

struct AgendaItem: Codable, Identifiable, Hashable {
    let id: String
    let position: Int
    let type: AgendaItemType
    let title: String
    let body: String
    let beschluss_text: String?
    let vote_yes: Int
    let vote_no: Int
    let vote_abstain: Int
    let vote_required_quorum: Int?
    let vote_result: AgendaItemVoteResult?
    let voting_basis: AgendaItemVotingBasis?
    let present_count: Int?
    let discussion: [DiscussionEntry]

    var voteTotal: Int { vote_yes + vote_no + vote_abstain }
}

struct AssemblyComment: Codable, Identifiable, Hashable {
    let id: String
    let assembly_id: String
    let author_user_id: String
    let author_label: String
    let author_role: AssemblyAuthorRole
    let body: String
    let created_at: Date
    let edited_at: Date?
}

struct Assembly: Codable, Identifiable, Hashable {
    let id: String
    let property_id: String
    /// Denormalised property identity so every ETV surface can render
    /// the Liegenschaft without a per-row fetch. Backend leaves these
    /// null only in unscoped/test contexts.
    let property_name: String?
    let property_hr_id: String?
    let title: String
    let description: String
    let status: AssemblyStatus
    let scheduled_start: Date
    let scheduled_end: Date
    let actual_start: Date?
    let actual_end: Date?
    let location: String
    /// Optional Microsoft Teams meetup-join URL. When set, the detail
    /// view renders a prominent purple "Teams-Meeting beitreten"
    /// button at the top — mirrors the portal treatment.
    let teams_meeting_url: String?
    let agenda_pdf_url: String?
    let protocol_pdf_url: String?
    let protocol_uploaded_at: Date?
    let agenda_items: [AgendaItem]
    let comments: [AssemblyComment]
}
