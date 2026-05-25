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
            persist(tokens)
        } catch let error as APIError {
            self.lastError = error.errorDescription
        } catch {
            self.lastError = error.localizedDescription
        }
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
            persist(tokens)
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
    private func persist(_ tokens: TokenResponse) {
        try? keychain.write(tokens.access_token, for: accessTokenKey)
        try? keychain.write(tokens.refresh_token, for: refreshTokenKey)
        if let raw = try? JSONEncoder().encode(tokens.user) {
            defaults.set(raw, forKey: cachedUserKey)
        }
        self.user = tokens.user
    }

    /// Clears tokens + cached user; SwiftUI flips back to the
    /// LoginView via WHVApp's branch. Doesn't tell the backend to
    /// invalidate the refresh token — Phase 2 hits POST /auth/logout
    /// when the endpoint lands.
    func signOut() {
        keychain.delete(accessTokenKey)
        keychain.delete(refreshTokenKey)
        defaults.removeObject(forKey: cachedUserKey)
        user = nil
    }
}
