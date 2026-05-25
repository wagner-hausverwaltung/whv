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

/// Minimal Ticket summary — only the fields the widget feeder
/// reads. The full Mitteilungen / Tickets screens get their own
/// richer types once those tabs land.
/// Wire shape for /me/tickets list rows. Status / category use the
/// real Swift enums so consumers don't deal with stringly-typed
/// values. Unknown status decodes to .neu defensively; unknown
/// category to .sonstigesOther (forward-compat with future server
/// additions). Both decoders surface on this list endpoint.
struct TicketSummary: Codable, Hashable, Identifiable {
    let id: String
    let property_id: String?
    let subject: String
    let status: TicketStatus
    let category: TicketCategory
    let last_message_at: Date
    let created_at: Date
    let closed_at: Date?
    let property_name: String?
    let property_address: String?
    let creator_email: String?

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        property_id = try c.decodeIfPresent(String.self, forKey: .property_id)
        subject = try c.decode(String.self, forKey: .subject)
        // Tolerate unknown status — backend may add NEU/OFFEN-style
        // values we don't know yet.
        if let raw = try? c.decode(String.self, forKey: .status),
           let s = TicketStatus(rawValue: raw) {
            status = s
        } else {
            status = .neu
        }
        if let raw = try? c.decode(String.self, forKey: .category),
           let cat = TicketCategory(rawValue: raw) {
            category = cat
        } else {
            category = .sonstigesOther
        }
        last_message_at = try c.decode(Date.self, forKey: .last_message_at)
        created_at = try c.decode(Date.self, forKey: .created_at)
        closed_at = try c.decodeIfPresent(Date.self, forKey: .closed_at)
        property_name = try c.decodeIfPresent(String.self, forKey: .property_name)
        property_address = try c.decodeIfPresent(String.self, forKey: .property_address)
        creator_email = try c.decodeIfPresent(String.self, forKey: .creator_email)
    }

    enum CodingKeys: String, CodingKey {
        case id, property_id, subject, status, category
        case last_message_at, created_at, closed_at
        case property_name, property_address, creator_email
    }
}

struct AnnouncementSummary: Codable, Hashable, Identifiable {
    let id: String
    let property_id: String
    let title: String
    let body: String
    let scheduled_publish_at: Date
    let notification_sent_at: Date?
    let property_name: String?
}

/// POST body for /me/announcements/{id}/comments. Mirrors backend's
/// AnnouncementCommentCreateRequest.
struct CreateAnnouncementCommentBody: Codable {
    let body: String
}

/// POST body for /me/tickets. Mirrors backend's TicketCreateRequest.
struct CreateTicketBody: Codable {
    let subject: String
    let body: String
    let category: String
    let property_id: String?
    let share_scope: String
}

/// POST body for /me/tickets/{id}/messages. Only the body field is
/// surfaced today — owners can't post internal notes (the server
/// silently coerces is_internal_note to false on /me/*).
struct CreateTicketMessageBody: Codable {
    let body: String
}

/// POST body for /auth/refresh. Single field — the backend swaps it
/// for a new access+refresh pair plus the user envelope.
struct RefreshRequest: Codable {
    let refresh_token: String
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
    /// Reads the refresh token (same lifetime as the access token,
    /// also in Keychain). Used by the 401 retry path to swap an
    /// expired access token for a fresh one before bouncing the user
    /// to LoginView.
    let refreshTokenProvider: () -> String?
    /// Called when /auth/refresh returns a new token pair so the
    /// AuthStore-backed Keychain entries stay in lockstep with what
    /// the client is using on retried requests.
    let onTokenRefreshed: ((TokenResponse) -> Void)?

    init(
        baseURL: URL = APIClient.stagingBaseURL,
        session: URLSession = .shared,
        tokenProvider: @escaping () -> String? = APIClient.defaultTokenProvider,
        refreshTokenProvider: @escaping () -> String? = APIClient.defaultRefreshTokenProvider,
        onTokenRefreshed: ((TokenResponse) -> Void)? = APIClient.defaultOnTokenRefreshed
    ) {
        self.baseURL = baseURL
        self.session = session
        self.tokenProvider = tokenProvider
        self.refreshTokenProvider = refreshTokenProvider
        self.onTokenRefreshed = onTokenRefreshed
    }

    /// Default: read `access_token` out of the shared Keychain. Same
    /// key AuthStore writes to. Keeping this static so the type can
    /// be constructed without dependency injection — picks up the
    /// token at call time.
    static func defaultTokenProvider() -> String? {
        Keychain().read("access_token")
    }

    static func defaultRefreshTokenProvider() -> String? {
        Keychain().read("refresh_token")
    }

