// Persistent state for "which Liegenschaft is the user acting on
// right now". UserDefaults-backed — survives app restarts; a fresh
// install lands on the picker, a returning user lands on the last
// selection's main view.
//
// MainActor-bound so SwiftUI views can `@EnvironmentObject` it
// without worrying about thread hops.

import Foundation

@MainActor
final class LiegenschaftStore: ObservableObject {
    /// The active Liegenschaft, or nil if the user hasn't picked
    /// one yet (or just cleared it via "Liegenschaft wechseln").
    /// SwiftUI observes this — flipping to nil sends the user back
    /// to the picker via WHVApp's branch.
    @Published private(set) var selected: Liegenschaft?

    /// Catalogue the user can pick from. Demo today; in Phase 2
    /// this comes from `/me/properties` (an env-injected service).
    let available: [Liegenschaft]

    private let storageKey = "WHV.selectedLiegenschaftId"
    private let defaults: UserDefaults

    init(
        available: [Liegenschaft] = Liegenschaft.demo,
        defaults: UserDefaults = .standard
    ) {
        self.available = available
        self.defaults = defaults
        if let savedId = defaults.string(forKey: storageKey),
           let match = available.first(where: { $0.id == savedId })
        {
            // Persisted ID resolves to a still-present row — restore
            // the selection so the user lands on the main view.
            self.selected = match
        } else if let saved = defaults.string(forKey: storageKey) {
            // Persisted ID points at a Liegenschaft no longer in the
            // catalogue (deleted / unassigned). Clear the dangling
            // pointer so we re-prompt cleanly.
            _ = saved
            defaults.removeObject(forKey: storageKey)
        }
    }

    func select(_ l: Liegenschaft) {
        selected = l
        defaults.set(l.id, forKey: storageKey)
    }

    /// Drop the active selection. Triggers the WHVApp root to swap
    /// back to the picker. Doesn't delete any other state.
    func clear() {
        selected = nil
        defaults.removeObject(forKey: storageKey)
    }
}
