// Dynamic WHV home/lock-screen widget.
//
// Reads a unified snapshot from App Group UserDefaults (written by
// the host app's WidgetSync.refresh after every Versammlungen
// fetch) and picks the most relevant item to surface. Priority is
// fixed in `PriorityResolver` — the widget never re-orders past
// the resolver, so the user sees the same "most actionable" item
// consistently across home + lock-screen surfaces.
//
// Family handling:
//   small + accessoryRectangular + accessoryInline → top 1
//   medium → top 1 prominently, top 2 as a sub-row beneath
//
// The widget never talks to the network. Anything stale in the
// snapshot is the host app's problem; we just render what we read.

import SwiftUI
import WidgetKit

// MARK: - App Group bridge (mirrors host-side WidgetSync types)

struct WidgetSnapshot: Codable {
    let updatedAt: Date
    let inProgressEtv: WidgetEtvPayload?
    let upcomingEtv: WidgetEtvPayload?
    let latestEtvComment: WidgetCommentPayload?
    let openTicketCount: Int
    let newestOpenTicket: WidgetTicketPayload?
    let latestAnnouncement: WidgetAnnouncementPayload?
}

struct WidgetEtvPayload: Codable {
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

enum WidgetStorage {
    static let appGroup = "group.com.wagner-hausverwaltung.WHV"
    static let snapshotKey = "WHV.widget.snapshot"

    static func loadSnapshot() -> WidgetSnapshot? {
        guard let defaults = UserDefaults(suiteName: appGroup),
              let raw = defaults.data(forKey: snapshotKey)
        else { return nil }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return try? decoder.decode(WidgetSnapshot.self, from: raw)
    }
}

// MARK: - Priority

/// What the widget actually surfaces, top-N. Each case carries the
/// payload needed to render it.
enum WidgetItem {
    case etvInProgress(WidgetEtvPayload)
    case etvSoon(WidgetEtvPayload)         // within 5h
    case ticketFresh(WidgetTicketPayload, count: Int)  // ≥1 open, recent activity
    case ticketCountOnly(count: Int)       // open tickets but no recent activity
    case etvNewComment(WidgetCommentPayload)
    case announcementFresh(WidgetAnnouncementPayload)
    case etvUpcoming(WidgetEtvPayload)     // within 14 days but >5h out
    case quiet                              // nothing actionable
}

enum PriorityResolver {
    /// Up to N items, in priority order. `quiet` only appears alone.
    static func resolve(_ snapshot: WidgetSnapshot?, now: Date = Date(), limit: Int = 2) -> [WidgetItem] {
        guard let s = snapshot else { return [.quiet] }
        var out: [WidgetItem] = []

        if let etv = s.inProgressEtv {
            out.append(.etvInProgress(etv))
        }
        if out.count < limit, let etv = s.upcomingEtv,
           etv.scheduledStart <= now.addingTimeInterval(5 * 3600) {
            out.append(.etvSoon(etv))
        }
        if out.count < limit, let ticket = s.newestOpenTicket {
            out.append(.ticketFresh(ticket, count: s.openTicketCount))
        } else if out.count < limit, s.openTicketCount > 0 {
            out.append(.ticketCountOnly(count: s.openTicketCount))
        }
        if out.count < limit, let comment = s.latestEtvComment {
            out.append(.etvNewComment(comment))
        }
        if out.count < limit, let announcement = s.latestAnnouncement {
            out.append(.announcementFresh(announcement))
        }
        if out.count < limit, let etv = s.upcomingEtv,
           etv.scheduledStart > now.addingTimeInterval(5 * 3600) {
            out.append(.etvUpcoming(etv))
        }

        if out.isEmpty {
            return [.quiet]
        }
        return out
    }
}

// MARK: - Timeline

struct UpcomingEtvEntry: TimelineEntry {
    let date: Date
    let items: [WidgetItem]
}

struct UpcomingEtvProvider: TimelineProvider {
    func placeholder(in context: Context) -> UpcomingEtvEntry {
        UpcomingEtvEntry(date: Date(), items: [.etvSoon(.preview)])
    }

    func getSnapshot(in context: Context, completion: @escaping (UpcomingEtvEntry) -> Void) {
        let resolved = PriorityResolver.resolve(WidgetStorage.loadSnapshot())
        let final = resolved.isEmpty ? [.etvSoon(.preview)] : resolved
        completion(UpcomingEtvEntry(date: Date(), items: final))
    }

