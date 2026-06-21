// Umlaufbeschluss (circular resolution) models — mirror the backend's
// ResolutionResponse + ResolutionDetailResponse + ResolutionTally + VoteResponse
// (backend/app/schemas/circular.py). Owner-facing and READ-ONLY: voting happens
// via the e-mail link, so the app only shows resolutions, their tally, the
// caller's own vote and the result. snake_case to match the JSON keys verbatim
// (the shared decoder doesn't convert).

import Foundation

enum ResolutionStatus: String, Codable, CaseIterable {
    case entwurf = "ENTWURF"
    case offen = "OFFEN"
    case geschlossen = "GESCHLOSSEN"
    case angenommen = "ANGENOMMEN"
    case abgelehnt = "ABGELEHNT"

    /// LocalizedStringResource so the build extractor picks the labels up and
    /// Text(_:) swaps language live (status words are generic, not §7 terms).
    var label: LocalizedStringResource {
        switch self {
        case .entwurf: return "Entwurf"
        case .offen: return "Offen"
        case .geschlossen: return "Geschlossen"
        case .angenommen: return "Angenommen"
        case .abgelehnt: return "Abgelehnt"
        }
    }

    var isOpen: Bool { self == .offen }
    var isDecided: Bool { self == .angenommen || self == .abgelehnt }
}

/// WEG counting rule. KLASSISCH = traditional all-must-agree (Allstimmigkeit);
/// MEHRHEITS = simple majority. German legal terms stay German (§7).
enum ResolutionMode: String, Codable {
    case klassisch = "KLASSISCH"
    case mehrheits = "MEHRHEITS"

    var label: LocalizedStringResource {
        switch self {
        case .klassisch: return "Allstimmigkeit"
        case .mehrheits: return "Mehrheitsbeschluss"
        }
    }
}

enum VoteChoice: String, Codable {
    case ja = "JA"
    case nein = "NEIN"
    case enthaltung = "ENTHALTUNG"

    var label: LocalizedStringResource {
        switch self {
        case .ja: return "Ja"
        case .nein: return "Nein"
        case .enthaltung: return "Enthaltung"
        }
    }
}

struct ResolutionSummary: Codable, Identifiable {
    let id: String
    let property_id: String
    let title: String
    let mode: ResolutionMode
    let status: ResolutionStatus
    let opens_at: Date
    let closes_at: Date
    let required_quorum: Int
    let decided_at: Date?
    let created_at: Date
}

struct ResolutionTally: Codable {
    let eligible_voters: Int
    let cast: Int
    let ja: Int
    let nein: Int
    let enthaltung: Int
    let quorum_met: Bool
    let unanimous_yes: Bool
}

/// The caller's own vote only (the owner endpoint filters the full log down to
/// `my_vote`). Extra JSON keys (id, resolution_id, …) are ignored by Codable.
struct ResolutionVote: Codable {
    let choice: VoteChoice
    let voted_at: Date
}

struct ResolutionDetail: Codable, Identifiable {
    let id: String
    let property_id: String
    let title: String
    let mode: ResolutionMode
    let status: ResolutionStatus
    let opens_at: Date
    let closes_at: Date
    let required_quorum: Int
    let decided_at: Date?
    let created_at: Date
    let description: String
    let pdf_url: String?
    let result_pdf_url: String?
    let result: String?
    let tally: ResolutionTally
    let my_vote: ResolutionVote?
    let am_eligible: Bool
}
