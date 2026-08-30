//
//  PhoneWatchBridge.swift
//  WHV
//
//  iPhone side of the Apple Watch companion: answers the watch's commands
//  (start / stop / arrive / ticket / state) against TripTracker + the API and
//  pushes the trip state as application context whenever it changes. WCSession
//  wakes this app in the background for sendMessage, so the watch works with
//  the phone in the pocket.
//

import Combine
import CoreLocation
import Foundation
import WatchConnectivity

/// Mirror of the watch's WatchTripState — kept in sync by hand (tiny).
private struct WatchTripStateOut: Codable {
    var isRunning: Bool
    var startedAt: Date?
    var distanceM: Int
    var destinationName: String?
    var purposeLabel: String?
    var pendingUploads: Int
    var signedIn: Bool
    var updatedAt: Date
}

@MainActor
final class PhoneWatchBridge: NSObject {
    static let shared = PhoneWatchBridge()

    private let session: WCSession? = WCSession.isSupported() ? WCSession.default : nil
    private var subscriptions: Set<AnyCancellable> = []
    private let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.dateEncodingStrategy = .iso8601
        return e
    }()
    private var started = false

    func start() {
        guard !started, let session else { return }
        started = true
        session.delegate = self
        session.activate()
        let tracker = TripTracker.shared
        // Push state on every relevant change (throttled by Combine).
        Publishers.CombineLatest3(tracker.$isRunning, tracker.$liveDistanceM, tracker.$presetPropertyId)
            .debounce(for: .seconds(2), scheduler: RunLoop.main)
            .sink { [weak self] _, _, _ in self?.pushState() }
            .store(in: &subscriptions)
    }

    private func currentState() -> WatchTripStateOut {
        let t = TripTracker.shared
        let dest = t.presetPropertyId.flatMap { pid in t.knownPropertyName(pid) }
        return WatchTripStateOut(
            isRunning: t.isRunning,
            startedAt: t.startedAt,
            distanceM: t.liveDistanceM,
            destinationName: dest,
            purposeLabel: t.presetPurpose.map { TripPurpose.label(for: $0) },
            pendingUploads: t.pendingUploads,
            signedIn: APIClient.defaultTokenProvider() != nil,
            updatedAt: Date()
        )
    }

    private func stateJSON() -> String {
        (try? encoder.encode(currentState())).flatMap { String(data: $0, encoding: .utf8) } ?? "{}"
    }

    func pushState() {
        guard let session, session.activationState == .activated, session.isPaired, session.isWatchAppInstalled else { return }
        try? session.updateApplicationContext(["state": stateJSON()])
    }

    private func handle(_ message: [String: Any]) async -> [String: Any] {
        let tracker = TripTracker.shared
        let cmd = message["cmd"] as? String ?? ""
        var ok = true
        var text = ""
        switch cmd {
        case "start":
            if tracker.isRunning { text = "Fahrt läuft bereits." } else { tracker.startFromSiri(); text = "Fahrt gestartet." }
        case "stop":
            if tracker.isRunning { tracker.stopManually(); text = "Fahrt beendet — Zweck in der App bestätigen." } else { text = "Keine Fahrt aktiv." }
        case "arrive":
            if !tracker.isRunning { text = "Keine Fahrt aktiv." }
            else if let a = tracker.arriveFromSiri() {
                text = "Angekommen: \(a.property.name)" + (a.purpose.map { " · \(TripPurpose.label(for: $0))" } ?? "")
            } else { text = "Fahrt beendet, kein Objekt in der Nähe." }
        case "ticket":
            let body = (message["text"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            if body.count < 3 { ok = false; text = "Text zu kurz." } else { (ok, text) = await createTicket(body) }
        case "state":
            text = ""
        default:
            ok = false; text = "Unbekannter Befehl."
        }
        return ["ok": ok, "message": text, "state": stateJSON()]
    }

    /// Same placement rule as the Siri ticket: running trip's destination,
    /// else nearest object ≤ 300 m, else without object.
    private func createTicket(_ body: String) async -> (Bool, String) {
        let api = APIClient()
        let tracker = TripTracker.shared
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
        do {
            _ = try await api.createMyTicket(
                subject: String(body.prefix(60)) + (body.count > 60 ? "…" : ""),
                body: body,
                category: TicketCategory(rawValue: "SONSTIGES_OTHER") ?? TicketCategory.allCases.first!,
                propertyId: propertyId
            )
            return (true, "Ticket angelegt" + (propertyName.map { " für \($0)" } ?? "") + ".")
        } catch APIError.unauthorized {
            return (false, "Bitte auf dem iPhone anmelden.")
        } catch {
            return (false, "Ticket konnte nicht angelegt werden.")
        }
    }
}

extension PhoneWatchBridge: WCSessionDelegate {
    nonisolated func session(_ session: WCSession, activationDidCompleteWith activationState: WCSessionActivationState, error: Error?) {
        Task { @MainActor in self.pushState() }
    }

    nonisolated func sessionDidBecomeInactive(_ session: WCSession) {}

    nonisolated func sessionDidDeactivate(_ session: WCSession) {
        session.activate()
    }

    nonisolated func session(_ session: WCSession, didReceiveMessage message: [String: Any], replyHandler: @escaping ([String: Any]) -> Void) {
        Task { @MainActor in
            let reply = await self.handle(message)
            replyHandler(reply)
            self.pushState()
        }
    }

    nonisolated func session(_ session: WCSession, didReceiveMessage message: [String: Any]) {
        Task { @MainActor in _ = await self.handle(message); self.pushState() }
    }
}
