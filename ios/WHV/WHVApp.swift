// WHV iOS — Phase 2 starter scaffold.
//
// Three-stage startup:
//   1. Not signed in        → LoginView (mirrors portal /auth/login)
//   2. Signed in, no prop   → LiegenschaftPickerView
//   3. Signed in + prop     → RootTabView (the main app)
//
// All three stores live at the App level so a single instance
// serves the whole view tree — sign-out / picker-clear / settings
// changes are single-line state mutations, no view-tree gymnastics.
//
// SettingsStore drives the appearance + locale environment at the
// root so any view downstream picks them up automatically.

import SwiftUI

@main
struct WHVApp: App {
    @StateObject private var authStore: AuthStore
    @StateObject private var liegenschaftStore: LiegenschaftStore
    @StateObject private var settings: SettingsStore
    @StateObject private var deepLinkRouter: DeepLinkRouter
    @StateObject private var biometricLock: BiometricLockStore
    @StateObject private var demoStore: DemoStore
    // UIKit shim for the APNs device-token callbacks SwiftUI's
    // App lifecycle doesn't surface. Forwards to PushManager.shared.
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @Environment(\.scenePhase) private var scenePhase

    init() {
        // Single launch-arg gate. UI test runs (see WHVUITests)
        // inject -UITestScreenshots to neutralise environment state
        // that would otherwise interfere with screenshot capture:
        // biometric lock overlay, a stale signed-in session from a
        // previous run, and any accidental backend traffic if the
        // test taps Demo. Production launches early-return.
        Self.applyUITestScreenshotOverridesIfNeeded()
        // Construct the @StateObjects AFTER the override has touched
        // UserDefaults + Keychain, so each store's init reads the
        // neutralised state (BiometricLockStore + AuthStore both
        // hydrate from those layers in their initializer).
        _authStore = StateObject(wrappedValue: AuthStore())
        _liegenschaftStore = StateObject(wrappedValue: LiegenschaftStore())
        _settings = StateObject(wrappedValue: SettingsStore())
        _deepLinkRouter = StateObject(wrappedValue: DeepLinkRouter())
        _biometricLock = StateObject(wrappedValue: BiometricLockStore())
        _demoStore = StateObject(wrappedValue: DemoStore.shared)
    }

    private static func applyUITestScreenshotOverridesIfNeeded() {
        guard ProcessInfo.processInfo.arguments.contains("-UITestScreenshots") else { return }
        UserDefaults.standard.set(false, forKey: "WHV.biometrics.enabled")
        UserDefaults.standard.removeObject(forKey: "WHV.cachedUser")
        let keychain = Keychain()
        keychain.delete("access_token")
        keychain.delete("refresh_token")
        // Pre-arm the demo flag so any accidental authenticated call
        // (e.g. revalidate() if a token slipped through) short-circuits
        // to seed data rather than reaching staging.
        DemoFlag.isActive = true
    }

