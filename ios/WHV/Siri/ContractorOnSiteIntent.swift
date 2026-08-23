//
//  ContractorOnSiteIntent.swift
//  WHV
//
//  "Hey Siri, WHV Handwerker vor Ort" — Leistungsnachweis by voice. First
//  call for a Firma at an object opens a ticket "Handwerker vor Ort: <Firma>"
//  with the arrival time; the next call for the same Firma at the same
//  object the same day appends the departure time + duration. Later, the
//  contractor's invoice can be checked against these timestamps.
//

import AppIntents
import CoreLocation
import Foundation

struct ContractorOnSiteIntent: AppIntent {
    static var title: LocalizedStringResource = "WHV Handwerker vor Ort"
    static var description = IntentDescription(
        "Hält fest, dass ein Handwerker am Objekt ist (Ankunft) bzw. fertig ist (Abfahrt) — als Ticket-Notiz."
    )
    static var openAppWhenRun = false

    @Parameter(title: "Firma", requestValueDialog: IntentDialog("Welche Firma ist vor Ort?"))
    var firma: String

    static var parameterSummary: some ParameterSummary {
        Summary("Handwerker vor Ort: \(\.$firma)")
    }

    @MainActor
    func perform() async throws -> some IntentResult & ProvidesDialog {
        let name = firma.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty else { throw $firma.needsValueError(IntentDialog("Welche Firma ist vor Ort?")) }
        let api = APIClient()
        let tracker = TripTracker.shared

        // Where are we? Running trip's destination, else nearest object ≤ 300 m.
        var property: PropertyResponse?
        if let props = try? await api.getMyProperties() {
            if let pid = tracker.presetPropertyId {
                property = props.first { $0.id == pid }
            } else if let here = tracker.currentCoordinate {
                var best: (PropertyResponse, Double)?
                for p in props {
                    guard let lat = p.lat, let lng = p.lng else { continue }
                    let d = haversineMeters(here, CLLocationCoordinate2D(latitude: lat, longitude: lng))
                    if d <= 300, d < (best?.1 ?? .infinity) { best = (p, d) }
                }
                property = best?.0
            }
        }
        guard let property else {
            return .result(dialog: "Ich weiß nicht, an welchem Objekt Sie sind — bitte die Fahrt zum Objekt laufen lassen oder das Ticket in der App anlegen.")
        }

        let now = Date()
        let time = now.formatted(date: .omitted, time: .shortened)
        let subject = "Handwerker vor Ort: \(name)"
        // Same Firma, same object, today, still open → this is the departure.
        let existing = ((try? await api.getAdminTickets(propertyId: property.id)) ?? [])
            .filter { $0.closed_at == nil && $0.subject.caseInsensitiveCompare(subject) == .orderedSame && Calendar.current.isDateInToday($0.created_at) }
            .sorted { $0.created_at > $1.created_at }
            .first
        do {
            if let existing {
                let minutes = max(1, Int(now.timeIntervalSince(existing.created_at) / 60))
                _ = try await api.postMyTicketMessage(
                    ticketId: existing.id,
                    body: "Abfahrt \(time) · vor Ort ca. \(minutes) Min (per Siri, Standort \(property.name))."
                )
                return .result(dialog: IntentDialog(stringLiteral: "\(name) fertig um \(time), \(minutes) Minuten vor Ort. Im Ticket festgehalten."))
            }
            _ = try await api.createMyTicket(
                subject: subject,
                body: "Ankunft \(time) am \(property.name) (per Siri). Leistungsnachweis: Abfahrt folgt mit „Hey Siri, WHV Handwerker vor Ort“.",
                category: TicketCategory(rawValue: "SONSTIGES_OTHER") ?? TicketCategory.allCases.first!,
                propertyId: property.id
            )
            return .result(dialog: IntentDialog(stringLiteral: "\(name) vor Ort seit \(time) bei \(property.name) — notiert. Sagen Sie es nochmal, wenn sie fertig sind."))
        } catch APIError.unauthorized {
            return .result(dialog: "Bitte melden Sie sich zuerst in der WHV-App an.")
        } catch {
            return .result(dialog: "Das konnte gerade nicht gespeichert werden.")
        }
    }
}