    /// Default: persist the refreshed pair to Keychain so every
    /// subsequent request (across stores, across APIClient instances)
    /// picks up the new access token without a second refresh.
    /// AuthStore wraps this to also update its @Published `user`.
    static func defaultOnTokenRefreshed(_ tokens: TokenResponse) {
        let kc = Keychain()
        try? kc.write(tokens.access_token, for: "access_token")
        try? kc.write(tokens.refresh_token, for: "refresh_token")
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

    /// Trade a refresh token for a fresh access+refresh pair. Called
    /// by the 401 retry path, AND by AuthStore on cold start when it
    /// wants to revalidate stale credentials before the user starts
    /// tapping. 401 here means "refresh token has been revoked or
    /// is too old" — the caller should sign out.
    func refresh(refreshToken: String) async throws -> TokenResponse {
        var request = URLRequest(url: baseURL.appending(path: "/auth/refresh"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.httpBody = try JSONEncoder().encode(RefreshRequest(refresh_token: refreshToken))
        let (data, response) = try await performWithMapping(request)
        if let http = response as? HTTPURLResponse, http.statusCode == 401 {
            throw APIError.unauthorized
        }
        try Self.throwIfNotOK(response: response, data: data)
        return try Self.decode(TokenResponse.self, from: data)
    }

    // MARK: - /me (authed)

    /// GET /me — the current user envelope. AuthStore hits this on
    /// cold start to detect a server-revoked session.
    func getMe() async throws -> UserResponse {
        try await authedGET("/me")
    }

    /// GET /me/properties — list properties visible to the signed-in
    /// user. Verwalter sees all org properties; owners see only
    /// properties they're a contact on.
    func getMyProperties() async throws -> [PropertyResponse] {
        try await authedGET("/me/properties")
    }

    /// GET /me/assemblies/{id}/protocol → local file URL. Streams the
    /// PDF into the caller's temporary directory under a stable name
    /// (one file per assembly) so re-opens hit the same path. The
    /// returned URL is suitable for QLPreviewController.
    func downloadAssemblyProtocol(id: String) async throws -> URL {
        try await authedDownload(
            "/me/assemblies/\(id)/protocol",
            saveAs: "protokoll-\(id).pdf"
        )
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

    // MARK: - Tickets

    /// GET /me/tickets — every ticket the caller can see. Sorted
    /// newest-active first by the server.
    func listMyTickets() async throws -> [TicketSummary] {
        try await authedGET("/me/tickets")
    }

    /// GET /me/tickets?status=OFFEN — used by the dynamic widget to
    /// surface "X open tickets" + the newest one. Stays separate
    /// from listMyTickets so the widget snapshot is cheap.
    func listMyOpenTickets() async throws -> [TicketSummary] {
        try await authedGET("/me/tickets?status=OFFEN")
    }

    /// GET /me/tickets/{id} — full thread + participants.
    func getMyTicket(id: String) async throws -> TicketDetail {
        try await authedGET("/me/tickets/\(id)")
    }

    /// POST /me/tickets — open a new ticket. `propertyId` is optional;
    /// `share_scope` defaults to PRIVATE matching the backend.
    func createMyTicket(
        subject: String,
        body: String,
        category: TicketCategory,
        propertyId: String?
    ) async throws -> TicketDetail {
        try await authedJSON(
            "/me/tickets",
            method: "POST",
            body: CreateTicketBody(
                subject: subject,
                body: body,
                category: category.rawValue,
                property_id: propertyId,
                share_scope: "PRIVATE"
            )
        )
    }

    /// POST /me/tickets/{id}/messages — append a reply to the thread.
    func postMyTicketMessage(
        ticketId: String,
        body: String
    ) async throws -> TicketMessage {
        try await authedJSON(
            "/me/tickets/\(ticketId)/messages",
            method: "POST",
            body: CreateTicketMessageBody(body: body)
        )
    }

    /// GET /me/tickets/{id}/attachments/{aid}/file → local file URL
    /// suitable for QuickLook. Same authed-binary pattern as
    /// announcement attachments + protocol PDFs.
    func downloadTicketAttachment(
        ticketId: String,
        attachmentId: String,
        filename: String
    ) async throws -> URL {
        let safe = filename
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "\\", with: "_")
            .replacingOccurrences(of: "..", with: "_")
        return try await authedDownload(
            "/me/tickets/\(ticketId)/attachments/\(attachmentId)/file",
            saveAs: "ticket-att-\(attachmentId)-\(safe)"
        )
    }

    /// GET /me/properties/{id}/announcements — used by the dynamic
    /// widget to surface the newest published announcement.
    func listMyAnnouncementsForProperty(_ propertyId: String) async throws -> [AnnouncementSummary] {
        try await authedGET("/me/properties/\(propertyId)/announcements")
    }

    /// GET /me/announcements/{id} — full detail with attachments +
    /// comments embedded.
    func getAnnouncementDetail(id: String) async throws -> AnnouncementDetail {
        try await authedGET("/me/announcements/\(id)")
    }

    /// POST /me/announcements/{id}/comments — append a comment.
    /// Server fans out an email notification to Verwalter + thread.
    func postAnnouncementComment(
        announcementId: String,
        body: String
    ) async throws -> AnnouncementComment {
        try await authedJSON(
            "/me/announcements/\(announcementId)/comments",
            method: "POST",
            body: CreateAnnouncementCommentBody(body: body)
        )
    }

    /// GET /me/announcements/{id}/attachments/{aid}/download → local
    /// file URL. Same auth-gated streaming path as the protocol PDF.
    func downloadAnnouncementAttachment(
        announcementId: String,
        attachmentId: String,
        filename: String
    ) async throws -> URL {
        // Slug the filename so a "/" or weird character in the
        // server-provided name doesn't escape the tmp directory.
        let safe = filename
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "\\", with: "_")
            .replacingOccurrences(of: "..", with: "_")
        let target = "att-\(attachmentId)-\(safe)"
        return try await authedDownload(
            "/me/announcements/\(announcementId)/attachments/\(attachmentId)/download",
            saveAs: target
        )
    }

    // MARK: - Plumbing

    /// Generic authed JSON GET. The path is relative to baseURL and
    /// must already be URL-encoded. Returns a decoded T or throws an
    /// APIError that the caller surfaces to the UI verbatim.
    ///
    /// One-shot 401 retry: if the access token has expired but the
    /// refresh token is still valid, /auth/refresh trades it for a
    /// new pair and we replay the original request. A second 401
    /// (or a refresh-side 401) bubbles up as `.unauthorized` so the
    /// app can sign out.
    private func authedGET<T: Decodable>(_ path: String) async throws -> T {
        guard let token = tokenProvider() else { throw APIError.unauthorized }
        let url = baseURL.appending(path: path)
        do {
            let (data, response) = try await sendAuthed(url: url, method: "GET", body: nil, token: token)
            try Self.throwIfNotOK(response: response, data: data)
            return try Self.decodeAuthed(T.self, from: data)
        } catch APIError.unauthorized {
            let fresh = try await refreshOrThrow()
            let (data, response) = try await sendAuthed(url: url, method: "GET", body: nil, token: fresh)
            try Self.throwIfNotOK(response: response, data: data)
            return try Self.decodeAuthed(T.self, from: data)
        }
    }

    /// Generic authed JSON POST/PATCH with a Codable body. Same
    /// one-shot 401 retry semantics as `authedGET`.
    private func authedJSON<T: Decodable, B: Encodable>(
        _ path: String,
        method: String,
        body: B
    ) async throws -> T {
        guard let token = tokenProvider() else { throw APIError.unauthorized }
        let url = baseURL.appending(path: path)
        let encoded = try JSONEncoder().encode(body)
        do {
            let (data, response) = try await sendAuthed(url: url, method: method, body: encoded, token: token)
            try Self.throwIfNotOK(response: response, data: data)
            return try Self.decodeAuthed(T.self, from: data)
        } catch APIError.unauthorized {
            let fresh = try await refreshOrThrow()
            let (data, response) = try await sendAuthed(url: url, method: method, body: encoded, token: fresh)
            try Self.throwIfNotOK(response: response, data: data)
            return try Self.decodeAuthed(T.self, from: data)
        }
    }

    /// Authenticated binary download. Writes the body to
    /// `tmp/{saveAs}` and returns the URL. Same 401-refresh-retry
    /// path as the JSON helpers — QuickLook surfaces the file the
    /// user finally sees.
    private func authedDownload(_ path: String, saveAs filename: String) async throws -> URL {
        guard let token = tokenProvider() else { throw APIError.unauthorized }
        let url = baseURL.appending(path: path)
        let result: (Data, URLResponse)
        do {
            let r = try await sendAuthed(url: url, method: "GET", body: nil, token: token)
            try Self.throwIfNotOK(response: r.1, data: r.0)
            result = r
        } catch APIError.unauthorized {
            let fresh = try await refreshOrThrow()
            let r = try await sendAuthed(url: url, method: "GET", body: nil, token: fresh)
            try Self.throwIfNotOK(response: r.1, data: r.0)
            result = r
        }
        let dest = FileManager.default.temporaryDirectory.appendingPathComponent(filename)
        // Replace any older copy — same assembly id reuses the path,
        // and a stale file is worse than re-downloading.
        try? FileManager.default.removeItem(at: dest)
        try result.0.write(to: dest)
        return dest
    }

    /// Send a single authed request. Returns body+response or throws
    /// `.unauthorized` immediately on 401 (so the caller can decide
    /// whether to refresh). Other non-2xx statuses leave the
    /// status-code check to the caller (so download paths can
    /// reuse this helper without double-throwing).
    private func sendAuthed(
        url: URL,
        method: String,
        body: Data?,
        token: String
    ) async throws -> (Data, URLResponse) {
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        if let body {
            request.httpBody = body
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        let (data, response) = try await performWithMapping(request)
        if let http = response as? HTTPURLResponse, http.statusCode == 401 {
            throw APIError.unauthorized
        }
        return (data, response)
    }

    /// Pull the refresh token, hit /auth/refresh, persist the new
    /// pair via `onTokenRefreshed`, and hand back the new access
    /// token. Any failure bubbles up as `.unauthorized` so the
    /// caller can give up and sign out.
    private func refreshOrThrow() async throws -> String {
        guard let rt = refreshTokenProvider() else { throw APIError.unauthorized }
        let pair = try await refresh(refreshToken: rt)
        onTokenRefreshed?(pair)
        return pair.access_token
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
