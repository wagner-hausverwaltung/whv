// Ticket models — mirror backend's TicketResponse /
// TicketDetailResponse / TicketMessageResponse plus the
// TicketCategory + TicketStatus + TicketShareScope enums.
//
// Categories are the casavi taxonomy (32 values across 7 groups);
// labels + the German grouping live here so the new-ticket sheet
// can render a grouped picker without a metadata round-trip.

import Foundation

enum TicketStatus: String, Codable, CaseIterable {
    case neu = "NEU"
    case offen = "OFFEN"
    case wartetAufKunde = "WARTET_AUF_KUNDE"
    case geschlossen = "GESCHLOSSEN"

    /// LocalizedStringResource so the build extractor sees the
    /// values and `Text(_ resource:)` re-renders when the user
    /// toggles English in Settings. Same pattern as
    /// AssemblyStatus.label.
    var label: LocalizedStringResource {
        switch self {
        case .neu: return "Neu"
        case .offen: return "Offen"
        case .wartetAufKunde: return "Wartet auf Kunde"
        case .geschlossen: return "Geschlossen"
        }
    }

    /// True when the ticket is still in motion. Drives grouping in
    /// the list (Aktuell vs. Geschlossen).
    var isActive: Bool {
        self != .geschlossen
    }
}

enum TicketShareScope: String, Codable {
    case privateScope = "PRIVATE"
    case participants = "PARTICIPANTS"
    case property = "PROPERTY"
}

/// 32 categories — German labels matching the backend's
/// `ticket_categories.py`. Grouped via `group` so the new-ticket
/// picker mirrors the admin SPA's grouped select.
enum TicketCategory: String, Codable, CaseIterable {
    case allgemeinFrage = "ALLGEMEIN_FRAGE"
    case allgemeinKlingel = "ALLGEMEIN_KLINGEL"
    case allgemeinDokumente = "ALLGEMEIN_DOKUMENTE"
    case allgemeinOnboarding = "ALLGEMEIN_ONBOARDING"
    case allgemeinLob = "ALLGEMEIN_LOB"
    case allgemeinRueckruf = "ALLGEMEIN_RUECKRUF"
    case allgemeinSchluessel = "ALLGEMEIN_SCHLUESSEL"
    case allgemeinTelefonnotiz = "ALLGEMEIN_TELEFONNOTIZ"
    case buchhaltungBankSepa = "BUCHHALTUNG_BANK_SEPA"
    case buchhaltungBetriebskosten = "BUCHHALTUNG_BETRIEBSKOSTEN"
    case buchhaltungJahresabrechnung = "BUCHHALTUNG_JAHRESABRECHNUNG"
    case buchhaltungBelege = "BUCHHALTUNG_BELEGE"
    case buchhaltungAbbuchungen = "BUCHHALTUNG_ABBUCHUNGEN"
    case vertriebBewertung = "VERTRIEB_BEWERTUNG"
    case vertriebBeratung = "VERTRIEB_BERATUNG"
    case vertriebInteresse = "VERTRIEB_INTERESSE"
    case mieterWechsel = "MIETER_WECHSEL"
    case schadenAllgemein = "SCHADEN_ALLGEMEIN"
    case schadenBaumangel = "SCHADEN_BAUMANGEL"
    case schadenElementar = "SCHADEN_ELEMENTAR"
    case schadenFeuer = "SCHADEN_FEUER"
    case schadenSchaedlinge = "SCHADEN_SCHAEDLINGE"
    case schadenStrom = "SCHADEN_STROM"
    case schadenAbwasser = "SCHADEN_ABWASSER"
    case schadenWasser = "SCHADEN_WASSER"
    case wegAnfrage = "WEG_ANFRAGE"
    case wegBeschlussantrag = "WEG_BESCHLUSSANTRAG"
    case wegLegionellen = "WEG_LEGIONELLEN"
    case sonstigesDaten = "SONSTIGES_DATEN"
    case sonstigesBeschlussumsetzung = "SONSTIGES_BESCHLUSSUMSETZUNG"
    case sonstigesEtv = "SONSTIGES_ETV"
    case sonstigesRelay = "SONSTIGES_RELAY"
    case sonstigesStoerung = "SONSTIGES_STOERUNG"
    case sonstigesOther = "SONSTIGES_OTHER"

    /// Unknown values from the server decode as `.sonstigesOther`
    /// instead of failing the whole detail fetch — forward-compat
    /// with future categories.
    init(from decoder: Decoder) throws {
        let raw = try decoder.singleValueContainer().decode(String.self)
        self = TicketCategory(rawValue: raw) ?? .sonstigesOther
    }

    /// Group key — used as a String identity for grouped()
    /// (matches the backend GROUPS_ORDER) AND for the
    /// localized header. `groupLabel` returns the user-facing
    /// LocalizedStringResource the picker section header reads.
    var group: String {
        switch self {
        case .allgemeinFrage, .allgemeinKlingel, .allgemeinDokumente,
             .allgemeinOnboarding, .allgemeinLob, .allgemeinRueckruf,
             .allgemeinSchluessel, .allgemeinTelefonnotiz:
            return "Allgemeines"
        case .buchhaltungBankSepa, .buchhaltungBetriebskosten,
             .buchhaltungJahresabrechnung, .buchhaltungBelege,
             .buchhaltungAbbuchungen:
            return "Buchhaltung"
        case .vertriebBewertung, .vertriebBeratung, .vertriebInteresse:
            return "Immobilienvertrieb"
        case .mieterWechsel:
            return "Mietverwaltung"
        case .schadenAllgemein, .schadenBaumangel, .schadenElementar,
             .schadenFeuer, .schadenSchaedlinge, .schadenStrom,
             .schadenAbwasser, .schadenWasser:
            return "Schadensmeldung"
        case .wegAnfrage, .wegBeschlussantrag, .wegLegionellen:
            return "WEG-Verwaltung"
        case .sonstigesDaten, .sonstigesBeschlussumsetzung, .sonstigesEtv,
             .sonstigesRelay, .sonstigesStoerung, .sonstigesOther:
            return "Sonstiges"
        }
    }

