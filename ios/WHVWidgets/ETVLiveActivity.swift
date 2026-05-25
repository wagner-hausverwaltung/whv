// Lock-Screen + Dynamic-Island UI for an ongoing-or-imminent ETV.
//
// Host-app side starts an Activity<ETVActivityAttributes> when an
// assembly is within T-5h, and ends it after `scheduled_end + 30
// min`. This file owns what the widget process draws while the
// activity is live.
//
// Layout intent: the user is glancing — make the next-most-likely
// action (Teams join when there's a link, "Ich komme später"
// otherwise) the largest tap target. Detail-page deep link sits
// quietly to the side via the Link wrapper (whv://assembly/{id}).

import ActivityKit
import AppIntents
import SwiftUI
import WidgetKit

@available(iOS 17.0, *)
struct ETVLiveActivity: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: ETVActivityAttributes.self) { context in
            // Lock Screen banner.
            LockScreenView(context: context)
                .activityBackgroundTint(Color.black.opacity(0.85))
                .activitySystemActionForegroundColor(.white)
        } dynamicIsland: { context in
            DynamicIsland {
                DynamicIslandExpandedRegion(.leading) {
                    ExpandedLeading(context: context)
                }
                DynamicIslandExpandedRegion(.trailing) {
                    ExpandedTrailing(context: context)
                }
                DynamicIslandExpandedRegion(.center) {
                    ExpandedCenter(context: context)
                }
                DynamicIslandExpandedRegion(.bottom) {
                    ExpandedBottom(context: context)
                }
            } compactLeading: {
                Image(systemName: "person.3.fill")
                    .foregroundStyle(.tint)
            } compactTrailing: {
                CompactTrailing(context: context)
            } minimal: {
                Image(systemName: lateBadgeIcon(context.state.lateStatus))
                    .foregroundStyle(lateBadgeColor(context.state.lateStatus))
            }
            .widgetURL(URL(string: "whv://assembly/\(context.attributes.assemblyId)"))
            .keylineTint(Color(red: 0.36, green: 0.32, blue: 0.78))
        }
    }
}

// MARK: - Lock Screen card

@available(iOS 17.0, *)
private struct LockScreenView: View {
    let context: ActivityViewContext<ETVActivityAttributes>

