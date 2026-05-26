// Builds a unified snapshot of "what's actionable right now" for
// the home/lock-screen widget. Five data sources collapse into one
// JSON blob in App Group UserDefaults; the widget process picks
// the top-priority item (or top 2 for the medium family) and
// renders the appropriate template.
//
// Lives entirely in the host app — the widget never talks to the
// network or to the Keychain. App Group UserDefaults is the only
// bridge.
//
// Refresh trigger: WidgetSync.refresh runs after every successful
// AssemblyListStore.load and after sign-out (the latter clears
// everything). The 30-min fallback timeline in the widget covers
// stretches where the user doesn't open the app.

import Foundation
import WidgetKit

/// Single payload pushed to the widget. Optionals collapse to nil
/// when the corresponding source has nothing relevant — the widget
/// uses presence + freshness to decide what to render.
struct WidgetSnapshot: Codable {
    let updatedAt: Date
    let inProgressEtv: WidgetUpcomingEtvPayload?
    let upcomingEtv: WidgetUpcomingEtvPayload?
    let latestEtvComment: WidgetCommentPayload?
    let openTicketCount: Int
    let newestOpenTicket: WidgetTicketPayload?
    let latestAnnouncement: WidgetAnnouncementPayload?
}

struct WidgetUpcomingEtvPayload: Codable {
    let assemblyId: String
    let title: String
    let propertyName: String?
    let scheduledStart: Date
    let scheduledEnd: Date
    let location: String
    let teamsMeetingUrl: String?
    let status: String
}

struct WidgetCommentPayload: Codable {
    let assemblyId: String
    let assemblyTitle: String
    let authorLabel: String
    let authorRole: String
    let body: String
    let createdAt: Date
}

struct WidgetTicketPayload: Codable {
    let id: String
    let subject: String
    let category: String
    let lastMessageAt: Date
    let propertyName: String?
}

struct WidgetAnnouncementPayload: Codable {
    let id: String
    let title: String
    let body: String
    let publishedAt: Date
    let propertyName: String?
}

enum WidgetSync {
    static let appGroup = "group.com.wagner-hausverwaltung.WHV"
    static let snapshotKey = "WHV.widget.snapshot"
    /// "Upcoming" cutoff for surfacing an ETV. Matches §8.9 — anything
    /// further out isn't actionable enough for a glance widget.
    static let etvLookaheadDays: TimeInterval = 14
    /// How fresh comments / announcements / ticket activity have to
    /// be to qualify for the widget. Anything older falls off the
    /// "what's actionable right now" surface.
    static let freshnessSeconds: TimeInterval = 48 * 3600

