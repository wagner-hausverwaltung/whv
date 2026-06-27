// WHV "Aktuelles" home-screen widget.
//
// Reads the unified activity feed (ActivitySnapshot) the host app
// writes into App Group UserDefaults after every GET /me/activity
// fetch, and renders it per widget family. The feed arrives
// pre-sorted (most urgent first) — the widget never re-orders it.
//
// Family handling:
//   systemSmall → the single top item
//   systemMedium → top 2–3 items as rows
//   systemLarge → up to ~6 items as a compact list
//   accessoryRectangular / accessoryInline → the top item (lock screen)
//
// Tap targets deep-link via the item's deep_link (whv://…). On small
// + accessory families one .widgetURL covers the whole widget (iOS
// honours a single URL per non-interactive widget); medium + large
// wrap each row in a Link so individual rows route independently.
//
// The widget never talks to the network — the host app owns freshness.
// The shared ActivityStorage / ActivityItem types live in ios/Shared.

import SwiftUI
import WidgetKit

// MARK: - Tap URL

extension ActivityItem {
    /// The 4 "fallback" deep-link hosts have no by-id detail screen on
    /// iOS — they land the user on a property-scoped tab. Because the
    /// feed is cross-property, those taps must carry the item's OWN
    /// property so the app can switch the active Liegenschaft first
    /// (the by-id detail hosts — etv/announcement/resolution/ticket —
    /// route by id and need no property hint).
    private static let propertyScopedHosts: Set<String> =
        ["document", "invoice", "meter", "calendar"]

    /// The URL a tap should open. Identical to `deepLink` except for
    /// the property-scoped hosts, where we append `?property=<uuid>`
    /// (when we know it) so the shell can select the right property.
    var tapURL: URL? {
        guard let base = URL(string: deepLink) else { return nil }
        guard let pid = propertyId, !pid.isEmpty else { return base }
        // Host is the segment after the scheme: whv://meter/{id} → host
        // "meter"; whv:///meter/{id} → first path component. Mirror the
        // both-forms tolerance in DeepLinkRouter.
        let host = resolvedHost(of: base)
        guard Self.propertyScopedHosts.contains(host) else { return base }
        guard var comps = URLComponents(url: base, resolvingAgainstBaseURL: false)
        else { return base }
        var items = comps.queryItems ?? []
        items.append(URLQueryItem(name: "property", value: pid))
        comps.queryItems = items
        return comps.url ?? base
    }

    private func resolvedHost(of url: URL) -> String {
        if let h = url.host, !h.isEmpty { return h.lowercased() }
        // whv:///meter/{id} → empty host, host lives in the path.
        let trimmed = url.path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        return trimmed.split(separator: "/").first.map { String($0).lowercased() } ?? ""
    }
}

// MARK: - Timeline

struct ActivityEntry: TimelineEntry {
    let date: Date
    let items: [ActivityItem]
}

struct ActivityProvider: TimelineProvider {
    func placeholder(in context: Context) -> ActivityEntry {
        ActivityEntry(date: Date(), items: ActivityItem.previewItems)
    }

    func getSnapshot(in context: Context, completion: @escaping (ActivityEntry) -> Void) {
        let items = ActivityStorage.read()?.items ?? ActivityItem.previewItems
        completion(ActivityEntry(date: Date(), items: items))
    }

    func getTimeline(
        in context: Context,
        completion: @escaping (Timeline<ActivityEntry>) -> Void
    ) {
        let now = Date()
        let items = ActivityStorage.read()?.items ?? []
        // Two timeline points: now + a 30-min fallback. The real
        // refresh signal is the host app's reloadAllTimelines() after
        // each GET /me/activity; the fallback covers idle stretches.
        let next = now.addingTimeInterval(30 * 60)
        let timeline = Timeline(
            entries: [
                ActivityEntry(date: now, items: items),
                ActivityEntry(date: next, items: items),
            ],
            policy: .after(next)
        )
        completion(timeline)
    }
}

// MARK: - Widget

struct ActivityWidget: Widget {
    let kind = "WHVActivityWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: ActivityProvider()) { entry in
            ActivityWidgetView(entry: entry)
                .containerBackground(.fill.tertiary, for: .widget)
        }
        .configurationDisplayName("WHV — Aktuelles")
        .description("Zeigt die neuesten WHV-Hinweise: Versammlungen, Beschlüsse, Mitteilungen, Dokumente, Rechnungen, Termine und fällige Zählerstände.")
        .supportedFamilies([
            .systemSmall,
            .systemMedium,
            .systemLarge,
            .accessoryRectangular,
            .accessoryInline,
        ])
    }
}

// MARK: - Root view

struct ActivityWidgetView: View {
    let entry: ActivityEntry
    @Environment(\.widgetFamily) private var family

    var body: some View {
        switch family {
        case .accessoryInline:
            InlineActivityView(item: entry.items.first)
        case .accessoryRectangular:
            RectangularActivityView(item: entry.items.first)
                .widgetURL(entry.items.first?.tapURL)
        case .systemMedium:
            ListActivityView(items: entry.items, maxRows: 3)
        case .systemLarge:
            ListActivityView(items: entry.items, maxRows: 6)
        // .systemSmall + any other (unsupported) family fall back to
        // the single-item small layout.
        default:
            SmallActivityView(item: entry.items.first)
                .widgetURL(entry.items.first?.tapURL)
        }
    }
}

// MARK: - Empty state

private struct EmptyActivityView: View {
    var compact = false