    var body: some View {
        Link(destination: detailURL) {
            VStack(alignment: .leading, spacing: 8) {
                header
                if let prop = context.attributes.propertyName, !prop.isEmpty {
                    Label(prop, systemImage: "building.2")
                        .font(.caption2)
                        .foregroundStyle(.white.opacity(0.7))
                        .lineLimit(1)
                }
                timeline
                if !context.attributes.agendaPreview.isEmpty {
                    agendaPreview
                }
                Label(context.attributes.location, systemImage: "mappin.and.ellipse")
                    .font(.caption)
                    .foregroundStyle(.white.opacity(0.85))
                    .lineLimit(1)
                actionRow
            }
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var header: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 2) {
                Text("Eigentümerversammlung")
                    .font(.caption2.weight(.bold))
                    .foregroundStyle(.white.opacity(0.7))
                    .textCase(.uppercase)
                Text(context.attributes.title)
                    .font(.headline)
                    .foregroundStyle(titleColor)
                    .lineLimit(2)
            }
            Spacer(minLength: 0)
            lateChip
        }
    }

    private var timeline: some View {
        HStack(spacing: 8) {
            Image(systemName: "clock")
                .font(.caption2)
            VStack(alignment: .leading, spacing: 0) {
                Text(timeRange)
                    .font(.caption.weight(.semibold))
                Text(relativeLine)
                    .font(.caption2)
                    .foregroundStyle(.white.opacity(0.7))
            }
        }
        .foregroundStyle(.white)
    }

    private var agendaPreview: some View {
        VStack(alignment: .leading, spacing: 1) {
            Text("Tagesordnung")
                .font(.caption2.weight(.semibold))
                .foregroundStyle(.white.opacity(0.7))
                .textCase(.uppercase)
            ForEach(Array(context.attributes.agendaPreview.prefix(3).enumerated()), id: \.0) { idx, top in
                Text("\(idx + 1). \(top)")
                    .font(.caption2)
                    .foregroundStyle(.white.opacity(0.85))
                    .lineLimit(1)
            }
        }
    }

    private var actionRow: some View {
        HStack(spacing: 8) {
            if let url = teamsURL {
                Link(destination: url) {
                    Label("Teams", systemImage: "video.fill")
                        .font(.caption.weight(.semibold))
                        .padding(.horizontal, 10)
                        .padding(.vertical, 6)
                        .foregroundStyle(.white)
                        .background(
                            RoundedRectangle(cornerRadius: 8)
                                .fill(Self.teamsPurple)
                        )
                }
            }
            Button(intent: RunningLateIntent(activityID: context.activityID)) {
                Label(lateButtonLabel, systemImage: "hourglass")
                    .font(.caption.weight(.semibold))
                    .padding(.horizontal, 10)
                    .padding(.vertical, 6)
                    .foregroundStyle(.white)
                    .background(
                        RoundedRectangle(cornerRadius: 8)
                            .fill(lateButtonBackground)
                    )
            }
            .buttonStyle(.plain)
            .disabled(context.state.lateStatus == .runningLate)
            Spacer(minLength: 0)
            Image(systemName: "chevron.right")
                .font(.caption2)
                .foregroundStyle(.white.opacity(0.7))
        }
    }

    private var lateChip: some View {
        Group {
            if context.state.lateStatus == .runningLate {
                Label("verspätet", systemImage: "hourglass.bottomhalf.filled")
                    .font(.caption2.weight(.bold))
                    .foregroundStyle(.black)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 3)
                    .background(Capsule().fill(Color.orange))
            }
        }
    }

    private var titleColor: Color {
        context.state.lateStatus == .runningLate ? .orange : .white
    }

    private static let teamsPurple = Color(red: 0.36, green: 0.32, blue: 0.78)

    private var lateButtonBackground: Color {
        context.state.lateStatus == .runningLate ? .gray.opacity(0.5) : .orange
    }

    private var lateButtonLabel: String {
        context.state.lateStatus == .runningLate ? "Verspätet" : "Ich komme später"
    }

    private var timeRange: String {
        let df = DateFormatter()
        df.locale = Locale(identifier: "de_DE")
        df.dateFormat = "EEE, d. MMM, HH:mm"
        let from = df.string(from: context.attributes.scheduledStart)
        df.dateFormat = "HH:mm"
        let to = df.string(from: context.attributes.scheduledEnd)
        return "\(from) – \(to) Uhr"
    }

    private var relativeLine: String {
        relativeLabel(for: context.attributes.scheduledStart)
    }

    private var detailURL: URL {
        URL(string: "whv://assembly/\(context.attributes.assemblyId)")!
    }

    private var teamsURL: URL? {
        guard let s = context.attributes.teamsMeetingUrl, !s.isEmpty else { return nil }
        return URL(string: s)
    }
}

// MARK: - Dynamic Island

@available(iOS 17.0, *)
private struct CompactTrailing: View {
    let context: ActivityViewContext<ETVActivityAttributes>

    var body: some View {
        Text(compactRelative(context.attributes.scheduledStart))
            .font(.caption2.weight(.semibold))
            .foregroundStyle(context.state.lateStatus == .runningLate ? .orange : .primary)
    }
}

@available(iOS 17.0, *)
private struct ExpandedLeading: View {
    let context: ActivityViewContext<ETVActivityAttributes>

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text("ETV")
                .font(.caption2.weight(.bold))
                .foregroundStyle(.secondary)
            Text(context.attributes.title)
                .font(.caption.weight(.semibold))
                .lineLimit(2)
                .foregroundStyle(.primary)
        }
    }
}

@available(iOS 17.0, *)
private struct ExpandedTrailing: View {
    let context: ActivityViewContext<ETVActivityAttributes>

