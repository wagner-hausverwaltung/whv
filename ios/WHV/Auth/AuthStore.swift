// Auth state for the iOS app. ObservableObject so SwiftUI views
// can react to sign-in / sign-out without manual notification
// wiring.
//
// Persistence layout:
//   Keychain: access_token, refresh_token   (secrets)
//   UserDefaults: cached UserResponse JSON  (non-secret display data)
//
// On launch we hydrate from Keychain — if a token is present, the
// user is considered signed in. Phase 2 will add a startup `GET
// /auth/me` to validate the token + refresh the cached User and
// kick the user back to login if the token has been revoked.

import Foundation

@MainActor
final class AuthStore: ObservableObject {
    @Published private(set) var user: UserResponse?
    @Published var isAuthenticating = false
    @Published var lastError: String?

    var signedIn: Bool { user != nil }

    /// Hooks the App wires up to refresh / wipe downstream stores
    /// (today: LiegenschaftStore) on auth transitions. Optional so
    /// the store can still be used in #Preview without ceremony.
    var onSignIn: (() async -> Void)?
    var onSignOut: (() -> Void)?

    private let api: APIClient
    private let keychain: Keychain
    private let defaults: UserDefaults

    private let accessTokenKey = "access_token"
    private let refreshTokenKey = "refresh_token"
    private let cachedUserKey = "WHV.cachedUser"

    init(
        api: APIClient = APIClient(),
        keychain: Keychain = Keychain(),
        defaults: UserDefaults = .standard
    ) {
        self.api = api
        self.keychain = keychain
        self.defaults = defaults

        // Hydrate from cache. If we have both a token AND a cached
        // user we can render the signed-in shell immediately; a
        // /auth/me round-trip can revalidate in the background once
        // that endpoint exists.
        if keychain.read(accessTokenKey) != nil,
           let raw = defaults.data(forKey: cachedUserKey),
           let cached = try? JSONDecoder().decode(UserResponse.self, from: raw)
        {
            self.user = cached
        }
    }

    func login(email: String, password: String) async {
        lastError = nil
        isAuthenticating = true
        defer { isAuthenticating = false }

        do {
            let tokens = try await api.login(email: email, password: password)
            await persist(tokens)
        } catch let error as APIError {
            // 422 on /auth/login = the address didn't validate (classic: "~"
            // instead of "-" from an autocorrecting keyboard). A status code
            // alone has cost support round-trips; say what to check.
            if case .http(let status, _) = error, status == 422 {
                self.lastError = "E-Mail-Adresse ungültig – bitte Schreibweise prüfen (z. B. Bindestrich statt „~“)."
            } else {
                self.lastError = error.errorDescription
            }
        } catch {
            self.lastError = error.localizedDescription
        }
    }

    /// Activates demo mode and flips `user` to the fake demo
    /// identity. No network call, no Keychain write — everything
    /// downstream consults DemoStore.shared via DemoFlag.isActive
    /// and short-circuits to seed data.
    func signInAsDemo() async {
        DemoStore.shared.activate()
        user = DemoStore.shared.demoUser
        // No token writes, no /me/properties fetch — every Store's
        // call into APIClient short-circuits.
        await onSignIn?()
    }

    /// Same code path as login — once the backend hands back a token
    /// pair, the user is signed in. The redemption screen can then
    /// dismiss; WHVApp's gate flips because `user` is now set.
    func redeemInvite(code: String, email: String, password: String) async {
        lastError = nil
        isAuthenticating = true
        defer { isAuthenticating = false }

        do {
            let tokens = try await api.redeemInvite(
                code: code,
                email: email,
                password: password
            )
            await persist(tokens)
        } catch let error as APIError {
            self.lastError = error.errorDescription
        } catch {
            self.lastError = error.localizedDescription
        }
    }

    /// Common write path used by both `login` and `redeemInvite` so
    /// the Keychain/UserDefaults wiring is defined once. Always called
    /// on the main actor (the class is @MainActor), so the @Published
    /// assignment is safe.
    private func persist(_ tokens: TokenResponse) async {
        try? keychain.write(tokens.access_token, for: accessTokenKey)
        try? keychain.write(tokens.refresh_token, for: refreshTokenKey)
        if let raw = try? JSONEncoder().encode(tokens.user) {
            defaults.set(raw, forKey: cachedUserKey)
        }
        self.user = tokens.user
        // Refresh downstream stores (Liegenschaften) before the App
        // root flips to the picker, so the user sees real data on
        // first render rather than a flash of empty.
        await onSignIn?()
    }

    /// Clears tokens + cached user; SwiftUI flips back to the
    /// LoginView via WHVApp's branch. Doesn't tell the backend to
    /// invalidate the refresh token — Phase 2 hits POST /auth/logout
    /// when the endpoint lands.
    func signOut() {
        // Demo mode shuts down cleanly without touching Keychain
        // (it never wrote there). Live mode wipes both the auth
        // tokens and the cached user envelope.
        if DemoStore.shared.isActive {
            DemoStore.shared.deactivate()
        } else {
            keychain.delete(accessTokenKey)
            keychain.delete(refreshTokenKey)
            defaults.removeObject(forKey: cachedUserKey)
        }
        user = nil
        ActivitySync.clear()
        Task { await LiveActivityManager.endAll() }
        onSignOut?()
    }

    /// Cold-start credential check. Hits /me with the cached token;
    /// if the server has revoked the session (or both tokens have
    /// expired past the refresh window) the APIClient throws
    /// `.unauthorized` even after one refresh attempt — that's our
    /// signal to drop the cached user and bounce to LoginView.
    /// Successful round-trip silently refreshes the cached user envelope
    /// so role/email updates land without a re-login.
    func revalidate() async {
        guard signedIn else { return }
        do {
            let fresh = try await api.getMe()
            self.user = fresh
            if let raw = try? JSONEncoder().encode(fresh) {
                defaults.set(raw, forKey: cachedUserKey)
            }
        } catch APIError.unauthorized {
            // Both tokens unusable. Wipe and bounce.
            signOut()
        } catch {
            // Network blip — leave the cached user in place so the
            // user can still scroll around the app, downstream calls
            // will surface their own errors.
        }
    }
}
