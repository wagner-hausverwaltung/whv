// Upcoming ETV widget — Lock Screen + Home Screen sizes.
//
// Data path: the host app writes a JSON snapshot of the next
// upcoming assembly to the shared App Group UserDefaults on every
// /me/properties/{id}/assemblies fetch, then calls
// WidgetCenter.shared.reloadAllTimelines(). The widget never talks
// to the network itself — keeps the widget process small and
// avoids the auth-in-extension headache.
//
// Empty state: when nothing is upcoming (or the user hasn't opened
// the app yet) we render a quiet "Keine Versammlung geplant" card
// instead of leaving the widget blank.

import SwiftUI
import WidgetKit

// MARK: - App Group bridge

/// Mirror of the host app's WidgetSnapshot wire shape. Lives here
/// rather than in a shared framework because the only thing the
/// widget needs from the app is "the next ETV" — a single JSON
/// blob in App Group UserDefaults is simpler than scaffolding a
/// shared module.
struct WidgetUpcomingEtv: Codable {
    let assemblyId: String
    let title: String
    let propertyName: String?
    let scheduledStart: Date
    let scheduledEnd: Date
    let location: String
    let teamsMeetingUrl: String?
    let status: String  // "GEPLANT" / "EINGELADEN" / "ABGEHALTEN" / "ABGESAGT"
}

enum WidgetStorage {
    static let appGroup = "group.com.wagner-hausverwaltung.WHV"
    static let nextEtvKey = "WHV.widget.nextEtv"

    static func loadNextEtv() -> WidgetUpcomingEtv? {
        guard let defaults = UserDefaults(suiteName: appGroup),
              let raw = defaults.data(forKey: nextEtvKey)
        else { return nil }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return try? decoder.decode(WidgetUpcomingEtv.self, from: raw)
    }
}

// MARK: - Timeline

struct UpcomingEtvEntry: TimelineEntry {
    let date: Date
    let etv: WidgetUpcomingEtv?
}

struct UpcomingEtvProvider: TimelineProvider {
    func placeholder(in context: Context) -> UpcomingEtvEntry {
        UpcomingEtvEntry(date: Date(), etv: .preview)
    }

    func getSnapshot(in context: Context, completion: @escaping (UpcomingEtvEntry) -> Void) {
        // Widget gallery preview uses the real snapshot when one is
        // available so the screenshot matches what the user would
        // actually see post-install. Falls back to .preview when
        // the app hasn't run yet.
        let etv = WidgetStorage.loadNextEtv() ?? .preview
        completion(UpcomingEtvEntry(date: Date(), etv: etv))
    }

    func getTimeline(
        in context: Context,
        completion: @escaping (Timeline<UpcomingEtvEntry>) -> Void
    ) {
        let now = Date()
        let etv = WidgetStorage.loadNextEtv()
        // Two timeline points: now (with current ETV) and a 30-min
        // refresh point. The host app's reloadAllTimelines() is the
        // primary refresh signal; the 30-min fallback covers cases
        // where the app hasn't been opened recently.
        let next = now.addingTimeInterval(30 * 60)
        let timeline = Timeline(
            entries: [
                UpcomingEtvEntry(date: now, etv: etv),
                UpcomingEtvEntry(date: next, etv: etv),
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
            UpcomingEtvView(entry: entry)
                .containerBackground(.fill.tertiary, for: .widget)
        }
        .configurationDisplayName("Nächste Versammlung")
        .description("Zeigt die nächste anstehende Eigentümerversammlung.")
        .supportedFamilies([
            .systemSmall,
            .systemMedium,
            .accessoryRectangular,
            .accessoryInline,
        ])
    }
}

// MARK: - Views

struct UpcomingEtvView: View {
    let entry: UpcomingEtvEntry
    @Environment(\.widgetFamily) private var family

    var body: some View {
        switch family {
        case .accessoryInline:
            inlineView
        case .accessoryRectangular:
            rectangularView
        case .systemMedium:
            mediumView
        default:
            smallView
        }
    }

    private static let teamsPurple = Color(red: 0.36, green: 0.32, blue: 0.78)

    // Single-line Lock Screen text — limited by iOS to ~30 chars
    // rendered. Keep it scannable in a glance.
    private var inlineView: some View {
        Group {
            if let etv = entry.etv {
                Text("ETV: \(formatRelative(etv.scheduledStart))")
            } else {
                Text("ETV: keine geplant")
            }
        }
    }

