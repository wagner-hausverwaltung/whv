// WHV iOS — Phase 2 starter scaffold.
//
// Single SwiftUI entry point. TabView holds the eventual full set of
// screens documented in REQUIREMENTS.md §8.3; in v1 only Fachinfos is
// wired up (RSS feed from vermieter1x1.de). The others render
// placeholders so the tab bar shape matches the final app and the
// user can preview structure in the Simulator while Phase 2 fills
// in auth, properties, tickets, etc.

import SwiftUI

@main
struct WHVApp: App {
    var body: some Scene {
        WindowGroup {
            RootTabView()
        }
    }
}