    var body: some Scene {
        WindowGroup {
            ZStack {
                // Demo banner is a real VStack sibling above the
                // entire view tree — sits over the status bar
                // safe area and pushes ALL downstream content
                // (including TabView + NavigationStacks) down so
                // nothing collides with the banner. Previous
                // attempts via .overlay / .safeAreaInset on
                // RootTabView left the nav header partially under
                // the strip on iPad.
                VStack(spacing: 0) {
                    if demoStore.isActive {
                        DemoBanner { authStore.signOut() }
                            .transition(.move(edge: .top).combined(with: .opacity))
                    }
                    rootView
                }
                    .animation(.easeInOut(duration: 0.2), value: demoStore.isActive)
                    .environmentObject(authStore)
                    .environmentObject(liegenschaftStore)
                    .environmentObject(settings)
                    .environmentObject(deepLinkRouter)
                    .environmentObject(biometricLock)
                    .environmentObject(demoStore)
                // Lock overlay sits on top of the entire tree when
                // active — covers every tab + every nav stack +
                // every modal sheet underneath. Sign-in is gated
                // separately (rootView), so the lock only matters
                // for already-authenticated sessions.
                if biometricLock.isLocked && authStore.signedIn {
                    BiometricLockView()
                        .environmentObject(biometricLock)
                        .transition(.opacity)
                }
            }
            .animation(.easeInOut(duration: 0.2), value: biometricLock.isLocked)
            .onChange(of: scenePhase) { _, newPhase in
                switch newPhase {
                case .background:
                    biometricLock.didEnterBackground()
                case .active:
                    biometricLock.didBecomeActive()
                default:
                    break
                }
            }
                // Widget taps + Universal Links land here. The
                // router decodes them; RootTabView (when mounted)
                // observes pendingTarget and reacts. Links that
                // arrive before sign-in stay queued until the user
                // has authenticated, then the tab shell picks them
                // up on first render.
                .onOpenURL { url in
                    deepLinkRouter.handle(url)
                }
                .task {
                    // Wire AuthStore → LiegenschaftStore transitions.
                    // Sign-in pre-loads /me/properties so the picker
                    // renders immediately; sign-out wipes the
                    // catalogue + selection so the next user doesn't
                    // see the previous account's data.
                    authStore.onSignIn = { [weak liegenschaftStore] in
                        await liegenschaftStore?.load()
                        // Ask for push permission + register the
                        // device token now that there's a backend
                        // session to attach it to. No-ops in demo.
                        await PushManager.shared.requestAuthorizationAndRegister()
                    }
                    authStore.onSignOut = { [weak liegenschaftStore] in
                        liegenschaftStore?.reset()
                        // Drop this device's token so a signed-out
                        // phone stops getting the previous user's
                        // pushes.
                        PushManager.shared.unregister()
                    }
                    // Notification taps route through the same
                    // DeepLinkRouter the widget + universal links
                    // use — PushManager converts the payload's
                    // whv.deep_link to a URL and calls this.
                    PushManager.shared.onDeepLink = { [weak deepLinkRouter] url in
                        deepLinkRouter?.handle(url)
                    }
                    // Any 401 from a downstream call (after one
                    // refresh attempt) bounces the user to the login
                    // screen — same path as a manual sign-out. We
                    // route through AuthStore so the cached user
                    // gets cleared too.
                    liegenschaftStore.onUnauthorized = { [weak authStore] in
                        authStore?.signOut()
                    }
                    // Already-signed-in launch: revalidate against
                    // /me first (catches a server-side revocation
                    // BEFORE the user starts tapping) and only then
                    // hydrate the catalogue. revalidate() will
                    // signOut() on a hard 401 — guard for that so we
                    // don't fire a redundant /me/properties call.
                    if authStore.signedIn {
                        await authStore.revalidate()
                    }
                    if authStore.signedIn, liegenschaftStore.available.isEmpty {
                        await liegenschaftStore.load()
                    }
                }
                // .system maps to nil → app follows the device.
                // .light/.dark force the override on every view in
                // the tree.
                .preferredColorScheme(settings.appearance.colorScheme)
                // Locale override only applies when language !=
                // System — otherwise SwiftUI uses Locale.current,
                // which respects device settings.
                .environment(
                    \.locale,
                    settings.language.locale ?? Locale.current
                )
                // Cross-fade transitions on the auth + Liegenschaft
                // gates so the user sees a smooth swap, not a hard
                // cut, when sign-in completes or "Liegenschaft
                // wechseln" fires.
                .animation(.easeInOut(duration: 0.25), value: authStore.signedIn)
                .animation(.easeInOut(duration: 0.25), value: liegenschaftStore.selected)
        }
    }

    @ViewBuilder
    private var rootView: some View {
        if !authStore.signedIn {
            LoginView()
        } else if liegenschaftStore.selected == nil {
            LiegenschaftPickerView()
        } else {
            RootTabView()
        }
    }
}