    /// Fans out the additional fetches in parallel, builds the
    /// snapshot, writes it, and asks WidgetKit to reload. Best-
    /// effort throughout — a single failing fetch leaves its slot
    /// nil rather than aborting the whole refresh.
    static func refresh(
        api: APIClient,
        propertyId: String?,
        assemblies: [AssemblySummary]
    ) async {
        let now = Date()
        let (inProgress, upcoming) = pickEtv(from: assemblies, now: now)

        async let ticketsResult: [TicketSummary] = (try? await api.listMyOpenTickets()) ?? []
        async let announcementsResult: [AnnouncementSummary] = await fetchAnnouncements(
            api: api,
            propertyId: propertyId
        )
        // Latest comment is fetched against the assembly we're about
        // to surface (in-progress wins; otherwise upcoming). If
        // neither, skip — comments only matter in context of an ETV
        // that's already on the widget.
        let commentTargetId = inProgress?.assemblyId ?? upcoming?.assemblyId
        let commentTargetTitle = inProgress?.title ?? upcoming?.title
        async let commentResult: AssemblyComment? = fetchLatestComment(
            api: api,
            assemblyId: commentTargetId,
            now: now
        )

        let tickets = await ticketsResult
        let announcements = await announcementsResult
        let comment = await commentResult

        let newestTicket = tickets
            .sorted { $0.last_message_at > $1.last_message_at }
            .first { now.timeIntervalSince($0.last_message_at) <= freshnessSeconds }
        let newestAnnouncement = announcements
            .compactMap { a -> (AnnouncementSummary, Date)? in
                guard let sent = a.notification_sent_at, sent <= now else { return nil }
                return (a, sent)
            }
            .sorted { $0.1 > $1.1 }
            .first { now.timeIntervalSince($0.1) <= freshnessSeconds }

        let snapshot = WidgetSnapshot(
            updatedAt: now,
            inProgressEtv: inProgress,
            upcomingEtv: upcoming,
            latestEtvComment: comment.flatMap { c in
                guard let title = commentTargetTitle, let aid = commentTargetId else { return nil }
                return WidgetCommentPayload(
                    assemblyId: aid,
                    assemblyTitle: title,
                    authorLabel: c.author_label,
                    authorRole: c.author_role.rawValue,
                    body: String(c.body.prefix(140)),
                    createdAt: c.created_at
                )
            },
            openTicketCount: tickets.count,
            newestOpenTicket: newestTicket.map { t in
                WidgetTicketPayload(
                    id: t.id,
                    subject: t.subject,
                    category: t.category.labelString,
                    lastMessageAt: t.last_message_at,
                    propertyName: t.property_name
                )
            },
            latestAnnouncement: newestAnnouncement.map { (a, sent) in
                WidgetAnnouncementPayload(
                    id: a.id,
                    title: a.title,
                    body: String(a.body.prefix(180)),
                    publishedAt: sent,
                    propertyName: a.property_name
                )
            }
        )

        write(snapshot)
        WidgetCenter.shared.reloadAllTimelines()
    }

    /// Sign-out path — wipe the slot so the next user doesn't briefly
    /// see the previous account's data on their Home Screen.
    static func clear() {
        guard let defaults = UserDefaults(suiteName: appGroup) else { return }
        defaults.removeObject(forKey: snapshotKey)
        WidgetCenter.shared.reloadAllTimelines()
    }

    // MARK: - Internals

    private static func write(_ snapshot: WidgetSnapshot) {
        guard let defaults = UserDefaults(suiteName: appGroup) else { return }
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        if let data = try? encoder.encode(snapshot) {
            defaults.set(data, forKey: snapshotKey)
        }
    }

    private static func pickEtv(
        from list: [AssemblySummary],
        now: Date
    ) -> (inProgress: WidgetUpcomingEtvPayload?, upcoming: WidgetUpcomingEtvPayload?) {
        let inProgressSummary = list
            .filter { $0.scheduled_start <= now && now <= $0.scheduled_end }
            .sorted { $0.scheduled_start < $1.scheduled_start }
            .first
        let horizon = now.addingTimeInterval(etvLookaheadDays * 86_400)
        let upcomingSummary = list
            .filter { $0.status.isUpcoming }
            .filter { $0.scheduled_start > now && $0.scheduled_start <= horizon }
            .sorted { $0.scheduled_start < $1.scheduled_start }
            .first
        return (
            inProgressSummary.map(payload(from:)),
            upcomingSummary.map(payload(from:))
        )
    }

    private static func payload(from s: AssemblySummary) -> WidgetUpcomingEtvPayload {
        WidgetUpcomingEtvPayload(
            assemblyId: s.id,
            title: s.title,
            propertyName: s.property_name,
            scheduledStart: s.scheduled_start,
            scheduledEnd: s.scheduled_end,
            location: s.location,
            teamsMeetingUrl: s.teams_meeting_url,
            status: s.status.rawValue
        )
    }

    private static func fetchAnnouncements(
        api: APIClient,
        propertyId: String?
    ) async -> [AnnouncementSummary] {
        guard let propertyId else { return [] }
        return (try? await api.listMyAnnouncementsForProperty(propertyId)) ?? []
    }

    private static func fetchLatestComment(
        api: APIClient,
        assemblyId: String?,
        now: Date
    ) async -> AssemblyComment? {
        guard let assemblyId else { return nil }
        let comments = (try? await api.listAssemblyComments(assemblyId: assemblyId)) ?? []
        return comments
            .sorted { $0.created_at > $1.created_at }
            .first { now.timeIntervalSince($0.created_at) <= freshnessSeconds }
    }
}
