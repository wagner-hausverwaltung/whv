// Liegenschaft (property) — the unit the user picks at app start.
//
// Stub model for the iOS scaffold. The fields mirror the eventual
// `PropertyResponse` from the backend (`backend/app/schemas/property.py`)
// so Phase 2 can swap the `Liegenschaft.demo` source for a fetched
// list without changing this file.

import Foundation

struct Liegenschaft: Identifiable, Hashable, Codable {
    /// Backend uses UUIDv7 strings for property IDs; we keep it as
    /// String so the scaffold's stub IDs are valid too. Switch to
    /// UUID once the API is wired up.
    let id: String
    let name: String
    let address: String
    /// "Mietverwaltung" | "WEG-Verwaltung" | "Sondereigentum" etc.
    /// Surfaced as a subtitle on the picker rows + on Einstellungen.
    let type: String?
}

extension Liegenschaft {
    /// Demo data for SwiftUI #Preview blocks only. The live flow
    /// hydrates `LiegenschaftStore.available` from /me/properties at
    /// sign-in — production users never see this set.
    static let demo: [Liegenschaft] = [
        Liegenschaft(
            id: "019e5f2a-ad1c-7c90-b7d1-3fe2f670136f",
            name: "MV Hohewartstraße 13",
            address: "70469 Stuttgart",
            type: "RENTAL"
        ),
        Liegenschaft(
            id: "demo-weg-koenigstrasse",
            name: "WEG Königstraße 42",
            address: "70173 Stuttgart",
            type: "OWNER"
        ),
    ]

    /// Map a backend PropertyResponse to the iOS picker row shape.
    /// We collapse the address into a single line because that's how
    /// the picker actually presents it.
    init(from p: PropertyResponse) {
        self.id = p.id
        self.name = p.name
        self.type = p.type
        let streetLine = [p.street, p.number].compactMap { $0 }.joined(separator: " ")
        let cityLine = [p.postal_code, p.city].compactMap { $0 }.joined(separator: " ")
        let combined = [streetLine, cityLine]
            .filter { !$0.isEmpty }
            .joined(separator: ", ")
        self.address = combined.isEmpty ? "—" : combined
    }
}

extension Liegenschaft {
    /// German-correspondence label for the property's administration
    /// type. Backend stores Impower's raw enum (OWNER / RENTAL /
    /// STRATA); the user-facing copy WHV uses is WEG / MV / SEV.
    /// Falls back to `type` for unknown values, or "—" if missing.
    var typeLabel: String {
        switch type {
        case "OWNER": return "WEG"
        case "RENTAL": return "MV"
        case "STRATA": return "SEV"
        default: return type ?? "—"
        }
    }

    /// Long form for captions ("WEG-Verwaltung" etc.); raw type for
    /// anything the mapping does not know.
    var typeLongLabel: String {
        switch type {
        case "OWNER": return "WEG-Verwaltung"
        case "RENTAL": return "Mietverwaltung"
        case "STRATA": return "Sondereigentumsverwaltung"
        default: return type ?? "—"
        }
    }

    /// "Does this property carry MEA / Miteigentumsanteile?" WEG and
    /// SEV do (ownership-share concept); MV (rental) does not, so
    /// PropertyDetailView hides the MEA metric entirely on MV.
    var hasOwnershipShares: Bool {
        type == "OWNER" || type == "STRATA"
    }
}
