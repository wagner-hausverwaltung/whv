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
    let discussion: [DiscussionEntry]

    var voteTotal: Int { vote_yes + vote_no + vote_abstain }
}

struct Assembly: Codable, Identifiable, Hashable {
    let id: String
    let property_id: String
    let title: String
    let description: String
    let status: AssemblyStatus
    let scheduled_start: Date
    let scheduled_end: Date
    let actual_start: Date?
    let actual_end: Date?
    let location: String
    let agenda_pdf_url: String?
    let protocol_pdf_url: String?
    let protocol_uploaded_at: Date?
    let agenda_items: [AgendaItem]
}