    var body: some View {
        VStack(spacing: 6) {
            Image(systemName: "checkmark.circle")
                .font(compact ? .body : .title2)
                .foregroundStyle(.secondary)
            Text("Keine neuen Hinweise")
                .font(compact ? .caption2 : .subheadline)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

// MARK: - Lock screen (inline)

private struct InlineActivityView: View {
    let item: ActivityItem?

    var body: some View {
        if let item {
            Label {
                Text(item.title)
            } icon: {
                Image(systemName: item.kind.sfSymbol)
            }
        } else {
            Text("WHV: Keine neuen Hinweise")
        }
    }
}

// MARK: - Lock screen (rectangular)

private struct RectangularActivityView: View {
    let item: ActivityItem?

    var body: some View {
        if let item {
            VStack(alignment: .leading, spacing: 2) {
                Label {
                    Text(item.title)
                        .font(.caption.weight(.semibold))
                        .lineLimit(1)
                } icon: {
                    Image(systemName: item.kind.sfSymbol)
                }
                .widgetAccentable()
                if !item.subtitle.isEmpty {
                    Text(item.subtitle)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
                if let prop = item.propertyName, !prop.isEmpty {
                    Text(prop)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }
        } else {
            Text("Keine neuen Hinweise")
                .font(.caption)
        }
    }
}

// MARK: - Home screen (small)

private struct SmallActivityView: View {
    let item: ActivityItem?

    var body: some View {
        if let item {
            VStack(alignment: .leading, spacing: 6) {
                Image(systemName: item.kind.sfSymbol)
                    .font(.title3.weight(.semibold))
                    .foregroundStyle(.white)
                    .frame(width: 32, height: 32)
                    .background(
                        RoundedRectangle(cornerRadius: 8).fill(.tint)
                    )
                Text(item.title)
                    .font(.subheadline.weight(.semibold))
                    .lineLimit(2)
                if !item.subtitle.isEmpty {
                    Text(item.subtitle)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }
                Spacer(minLength: 0)
                if let prop = item.propertyName, !prop.isEmpty {
                    Text(prop)
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                        .lineLimit(1)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        } else {
            EmptyActivityView()
        }
    }
}

// MARK: - Home screen (medium + large)

private struct ListActivityView: View {
    let items: [ActivityItem]
    let maxRows: Int

    private var shown: [ActivityItem] {
        Array(items.prefix(maxRows))
    }

    var body: some View {
        if shown.isEmpty {
            EmptyActivityView()
        } else {
            VStack(alignment: .leading, spacing: 8) {
                ForEach(Array(shown.enumerated()), id: \.element.id) { idx, item in
                    rowLink(item)
                    if idx != shown.count - 1 {
                        Divider()
                    }
                }
                Spacer(minLength: 0)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    /// Each row deep-links independently. An invalid URL degrades to a
    /// plain row (still renders, just not tappable).
    @ViewBuilder
    private func rowLink(_ item: ActivityItem) -> some View {
        if let url = item.tapURL {
            Link(destination: url) { ActivityRow(item: item) }
        } else {
            ActivityRow(item: item)
        }
    }
}

private struct ActivityRow: View {
    let item: ActivityItem

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: item.kind.sfSymbol)
                .font(.callout.weight(.semibold))
                .foregroundStyle(.white)
                .frame(width: 30, height: 30)
                .background(
                    RoundedRectangle(cornerRadius: 7).fill(.tint)
                )
            VStack(alignment: .leading, spacing: 1) {
                Text(item.title)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(.primary)
                    .lineLimit(1)
                if !item.subtitle.isEmpty {
                    Text(item.subtitle)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
                if let prop = item.propertyName, !prop.isEmpty {
                    Text(prop)
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                        .lineLimit(1)
                }
            }
            Spacer(minLength: 0)
        }
    }
}

// MARK: - Preview helpers

extension ActivityItem {
    static let previewItems: [ActivityItem] = [
        ActivityItem(
            type: "ETV",
            id: "preview-etv",
            title: "Ordentliche Eigentümerversammlung 2026",
            subtitle: "Vereinsheim Königstraße 42",
            timestamp: Date().addingTimeInterval(3 * 86_400),
            priority: 0,
            propertyName: "WEG Königstraße 42",
            deepLink: "whv://etv/preview-etv"
        ),
        ActivityItem(
            type: "ANNOUNCEMENT",
            id: "preview-ann",
            title: "Wartung Aufzug am Dienstag",
            subtitle: "Der Aufzug steht von 8–12 Uhr still.",
            timestamp: Date().addingTimeInterval(-3600),
            priority: 10,
            propertyName: "Schmidener Str. 12",
            deepLink: "whv://announcement/preview-ann"
        ),
        ActivityItem(
            type: "METER_DUE",
            id: "preview-meter",
            title: "Zählerstand fällig",
            subtitle: "Wärmemengenzähler ablesen",
            timestamp: Date(),
            priority: 5,
            propertyName: "Friedrichstr. 33",
            propertyId: "preview-property-friedrichstr",
            deepLink: "whv://meter/preview-meter"
        ),
    ]
}

#Preview(as: .systemSmall) {
    ActivityWidget()
} timeline: {
    ActivityEntry(date: .now, items: ActivityItem.previewItems)
    ActivityEntry(date: .now, items: [])
}

#Preview(as: .systemMedium) {
    ActivityWidget()
} timeline: {
    ActivityEntry(date: .now, items: ActivityItem.previewItems)
}

#Preview(as: .systemLarge) {
    ActivityWidget()
} timeline: {
    ActivityEntry(date: .now, items: ActivityItem.previewItems)
}

#Preview(as: .accessoryRectangular) {
    ActivityWidget()
} timeline: {
    ActivityEntry(date: .now, items: ActivityItem.previewItems)
}
