//
//  WatchTicketIntent.swift
//  WHVWatch
//
//  App Intent on the watch: "WHV Ticket" — also mappable to the Action
//  button of an Apple Watch Ultra (Settings → Action Button → Shortcut).
//  Dictation happens via the intent's parameter; the text is relayed to
//  the phone, which files the ticket at the current object.
//

import AppIntents
import Foundation

struct WatchTicketIntent: AppIntent {
    static var title: LocalizedStringResource = "WHV Ticket"
    static var description = IntentDescription("Legt per Diktat ein Ticket am aktuellen Objekt an (über das iPhone).")
    static var openAppWhenRun = false

    @Parameter(title: "Ticket", requestValueDialog: IntentDialog("Was soll ins Ticket?"))
    var text: String

    @MainActor
    func perform() async throws -> some IntentResult & ProvidesDialog {
        let body = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard body.count >= 3 else { throw $text.needsValueError(IntentDialog("Was soll ins Ticket?")) }
        await WatchBridge.shared.send("ticket", ["text": body])
        return .result(dialog: IntentDialog(stringLiteral: WatchBridge.shared.lastMessage ?? "Ticket angelegt."))
    }
}

struct WatchArriveIntent: AppIntent {
    static var title: LocalizedStringResource = "WHV Ankunft"
    static var openAppWhenRun = false

    @MainActor
    func perform() async throws -> some IntentResult & ProvidesDialog {
        await WatchBridge.shared.send("arrive")
        return .result(dialog: IntentDialog(stringLiteral: WatchBridge.shared.lastMessage ?? "Angekommen."))
    }
}

struct WHVWatchShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(intent: WatchTicketIntent(), phrases: ["\(.applicationName) Ticket"], shortTitle: "WHV Ticket", systemImageName: "tray.and.arrow.down.fill")
        AppShortcut(intent: WatchArriveIntent(), phrases: ["\(.applicationName) Ankunft"], shortTitle: "WHV Ankunft", systemImageName: "flag.checkered")
    }
}