    private var rectangularView: some View {
        VStack(alignment: .leading, spacing: 2) {
            if let etv = entry.etv {
                Text("Nächste ETV")
                    .font(.caption2.weight(.semibold))
                    .widgetAccentable()
                Text(etv.title)
                    .font(.caption.weight(.semibold))
                    .lineLimit(2)
                Text(formatShort(etv.scheduledStart))
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            } else {
                Text("Keine Versammlung")
                    .font(.caption.weight(.semibold))
                    .widgetAccentable()
                Text("Nichts geplant")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
        }
    }

    private var smallView: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("ETV")
                .font(.caption2.weight(.bold))
                .foregroundStyle(.secondary)
                .textCase(.uppercase)
            if let etv = entry.etv {
                Text(etv.title)
                    .font(.subheadline.weight(.semibold))
                    .lineLimit(2)
                if let prop = etv.propertyName, !prop.isEmpty {
                    Text(prop)
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                        .lineLimit(1)
                }
                Spacer(minLength: 0)
                Text(formatShort(etv.scheduledStart))
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.primary)
                Text(formatRelative(etv.scheduledStart))
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            } else {
                Spacer(minLength: 0)
                Text("Keine Versammlung geplant")
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(.secondary)
                Spacer(minLength: 0)
            }
        }
    }

    private var mediumView: some View {
        HStack(alignment: .top, spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text("Nächste ETV")
                    .font(.caption.weight(.bold))
                    .foregroundStyle(.secondary)
                    .textCase(.uppercase)
                if let etv = entry.etv {
                    Text(etv.title)
                        .font(.headline)
                        .lineLimit(2)
                    if let prop = etv.propertyName, !prop.isEmpty {
                        Text(prop)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                    HStack(spacing: 6) {
                        Image(systemName: "calendar")
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                        Text(formatShort(etv.scheduledStart))
                            .font(.caption)
                    }
                    .foregroundStyle(.secondary)
                    HStack(spacing: 6) {
                        Image(systemName: "mappin.and.ellipse")
                            .font(.caption2)
                        Text(etv.location)
                            .font(.caption)
                            .lineLimit(1)
                    }
                    .foregroundStyle(.secondary)
                } else {
                    Text("Keine Versammlung geplant")
                        .font(.subheadline.weight(.medium))
                        .foregroundStyle(.secondary)
                    Spacer(minLength: 0)
                }
            }
            Spacer(minLength: 0)
            if let etv = entry.etv {
                relativeBadge(for: etv.scheduledStart)
            }
        }
    }

    private func relativeBadge(for date: Date) -> some View {
        VStack(spacing: 2) {
            Text(daysUntil(date))
                .font(.system(size: 22, weight: .bold))
            Text(daysUntilUnit(date))
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(
            RoundedRectangle(cornerRadius: 10)
                .fill(Color.accentColor.opacity(0.18))
        )
    }

    // MARK: - Formatting helpers

    private func formatShort(_ date: Date) -> String {
        let df = DateFormatter()
        df.locale = Locale(identifier: "de_DE")
        df.dateFormat = "dd.MM., HH:mm"
        return df.string(from: date)
    }

    /// "in 3 Tagen" / "morgen" / "heute" / "in 2 Wochen" — purely
    /// presentational so we don't ship RelativeDateTimeFormatter's
    /// English fallback on a German device with locale overrides.
    private func formatRelative(_ date: Date) -> String {
        let days = Calendar.current.dateComponents([.day], from: Date(), to: date).day ?? 0
        if days < 0 { return "vergangen" }
        if days == 0 { return "heute" }
        if days == 1 { return "morgen" }
        if days < 7 { return "in \(days) Tagen" }
        let weeks = days / 7
        return weeks == 1 ? "in 1 Woche" : "in \(weeks) Wochen"
    }

    private func daysUntil(_ date: Date) -> String {
        let days = max(0, Calendar.current.dateComponents([.day], from: Date(), to: date).day ?? 0)
        if days >= 7 {
            return "\(days / 7)"
        }
        return "\(days)"
    }

    private func daysUntilUnit(_ date: Date) -> String {
        let days = max(0, Calendar.current.dateComponents([.day], from: Date(), to: date).day ?? 0)
        if days >= 14 { return "Wochen" }
        if days >= 7 { return "Woche" }
        if days == 1 { return "Tag" }
        return "Tage"
    }
}

// MARK: - Preview helpers

extension WidgetUpcomingEtv {
    static let preview = WidgetUpcomingEtv(
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
    UpcomingEtvEntry(date: .now, etv: .preview)
    UpcomingEtvEntry(date: .now, etv: nil)
}

#Preview(as: .systemMedium) {
    UpcomingEtvWidget()
} timeline: {
    UpcomingEtvEntry(date: .now, etv: .preview)
    UpcomingEtvEntry(date: .now, etv: nil)
}

#Preview(as: .accessoryRectangular) {
    UpcomingEtvWidget()
} timeline: {
    UpcomingEtvEntry(date: .now, etv: .preview)
}
