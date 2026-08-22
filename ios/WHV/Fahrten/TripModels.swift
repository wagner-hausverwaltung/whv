//
//  TripModels.swift
//  WHV
//
//  Wire models for the Fahrtenbuch (ADR-0020). Mirrors app/schemas/trip.py.
//

import CoreLocation
import Foundation

struct TripResponse: Codable, Identifiable, Hashable {
    let id: String
    let user_id: String
    let user_email: String?
    let property_id: String?
    let property_name: String?
    let status: String  // RUNNING | OPEN | CONFIRMED
    let source: String  // AUTO | MANUAL | CARPLAY
    let purpose: String?
    let started_at: Date
    let ended_at: Date?
    let start_lat: Double?
    let start_lng: Double?
    let end_lat: Double?
    let end_lng: Double?
    let distance_m: Int?
    /// Pydantic serialises Decimal as a string ("12.3").
    let distance_km: String
    let route_polyline: String?
    let rate_cents_per_km: Int
    let amount_cents: Int
    let note: String?

    var distanceKm: Double { Double(distance_km.replacingOccurrences(of: ",", with: ".")) ?? 0 }
    var amountEUR: Double { Double(amount_cents) / 100 }
    var isOpen: Bool { status == "OPEN" }
    var endCoordinate: CLLocationCoordinate2D? {
        guard let lat = end_lat, let lng = end_lng else { return nil }
        return CLLocationCoordinate2D(latitude: lat, longitude: lng)
    }
}

struct TripStartBody: Encodable {
    let started_at: Date
    let start_lat: Double?
    let start_lng: Double?
    let source: String
}

struct TripCompleteBody: Codable {
    let started_at: Date
    let ended_at: Date
    let start_lat: Double?
    let start_lng: Double?
    let end_lat: Double?
    let end_lng: Double?
    let distance_m: Int
    let route_polyline: String?
    let source: String
    let purpose: String?
    let property_id: String?
}

/// Partial update — only non-nil fields are sent (see APIClient encoder:
/// `nil` optionals are omitted, so the backend's `model_fields_set` logic
/// only touches what the user actually changed). `clear_property` is a
/// client-side flag turned into an explicit `property_id: null`.
struct TripUpdateBody: Encodable {
    var ended_at: Date? = nil
    var end_lat: Double? = nil
    var end_lng: Double? = nil
    var distance_m: Int? = nil
    var route_polyline: String? = nil
    var purpose: String? = nil
    var property_id: String? = nil
    var note: String? = nil
    var clearProperty: Bool = false

    enum CodingKeys: String, CodingKey {
        case ended_at, end_lat, end_lng, distance_m, route_polyline, purpose, property_id, note
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encodeIfPresent(ended_at, forKey: .ended_at)
        try c.encodeIfPresent(end_lat, forKey: .end_lat)
        try c.encodeIfPresent(end_lng, forKey: .end_lng)
        try c.encodeIfPresent(distance_m, forKey: .distance_m)
        try c.encodeIfPresent(route_polyline, forKey: .route_polyline)
        try c.encodeIfPresent(purpose, forKey: .purpose)
        try c.encodeIfPresent(note, forKey: .note)
        if clearProperty {
            try c.encodeNil(forKey: .property_id)
        } else {
            try c.encodeIfPresent(property_id, forKey: .property_id)
        }
    }
}

/// Display metadata for trip purposes — one place for label + icon.
enum TripPurpose: String, CaseIterable, Identifiable {
    case besichtigung = "BESICHTIGUNG"
    case etv = "ETV"
    case handwerkertermin = "HANDWERKERTERMIN"
    case eigentuemertermin = "EIGENTUEMERTERMIN"
    case buero = "BUERO"
    case sonstiges = "SONSTIGES"
    case privat = "PRIVAT"

    var id: String { rawValue }

    var label: String {
        switch self {
        case .besichtigung: return "Besichtigung"
        case .etv: return "Eigentümerversammlung"
        case .handwerkertermin: return "Handwerkertermin"
        case .eigentuemertermin: return "Eigentümertermin"
        case .buero: return "Büro"
        case .sonstiges: return "Sonstiges"
        case .privat: return "Privat"
        }
    }

    var systemImage: String {
        switch self {
        case .besichtigung: return "binoculars.fill"
        case .etv: return "person.3.fill"
        case .handwerkertermin: return "wrench.and.screwdriver.fill"
        case .eigentuemertermin: return "person.fill"
        case .buero: return "building.2.fill"
        case .sonstiges: return "ellipsis.circle.fill"
        case .privat: return "house.fill"
        }
    }

    /// Purposes that need a property to make sense in the Auslagen statement.
    var wantsProperty: Bool {
        switch self {
        case .besichtigung, .etv, .handwerkertermin, .eigentuemertermin: return true
        case .buero, .sonstiges, .privat: return false
        }
    }

    static func label(for raw: String?) -> String {
        guard let raw, let p = TripPurpose(rawValue: raw) else { return "Zweck offen" }
        return p.label
    }
}

enum TripFormat {
    static func km(_ meters: Int?) -> String {
        let km = Double(meters ?? 0) / 1000
        return String(format: "%.1f km", km).replacingOccurrences(of: ".", with: ",")
    }

    static func eur(_ cents: Int) -> String {
        let f = NumberFormatter()
        f.numberStyle = .currency
        f.currencyCode = "EUR"
        f.locale = Locale(identifier: "de_DE")
        return f.string(from: NSNumber(value: Double(cents) / 100)) ?? "—"
    }
}
