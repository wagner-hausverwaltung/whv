//
//  CallDirectorySync.swift
//  WHV
//
//  Caller ID for the Verwalter: pulls /me/call-directory (owners, tenants,
//  vendors with phone numbers → "Name · Objekt (Rolle)"), writes the list
//  into the app-group container and asks CallKit to reload the
//  WHVCallDirectory extension. The extension itself is dumb by design; all
//  normalisation happens on the server, all fetching here.
//
//  Verwalter-only (the endpoint is role-gated, owners never get the org's
//  phone book). Runs at most every 12 h on its own; Einstellungen has a
//  manual button plus the enable/disable status and a jump to iOS Settings
//  (Telefon → Anrufe blockieren u. identifizieren).
//

import CallKit
import Combine
import Foundation
import OSLog
import UIKit
import UserNotifications

struct CallDirectoryResponse: Codable {
    struct Entry: Codable {
        let number: Int64
        let label: String
    }
    let entries: [Entry]
    let contacts: Int
}

@MainActor
final class CallDirectorySync: ObservableObject {
    static let shared = CallDirectorySync()

    @Published private(set) var status: CXCallDirectoryManager.EnabledStatus = .unknown
    @Published private(set) var lastSync: Date?
    @Published private(set) var entryCount: Int = 0
    @Published private(set) var busy = false
    @Published private(set) var lastError: String?

    private let api = APIClient()
    private let defaults = UserDefaults.standard
    private let log = Logger(subsystem: "com.wagner-hausverwaltung.portal", category: "calldirectory")
    private enum Keys {
        static let lastSync = "calldir.lastSync"
        static let count = "calldir.count"
    }
    private let interval: TimeInterval = 12 * 3600

    private init() {
        lastSync = defaults.object(forKey: Keys.lastSync) as? Date
        entryCount = defaults.integer(forKey: Keys.count)
    }

    func refreshStatus() async {
        status = await withCheckedContinuation { cont in
            CXCallDirectoryManager.sharedInstance.getEnabledStatusForExtension(
                withIdentifier: CallDirectoryStore.extensionIdentifier
            ) { status, _ in cont.resume(returning: status) }
        }
    }

    /// Sync when due (12 h) — called on sign-in and on foreground.
    func syncIfDue() async {
        if let last = lastSync, Date().timeIntervalSince(last) < interval { return }
        await sync()
    }

    func sync() async {
        guard !busy, !DemoFlag.isActive else { return }
        busy = true
        lastError = nil
        defer { busy = false }
        do {
            let r: CallDirectoryResponse = try await api.getCallDirectory()
            let snapshot = CallDirectorySnapshot(
                generatedAt: Date(),
                entries: r.entries.map { CallDirectoryEntry(number: $0.number, label: $0.label) }
            )
            try CallDirectoryStore.save(snapshot)
            try await reloadExtension()
            lastSync = Date()
            entryCount = snapshot.entries.count
            defaults.set(lastSync, forKey: Keys.lastSync)
            defaults.set(entryCount, forKey: Keys.count)
            log.info("call directory synced: \(snapshot.entries.count) entries")
        } catch APIError.unauthorized {
            // Not signed in (or not a Verwalter): silently skip.
        } catch {
            log.error("call directory sync failed: \(String(describing: error), privacy: .public)")
            lastError = "Anrufer-Liste konnte nicht aktualisiert werden."
        }
        await refreshStatus()
    }

    private func reloadExtension() async throws {
        try await withCheckedThrowingContinuation { (cont: CheckedContinuation<Void, Error>) in
            CXCallDirectoryManager.sharedInstance.reloadExtension(
                withIdentifier: CallDirectoryStore.extensionIdentifier
            ) { error in
                // "disabled" is not a sync failure — the list is on disk and
                // loads the moment the user enables the extension.
                if let error, (error as NSError).code != CXErrorCodeCallDirectoryManagerError.extensionDisabled.rawValue {
                    cont.resume(throwing: error)
                } else {
                    cont.resume()
                }
            }
        }
    }

    /// iOS Settings → Telefon → Anrufe blockieren u. identifizieren (iOS 13.4+).
    func openSettings() {
        CXCallDirectoryManager.sharedInstance.openSettings { _ in }
    }
}

// MARK: - After a call: offer to log it

/// Watches phone calls (CallKit exposes begin/end, never the number) and,
/// when a connected call ends, posts a local notification that opens the
/// new-ticket sheet — "Telefonat festhalten?". Verwalter-only, while the
/// app is alive (foreground or background).
@MainActor
final class CallLogPrompt: NSObject, CXCallObserverDelegate {
    static let shared = CallLogPrompt()
    private let observer = CXCallObserver()
    private var connectedAt: [UUID: Date] = [:]
    private var started = false

    func start() {
        guard !started else { return }
        started = true
        observer.setDelegate(self, queue: .main)
    }

    nonisolated func callObserver(_ callObserver: CXCallObserver, callChanged call: CXCall) {
        Task { @MainActor in self.handle(call) }
    }

    private func handle(_ call: CXCall) {
        if call.hasConnected, connectedAt[call.uuid] == nil {
            connectedAt[call.uuid] = Date()
        }
        guard call.hasEnded else { return }
        defer { connectedAt[call.uuid] = nil }
        guard let since = connectedAt[call.uuid], Date().timeIntervalSince(since) >= 15 else { return }
        let content = UNMutableNotificationContent()
        content.title = "Telefonat festhalten?"
        content.body = "Tippen, um das Gespräch als Ticket-Notiz zu diktieren — oder „Hey Siri, WHV Ticket“."
        content.sound = nil
        content.userInfo = ["whv": ["deep_link": "whv://new-ticket"]]
        let req = UNNotificationRequest(identifier: "call-log-\(call.uuid.uuidString)", content: content, trigger: nil)
        UNUserNotificationCenter.current().add(req)
    }
}
