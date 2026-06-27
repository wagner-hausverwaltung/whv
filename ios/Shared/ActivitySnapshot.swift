// Shared model for the unified "what's new" activity feed widget.
//
// The host app fetches GET /me/activity (authed, JWT) and writes an
// ActivitySnapshot into App Group UserDefaults under
// `WHV.widget.activity`; the WidgetKit extension reads it back. The
// widget process never touches the network or Keychain — App Group
// UserDefaults is the only bridge, exactly like the older
// WidgetSnapshot (ETV-only) path it supersedes.
//
// Lives in ios/Shared/ rather than under either target's folder so
// both WHV (app) and WHVWidgets (extension) compile against the same
// type without cross-target import gymnastics. Like ETVActivity.swift,
// this file is added to BOTH targets' Sources phases in the xcodeproj.

import Foundation

/// One row of the backend `GET /me/activity` feed. Mirrors the JSON
/// item shape field-for-field. `type` is kept as a raw String (the
/// backend may add new kinds) and mapped to an `ActivityKind` for
/// display via `kind`; unknown strings fall back to `.unknown`.
public struct ActivityItem: Codable, Hashable, Identifiable {
    public let type: String
    public let id: String
    public let title: String
    public let subtitle: String
    public let timestamp: Date
    /// Lower = more urgent. The backend already sorts most-urgent
    /// first, so the widget renders in array order and never re-sorts.
    public let priority: Int
    public let propertyName: String?
    /// The item's own property UUID (backend `property_id`). The feed
    /// is cross-property, so a tap must be able to switch the app to
    /// THIS item's Liegenschaft before opening its tab — the widget
    /// appends it as a `?property=` query on the fallback deep links.
    public let propertyId: String?
    public let deepLink: String

    public init(
        type: String,
        id: String,
        title: String,
        subtitle: String,
        timestamp: Date,
        priority: Int,
        propertyName: String?,
        propertyId: String? = nil,
        deepLink: String
    ) {
        self.type = type
        self.id = id
        self.title = title
        self.subtitle = subtitle
        self.timestamp = timestamp
        self.priority = priority
        self.propertyName = propertyName
        self.propertyId = propertyId
        self.deepLink = deepLink
    }

    // Wire keys: property_name + property_id + deep_link are snake_case
    // on the backend; the rest match. property_id is re-added so the
    // host app can switch to the item's own Liegenschaft on tap.
    enum CodingKeys: String, CodingKey {
        case type, id, title, subtitle, timestamp, priority
        case propertyName = "property_name"
        case propertyId = "property_id"
        case deepLink = "deep_link"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        type = try c.decode(String.self, forKey: .type)
        id = try c.decode(String.self, forKey: .id)
        title = try c.decode(String.self, forKey: .title)
        // subtitle is occasionally absent / null on the wire — default
        // to empty so a missing field never fails the whole decode.
        subtitle = (try? c.decode(String.self, forKey: .subtitle)) ?? ""
        timestamp = try c.decode(Date.self, forKey: .timestamp)
        priority = try c.decode(Int.self, forKey: .priority)
        propertyName = try c.decodeIfPresent(String.self, forKey: .propertyName)
        propertyId = try c.decodeIfPresent(String.self, forKey: .propertyId)
        deepLink = try c.decode(String.self, forKey: .deepLink)
    }

    /// Typed view of the raw `type` string for icon / styling lookup.
    public var kind: ActivityKind {
        ActivityKind(rawValue: type) ?? .unknown
    }
}

/// The activity types the backend emits. `unknown` keeps the widget
/// forward-compatible with server-side additions (renders a neutral
/// icon rather than failing).
public enum ActivityKind: String, Codable {
    case resolution = "RESOLUTION"
    case etv = "ETV"
    case etvComment = "ETV_COMMENT"
    case document = "DOCUMENT"
    case invoice = "INVOICE"
    case announcement = "ANNOUNCEMENT"
    case calendar = "CALENDAR"
    case meterDue = "METER_DUE"
    case unknown = "UNKNOWN"

    /// SF Symbol per kind — shared by every widget family so the small
    /// / medium / large surfaces stay visually consistent.
    public var sfSymbol: String {
        switch self {
        case .resolution: return "checkmark.seal"
        case .etv: return "person.3"
        case .etvComment: return "bubble.left"
        case .document: return "doc.text"
        case .invoice: return "eurosign.circle"
        case .announcement: return "megaphone"
        case .calendar: return "calendar"
        case .meterDue: return "gauge"
        case .unknown: return "bell"
        }
    }
}

/// The payload written to App Group UserDefaults. `updatedAt` lets the
/// widget show staleness if ever needed; `items` arrives pre-sorted.
public struct ActivitySnapshot: Codable {
    public let updatedAt: Date
    public let items: [ActivityItem]

    public init(updatedAt: Date, items: [ActivityItem]) {
        self.updatedAt = updatedAt
        self.items = items
    }
}

/// App Group bridge for the activity feed. Shared by the host app
/// (write) and the widget extension (read) so the suite name + key +
/// ISO-8601 (de)coding strategy can never drift between the two sides.
public enum ActivityStorage {
    public static let appGroup = "group.com.wagner-hausverwaltung.portal"
    public static let snapshotKey = "WHV.widget.activity"

    /// ISO-8601 with fractional-seconds fallback — matches the backend
    /// timestamp shapes (Pydantic v2 emits microseconds). Used on both
    /// sides so a snapshot written by the app always decodes in the
    /// widget process.
    private static let withFractional: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()
    private static let plain: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()

    public static func makeEncoder() -> JSONEncoder {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .custom { date, encoder in
            var c = encoder.singleValueContainer()
            try c.encode(withFractional.string(from: date))
        }
        return encoder
    }

    public static func makeDecoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .custom { decoder in
            let c = try decoder.singleValueContainer()
            let str = try c.decode(String.self)
            if let d = withFractional.date(from: str) { return d }
            if let d = plain.date(from: str) { return d }
            throw DecodingError.dataCorruptedError(
                in: c, debugDescription: "Invalid ISO8601 date: \(str)")
        }
        return decoder
    }

    /// Write the snapshot to the App Group. Best-effort: a missing
    /// suite or an encode failure leaves the previous snapshot in place.
    public static func write(_ snapshot: ActivitySnapshot) {
        guard let defaults = UserDefaults(suiteName: appGroup) else { return }
        if let data = try? makeEncoder().encode(snapshot) {
            defaults.set(data, forKey: snapshotKey)
        }
    }

    /// Read the snapshot back. Returns nil when nothing has been
    /// written yet (fresh install / signed out).
    public static func read() -> ActivitySnapshot? {
        guard let defaults = UserDefaults(suiteName: appGroup),
              let raw = defaults.data(forKey: snapshotKey)
        else { return nil }
        return try? makeDecoder().decode(ActivitySnapshot.self, from: raw)
    }

    /// Wipe the slot — called on sign-out so the next user never sees
    /// the previous account's feed on their Home Screen.
    public static func clear() {
        guard let defaults = UserDefaults(suiteName: appGroup) else { return }
        defaults.removeObject(forKey: snapshotKey)
    }
}
