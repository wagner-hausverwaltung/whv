// Zähler (meter) + Zählerstand (reading) wire shapes — mirror the
// backend MeterResponse / MeterReadingResponse / MeterReadingOCRResult.
//
// Dates that arrive as plain "YYYY-MM-DD" (read_on) are kept as String
// because APIClient.jsonDecoder expects full ISO-8601 datetimes and would
// otherwise fail to decode a date-only value.
//
// Numeric reading values are decoded LENIENTLY (number OR numeric string):
// the backend now serializes them as JSON numbers, but Pydantic's default
// for Decimal is a string — accepting both means a server-side change can
// never again break "Couldn't load Zähler".

import Foundation

/// Decode a Double from either a JSON number or a numeric string.
private func flexibleDouble<K: CodingKey>(_ c: KeyedDecodingContainer<K>, _ key: K) -> Double? {
    if let d = try? c.decode(Double.self, forKey: key) { return d }
    if let s = try? c.decode(String.self, forKey: key) { return Double(s) }
    return nil
}

/// Parse a backend date-only string ("YYYY-MM-DD") into a Date at the
/// start of that day. The API serializes meter `reading_due_date` and
/// `latest_reading_on` as date-only values, which APIClient.jsonDecoder
/// (full ISO-8601 only) can't decode — so they stay String on the wire
/// and we parse them here for the highlight math.
private let meterDayFormatter: DateFormatter = {
    let f = DateFormatter()
    f.locale = Locale(identifier: "en_US_POSIX")
    f.timeZone = .current
    f.dateFormat = "yyyy-MM-dd"
    return f
}()

private func parseMeterDay(_ iso: String?) -> Date? {
    guard let iso else { return nil }
    guard let parsed = meterDayFormatter.date(from: iso) else { return nil }
    return Calendar.current.startOfDay(for: parsed)
}

enum MeterType: String, CaseIterable {
    case strom = "STROM"
    case gas = "GAS"
    case wasser = "WASSER"
    case warmwasser = "WARMWASSER"
    case waerme = "WAERME"
    case sonstiges = "SONSTIGES"

    var label: String {
        switch self {
        case .strom: return "Strom"
        case .gas: return "Gas"
        case .wasser: return "Wasser (kalt)"
        case .warmwasser: return "Warmwasser"
        case .waerme: return "Wärme"
        case .sonstiges: return "Sonstiges"
        }
    }

    var systemImage: String {
        switch self {
        case .strom: return "bolt.fill"
        case .gas: return "flame.fill"
        case .wasser: return "drop.fill"
        case .warmwasser: return "drop.degreesign.fill"
        case .waerme: return "thermometer.medium"
        case .sonstiges: return "gauge.medium"
        }
    }
}

struct MeterSummary: Codable, Hashable, Identifiable {
    let id: String
    let property_id: String
    let unit_id: String?
    let meter_number: String
    let meter_type: String
    let description: String?
    let location: String?
    let unit_label: String?
    let is_active: Bool
    let unit_name: String?
    let latest_reading_value: Double?
    let latest_reading_on: String?
    // Current quarter's reading deadline ("YYYY-MM-DD"). Kept String
    // for the same reason as latest_reading_on — see parseMeterDay.
    let reading_due_date: String?
    let reading_count: Int

    var type: MeterType { MeterType(rawValue: meter_type) ?? .sonstiges }

    /// How close (in days) a `reading_due_date` may be before the meter
    /// is flagged "due soon" — and the look-back window that a recent
    /// reading must fall within to clear that flag.
    static let dueSoonWindowDays = 45

    /// The reading deadline parsed to a start-of-day Date, or nil.
    var readingDueDate: Date? { parseMeterDay(reading_due_date) }

    /// The latest actual reading date parsed to a start-of-day Date, or nil.
    var latestReadingDate: Date? { parseMeterDay(latest_reading_on) }

