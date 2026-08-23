//
//  TripWHVIntents.swift
//  WHV
//
//  "Hey Siri, WHV Abfahrt" / "Hey Siri, WHV Ankunft" — the Fahrtenbuch by
//  voice, no screen needed. Abfahrt starts a trip; Ankunft ends it at the
//  nearest object (≤ 300 m) with the purpose from today's appointment (or
//  the preset), so the trip uploads confirmed.
//

import AppIntents
import Foundation

struct DepartWHVIntent: AppIntent {
    static var title: LocalizedStringResource = "WHV Abfahrt"
    static var description = IntentDescription("Startet eine Fahrt im WHV-Fahrtenbuch.")
    static var openAppWhenRun = false

    @MainActor
    func perform() async throws -> some IntentResult & ProvidesDialog {
        let tracker = TripTracker.shared
        guard tracker.isAvailable else {
            return .result(dialog: "Im Demo-Modus ist das Fahrtenbuch nicht verfügbar.")
        }
        if tracker.isRunning {
            let since = tracker.startedAt.map { " seit \($0.formatted(date: .omitted, time: .shortened))" } ?? ""
            return .result(dialog: IntentDialog(stringLiteral: "Die Fahrt läuft bereits\(since)."))
        }
        tracker.startFromSiri()
        return .result(dialog: "Fahrt gestartet. Gute Fahrt!")
    }
}

struct ArriveWHVIntent: AppIntent {
    static var title: LocalizedStringResource = "WHV Ankunft"
    static var description = IntentDescription("Beendet die laufende Fahrt am aktuellen Objekt.")
    static var openAppWhenRun = false

    @MainActor
    func perform() async throws -> some IntentResult & ProvidesDialog {
        let tracker = TripTracker.shared
        guard tracker.isRunning else {
            return .result(dialog: "Es läuft gerade keine Fahrt.")
        }
        let km = String(format: "%.1f", Double(tracker.liveDistanceM) / 1000).replacingOccurrences(of: ".", with: ",")
        if let arrival = tracker.arriveFromSiri() {
            let purpose = arrival.purpose.map { ", \(TripPurpose.label(for: $0))" } ?? ""
            return .result(dialog: IntentDialog(stringLiteral: "Angekommen bei \(arrival.property.name)\(purpose). \(km) Kilometer gespeichert."))
        }
        return .result(dialog: IntentDialog(stringLiteral: "Fahrt beendet, \(km) Kilometer. Kein Objekt in der Nähe — Zweck und Objekt bitte in der App bestätigen."))
    }
}
