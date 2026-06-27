// Eigentümerversammlung models — mirror the backend's Pydantic
// AssemblyResponse + AssemblyDetailResponse + AssemblyCommentResponse
// shapes (backend/app/schemas/etv.py).
//
// Two structs, not one: the list endpoint returns the summary
// (AssemblyResponse), the detail endpoint returns the full tree
// (AssemblyDetailResponse). Comments are a separate endpoint
// (AssemblyCommentResponse) and are fetched alongside detail by
// view-level state.

import Foundation

enum AssemblyStatus: String, Codable, CaseIterable {
    case geplant = "GEPLANT"
    case eingeladen = "EINGELADEN"
    case abgehalten = "ABGEHALTEN"
    case abgesagt = "ABGESAGT"

    /// Returning LocalizedStringResource (vs. String) lets the
    /// Xcode build extractor pick these labels up automatically
    /// AND lets `Text(_ resource:)` swap language on the fly when
    /// the user toggles English in Settings. Plain Strings here
    /// would be invisible to both pipelines.
    var label: LocalizedStringResource {
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

    var label: LocalizedStringResource {
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

    var label: LocalizedStringResource {
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

    var label: LocalizedStringResource {
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

    var label: LocalizedStringResource {
        switch self {
        case .verwalter: return "Verwalter"
        case .eigentuemer: return "Eigentümer"
        case .mieter: return "Mieter"
        case .beirat: return "Beirat"
        case .dienstleister: return "Dienstleister"
        case .unknown: return ""
        }
    }

    /// True for the "no role known" sentinel — used to hide the
    /// role chip when present_at == .unknown. Lets call sites
    /// keep their existing `.isEmpty` check semantically without
    /// poking into LocalizedStringResource internals.
    var hasLabel: Bool { self != .unknown }
}

struct DiscussionEntry: Codable, Identifiable, Hashable {
    let id: String
    let position: Int
    let speaker_label: String
    let content: String
}

/// Supporting file attached to a single Tagesordnungspunkt — PDF,
/// photo, spreadsheet. Rendered inline under the item in
/// AssemblyDetailView so attendees see the context without
/// hunting through the protocol at the end.
struct AgendaItemAttachment: Codable, Identifiable, Hashable {
    let id: String
    let filename: String
    let mime_type: String?
    let size_bytes: Int
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
    /// Files attached to this specific TOP. Defaulted to [] via the
    /// custom decoder so older payloads without the field still
    /// parse cleanly.
    let attachments: [AgendaItemAttachment]

    var voteTotal: Int { vote_yes + vote_no + vote_abstain }

    /// Memberwise init kept explicit because the custom Decodable
    /// init disables Swift's auto-synthesised one. Demo seed data
    /// constructs values directly via this initializer.
    init(
        id: String,
        position: Int,
        type: AgendaItemType,
        title: String,
        body: String,
        beschluss_text: String?,
        vote_yes: Int,
        vote_no: Int,
        vote_abstain: Int,
        vote_required_quorum: Int?,
        vote_result: AgendaItemVoteResult?,
        voting_basis: AgendaItemVotingBasis?,
        present_count: Int?,
        discussion: [DiscussionEntry],
        attachments: [AgendaItemAttachment] = []
    ) {
        self.id = id
        self.position = position
        self.type = type
        self.title = title
        self.body = body
        self.beschluss_text = beschluss_text
        self.vote_yes = vote_yes
        self.vote_no = vote_no
        self.vote_abstain = vote_abstain
        self.vote_required_quorum = vote_required_quorum
        self.vote_result = vote_result
        self.voting_basis = voting_basis
        self.present_count = present_count
        self.discussion = discussion
        self.attachments = attachments
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        position = try c.decode(Int.self, forKey: .position)
        type = try c.decode(AgendaItemType.self, forKey: .type)
        title = try c.decode(String.self, forKey: .title)
        body = try c.decode(String.self, forKey: .body)
        beschluss_text = try c.decodeIfPresent(String.self, forKey: .beschluss_text)
        vote_yes = try c.decode(Int.self, forKey: .vote_yes)
        vote_no = try c.decode(Int.self, forKey: .vote_no)
        vote_abstain = try c.decode(Int.self, forKey: .vote_abstain)
        vote_required_quorum = try c.decodeIfPresent(Int.self, forKey: .vote_required_quorum)
        vote_result = try c.decodeIfPresent(AgendaItemVoteResult.self, forKey: .vote_result)
        voting_basis = try c.decodeIfPresent(AgendaItemVotingBasis.self, forKey: .voting_basis)
        present_count = try c.decodeIfPresent(Int.self, forKey: .present_count)
        discussion = (try? c.decode([DiscussionEntry].self, forKey: .discussion)) ?? []
        attachments = (try? c.decode([AgendaItemAttachment].self, forKey: .attachments)) ?? []
    }

    enum CodingKeys: String, CodingKey {
        case id, position, type, title, body, beschluss_text
        case vote_yes, vote_no, vote_abstain, vote_required_quorum
        case vote_result, voting_basis, present_count
        case discussion, attachments
    }
}

/// One Q&A entry under an assembly. Lives on its own endpoint:
/// GET/POST /me/assemblies/{id}/comments.
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

/// Header-only summary returned by GET /me/properties/{id}/assemblies.
/// Used to render the list. Distinct from `Assembly` so the list
/// row code can't accidentally rely on agenda data it doesn't have.
struct AssemblySummary: Codable, Identifiable, Hashable {
    let id: String
    let property_id: String
    let property_name: String?
    let property_hr_id: String?
    let title: String
    let status: AssemblyStatus
    let scheduled_start: Date
    let scheduled_end: Date
    let actual_start: Date?
    let actual_end: Date?
    let location: String
    let teams_meeting_url: String?
    let protocol_pdf_url: String?
    let protocol_uploaded_at: Date?
    /// When the Einladung-PDF was uploaded — the most accurate "this
    /// assembly just arrived for the owner" signal. Optional: not every
    /// assembly has an invitation yet.
    let invitation_uploaded_at: Date?
    /// When the assembly record was created. Fallback for the NEU badge
    /// when no invitation has been uploaded.
    let created_at: Date?

    /// Best available "added recently" date driving the NEU badge:
    /// the Einladung upload if present, else the record creation date.
    var addedRecentlyDate: Date? {
        invitation_uploaded_at ?? created_at
    }

    /// Explicit memberwise init with defaults for the recency dates so
    /// the demo builders (which don't have them) keep compiling. A plain
    /// memberwise init does NOT suppress Codable synthesis, so the
    /// network decode path is unaffected.
    init(
        id: String,
        property_id: String,
        property_name: String?,
        property_hr_id: String?,
        title: String,
        status: AssemblyStatus,
        scheduled_start: Date,
        scheduled_end: Date,
        actual_start: Date?,
        actual_end: Date?,
        location: String,
        teams_meeting_url: String?,
        protocol_pdf_url: String?,
        protocol_uploaded_at: Date?,
        invitation_uploaded_at: Date? = nil,
        created_at: Date? = nil
    ) {
        self.id = id
        self.property_id = property_id
        self.property_name = property_name
        self.property_hr_id = property_hr_id
        self.title = title
        self.status = status
        self.scheduled_start = scheduled_start
        self.scheduled_end = scheduled_end
        self.actual_start = actual_start
        self.actual_end = actual_end
        self.location = location
        self.teams_meeting_url = teams_meeting_url
        self.protocol_pdf_url = protocol_pdf_url
        self.protocol_uploaded_at = protocol_uploaded_at
        self.invitation_uploaded_at = invitation_uploaded_at
        self.created_at = created_at
    }
}

/// Full detail returned by GET /me/assemblies/{id}. Comments are
/// fetched separately by the view that renders this.
struct Assembly: Codable, Identifiable, Hashable {
    let id: String
    let property_id: String
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
    let teams_meeting_url: String?
    let agenda_pdf_url: String?
    let protocol_pdf_url: String?
    let protocol_uploaded_at: Date?
    let agenda_items: [AgendaItem]
}
