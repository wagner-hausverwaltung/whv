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
    @StateObject private var authStore = AuthStore()
    @StateObject private var liegenschaftStore = LiegenschaftStore()
    @StateObject private var settings = SettingsStore()
    @StateObject private var deepLinkRouter = DeepLinkRouter()
    @StateObject private var biometricLock = BiometricLockStore()
    @StateObject private var demoStore = DemoStore.shared
    @Environment(\.scenePhase) private var scenePhase

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
                    }
                    authStore.onSignOut = { [weak liegenschaftStore] in
                        liegenschaftStore?.reset()
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
