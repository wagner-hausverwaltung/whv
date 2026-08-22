//
//  NoteWHVIntent.swift
//  WHV
//
//  "Hey Siri, WHV Notiz" — dictate what you see at the object and it becomes
//  a ticket on that property: the running trip's destination if there is
//  one, else the nearest managed property (≤ 300 m), else a ticket without
//  property. Created as the Verwalter's own (private) ticket, so it shows in
//  the admin queue, on the CarPlay object page under "Offene Tickets", and
//  nowhere an owner would see it. Hands-free capture in the car is the whole
//  point; no CarPlay entitlement involved.
//

import AppIntents
import CoreLocation
import Foundation

struct NoteWHVIntent: AppIntent {
    static var title: LocalizedStringResource = "WHV Notiz"
    static var description = IntentDescription(
        "Diktiert eine Notiz, die als Ticket am aktuellen Objekt angelegt wird."
    )
    static var openAppWhenRun = false

    @Parameter(
        title: "Notiz",
        requestValueDialog: IntentDialog("Was soll ich notieren?")
    )
    var text: String

    static var parameterSummary: some ParameterSummary {
        Summary("WHV Notiz: \(\.$text)")
    }

    @MainActor
    func perform() async throws -> some IntentResult & ProvidesDialog {
        let body = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !body.isEmpty else {
            throw $text.needsValueError(IntentDialog("Was soll ich notieren?"))
        }
        let api = APIClient()
        let tracker = TripTracker.shared

        // Where are we? Running trip's destination beats a GPS guess.
        var propertyId: String? = tracker.presetPropertyId
        var propertyName: String?
        if let props = try? await api.getMyProperties() {
            if let pid = propertyId {
                propertyName = props.first { $0.id == pid }?.name
            } else if let here = tracker.currentCoordinate {
                var best: (PropertyResponse, Double)?
                for p in props {
                    guard let lat = p.lat, let lng = p.lng else { continue }
                    let d = haversineMeters(here, CLLocationCoordinate2D(latitude: lat, longitude: lng))
                    if d <= 300, d < (best?.1 ?? .infinity) { best = (p, d) }
                }
                propertyId = best?.0.id
                propertyName = best?.0.name
            }
        }

        let subject = "Notiz: " + String(body.prefix(60)) + (body.count > 60 ? "…" : "")
        let category = TicketCategory(rawValue: "ALLGEMEIN_TELEFONNOTIZ")
            ?? TicketCategory.allCases.first!
        do {
            _ = try await api.createMyTicket(
                subject: subject, body: body, category: category, propertyId: propertyId
            )
        } catch APIError.unauthorized {
            return .result(dialog: "Bitte melden Sie sich zuerst in der WHV-App an.")
        } catch {
            return .result(dialog: "Die Notiz konnte gerade nicht gespeichert werden.")
        }
        let where_ = propertyName.map { " für \($0)" } ?? " ohne Objekt"
        return .result(dialog: IntentDialog(stringLiteral: "Notiert\(where_)."))
    }
}
