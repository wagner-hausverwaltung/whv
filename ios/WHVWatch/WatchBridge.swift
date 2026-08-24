//
//  WatchBridge.swift
//  WHVWatch
//
//  WatchConnectivity client. Commands go to the phone as messages with a
//  reply; the phone pushes the trip state as application context whenever
//  it changes (and on every reply), so the screen is current even after a
//  relaunch.
//

import Combine
import Foundation
import WatchConnectivity

struct WatchTripState: Codable, Equatable {
    var isRunning: Bool = false
    var startedAt: Date?
    var distanceM: Int = 0
    var destinationName: String?
    var purposeLabel: String?
    var pendingUploads: Int = 0
    var signedIn: Bool = false
    var updatedAt: Date = .distantPast
}

@MainActor
final class WatchBridge: NSObject, ObservableObject {
    static let shared = WatchBridge()

    @Published private(set) var state = WatchTripState()
    @Published private(set) var reachable = false
    @Published private(set) var lastMessage: String?
    @Published private(set) var busy = false

    private let session: WCSession? = WCSession.isSupported() ? WCSession.default : nil
    private let encoder = JSONEncoder()
    private let decoder = JSONDecoder()

    /// `-ScreenshotTrip` launch argument (App Store screenshots in the
    /// watch simulator, which has no paired phone): show a running sample
    /// trip and never talk to WatchConnectivity.
    private let screenshotMode = ProcessInfo.processInfo.arguments.contains { $0.hasPrefix("-Screenshot") }

    private override init() {
        super.init()
        encoder.dateEncodingStrategy = .iso8601
        decoder.dateDecodingStrategy = .iso8601
        if screenshotMode {
            let running = ProcessInfo.processInfo.arguments.contains("-ScreenshotTrip")
            state = WatchTripState(
                isRunning: running,
                startedAt: running ? Date().addingTimeInterval(-17 * 60) : nil,
                distanceM: running ? 12_400 : 0,
                destinationName: running ? "WEG Hasenbergstraße 32, Stuttgart" : nil,
                purposeLabel: running ? "Eigentümerversammlung" : nil,
                pendingUploads: 0,
                signedIn: true,
                updatedAt: Date()
            )
            return
        }
        session?.delegate = self
        session?.activate()
    }

    /// Send a command and wait for the phone's reply (≈ 1–3 s). The phone
    /// answers with {"ok": Bool, "message": String, "state": <json>}.
    func send(_ command: String, _ extra: [String: Any] = [:]) async {
        if screenshotMode { return }
        guard let session, session.activationState == .activated else {
            lastMessage = "iPhone nicht verbunden."
            return
        }
        busy = true
        defer { busy = false }
        var payload: [String: Any] = ["cmd": command]
        extra.forEach { payload[$0.key] = $0.value }
        do {
            let reply: [String: Any] = try await withCheckedThrowingContinuation { cont in
                session.sendMessage(payload, replyHandler: { cont.resume(returning: $0) }) { cont.resume(throwing: $0) }
            }
            apply(reply)
            lastMessage = reply["message"] as? String
        } catch {
            lastMessage = "iPhone nicht erreichbar — bitte in der Nähe halten."
        }
    }

    private func apply(_ dict: [String: Any]) {
        if let raw = dict["state"] as? String, let data = raw.data(using: .utf8),
           let s = try? decoder.decode(WatchTripState.self, from: data) {
            state = s
        }
    }

    func refresh() async { await send("state") }
}

extension WatchBridge: WCSessionDelegate {
    nonisolated func session(_ session: WCSession, activationDidCompleteWith activationState: WCSessionActivationState, error: Error?) {
        Task { @MainActor in
            self.reachable = session.isReachable
            self.apply(session.receivedApplicationContext)
            await self.refresh()
        }
    }

    nonisolated func sessionReachabilityDidChange(_ session: WCSession) {
        Task { @MainActor in self.reachable = session.isReachable }
    }

    nonisolated func session(_ session: WCSession, didReceiveApplicationContext applicationContext: [String: Any]) {
        Task { @MainActor in self.apply(applicationContext) }
    }
}
