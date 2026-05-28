// Push-notification coordinator.
//
// Lifecycle:
//   sign-in  → requestAuthorizationAndRegister() asks the user for
//              notification permission, then registers for remote
//              notifications. iOS calls back into AppDelegate's
//              didRegisterForRemoteNotifications… with the token,
//              which hands it here via `didReceive(token:)`.
//   token    → POST /me/devices so the backend can fan ETV-comment /
//              ticket pushes out to this device.
//   sign-out → unregister() DELETEs the token so the signed-out
//              phone stops getting the previous user's pushes.
//
// A singleton because the UIKit AppDelegate (which receives the
// system token callback) and the SwiftUI stores both need to reach
// the same instance, and there's exactly one push state per app
// process.

import Foundation
import OSLog
import UIKit
import UserNotifications

@MainActor
final class PushManager: NSObject, ObservableObject {
    static let shared = PushManager()

    private let log = Logger(subsystem: "com.wagner-hausverwaltung.portal", category: "push")
    private let api = APIClient()

    /// The most recent APNs token iOS handed us this launch. We keep
    /// it so sign-out can DELETE the right token even if the token
    /// callback and the sign-out happen far apart.
    private var currentToken: String?

    /// Closure WHVApp wires to `deepLinkRouter.handle`. Invoked when
    /// the user taps a notification — the payload's `whv.deep_link`
    /// is converted to a whv:// URL and routed exactly like a widget
    /// tap.
    var onDeepLink: ((URL) -> Void)?

    /// Sandbox for Debug/Xcode installs, production for TestFlight /
    /// App Store. Must match the `aps-environment` entitlement value
    /// Xcode stamps per build config, which is what mints the token.
    private var environment: String {
        #if DEBUG
            return "SANDBOX"
        #else
            return "PRODUCTION"
        #endif
    }

    /// Ask for notification permission (once; iOS remembers the
    /// answer) then register for remote notifications if granted.
    /// Called on sign-in. No-ops in demo mode — a demo session has
    /// no backend account to attach a token to.
    func requestAuthorizationAndRegister() async {
        if DemoFlag.isActive { return }
        let center = UNUserNotificationCenter.current()
        center.delegate = self
        do {
            let granted = try await center.requestAuthorization(options: [
                .alert, .badge, .sound,
            ])
            guard granted else {
                log.info("push: authorization denied")
                return
            }
            // registerForRemoteNotifications must run on the main
            // thread; we're already @MainActor.
            UIApplication.shared.registerForRemoteNotifications()
        } catch {
            log.error("push: authorization request failed: \(error.localizedDescription)")
        }
    }

    /// Called from AppDelegate when iOS delivers the device token.
    func didReceive(token: Data) {
        let hex = token.map { String(format: "%02x", $0) }.joined()
        currentToken = hex
        Task {
            do {
                try await api.registerDevice(apnsToken: hex, environment: environment)
                log.info("push: device registered (\(self.environment, privacy: .public))")
            } catch {
                log.error("push: register failed: \(error.localizedDescription)")
            }
        }
    }

    func didFailToRegister(error: Error) {
        log.error("push: APNs registration failed: \(error.localizedDescription)")
    }

    /// Drop the token on sign-out. Best-effort: we deliberately
    /// don't await this in a way that could block the sign-out UI.
    func unregister() {
        guard let token = currentToken else { return }
        let api = self.api
        Task {
            try? await api.unregisterDevice(apnsToken: token)
        }
        currentToken = nil
    }

    /// Convert a tapped notification's payload into a deep-link URL
    /// and route it. The backend puts the link under
    /// `whv.deep_link` (e.g. "whv://etv/<id>").
    func handleNotificationPayload(_ userInfo: [AnyHashable: Any]) {
        guard
            let whv = userInfo["whv"] as? [AnyHashable: Any],
            let link = whv["deep_link"] as? String,
            let url = URL(string: link)
        else { return }
        onDeepLink?(url)
    }
}

extension PushManager: UNUserNotificationCenterDelegate {
    /// Foreground delivery — show the banner + play the sound even
    /// when the app is open, so a Verwalter watching the ticket
    /// queue still gets the nudge.
    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification,
        withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void
    ) {
        completionHandler([.banner, .sound, .badge])
    }

    /// Tap handling — route via the deep-link payload.
    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse,
        withCompletionHandler completionHandler: @escaping () -> Void
    ) {
        let userInfo = response.notification.request.content.userInfo
        Task { @MainActor in
            self.handleNotificationPayload(userInfo)
            completionHandler()
        }
    }
}