    func getTimeline(
        in context: Context,
        completion: @escaping (Timeline<UpcomingEtvEntry>) -> Void
    ) {
        let now = Date()
        let resolved = PriorityResolver.resolve(WidgetStorage.loadSnapshot(), now: now)
        // Two timeline points: now + 30-min refresh fallback. Real
        // refresh signal is the host app's reloadAllTimelines() on
        // every Versammlungen fetch.
        let next = now.addingTimeInterval(30 * 60)
        let timeline = Timeline(
            entries: [
                UpcomingEtvEntry(date: now, items: resolved),
                UpcomingEtvEntry(date: next, items: resolved),
            ],
            policy: .after(next)
        )
        completion(timeline)
    }
}

// MARK: - Widget

struct UpcomingEtvWidget: Widget {
    let kind = "UpcomingEtvWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: UpcomingEtvProvider()) { entry in
            WidgetView(entry: entry)
                .containerBackground(.fill.tertiary, for: .widget)
        }
        .configurationDisplayName("WHV — Übersicht")
        .description("Zeigt die wichtigsten WHV-Themen: kommende ETV, neue Mitteilungen, offene Tickets.")
        .supportedFamilies([
            .systemSmall,
            .systemMedium,
            .accessoryRectangular,
            .accessoryInline,
        ])
    }
}

// MARK: - Views

struct WidgetView: View {
    let entry: UpcomingEtvEntry
    @Environment(\.widgetFamily) private var family

    var body: some View {
        switch family {
        case .accessoryInline:
            InlineView(item: entry.items.first ?? .quiet)
        case .accessoryRectangular:
            RectangularView(item: entry.items.first ?? .quiet)
        case .systemMedium:
            MediumView(items: entry.items)
        default:
            SmallView(item: entry.items.first ?? .quiet)
        }
    }
}

// --- Lock Screen (inline) -------------------------------------------------

private struct InlineView: View {
    let item: WidgetItem

    var body: some View {
        switch item {
        case .etvInProgress(let etv):
            Text("ETV läuft: \(etv.title)")
        case .etvSoon(let etv):
            Text("ETV: \(formatRelative(etv.scheduledStart))")
        case .etvUpcoming(let etv):
            Text("ETV: \(formatRelative(etv.scheduledStart))")
        case .ticketFresh(_, let count), .ticketCountOnly(let count):
            Text("Tickets offen: \(count)")
        case .etvNewComment(let comment):
            Text("Neue Frage: \(comment.authorLabel)")
        case .announcementFresh(let announcement):
            Text("Mitteilung: \(announcement.title)")
        case .quiet:
            Text("WHV: alles ruhig")
        }
    }
}

// --- Lock Screen (rectangular) --------------------------------------------

private struct RectangularView: View {
    let item: WidgetItem

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(rectangularHeader(item))
                .font(.caption2.weight(.semibold))
                .widgetAccentable()
            Text(rectangularPrimary(item))
                .font(.caption.weight(.semibold))
                .lineLimit(2)
            if let sub = rectangularSecondary(item) {
                Text(sub)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
        }
    }

    private func rectangularHeader(_ item: WidgetItem) -> String {
        switch item {
        case .etvInProgress: return "ETV läuft"
        case .etvSoon: return "ETV bald"
        case .etvUpcoming: return "Nächste ETV"
        case .ticketFresh, .ticketCountOnly: return "Offene Tickets"
        case .etvNewComment: return "Neue Frage"
        case .announcementFresh: return "Mitteilung"
        case .quiet: return "WHV"
        }
    }

    private func rectangularPrimary(_ item: WidgetItem) -> String {
        switch item {
        case .etvInProgress(let etv), .etvSoon(let etv), .etvUpcoming(let etv):
            return etv.title
        case .ticketFresh(let t, _):
            return t.subject
        case .ticketCountOnly(let count):
            return "\(count) offen"
        case .etvNewComment(let c):
            return c.body
        case .announcementFresh(let a):
            return a.title
        case .quiet:
            return "Nichts Neues"
        }
    }

    private func rectangularSecondary(_ item: WidgetItem) -> String? {
        switch item {
        case .etvInProgress(let etv), .etvSoon(let etv), .etvUpcoming(let etv):
            return formatShort(etv.scheduledStart)
        case .ticketFresh(let t, let count):
            return "\(count) offen · \(formatRelative(t.lastMessageAt))"
        case .ticketCountOnly:
            return nil
        case .etvNewComment(let c):
            return c.authorLabel
        case .announcementFresh(let a):
            return formatRelative(a.publishedAt)
        case .quiet:
            return nil
        }
    }
}

// --- Home Screen (small) --------------------------------------------------