    /// True when this meter needs reading attention: there's a due date
    /// within the next `dueSoonWindowDays` (or already overdue) AND no
    /// actual reading was taken in the last `dueSoonWindowDays`. A recent
    /// reading clears the flag; an old/absent reading with an approaching
    /// deadline keeps it lit. Pure date math, no quarter logic.
    var isReadingDueSoon: Bool {
        guard let due = readingDueDate else { return false }
        let cal = Calendar.current
        let today = cal.startOfDay(for: Date())
        guard let dueThreshold = cal.date(byAdding: .day, value: Self.dueSoonWindowDays, to: today)
        else { return false }
        // Due within the window (or overdue)?
        guard due <= dueThreshold else { return false }
        // Cleared by a reading taken in the last window of days?
        guard let recentCutoff = cal.date(byAdding: .day, value: -Self.dueSoonWindowDays, to: today)
        else { return true }
        if let last = latestReadingDate, last >= recentCutoff { return false }
        return true
    }

    enum CodingKeys: String, CodingKey {
        case id, property_id, unit_id, meter_number, meter_type
        case description, location, unit_label, is_active, unit_name
        case latest_reading_value, latest_reading_on, reading_due_date, reading_count
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        property_id = try c.decode(String.self, forKey: .property_id)
        unit_id = try c.decodeIfPresent(String.self, forKey: .unit_id)
        meter_number = try c.decode(String.self, forKey: .meter_number)
        meter_type = try c.decode(String.self, forKey: .meter_type)
        description = try c.decodeIfPresent(String.self, forKey: .description)
        location = try c.decodeIfPresent(String.self, forKey: .location)
        unit_label = try c.decodeIfPresent(String.self, forKey: .unit_label)
        is_active = try c.decode(Bool.self, forKey: .is_active)
        unit_name = try c.decodeIfPresent(String.self, forKey: .unit_name)
        latest_reading_value = flexibleDouble(c, .latest_reading_value)
        latest_reading_on = try c.decodeIfPresent(String.self, forKey: .latest_reading_on)
        reading_due_date = try c.decodeIfPresent(String.self, forKey: .reading_due_date)
        reading_count = try c.decode(Int.self, forKey: .reading_count)
    }
}

struct MeterReadingItem: Codable, Hashable, Identifiable {
    let id: String
    let meter_id: String
    let value: Double
    let read_on: String
    let source: String  // "MANUAL" | "OCR"
    let note: String?
    let has_photo: Bool
    let reported_by_email: String?

    enum CodingKeys: String, CodingKey {
        case id, meter_id, value, read_on, source, note, has_photo, reported_by_email
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        meter_id = try c.decode(String.self, forKey: .meter_id)
        guard let v = flexibleDouble(c, .value) else {
            throw DecodingError.dataCorruptedError(
                forKey: .value, in: c, debugDescription: "value is not a number or numeric string")
        }
        value = v
        read_on = try c.decode(String.self, forKey: .read_on)
        source = try c.decode(String.self, forKey: .source)
        note = try c.decodeIfPresent(String.self, forKey: .note)
        has_photo = try c.decode(Bool.self, forKey: .has_photo)
        reported_by_email = try c.decodeIfPresent(String.self, forKey: .reported_by_email)
    }
}

struct MeterOCRResult: Codable {
    let suggested_value: Double?
    let meter_number: String?
    let confidence: Double?
    let ocr_raw: String?
    let provider_available: Bool

    enum CodingKeys: String, CodingKey {
        case suggested_value, meter_number, confidence, ocr_raw, provider_available
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        suggested_value = flexibleDouble(c, .suggested_value)
        meter_number = try c.decodeIfPresent(String.self, forKey: .meter_number)
        confidence = flexibleDouble(c, .confidence)
        ocr_raw = try c.decodeIfPresent(String.self, forKey: .ocr_raw)
        provider_available = try c.decode(Bool.self, forKey: .provider_available)
    }
}
