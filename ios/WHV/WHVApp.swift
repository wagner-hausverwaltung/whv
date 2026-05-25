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

    var body: some Scene {
        WindowGroup {
            rootView
                .environmentObject(authStore)
                .environmentObject(liegenschaftStore)
                .environmentObject(settings)
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
                    // Already-signed-in launch: hydrate the catalogue
                    // so the picker isn't blank on cold start.
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