private struct SmallView: View {
    let item: WidgetItem

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 6) {
                Image(systemName: kindIcon(item))
                    .font(.caption.weight(.bold))
                    .foregroundStyle(kindColor(item))
                Text(kindLabel(item))
                    .font(.caption2.weight(.bold))
                    .foregroundStyle(.secondary)
                    .textCase(.uppercase)
                Spacer(minLength: 0)
            }
            Text(smallPrimary(item))
                .font(.subheadline.weight(.semibold))
                .lineLimit(2)
            if let prop = smallPropertyLine(item), !prop.isEmpty {
                Text(prop)
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
                    .lineLimit(1)
            }
            Spacer(minLength: 0)
            if let footer = smallFooter(item) {
                Text(footer)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
        }
    }

    private func smallPrimary(_ item: WidgetItem) -> String {
        switch item {
        case .etvInProgress(let etv), .etvSoon(let etv), .etvUpcoming(let etv):
            return etv.title
        case .ticketFresh(let t, _):
            return t.subject
        case .ticketCountOnly(let count):
            return "\(count) offene Tickets"
        case .etvNewComment(let c):
            return "Frage zur ETV: \(c.body)"
        case .announcementFresh(let a):
            return a.title
        case .quiet:
            return "Alles ruhig"
        }
    }

    private func smallPropertyLine(_ item: WidgetItem) -> String? {
        switch item {
        case .etvInProgress(let e), .etvSoon(let e), .etvUpcoming(let e):
            return e.propertyName
        case .ticketFresh(let t, _):
            return t.propertyName
        case .announcementFresh(let a):
            return a.propertyName
        case .etvNewComment(let c):
            return c.assemblyTitle
        case .ticketCountOnly, .quiet:
            return nil
        }
    }

    private func smallFooter(_ item: WidgetItem) -> String? {
        switch item {
        case .etvInProgress: return "läuft jetzt"
        case .etvSoon(let etv), .etvUpcoming(let etv):
            return formatRelative(etv.scheduledStart)
        case .ticketFresh(let t, let count):
            return "\(count) offen · \(formatRelative(t.lastMessageAt))"
        case .ticketCountOnly:
            return nil
        case .etvNewComment(let c):
            return "\(c.authorLabel) · \(formatRelative(c.createdAt))"
        case .announcementFresh(let a):
            return formatRelative(a.publishedAt)
        case .quiet:
            return nil
        }
    }
}

// --- Home Screen (medium) -------------------------------------------------

private struct MediumView: View {
    let items: [WidgetItem]

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let primary = items.first {
                primaryCard(primary)
            }
            if items.count > 1 {
                Divider()
                secondaryCard(items[1])
            }
            Spacer(minLength: 0)
        }
    }

    @ViewBuilder
    private func primaryCard(_ item: WidgetItem) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: kindIcon(item))
                .font(.title3)
                .foregroundStyle(.white)
                .frame(width: 36, height: 36)
                .background(
                    RoundedRectangle(cornerRadius: 8)
                        .fill(kindColor(item))
                )
            VStack(alignment: .leading, spacing: 2) {
                Text(kindLabel(item))
                    .font(.caption2.weight(.bold))
                    .foregroundStyle(.secondary)
                    .textCase(.uppercase)
                Text(mediumPrimaryTitle(item))
                    .font(.subheadline.weight(.semibold))
                    .lineLimit(2)
                if let sub = mediumPrimarySub(item) {
                    Text(sub)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }
            Spacer(minLength: 0)
        }
    }

    @ViewBuilder
    private func secondaryCard(_ item: WidgetItem) -> some View {
        HStack(spacing: 8) {
            Image(systemName: kindIcon(item))
                .font(.caption.weight(.semibold))
                .foregroundStyle(kindColor(item))
            VStack(alignment: .leading, spacing: 1) {
                Text(mediumPrimaryTitle(item))
                    .font(.caption.weight(.semibold))
                    .lineLimit(1)
                if let sub = mediumPrimarySub(item) {
                    Text(sub)
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                        .lineLimit(1)
                }
            }
            Spacer(minLength: 0)
        }
    }

    private func mediumPrimaryTitle(_ item: WidgetItem) -> String {
        switch item {
        case .etvInProgress(let etv), .etvSoon(let etv), .etvUpcoming(let etv):
            return etv.title
        case .ticketFresh(let t, _):
            return t.subject
        case .ticketCountOnly(let count):
            return "\(count) offene Tickets"
        case .etvNewComment(let c):
            return c.body
        case .announcementFresh(let a):
            return a.title
        case .quiet:
            return "Alles ruhig"
        }
    }

    private func mediumPrimarySub(_ item: WidgetItem) -> String? {
        switch item {
        case .etvInProgress(let etv):
            return "läuft jetzt · \(etv.location)"
        case .etvSoon(let etv), .etvUpcoming(let etv):
            return "\(formatRelative(etv.scheduledStart)) · \(etv.propertyName ?? etv.location)"
        case .ticketFresh(let t, let count):
            return "\(count) offen · \(t.propertyName ?? "—")"
        case .ticketCountOnly:
            return nil
        case .etvNewComment(let c):
            return "\(c.authorLabel) · \(c.assemblyTitle)"
        case .announcementFresh(let a):
            return "\(formatRelative(a.publishedAt)) · \(a.propertyName ?? "—")"
        case .quiet:
            return nil
        }
    }
}

