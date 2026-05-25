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
    /// Demo data for the Phase 2 scaffold. Replaced at the
    /// `LiegenschaftStore` boundary once the `/me/properties` API
    /// is wired up — no other call sites should touch this.
    ///
    /// Includes the real Hohewartstraße property from staging so
    /// the scaffold is recognisable when the dev wires the same
    /// backend up later; the second entry is a stub WEG to make
    /// the picker actually feel like a picker.
    static let demo: [Liegenschaft] = [
        Liegenschaft(
            id: "019e5f2a-ad1c-7c90-b7d1-3fe2f670136f",
            name: "MV Hohewartstraße 13",
            address: "70469 Stuttgart",
            type: "Mietverwaltung"
        ),
        Liegenschaft(
            id: "demo-weg-koenigstrasse",
            name: "WEG Königstraße 42",
            address: "70173 Stuttgart",
            type: "WEG-Verwaltung"
        ),
    ]
}
