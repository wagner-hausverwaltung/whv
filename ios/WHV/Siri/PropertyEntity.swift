//
//  PropertyEntity.swift
//  WHV
//
//  The caller's objects (WEG/MV/SEV) as an AppEntity, so Siri can ask
//  "Für welches Objekt?" and resolve the spoken street name / short code
//  (H32) itself. Backed by /me/properties — the same list the app shows.
//

import AppIntents
import Foundation

struct PropertyEntity: AppEntity {
    static var typeDisplayRepresentation = TypeDisplayRepresentation(name: "Objekt")
    static var defaultQuery = PropertyEntityQuery()

    let id: String
    let name: String
    let detail: String

    var displayRepresentation: DisplayRepresentation {
        DisplayRepresentation(title: "\(name)", subtitle: "\(detail)")
    }

    init(_ p: PropertyResponse) {
        id = p.id
        name = p.name
        detail = [p.postal_code, p.city].compactMap { $0 }.joined(separator: " ")
    }
}

struct PropertyEntityQuery: EntityStringQuery {
    func entities(for identifiers: [String]) async throws -> [PropertyEntity] {
        let all = (try? await APIClient().getMyProperties()) ?? []
        return all.filter { identifiers.contains($0.id) }.map(PropertyEntity.init)
    }

    /// Spoken "Hasenbergstraße", "Hasenberg", "H32", "Königstraße 42" …
    func entities(matching string: String) async throws -> [PropertyEntity] {
        let all = (try? await APIClient().getMyProperties()) ?? []
        let q = PropertyMatch.fold(string)
        guard q.count >= 2 else { return [] }
        let hits = all.filter { p in
            PropertyMatch.keys(for: p).contains { $0.contains(q) || q.contains($0) }
        }
        return hits.map(PropertyEntity.init)
    }

    func suggestedEntities() async throws -> [PropertyEntity] {
        ((try? await APIClient().getMyProperties()) ?? []).prefix(30).map(PropertyEntity.init)
    }
}

/// Shared fuzzy-ish matching of dictated text against an object: street
/// name and Impower short code, with "straße/strasse/str." folded and spaces
/// removed so dictation variants still match.
enum PropertyMatch {
    static func fold(_ s: String) -> String {
        s.lowercased()
            .replacingOccurrences(of: "straße", with: "str")
            .replacingOccurrences(of: "strasse", with: "str")
            .replacingOccurrences(of: "str.", with: "str")
            .replacingOccurrences(of: "-", with: "")
            .replacingOccurrences(of: " ", with: "")
    }

    /// Keys worth matching for an object: folded street (≥ 4 chars), folded
    /// name, short code ("Stuttgart_H32" → "h32").
    static func keys(for p: PropertyResponse) -> [String] {
        var keys: [String] = []
        if let street = p.street, street.count >= 4 { keys.append(fold(street)) }
        keys.append(fold(p.name))
        if let hr = p.property_hr_id, let code = hr.split(separator: "_").last, code.count >= 2 {
            keys.append(fold(String(code)))
        }
        return keys
    }

    /// Longest key contained in the (folded) text wins.
    static func property(named text: String, in props: [PropertyResponse]) -> PropertyResponse? {
        let q = fold(text)
        var best: (PropertyResponse, Int)?
        for p in props {
            for k in keys(for: p) where k.count >= 3 && q.contains(k) {
                if k.count > (best?.1 ?? 0) { best = (p, k.count) }
            }
        }
        return best?.0
    }
}