// MARK: - Shared kind styling

private func kindIcon(_ item: WidgetItem) -> String {
    switch item {
    case .etvInProgress, .etvSoon, .etvUpcoming: return "person.3.fill"
    case .ticketFresh, .ticketCountOnly: return "tray.full.fill"
    case .etvNewComment: return "bubble.left.fill"
    case .announcementFresh: return "megaphone.fill"
    case .quiet: return "checkmark.seal.fill"
    }
}

private func kindColor(_ item: WidgetItem) -> Color {
    switch item {
    case .etvInProgress: return .red                    // most urgent
    case .etvSoon: return Color(red: 0.36, green: 0.32, blue: 0.78)  // Teams purple — same as button
    case .etvUpcoming: return .accentColor
    case .ticketFresh, .ticketCountOnly: return .orange
    case .etvNewComment: return .blue
    case .announcementFresh: return .green
    case .quiet: return .secondary
    }
}

private func kindLabel(_ item: WidgetItem) -> String {
    switch item {
    case .etvInProgress: return "Versammlung läuft"
    case .etvSoon: return "ETV bald"
    case .etvUpcoming: return "Nächste ETV"
    case .ticketFresh, .ticketCountOnly: return "Tickets"
    case .etvNewComment: return "Neue Frage"
    case .announcementFresh: return "Mitteilung"
    case .quiet: return "WHV"
    }
}

// MARK: - Formatting helpers

private func formatShort(_ date: Date) -> String {
    let df = DateFormatter()
    df.locale = Locale(identifier: "de_DE")
    df.dateFormat = "dd.MM., HH:mm"
    return df.string(from: date)
}

private func formatRelative(_ date: Date) -> String {
    let now = Date()
    let interval = date.timeIntervalSince(now)
    let absMins = Int(abs(interval) / 60)
    if interval < 0 {
        if absMins < 60 { return "vor \(absMins) min" }
        let hours = absMins / 60
        if hours < 24 { return "vor \(hours) h" }
        let days = hours / 24
        return days == 1 ? "gestern" : "vor \(days) Tagen"
    }
    if absMins == 0 { return "jetzt" }
    if absMins < 60 { return "in \(absMins) min" }
    let hours = absMins / 60
    if hours < 24 { return "in \(hours) h" }
    let days = hours / 24
    if days == 1 { return "morgen" }
    if days < 7 { return "in \(days) Tagen" }
    let weeks = days / 7
    return weeks == 1 ? "in 1 Woche" : "in \(weeks) Wochen"
}

// MARK: - Preview helpers

extension WidgetEtvPayload {
    static let preview = WidgetEtvPayload(
        assemblyId: "preview",
        title: "Ordentliche Eigentümerversammlung 2026",
        propertyName: "WEG Königstraße 42",
        scheduledStart: Date().addingTimeInterval(3 * 86_400 + 18 * 3600),
        scheduledEnd: Date().addingTimeInterval(3 * 86_400 + 21 * 3600),
        location: "Vereinsheim Königstraße 42",
        teamsMeetingUrl: nil,
        status: "EINGELADEN"
    )
}

#Preview(as: .systemSmall) {
    UpcomingEtvWidget()
} timeline: {
    UpcomingEtvEntry(date: .now, items: [.etvSoon(.preview)])
    UpcomingEtvEntry(date: .now, items: [.quiet])
}

#Preview(as: .systemMedium) {
    UpcomingEtvWidget()
} timeline: {
    UpcomingEtvEntry(date: .now, items: [
        .etvSoon(.preview),
        .ticketCountOnly(count: 3),
    ])
}

#Preview(as: .accessoryRectangular) {
    UpcomingEtvWidget()
} timeline: {
    UpcomingEtvEntry(date: .now, items: [.etvSoon(.preview)])
}
