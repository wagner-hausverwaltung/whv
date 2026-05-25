// Persistent state for "which Liegenschaft is the user acting on
// right now". UserDefaults-backed — survives app restarts; a fresh
// install lands on the picker, a returning user lands on the last
// selection's main view.
//
// `available` hydrates from /me/properties after sign-in. Until
// `load()` runs (or if it fails), it stays at `[]` and the picker
// shows a loading / empty state.

import Foundation

@MainActor
final class LiegenschaftStore: ObservableObject {
    /// The active Liegenschaft, or nil if the user hasn't picked
    /// one yet (or just cleared it via "Liegenschaft wechseln").
    /// SwiftUI observes this — flipping to nil sends the user back
    /// to the picker via WHVApp's branch.
    @Published private(set) var selected: Liegenschaft?

    /// Catalogue the user can pick from. Populated by `load()` from
    /// /me/properties; starts empty so SwiftUI can show a loading
    /// state until the call completes.
    @Published private(set) var available: [Liegenschaft] = []
    @Published private(set) var isLoading = false
    @Published var lastError: String?

    /// Fired when the API surface returns 401 even after a token
    /// refresh attempt — the App routes this to AuthStore.signOut().
    /// Optional so unit tests + #Preview can ignore it.
    var onUnauthorized: (() -> Void)?

    private let storageKey = "WHV.selectedLiegenschaftId"
    private let defaults: UserDefaults
    private let api: APIClient

    init(
        api: APIClient = APIClient(),
        defaults: UserDefaults = .standard
    ) {
        self.api = api
        self.defaults = defaults
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

    /// Fetch the live catalogue from /me/properties. Idempotent: safe
    /// to call repeatedly (e.g. on sign-in + on Liegenschaft-picker
    /// appear). Restores the previously-selected Liegenschaft if it's
    /// still in the fetched list — otherwise clears the dangling
    /// pointer so the picker presents cleanly.
    func load() async {
        lastError = nil
        isLoading = true
        defer { isLoading = false }
        do {
            let rows = try await api.getMyProperties()
            let mapped = rows.map(Liegenschaft.init(from:))
            self.available = mapped
            if let savedId = defaults.string(forKey: storageKey),
               let match = mapped.first(where: { $0.id == savedId })
            {
                self.selected = match
            } else if self.selected != nil,
                      !mapped.contains(where: { $0.id == self.selected?.id })
            {
                self.selected = nil
                defaults.removeObject(forKey: storageKey)
            }
        } catch APIError.unauthorized {
            onUnauthorized?()
        } catch let error as APIError {
            self.lastError = error.errorDescription
        } catch {
            self.lastError = error.localizedDescription
        }
    }

    /// Drop loaded properties — used on sign-out so the next user
    /// doesn't briefly see the previous account's list.
    func reset() {
        available = []
        selected = nil
        defaults.removeObject(forKey: storageKey)
        lastError = nil
    }
}
