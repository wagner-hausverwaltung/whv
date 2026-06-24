// Zähler (meter) + Zählerstand (reading) wire shapes — mirror the
// backend MeterResponse / MeterReadingResponse / MeterReadingOCRResult.
//
// Dates that arrive as plain "YYYY-MM-DD" (read_on) are kept as String
// because APIClient.jsonDecoder expects full ISO-8601 datetimes and would
// otherwise fail to decode a date-only value. Decimal values arrive as
// JSON numbers (Pydantic v2) → Double is enough precision for display.

import Foundation

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
    let reading_count: Int

    var type: MeterType { MeterType(rawValue: meter_type) ?? .sonstiges }

    enum CodingKeys: String, CodingKey {
        case id, property_id, unit_id, meter_number, meter_type
        case description, location, unit_label, is_active, unit_name
        case latest_reading_value, latest_reading_on, reading_count
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
}

struct MeterOCRResult: Codable {
    let suggested_value: Double?
    let meter_number: String?
    let confidence: Double?
    let ocr_raw: String?
    let provider_available: Bool
}