    var body: some View {
        VStack(alignment: .trailing, spacing: 2) {
            Text(compactRelative(context.attributes.scheduledStart))
                .font(.caption.weight(.bold))
            if context.state.lateStatus == .runningLate {
                Label("verspätet", systemImage: "hourglass.bottomhalf.filled")
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(.orange)
            }
        }
    }
}

@available(iOS 17.0, *)
private struct ExpandedCenter: View {
    let context: ActivityViewContext<ETVActivityAttributes>

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Label(context.attributes.location, systemImage: "mappin.and.ellipse")
                .font(.caption2)
                .foregroundStyle(.secondary)
                .lineLimit(1)
            if let first = context.attributes.agendaPreview.first {
                Text("TOP 1: \(first)")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
        }
    }
}

@available(iOS 17.0, *)
private struct ExpandedBottom: View {
    let context: ActivityViewContext<ETVActivityAttributes>

    var body: some View {
        HStack(spacing: 8) {
            if let url = teamsURL {
                Link(destination: url) {
                    Label("Teams beitreten", systemImage: "video.fill")
                        .font(.caption.weight(.semibold))
                        .padding(.horizontal, 12)
                        .padding(.vertical, 7)
                        .foregroundStyle(.white)
                        .background(
                            RoundedRectangle(cornerRadius: 8)
                                .fill(Self.teamsPurple)
                        )
                }
            }
            Button(intent: RunningLateIntent(activityID: context.activityID)) {
                Label(context.state.lateStatus == .runningLate ? "Verspätet" : "Ich komme später",
                      systemImage: "hourglass")
                    .font(.caption.weight(.semibold))
                    .padding(.horizontal, 12)
                    .padding(.vertical, 7)
                    .foregroundStyle(.white)
                    .background(
                        RoundedRectangle(cornerRadius: 8)
                            .fill(context.state.lateStatus == .runningLate ? Color.gray.opacity(0.5) : Color.orange)
                    )
            }
            .buttonStyle(.plain)
            .disabled(context.state.lateStatus == .runningLate)
            Spacer(minLength: 0)
            Link(destination: URL(string: "whv://assembly/\(context.attributes.assemblyId)")!) {
                Image(systemName: "arrow.up.right.square")
                    .foregroundStyle(.secondary)
            }
        }
    }

    private static let teamsPurple = Color(red: 0.36, green: 0.32, blue: 0.78)

    private var teamsURL: URL? {
        guard let s = context.attributes.teamsMeetingUrl, !s.isEmpty else { return nil }
        return URL(string: s)
    }
}

// MARK: - Formatting helpers (file-scope so all subviews share)

private func relativeLabel(for date: Date) -> String {
    let now = Date()
    let interval = date.timeIntervalSince(now)
    if interval < 0 {
        let minsLate = Int(-interval / 60)
        if minsLate < 60 { return "läuft gerade · \(minsLate) min" }
        return "läuft gerade"
    }
    let mins = Int(interval / 60)
    if mins < 60 { return "in \(mins) min" }
    let hours = mins / 60
    if hours < 24 { return "in \(hours) h" }
    let days = hours / 24
    return days == 1 ? "morgen" : "in \(days) Tagen"
}

private func compactRelative(_ date: Date) -> String {
    let interval = date.timeIntervalSince(Date())
    if interval < 0 {
        let mins = Int(-interval / 60)
        return mins < 60 ? "\(mins)′" : "live"
    }
    let mins = Int(interval / 60)
    if mins < 60 { return "\(mins)′" }
    let hours = mins / 60
    if hours < 24 { return "\(hours)h" }
    return "\(hours / 24)d"
}

private func lateBadgeIcon(_ status: ETVActivityAttributes.LateStatus) -> String {
    status == .runningLate ? "hourglass.bottomhalf.filled" : "person.3.fill"
}

private func lateBadgeColor(_ status: ETVActivityAttributes.LateStatus) -> Color {
    status == .runningLate ? .orange : .accentColor
}
