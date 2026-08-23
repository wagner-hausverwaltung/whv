//
//  TripLiveActivity.swift
//  WHVWidgets
//
//  Dynamic Island + Lock Screen view for a running Dienstfahrt.
//

import ActivityKit
import SwiftUI
import WidgetKit

struct TripLiveActivity: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: TripActivityAttributes.self) { context in
            TripLockScreenView(context: context)
                .activityBackgroundTint(Color.black.opacity(0.85))
                .activitySystemActionForegroundColor(.white)
        } dynamicIsland: { context in
            DynamicIsland {
                DynamicIslandExpandedRegion(.leading) {
                    Label("Fahrt", systemImage: "car.fill")
                        .font(.caption).foregroundStyle(.secondary)
                }
                DynamicIslandExpandedRegion(.trailing) {
                    Text(tripKm(context.state.distanceM))
                        .font(.headline.monospacedDigit())
                }
                DynamicIslandExpandedRegion(.center) {
                    Text(context.state.destinationName ?? "Ziel offen")
                        .font(.subheadline.weight(.semibold))
                        .lineLimit(1)
                }
                DynamicIslandExpandedRegion(.bottom) {
                    HStack {
                        Text("seit \(context.attributes.startedAt, style: .time)")
                            .font(.caption).foregroundStyle(.secondary)
                        if let p = context.state.purposeLabel {
                            Text("· \(p)").font(.caption).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Button(intent: EndTripIntent()) {
                            Label("Beenden", systemImage: "stop.circle.fill")
                                .font(.caption.weight(.semibold))
                        }
                        .buttonStyle(.borderedProminent)
                        .tint(.red)
                    }
                }
            } compactLeading: {
                Image(systemName: "car.fill").foregroundStyle(.tint)
            } compactTrailing: {
                Text(tripKm(context.state.distanceM))
                    .font(.caption2.monospacedDigit())
            } minimal: {
                Image(systemName: "car.fill").foregroundStyle(.tint)
            }
            .widgetURL(URL(string: "whv://tab/start"))
            .keylineTint(Color(red: 0.09, green: 0.39, blue: 0.86))
        }
    }
}

private struct TripLockScreenView: View {
    let context: ActivityViewContext<TripActivityAttributes>

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: "car.fill")
                .font(.title2)
                .foregroundStyle(.tint)
            VStack(alignment: .leading, spacing: 2) {
                Text("Fahrt läuft · \(tripKm(context.state.distanceM))")
                    .font(.headline.monospacedDigit())
                Text(context.state.destinationName.map { "Ziel: \($0)" } ?? "Ziel wird am Ende vorgeschlagen")
                    .font(.caption).foregroundStyle(.secondary).lineLimit(1)
                HStack(spacing: 4) {
                    Text("seit \(context.attributes.startedAt, style: .time)")
                    if let p = context.state.purposeLabel { Text("· \(p)") }
                }
                .font(.caption2).foregroundStyle(.secondary)
            }
            Spacer()
            Button(intent: EndTripIntent()) {
                Label("Beenden", systemImage: "stop.circle.fill")
                    .font(.caption.weight(.semibold))
            }
            .buttonStyle(.borderedProminent)
            .tint(.red)
        }
        .padding(14)
    }
}

private func tripKm(_ m: Int) -> String {
    String(format: "%.1f km", Double(m) / 1000).replacingOccurrences(of: ".", with: ",")
}
