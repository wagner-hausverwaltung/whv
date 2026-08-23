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
        var q = question.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !q.isEmpty else {
            throw $question.needsValueError(IntentDialog("Was möchten Sie wissen?"))
        }
        // A real dialog, eyes-free: answer, then keep listening ("Noch eine
        // Frage?") until the user says no/thanks/done or stays silent. Every
        // round goes through the same conversation memory, so follow-ups keep
        // object and topic. Capped so a misheard "ja" can't loop forever.
        var lastAnswer = ""
        for round in 0..<Self.maxRounds {
            let answer = try await answer(to: q, property: round == 0 ? property : nil)
            lastAnswer = answer
            let spoken = Self.spokenForm(answer)
            let prompt = spoken + " " + String(localized: "Noch eine Frage?")
            let next: String
            do {
                next = try await $question.requestValue(IntentDialog(stringLiteral: prompt))
            } catch {
                // Siri session ended (silence, cancel) — the answer was spoken.
                return .result(value: lastAnswer, dialog: IntentDialog(stringLiteral: spoken))
            }
            let t = next.trimmingCharacters(in: .whitespacesAndNewlines)
            if t.isEmpty || Self.isGoodbye(t) { break }
            q = t
        }
        return .result(value: lastAnswer, dialog: "Alles klar.")
    }

    private static let maxRounds = 10

    /// "nein", "danke", "das war's", "fertig", "no", "thanks", "done" … —
    /// anything short that doesn't look like a question ends the dialog.
    static func isGoodbye(_ text: String) -> Bool {
        let t = text.lowercased()
            .trimmingCharacters(in: .punctuationCharacters.union(.whitespaces))
        let stops: Set<String> = [
            "nein", "nö", "ne", "nee", "nichts", "nichts mehr", "danke", "dankeschön", "vielen dank",
            "das wars", "das war's", "das war es", "fertig", "ende", "stopp", "stop", "tschüss",
            "passt", "alles gut", "nein danke", "no", "nope", "thanks", "thank you", "done",
            "that's all", "thats all", "that's it", "bye", "no thanks",
        ]
        return stops.contains(t)
    }

    /// One question → one answer, recorded in the conversation memory.
    private func answer(to q: String, property: PropertyEntity?) async throws -> String {
        // Scope the question to an object whenever we can tell which one:
        // named in the question → the conversation's object → running trip's
        // destination → nearest object ≤ 300 m → the object selected in the
        // app. Org-wide retrieval across 27 objects mostly abstains.
        let api = APIClient()
        // Follow-up within a few minutes → same conversation: replay the
        // recent turns and keep the object unless the question names another.
        let convo = SiriConversation.current()
        let conversationId = convo?.conversationId ?? UUID().uuidString.lowercased()
        var propertyId = property?.id
        if propertyId == nil, !DemoFlag.isActive {
            let props = (try? await api.getMyProperties()) ?? []
            if let named = PropertyMatch.property(named: q, in: props) {
                propertyId = named.id
            } else if let prev = convo?.propertyId, props.contains(where: { $0.id == prev }) {
                propertyId = prev
            } else if let inferred = await Self.resolvePropertyContext(question: q, props: props) {
                propertyId = inferred.id
            } else if !props.isEmpty, convo == nil {
                // Nothing to go on → let Siri ask back; the spoken answer is
                // resolved by PropertyEntityQuery and perform() runs again.
                throw $property.needsValueError(IntentDialog("Für welches Objekt? Sagen Sie den Straßennamen."))
            }
        }
        let language = Locale.current.language.languageCode?.identifier
        do {
            let r = try await api.askAssistant(
                question: q,
                history: (convo?.turns ?? []).map { AssistantHistoryTurn(role: $0.role, content: $0.content) },
                propertyId: propertyId,
                conversationId: conversationId,
                language: language
            )
            let answer = r.answer.isEmpty ? String(localized: "Dazu habe ich leider nichts gefunden.") : r.answer
            SiriConversation.record(
                conversationId: conversationId, question: q, answer: answer, propertyId: propertyId
            )
            return answer
        } catch APIError.unauthorized {
            return String(localized: "Bitte melden Sie sich zuerst in der WHV-App an.")
        } catch APIError.demoReadOnly {
            return String(localized: "Im Demo-Modus ist der Assistent nicht verfügbar.")
        } catch {
            return String(localized: "Der Assistent ist gerade nicht erreichbar.")
        }
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
