// Eigentümerversammlungen — list view grouped into Geplant + Vergangen.
//
// The list reads from a per-property demo dataset; Phase 2.1 swaps
// the source for /me/properties/{id}/assemblies + /me/assemblies/{id}
// via EtvService (already drafted in Assembly.swift). The grouped
// shape + row layout stays the same.

import SwiftUI

struct VersammlungenTab: View {
    @EnvironmentObject var liegenschaftStore: LiegenschaftStore

    var body: some View {
        NavigationStack {
            content
                .navigationTitle("Versammlungen")
        }
    }

    @ViewBuilder
    private var content: some View {
        if let l = liegenschaftStore.selected {
            AssemblyList(assemblies: DemoAssemblies.sample(for: l))
        } else {
            ContentUnavailableView(
                "Keine Liegenschaft gewählt",
                systemImage: "building.2",
                description: Text(
                    "Versammlungen werden pro Liegenschaft angezeigt."
                )
            )
        }
    }
}

private struct AssemblyList: View {
    let assemblies: [Assembly]

    private var upcoming: [Assembly] {
        assemblies
            .filter { $0.status.isUpcoming }
            .sorted { $0.scheduled_start < $1.scheduled_start }
    }
    private var past: [Assembly] {
        assemblies
            .filter { !$0.status.isUpcoming }
            .sorted { $0.scheduled_start > $1.scheduled_start }
    }

    var body: some View {
        Group {
            if assemblies.isEmpty {
                ContentUnavailableView(
                    "Keine Versammlungen",
                    systemImage: "calendar.badge.exclamationmark",
                    description: Text(
                        "Sobald die Verwaltung eine Versammlung anlegt, "
                        + "erscheint sie hier."
                    )
                )
            } else {
                List {
                    if !upcoming.isEmpty {
                        Section("Geplant") {
                            ForEach(upcoming) { row(for: $0) }
                        }
                    }
                    if !past.isEmpty {
                        Section("Vergangen") {
                            ForEach(past) { row(for: $0) }
                        }
                    }
                }
                .listStyle(.insetGrouped)
            }
        }
    }

    private func row(for a: Assembly) -> some View {
        NavigationLink {
            AssemblyDetailView(assembly: a)
        } label: {
            HStack(alignment: .center, spacing: 12) {
                statusBadge(for: a.status)
                VStack(alignment: .leading, spacing: 3) {
                    Text(a.title)
                        .font(.subheadline.weight(.semibold))
                        .lineLimit(2)
                    if let propertyLine = propertyLine(for: a) {
                        HStack(spacing: 6) {
                            Image(systemName: "building.2")
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                            Text(propertyLine)
                                .font(.caption2.weight(.medium))
                                .foregroundStyle(.secondary)
                                .lineLimit(1)
                        }
                    }
                    Text(formatDateRange(a.scheduled_start, a.scheduled_end))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    HStack(spacing: 6) {
                        Image(systemName: "mappin.and.ellipse")
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                        Text(a.location)
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                            .lineLimit(1)
                    }
                    if a.protocol_pdf_url != nil {
                        HStack(spacing: 4) {
                            Image(systemName: "doc.text.fill")
                                .foregroundStyle(.tint)
                            Text("Protokoll verfügbar")
                                .foregroundStyle(.tint)
                        }
                        .font(.caption2.weight(.medium))
                        .padding(.top, 2)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .padding(.vertical, 4)
        }
    }

    /// "WEG Königstr. 42 · STUTTGART_K42" — mirrors the chip on
    /// admin + portal. Falls back to either part if the other is
    /// missing, returns nil if neither is present.
    private func propertyLine(for a: Assembly) -> String? {
        let parts = [a.property_name, a.property_hr_id]
            .compactMap { $0 }
            .filter { !$0.isEmpty }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    @ViewBuilder
    private func statusBadge(for status: AssemblyStatus) -> some View {
        VStack(spacing: 2) {
            Image(systemName: badgeIcon(for: status))
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(.white)
                .frame(width: 36, height: 36)
                .background(badgeColor(for: status))
                .clipShape(RoundedRectangle(cornerRadius: 8))
            Text(status.label)
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
    }

    private func badgeIcon(for status: AssemblyStatus) -> String {
        switch status {
        case .geplant: return "calendar"
        case .eingeladen: return "envelope.open"
        case .abgehalten: return "checkmark.seal"
        case .abgesagt: return "xmark"
        }
    }

    private func badgeColor(for status: AssemblyStatus) -> Color {
        switch status {
        case .geplant: return .gray
        case .eingeladen: return .blue
        case .abgehalten: return .green
        case .abgesagt: return .red
        }
    }
}

/// Single-shot date-range formatter — same dd.MM.yyyy HH:mm Germans
/// expect, dropping the redundant day-of-week.
private func formatDateRange(_ start: Date, _ end: Date) -> String {
    let cal = Calendar.current
    let sameDay = cal.isDate(start, inSameDayAs: end)
    let date = DateFormatter()
    date.locale = Locale(identifier: "de_DE")
    date.dateFormat = "dd.MM.yyyy"
    let time = DateFormatter()
    time.locale = Locale(identifier: "de_DE")
    time.dateFormat = "HH:mm"
    if sameDay {
        return "\(date.string(from: start)), \(time.string(from: start))–\(time.string(from: end)) Uhr"
    }
    return "\(date.string(from: start)) \(time.string(from: start)) – \(date.string(from: end)) \(time.string(from: end))"
}

#Preview {
    VersammlungenTab()
        .environmentObject({
            let s = LiegenschaftStore()
            s.select(Liegenschaft.demo[0])
            return s
        }())
}
