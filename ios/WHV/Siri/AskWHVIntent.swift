//
//  AskWHVIntent.swift
//  WHV
//
//  "Hey Siri, frag WHV" — hands-free access to the RAG assistant, which is
//  what a Verwalter actually wants in the car. Siri asks for the question,
//  the intent calls /assistant/query in the app's own process (the JWT comes
//  from the Keychain like everywhere else) and Siri reads the answer aloud.
//  No CarPlay entitlement involved: App Intents + Siri work in any car, on
//  the phone, on the watch.
//
//  Free-text can't be part of the invocation phrase (App Shortcuts only bind
//  AppEntity/AppEnum parameters), so the flow is two-step by design:
//  "Frag WHV" → "Was möchten Sie wissen?" → answer.
//

import AppIntents
import CoreLocation
import Foundation

struct AskWHVIntent: AppIntent {
    static var title: LocalizedStringResource = "Frag WHV"
    static var description = IntentDescription(
        "Stellt dem WHV-Assistenten eine Frage zu Ihren Objekten, Dokumenten und Terminen."
    )
    // Runs in the background; Siri speaks the result. The app is not brought
    // to the foreground — essential while driving.
    static var openAppWhenRun = false

    /// Optional: the object the question is about. Set by Siri's ask-back
    /// ("Für welches Objekt?") when we can't infer it from the question,
    /// the running trip, GPS or the app's selection.
    @Parameter(title: "Objekt", requestValueDialog: IntentDialog("Für welches Objekt? Sagen Sie den Straßennamen."))
    var property: PropertyEntity?

    @Parameter(
        title: "Frage",
        requestValueDialog: IntentDialog("Was möchten Sie wissen?")
    )
    var question: String

    static var parameterSummary: some ParameterSummary {
        Summary("Frag WHV: \(\.$question)") {
            \.$property
        }
    }

    func perform() async throws -> some IntentResult & ProvidesDialog & ReturnsValue<String> {
        let q = question.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !q.isEmpty else {
            throw $question.needsValueError(IntentDialog("Was möchten Sie wissen?"))
        }
        // Scope the question to an object whenever we can tell which one:
        // named in the question → running trip's destination → nearest
        // object ≤ 300 m → the object selected in the app. Org-wide
        // retrieval across 27 objects mostly abstains ("nichts gefunden").
        let api = APIClient()
        var propertyId = property?.id
        if propertyId == nil, !DemoFlag.isActive {
            let props = (try? await api.getMyProperties()) ?? []
            if let inferred = await Self.resolvePropertyContext(question: q, props: props) {
                propertyId = inferred.id
            } else if !props.isEmpty {
                // Nothing to go on → let Siri ask back; the spoken answer is
                // resolved by PropertyEntityQuery and perform() runs again.
                throw $property.needsValueError(IntentDialog("Für welches Objekt? Sagen Sie den Straßennamen."))
            }
        }
        let language = Locale.current.language.languageCode?.identifier
        let answer: String
        do {
            let r = try await api.askAssistant(question: q, propertyId: propertyId, language: language)
            answer = r.answer.isEmpty ? String(localized: "Dazu habe ich leider nichts gefunden.") : r.answer
        } catch APIError.unauthorized {
            answer = String(localized: "Bitte melden Sie sich zuerst in der WHV-App an.")
        } catch APIError.demoReadOnly {
            answer = String(localized: "Im Demo-Modus ist der Assistent nicht verfügbar.")
        } catch {
            answer = String(localized: "Der Assistent ist gerade nicht erreichbar.")
        }
        // Siri reads the dialog; keep the spoken part digestible and hand the
        // full text back as the value (Shortcuts can show/forward it).
        let spoken = Self.spokenForm(answer)
        return .result(value: answer, dialog: IntentDialog(stringLiteral: spoken))
    }

