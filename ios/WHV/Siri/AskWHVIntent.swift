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
import Foundation

struct AskWHVIntent: AppIntent {
    static var title: LocalizedStringResource = "Frag WHV"
    static var description = IntentDescription(
        "Stellt dem WHV-Assistenten eine Frage zu Ihren Objekten, Dokumenten und Terminen."
    )
    // Runs in the background; Siri speaks the result. The app is not brought
    // to the foreground — essential while driving.
    static var openAppWhenRun = false

    @Parameter(
        title: "Frage",
        requestValueDialog: IntentDialog("Was möchten Sie wissen?")
    )
    var question: String

    static var parameterSummary: some ParameterSummary {
        Summary("Frag WHV: \(\.$question)")
    }

    func perform() async throws -> some IntentResult & ProvidesDialog & ReturnsValue<String> {
        let q = question.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !q.isEmpty else {
            throw $question.needsValueError(IntentDialog("Was möchten Sie wissen?"))
        }
        let answer: String
        do {
            let r = try await APIClient().askAssistant(question: q)
            answer = r.answer.isEmpty ? "Dazu habe ich leider nichts gefunden." : r.answer
        } catch APIError.unauthorized {
            answer = "Bitte melden Sie sich zuerst in der WHV-App an."
        } catch APIError.demoReadOnly {
            answer = "Im Demo-Modus ist der Assistent nicht verfügbar."
        } catch {
            answer = "Der Assistent ist gerade nicht erreichbar."
        }
        // Siri reads the dialog; keep the spoken part digestible and hand the
        // full text back as the value (Shortcuts can show/forward it).
        let spoken = Self.spokenForm(answer)
        return .result(value: answer, dialog: IntentDialog(stringLiteral: spoken))
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
            ],
            shortTitle: "WHV Handwerker vor Ort",
            systemImageName: "wrench.and.screwdriver.fill"
        )
        AppShortcut(
            intent: MessageContactIntent(),
            phrases: [
                "\(.applicationName) Notiz an \(\.$contact)",
                "\(.applicationName) Nachricht an \(\.$contact)",
            ],
            shortTitle: "WHV Notiz an Kontakt",
            systemImageName: "envelope.fill"
        )
    }
}
