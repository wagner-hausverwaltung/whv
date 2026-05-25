// Optional Face ID / Touch ID gate. When enabled, the app
// presents a blurred lock overlay any time it foregrounds after
// being backgrounded for ≥60s and refuses to lift it until the
// user authenticates with biometrics. Quick tab-switches don't
// trigger; a real walk-away from the device does.
//
// The threshold is deliberately conservative — most banking apps
// use ≤5s, which annoys users for no security benefit while the
// device is on the desk. 60s catches the "left it on the café
// table" pattern without nagging.
//
// Persistence:
//   UserDefaults: "WHV.biometrics.enabled" (Bool)
//   In-memory:    backgroundedAt + isLocked
//
// Biometric availability is checked once per app launch; if the
// device has no Face ID / Touch ID, the toggle row stays hidden in
// Settings and `isAvailable` reads false. This is informational
// only — re-prompting per refresh would be wasteful.

import Foundation
import LocalAuthentication

@MainActor
final class BiometricLockStore: ObservableObject {
    @Published private(set) var isLocked = false
    @Published var enabled: Bool {
        didSet {
            defaults.set(enabled, forKey: enabledKey)
        }
    }
    @Published private(set) var lastError: String?

    /// True when the device has a biometric sensor available + the
    /// user has set one up. Cached at init to avoid a per-frame LA
    /// call. The constant `biometryType` is also exposed so the
    /// Settings row can render the right copy ("Face ID" vs.
    /// "Touch ID").
    let isAvailable: Bool
    let biometryLabel: String

    /// Threshold past which a foreground triggers a fresh prompt.
    /// 60s — see file header.
    static let backgroundThreshold: TimeInterval = 60

    private let defaults: UserDefaults
    private let enabledKey = "WHV.biometrics.enabled"
    private var backgroundedAt: Date?

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        self.enabled = defaults.bool(forKey: enabledKey)

        let ctx = LAContext()
        var err: NSError?
        let canEvaluate = ctx.canEvaluatePolicy(
            .deviceOwnerAuthenticationWithBiometrics,
            error: &err
        )
        self.isAvailable = canEvaluate
        self.biometryLabel = Self.label(for: ctx.biometryType)
    }

    /// Call from WHVApp when the scene phase flips to .background.
    /// Records the timestamp; nothing else changes until the next
    /// foreground.
    func didEnterBackground(now: Date = Date()) {
        guard enabled, isAvailable else { return }
        backgroundedAt = now
    }

    /// Call from WHVApp when the scene phase flips to .active.
    /// Decides whether to lock based on the elapsed time. The lock
    /// overlay reads `isLocked` to gate the UI; the unlock action
    /// (`authenticate`) flips it back.
    func didBecomeActive(now: Date = Date()) {
        guard enabled, isAvailable else {
            isLocked = false
            return
        }
        if let backgroundedAt {
            let elapsed = now.timeIntervalSince(backgroundedAt)
            if elapsed >= Self.backgroundThreshold {
                isLocked = true
            }
        }
        backgroundedAt = nil
    }

    /// Prompts the user with Face ID / Touch ID. Returns whether
    /// the prompt succeeded; on failure, the lock overlay stays up
    /// and the user can re-press the unlock button.
    @discardableResult
    func authenticate() async -> Bool {
        guard isLocked else { return true }
        lastError = nil
        let ctx = LAContext()
        ctx.localizedFallbackTitle = ""  // hide the password fallback in v1
        do {
            let ok = try await ctx.evaluatePolicy(
                .deviceOwnerAuthenticationWithBiometrics,
                localizedReason: "Entsperren der WHV-App"
            )
            if ok {
                isLocked = false
                return true
            }
            return false
        } catch let err as LAError where err.code == .userCancel || err.code == .systemCancel {
            // User dismissed; stay locked. Don't surface an error.
            return false
        } catch {
            lastError = error.localizedDescription
            return false
        }
    }

    /// "Face ID" / "Touch ID" / "" — drives the Settings label.
    private static func label(for type: LABiometryType) -> String {
        switch type {
        case .faceID: return "Face ID"
        case .touchID: return "Touch ID"
        case .opticID: return "Optic ID"
        @unknown default: return ""
        }
    }
}
