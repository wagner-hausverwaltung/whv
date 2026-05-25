// Backend HTTP surface. Targets the same /auth/login endpoint the
// React portal uses, so a single set of credentials works across
// both clients.
//
// Scope is deliberately tiny for the scaffold: login + refresh +
// authenticated /me/* style GETs. Phase 2 expands this with PATCH/
// POST/etc. for tickets, announcements, etc. — same shape.

import Foundation

// MARK: - Wire shapes (mirror backend Pydantic models)

struct UserResponse: Codable, Hashable {
    let id: String
    let email: String
    let role: String  // "verwalter" | "eigentuemer" | "mieter" | "beirat" | "dienstleister"
    let organization_id: String
    let contact_id_impower: Int?
    let avatar_url: String?
}

struct TokenResponse: Codable {
    let access_token: String
    let refresh_token: String
    let expires_in: Int
    let user: UserResponse
}

struct LoginRequest: Codable {
    let email: String
    let password: String
}

/// Body for POST /auth/invite/redeem — same shape the React portal
/// sends (see web/src/pages/InviteRedeemPage.tsx), so the same
/// backend handler can serve both clients.
struct InviteRedeemRequest: Codable {
    let code: String
    let email: String
    let password: String
}

// MARK: - Errors

enum APIError: Error, LocalizedError {
    case invalidURL
    case network(Error)
    case http(status: Int, detail: String?)
    case decoding(Error)
    case unauthorized

    var errorDescription: String? {
        switch self {
        case .invalidURL:
            return "Ungültige URL"
        case .network(let err):
            return "Netzwerkfehler: \(err.localizedDescription)"
        case .http(let status, let detail):
            if let detail = detail, !detail.isEmpty {
                return detail
            }
            return "Server antwortete mit Status \(status)."
        case .decoding:
            return "Antwort konnte nicht ausgewertet werden."
        case .unauthorized:
            return "E-Mail oder Passwort ungültig."
        }
    }
}

// MARK: - Client

/// Async URLSession-based client for the WHV backend.
///
/// `baseURL` defaults to staging — Phase 2 wires this to a build
/// config or Info.plist key so the same binary can target prod
/// without recompilation.
struct APIClient {
    static let stagingBaseURL = URL(string: "https://staging.api.wagner-hausverwaltung.com")!

    let baseURL: URL
    let session: URLSession

    init(baseURL: URL = APIClient.stagingBaseURL, session: URLSession = .shared) {
        self.baseURL = baseURL
        self.session = session
    }

    // MARK: Auth

    /// Exchange (email, password) for tokens. Email is lowercased
    /// + trimmed before the call, matching the portal's behaviour
    /// (the backend is case-insensitive on lookup but we want both
    /// clients writing the same canonical form for any logging /
    /// debug stations to compare cleanly).
    func login(email: String, password: String) async throws -> TokenResponse {
        let body = LoginRequest(
            email: email.trimmingCharacters(in: .whitespacesAndNewlines).lowercased(),
            password: password
        )
        var request = URLRequest(url: baseURL.appending(path: "/auth/login"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.httpBody = try JSONEncoder().encode(body)

        let (data, response) = try await performWithMapping(request)

        if let http = response as? HTTPURLResponse, http.statusCode == 401 {
            throw APIError.unauthorized
        }
        try Self.throwIfNotOK(response: response, data: data)
        return try Self.decode(TokenResponse.self, from: data)
    }

    /// Redeem an invite code (POST /auth/invite/redeem). Returns the
    /// same TokenResponse as /auth/login — the backend creates the
    /// user, sets the password, and issues a fresh JWT pair in one
    /// step. No separate "activate account" follow-up needed.
    ///
    /// 400/409 from the backend bubble up as APIError.http with the
    /// FastAPI `detail` string so the registration screen can show
    /// "Einladung abgelaufen", "E-Mail-Adresse passt nicht", etc.
    /// verbatim — same UX the portal gets.
    func redeemInvite(
        code: String,
        email: String,
        password: String
    ) async throws -> TokenResponse {
        let body = InviteRedeemRequest(
            code: code.trimmingCharacters(in: .whitespacesAndNewlines),
            email: email.trimmingCharacters(in: .whitespacesAndNewlines).lowercased(),
            password: password
        )
        var request = URLRequest(url: baseURL.appending(path: "/auth/invite/redeem"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.httpBody = try JSONEncoder().encode(body)

        let (data, response) = try await performWithMapping(request)
        try Self.throwIfNotOK(response: response, data: data)
        return try Self.decode(TokenResponse.self, from: data)
    }

    // MARK: - Plumbing

    private func performWithMapping(_ request: URLRequest) async throws -> (Data, URLResponse) {
        do {
            return try await session.data(for: request)
        } catch {
            throw APIError.network(error)
        }
    }

    private static func throwIfNotOK(response: URLResponse, data: Data) throws {
        guard let http = response as? HTTPURLResponse else { return }
        guard !(200...299).contains(http.statusCode) else { return }
        // Backend uses FastAPI's `{detail: "..."}` for 4xx. Pull
        // the human-readable message out so the UI can surface it
        // verbatim — easier debugging than a numeric status code.
        var detail: String? = nil
        if let parsed = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            detail = parsed["detail"] as? String
        }
        throw APIError.http(status: http.statusCode, detail: detail)
    }

    private static func decode<T: Decodable>(_ type: T.Type, from data: Data) throws -> T {
        do {
            return try JSONDecoder().decode(type, from: data)
        } catch {
            throw APIError.decoding(error)
        }
    }
}
