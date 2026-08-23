//
//  MessageContactIntent.swift
//  WHV
//
//  "Hey Siri, WHV Notiz an Frau Fritz" — dictate a short message; the
//  backend e-mails it to the contact on WHV's behalf (reply-to the
//  Verwalter). Contacts are exposed to Siri as an AppEntity so the name can
//  be part of the phrase; the entity query searches /me/contacts/search.
//

import AppIntents
import Foundation

struct ContactSearchResult: Codable, Hashable, Identifiable {
    let id: String
    let name: String
    let email: String?
    let phone: String?
    let property_name: String?
    let role: String?
}

struct ContactMessageBody: Encodable {
    let text: String
    let subject: String?
}

struct ContactMessageResult: Codable {
    let sent: Bool
    let to: String?
    let detail: String
}

struct ContactEntity: AppEntity {
    static var typeDisplayRepresentation = TypeDisplayRepresentation(name: "Kontakt")
    static var defaultQuery = ContactEntityQuery()

    let id: String
    let name: String
    let detail: String

    var displayRepresentation: DisplayRepresentation {
        DisplayRepresentation(title: "\(name)", subtitle: "\(detail)")
    }

    init(_ r: ContactSearchResult) {
        id = r.id
        name = r.name
        detail = [r.role, r.property_name].compactMap { $0 }.joined(separator: " · ")
    }
}

struct ContactEntityQuery: EntityStringQuery {
    func entities(for identifiers: [String]) async throws -> [ContactEntity] {
        // Identifiers come from a previous match; resolve by name search
        // is not possible by id — return what Siri already knows.
        let all = (try? await APIClient().searchContacts(query: "", limit: 50)) ?? []
        return all.filter { identifiers.contains($0.id) }.map(ContactEntity.init)
    }

    func entities(matching string: String) async throws -> [ContactEntity] {
        ((try? await APIClient().searchContacts(query: string, limit: 20)) ?? []).map(ContactEntity.init)
    }

    func suggestedEntities() async throws -> [ContactEntity] {
        ((try? await APIClient().searchContacts(query: "", limit: 30)) ?? []).map(ContactEntity.init)
    }
}

struct MessageContactIntent: AppIntent {
    static var title: LocalizedStringResource = "WHV Notiz an Kontakt"
    static var description = IntentDescription("Schickt einem Eigentümer oder Mieter eine kurze Nachricht per E-Mail.")
    static var openAppWhenRun = false

    @Parameter(title: "Kontakt", requestValueDialog: IntentDialog("An wen?"))
    var contact: ContactEntity

    @Parameter(title: "Nachricht", requestValueDialog: IntentDialog("Was soll ich schreiben?"))
    var text: String

    static var parameterSummary: some ParameterSummary {
        Summary("Notiz an \(\.$contact): \(\.$text)")
    }

    @MainActor
    func perform() async throws -> some IntentResult & ProvidesDialog {
        let body = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard body.count >= 2 else { throw $text.needsValueError(IntentDialog("Was soll ich schreiben?")) }
        do {
            let r = try await APIClient().messageContact(id: contact.id, text: body)
            if r.sent {
                let name = contact.name
                return .result(dialog: IntentDialog("Gesendet an \(name)."))
            }
            return .result(dialog: IntentDialog(stringLiteral: r.detail))  // server text
        } catch APIError.unauthorized {
            return .result(dialog: "Bitte melden Sie sich zuerst in der WHV-App an.")
        } catch {
            return .result(dialog: "Die Nachricht konnte nicht gesendet werden.")
        }
    }
}