    var groupLabel: LocalizedStringResource {
        switch group {
        case "Allgemeines": return "Allgemeines"
        case "Buchhaltung": return "Buchhaltung"
        case "Immobilienvertrieb": return "Immobilienvertrieb"
        case "Mietverwaltung": return "Mietverwaltung"
        case "Schadensmeldung": return "Schadensmeldung"
        case "WEG-Verwaltung": return "WEG-Verwaltung"
        default: return "Sonstiges"
        }
    }

    var label: LocalizedStringResource {
        switch self {
        case .allgemeinFrage: return "Allgemeine Frage"
        case .allgemeinKlingel: return "Klingelschild"
        case .allgemeinDokumente: return "Dokumentenanfrage"
        case .allgemeinOnboarding: return "Onboarding"
        case .allgemeinLob: return "Lob"
        case .allgemeinRueckruf: return "Rückrufbitte"
        case .allgemeinSchluessel: return "Schlüssel"
        case .allgemeinTelefonnotiz: return "Telefonnotiz"
        case .buchhaltungBankSepa: return "Bankverbindung / SEPA"
        case .buchhaltungBetriebskosten: return "Betriebskosten"
        case .buchhaltungJahresabrechnung: return "Jahresabrechnung"
        case .buchhaltungBelege: return "Belege"
        case .buchhaltungAbbuchungen: return "Abbuchungen"
        case .vertriebBewertung: return "Immobilienbewertung"
        case .vertriebBeratung: return "Verkaufsberatung"
        case .vertriebInteresse: return "Kaufinteresse"
        case .mieterWechsel: return "Mieterwechsel"
        case .schadenAllgemein: return "Allgemeiner Schaden"
        case .schadenBaumangel: return "Baumangel"
        case .schadenElementar: return "Elementarschaden"
        case .schadenFeuer: return "Feuerschaden"
        case .schadenSchaedlinge: return "Schädlinge"
        case .schadenStrom: return "Stromausfall"
        case .schadenAbwasser: return "Abwasser"
        case .schadenWasser: return "Wasserschaden"
        case .wegAnfrage: return "WEG-Anfrage"
        case .wegBeschlussantrag: return "Beschlussantrag"
        case .wegLegionellen: return "Legionellenprüfung"
        case .sonstigesDaten: return "Datenänderung"
        case .sonstigesBeschlussumsetzung: return "Beschlussumsetzung"
        case .sonstigesEtv: return "ETV"
        case .sonstigesRelay: return "Weiterleitung"
        case .sonstigesStoerung: return "Störung"
        case .sonstigesOther: return "Sonstiges"
        }
    }

    /// Plain-String form for places that can't accept a
    /// LocalizedStringResource (widget payload writers etc.).
    /// Looks up the current locale's translation at call time.
    var labelString: String {
        String(localized: label)
    }

    /// Group order matches the backend's GROUPS_ORDER so the iOS
    /// picker and the admin SPA always agree.
    static let groupsOrder: [String] = [
        "Allgemeines",
        "Buchhaltung",
        "Immobilienvertrieb",
        "Mietverwaltung",
        "Schadensmeldung",
        "WEG-Verwaltung",
        "Sonstiges",
    ]

    static func grouped() -> [(group: String, items: [TicketCategory])] {
        groupsOrder.map { group in
            (group, allCases.filter { $0.group == group })
        }
    }
}

struct TicketMessageAttachment: Codable, Identifiable, Hashable {
    let id: String
    let filename: String
    let mime_type: String?
    let size_bytes: Int
    let created_at: Date
}

struct TicketMessage: Codable, Identifiable, Hashable {
    let id: String
    let ticket_id: String
    let author_user_id: String?
    let author_email: String?
    let body: String
    // Server-side split of an e-mail reply: fresh text vs. the quoted thread
    // below it. Optional so older cached payloads still decode; fall back to
    // `body` when absent.
    let visible_body: String?
    let quoted_body: String?
    let is_internal_note: Bool
    let created_at: Date
    let attachments: [TicketMessageAttachment]

    /// Text to render by default — the reply without its quoted history.
    var displayBody: String { visible_body ?? body }
}

struct TicketParticipant: Codable, Identifiable, Hashable {
    let user_id: String
    let email: String?
    let added_by_user_id: String?
    let added_at: Date

    var id: String { user_id }
}

/// Full detail with the message thread + participants embedded.
struct TicketDetail: Codable, Identifiable, Hashable {
    let id: String
    let property_id: String?
    let created_by_user_id: String?
    let assignee_user_id: String?
    let category: TicketCategory
    let status: TicketStatus
    let share_scope: TicketShareScope
    let subject: String
    let last_message_at: Date
    let created_at: Date
    let closed_at: Date?
    let property_name: String?
    let property_address: String?
    let creator_email: String?
    let creator_contact_label: String?
    let creator_contact_id_impower: Int?
    let external_sender_email: String?
    let messages: [TicketMessage]
    let participants: [TicketParticipant]
}
