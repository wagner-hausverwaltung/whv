// Eigentümerversammlungen — list view grouped into Geplant + Vergangen.
//
// Live source: GET /me/properties/{id}/assemblies. A small
// per-tab ObservableObject owns the fetch + loading/error state and
// reloads when the active Liegenschaft changes.

import SwiftUI

@MainActor
final class AssemblyListStore: ObservableObject {
    @Published private(set) var assemblies: [AssemblySummary] = []
    @Published private(set) var isLoading = false
    @Published var lastError: String?

    /// Tracks which property id is currently loaded so a switch back
    /// to a previously-viewed property shows its cached set instantly
    /// while we refresh in the background.
    private(set) var loadedPropertyId: String?
    var onUnauthorized: (() -> Void)?
    private let api: APIClient

    init(api: APIClient = APIClient()) {
        self.api = api
    }

    func load(propertyId: String, force: Bool = false) async {
        if loadedPropertyId == propertyId, !assemblies.isEmpty, !force {
            return
        }
        lastError = nil
        isLoading = true
        defer { isLoading = false }
        do {
            let rows = try await api.listMyAssemblies(propertyId: propertyId)
            self.assemblies = rows
            self.loadedPropertyId = propertyId
            // Surface the next upcoming ETV + other relevant items
            // (tickets, comments, announcements) on the Lock/Home
            // Screen widget. Best-effort: a failing fetch leaves
            // its slot nil; the snapshot still ships.
            let apiRef = self.api
            await WidgetSync.refresh(
                api: apiRef,
                propertyId: propertyId,
                assemblies: rows
            )
            // Live Activity is a separate surface — fires only when
            // an ETV is within 5h, so most refreshes are no-ops.
            await LiveActivityManager.reconcile(with: rows) { id in
                try? await apiRef.getAssemblyDetail(id: id)
            }
        } catch APIError.unauthorized {
            onUnauthorized?()
        } catch let error as APIError {
            self.lastError = error.errorDescription
        } catch {
            self.lastError = error.localizedDescription
        }
    }
}

struct VersammlungenTab: View {
    @EnvironmentObject var liegenschaftStore: LiegenschaftStore
    @EnvironmentObject var authStore: AuthStore
    @StateObject private var store = AssemblyListStore()

    var body: some View {
        NavigationStack {
            content
                .navigationTitle("Versammlungen")
                .toolbar {
                    if let l = liegenschaftStore.selected {
                        ToolbarItem(placement: .topBarTrailing) {
                            Button {
                                Task { await store.load(propertyId: l.id, force: true) }
                            } label: {
                                Image(systemName: "arrow.clockwise")
                            }
                            .disabled(store.isLoading)
                        }
                    }
                }
                .onAppear {
                    store.onUnauthorized = { [weak authStore] in
                        authStore?.signOut()
                    }
                }
        }
    }

    @ViewBuilder
    private var content: some View {
        if let l = liegenschaftStore.selected {
            AssemblyList(assemblies: store.assemblies, isLoading: store.isLoading, error: store.lastError) {
                Task { await store.load(propertyId: l.id, force: true) }
            }
            .task(id: l.id) {
                await store.load(propertyId: l.id)
            }
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
    let assemblies: [AssemblySummary]
    let isLoading: Bool
    let error: String?
    let onReload: () -> Void

    private var upcoming: [AssemblySummary] {
        assemblies
            .filter { $0.status.isUpcoming }
            .sorted { $0.scheduled_start < $1.scheduled_start }
    }
    private var past: [AssemblySummary] {
        assemblies
            .filter { !$0.status.isUpcoming }
            .sorted { $0.scheduled_start > $1.scheduled_start }
    }

    var body: some View {
        Group {
            if isLoading && assemblies.isEmpty {
                VStack(spacing: 12) {
                    ProgressView()
                    Text("Versammlungen werden geladen …")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if let err = error, assemblies.isEmpty {
                errorView(err)
            } else if assemblies.isEmpty {
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
                .refreshable { onReload() }
            }
        }
    }

    private func errorView(_ message: String) -> some View {
        VStack(spacing: 12) {
            Image(systemName: "exclamationmark.triangle")
                .font(.system(size: 48))
                .foregroundStyle(.tertiary)
            Text("Versammlungen konnten nicht geladen werden.")
                .font(.headline)
            Text(message)
                .font(.caption)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
            Button("Erneut versuchen", action: onReload)
                .buttonStyle(.borderedProminent)
        }
        .padding()
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func row(for a: AssemblySummary) -> some View {
        NavigationLink {
            AssemblyDetailView(assemblyId: a.id, fallback: a)
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
    private func propertyLine(for a: AssemblySummary) -> String? {
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
            return s
        }())
}
