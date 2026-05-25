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

/// Response from GET /auth/invite/{code} — lets the registration
/// screen pre-fill the email so the user doesn't have to retype an
/// address already in their inbox. Returning a different email than
/// the invite is the most common cause of "Einladung ungültig" errors;
/// pre-filling eliminates the typo failure mode.
struct InviteInfoResponse: Codable {
    let email: String
    let role: String
    let organization_name: String
    let expires_at: String
}

/// Mirror of backend PropertyResponse. Only the fields the iOS UI
/// actually reads — leaving impower_id/state/etc. out keeps the
/// decoder forward-compatible.
struct PropertyResponse: Codable, Hashable {
    let id: String
    let property_hr_id: String?
    let name: String
    let type: String
    let city: String?
    let street: String?
    let number: String?
    let postal_code: String?
    let image_url: String?
}

/// POST body for /me/assemblies/{id}/comments. Mirrors
/// CreateAssemblyCommentRequest.
struct CreateAssemblyCommentBody: Codable {
    let body: String
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
    /// Pulls the current access token at request time (not init time)
    /// so a fresh sign-in is picked up by long-lived APIClient
    /// instances without rebuilding them. Returns nil when no user
    /// is signed in; authed endpoints surface that as `.unauthorized`.
    let tokenProvider: () -> String?

    init(
        baseURL: URL = APIClient.stagingBaseURL,
        session: URLSession = .shared,
        tokenProvider: @escaping () -> String? = APIClient.defaultTokenProvider
    ) {
        self.baseURL = baseURL
        self.session = session
        self.tokenProvider = tokenProvider
    }

    /// Default: read `access_token` out of the shared Keychain. Same
    /// key AuthStore writes to. Keeping this static so the type can
    /// be constructed without dependency injection — picks up the
    /// token at call time.
    static func defaultTokenProvider() -> String? {
        Keychain().read("access_token")
    }

    /// JSONDecoder used by every authenticated GET. Backend serialises
    /// timestamps as ISO8601 with timezone, sometimes with fractional
    /// seconds (Pydantic v2 includes microseconds). Fall through both
    /// formats so we don't fail to decode microsecond-bearing rows.
    static let jsonDecoder: JSONDecoder = {
        let decoder = JSONDecoder()
        let withFractional = ISO8601DateFormatter()
        withFractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let plain = ISO8601DateFormatter()
        plain.formatOptions = [.withInternetDateTime]
        decoder.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            let str = try container.decode(String.self)
            if let d = withFractional.date(from: str) { return d }
            if let d = plain.date(from: str) { return d }
            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "Invalid ISO8601 date: \(str)"
            )
        }
        return decoder
    }()

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

    /// Look up an invite by code so the registration screen can
    /// pre-fill the email field as read-only. 404 covers
    /// not-found / expired / consumed — the client just shows the
    /// same "invite no longer valid" error in all three cases.
    func fetchInviteInfo(code: String) async throws -> InviteInfoResponse {
        let trimmed = code.trimmingCharacters(in: .whitespacesAndNewlines)
        // Path-component encoding for safety with stray characters.
        var components = URLComponents(
            url: baseURL.appending(path: "/auth/invite/").appending(path: trimmed),
            resolvingAgainstBaseURL: false
        )
        // appending(path:) already percent-encodes; URLComponents wrap
        // is just for symmetry with other helpers. Build the URL
        // directly to avoid a nil-unwrap.
        components?.path = "/auth/invite/\(trimmed)"
        let url = components?.url(relativeTo: baseURL) ?? baseURL.appending(path: "/auth/invite/\(trimmed)")
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        let (data, response) = try await performWithMapping(request)
        try Self.throwIfNotOK(response: response, data: data)
        return try Self.decode(InviteInfoResponse.self, from: data)
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

    // MARK: - /me (authed)

    /// GET /me/properties — list properties visible to the signed-in
    /// user. Verwalter sees all org properties; owners see only
    /// properties they're a contact on.
    func getMyProperties() async throws -> [PropertyResponse] {
        try await authedGET("/me/properties")
    }

    // MARK: - ETV (authed)

    /// GET /me/properties/{id}/assemblies — list-shape assemblies for
    /// one property. Filters out ABGESAGT server-side.
    func listMyAssemblies(propertyId: String) async throws -> [AssemblySummary] {
        try await authedGET("/me/properties/\(propertyId)/assemblies")
    }

    /// GET /me/assemblies/{id} — full detail with agenda items +
    /// discussion. Comments are a separate endpoint.
    func getAssemblyDetail(id: String) async throws -> Assembly {
        try await authedGET("/me/assemblies/\(id)")
    }

    /// GET /me/assemblies/{id}/comments — ordered chronologically.
    func listAssemblyComments(assemblyId: String) async throws -> [AssemblyComment] {
        try await authedGET("/me/assemblies/\(assemblyId)/comments")
    }

    /// POST /me/assemblies/{id}/comments — append a new Q&A entry.
    /// Server fans out an email to every Verwalter + prior commenter.
    func postAssemblyComment(
        assemblyId: String,
        body: String
    ) async throws -> AssemblyComment {
        try await authedJSON(
            "/me/assemblies/\(assemblyId)/comments",
            method: "POST",
            body: CreateAssemblyCommentBody(body: body)
        )
    }

    // MARK: - Plumbing

    /// Generic authed JSON GET. The path is relative to baseURL and
    /// must already be URL-encoded. Returns a decoded T or throws an
    /// APIError that the caller surfaces to the UI verbatim.
    private func authedGET<T: Decodable>(_ path: String) async throws -> T {
        guard let token = tokenProvider() else { throw APIError.unauthorized }
        var request = URLRequest(url: baseURL.appending(path: path))
        request.httpMethod = "GET"
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        let (data, response) = try await performWithMapping(request)
        try Self.throwIfNotOK(response: response, data: data)
        return try Self.decodeAuthed(T.self, from: data)
    }

    /// Generic authed JSON POST/PATCH with a Codable body.
    private func authedJSON<T: Decodable, B: Encodable>(
        _ path: String,
        method: String,
        body: B
    ) async throws -> T {
        guard let token = tokenProvider() else { throw APIError.unauthorized }
        var request = URLRequest(url: baseURL.appending(path: path))
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.httpBody = try JSONEncoder().encode(body)
        let (data, response) = try await performWithMapping(request)
        try Self.throwIfNotOK(response: response, data: data)
        return try Self.decodeAuthed(T.self, from: data)
    }

    /// Same as `decode` but routes through the ISO8601-aware decoder
    /// so datetime fields round-trip correctly. Login/refresh don't
    /// need it — their bodies are plain strings + ints.
    private static func decodeAuthed<T: Decodable>(_ type: T.Type, from data: Data) throws -> T {
        do {
            return try Self.jsonDecoder.decode(type, from: data)
        } catch {
            throw APIError.decoding(error)
        }
    }

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
        // 401 collapses to a single error case so the UI can react
        // generically (sign-out + bounce to LoginView). 403 stays a
        // generic .http for now — same screens shouldn't usually
        // see one once auth is correct.
        if http.statusCode == 401 {
            throw APIError.unauthorized
        }
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