    /// Which object is the question about? Longest street-name or short-code
    /// match in the question wins; otherwise the trip destination, the
    /// nearest object, then the app's current selection.
    @MainActor
    static func resolvePropertyContext(question: String, props: [PropertyResponse]) -> PropertyResponse? {
        if let named = PropertyMatch.property(named: question, in: props) { return named }
        let tracker = TripTracker.shared
        if let pid = tracker.presetPropertyId, let p = props.first(where: { $0.id == pid }) { return p }
        if let here = tracker.currentCoordinate {
            var best: (PropertyResponse, Double)?
            for p in props {
                guard let lat = p.lat, let lng = p.lng else { continue }
                let d = haversineMeters(here, CLLocationCoordinate2D(latitude: lat, longitude: lng))
                if d <= 300, d < (best?.1 ?? .infinity) { best = (p, d) }
            }
            if let best { return best.0 }
        }
        if let sel = UserDefaults.standard.string(forKey: "WHV.selectedLiegenschaftId"),
           let p = props.first(where: { $0.id == sel }) {
            return p
        }
        return nil
    }

    /// Markdown bullets / headers don't read well aloud; and very long
    /// answers are better cut with a hint than read for two minutes.
    static func spokenForm(_ text: String) -> String {
        var s = text
            .replacingOccurrences(of: "**", with: "")
            .replacingOccurrences(of: "#", with: "")
            .replacingOccurrences(of: "\n- ", with: ". ")
            .replacingOccurrences(of: "\n• ", with: ". ")
            .replacingOccurrences(of: "\n", with: " ")
        if s.count > 700 {
            let cut = s.index(s.startIndex, offsetBy: 700)
            s = String(s[..<cut]) + " … Den vollständigen Text finden Sie in der App."
        }
        return s
    }
}

struct WHVShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(
            intent: AskWHVIntent(),
            phrases: [
                "Frag \(.applicationName)",
                "Frage an \(.applicationName)",
                "\(.applicationName) fragen",
                // English alternates live in the base list too: iOS binds App
                // Shortcut phrases to the APP language, so a German-set app on
                // an English Siri would otherwise never match.
                "Ask \(.applicationName)",
            ],
            shortTitle: "Frag WHV",
            systemImageName: "bubble.left.and.text.bubble.right"
        )
        AppShortcut(
            intent: NoteWHVIntent(),
            phrases: [
                "\(.applicationName) Ticket",
                "Ticket an \(.applicationName)",
                "Neues Ticket für \(.applicationName)",
                "\(.applicationName) Notiz",
            ],
            shortTitle: "WHV Ticket",
            systemImageName: "tray.and.arrow.down.fill"
        )
        AppShortcut(
            intent: DepartWHVIntent(),
            phrases: [
                "\(.applicationName) Abfahrt",
                "Abfahrt \(.applicationName)",
                "\(.applicationName) Fahrt starten",
                "\(.applicationName) departure",
            ],
            shortTitle: "WHV Abfahrt",
            systemImageName: "car.fill"
        )
        AppShortcut(
            intent: ArriveWHVIntent(),
            phrases: [
                "\(.applicationName) Ankunft",
                "Ankunft \(.applicationName)",
                "\(.applicationName) Fahrt beenden",
                "\(.applicationName) arrival",
            ],
            shortTitle: "WHV Ankunft",
            systemImageName: "flag.checkered"
        )
        AppShortcut(
            intent: ContractorOnSiteIntent(),
            phrases: [
                "\(.applicationName) Handwerker vor Ort",
                "Handwerker vor Ort \(.applicationName)",
                "\(.applicationName) Handwerker",
                "\(.applicationName) contractor on site",
            ],
            shortTitle: "WHV Handwerker vor Ort",
            systemImageName: "wrench.and.screwdriver.fill"
        )
        AppShortcut(
            intent: MessageContactIntent(),
            phrases: [
                "\(.applicationName) Notiz an \(\.$contact)",
                "\(.applicationName) Nachricht an \(\.$contact)",
                "\(.applicationName) note to \(\.$contact)",
            ],
            shortTitle: "WHV Notiz an Kontakt",
            systemImageName: "envelope.fill"
        )
    }
}
