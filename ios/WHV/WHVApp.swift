// WHV iOS — Phase 2 starter scaffold.
//
// Two screens at the root level: the LiegenschaftPickerView (when
// no Liegenschaft is selected yet) and the main RootTabView (once
// the user has picked one). Selection persists in UserDefaults via
// LiegenschaftStore, so a returning user lands straight on the
// main view; "Liegenschaft wechseln" in Einstellungen clears the
// selection and sends the user back to the picker.
//
// The store is created at the App level so a single instance
// serves both the picker and the tabs — switching contexts mid-
// session is a one-line state mutation, no view-tree gymnastics.

import SwiftUI

@main
struct WHVApp: App {
    @StateObject private var liegenschaftStore = LiegenschaftStore()

    var body: some Scene {
        WindowGroup {
            Group {
                if liegenschaftStore.selected != nil {
                    RootTabView()
                } else {
                    LiegenschaftPickerView()
                }
            }
            .environmentObject(liegenschaftStore)
            // Cross-fade between picker and main view on selection
            // change — feels less abrupt than the default opacity
            // swap, especially on Liegenschaft wechseln (where the
            // user is consciously triggering the transition).
            .animation(.easeInOut(duration: 0.25), value: liegenschaftStore.selected)
        }
    }
}
