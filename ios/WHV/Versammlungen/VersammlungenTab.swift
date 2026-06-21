// ETV tab — a segmented control switches between Versammlungen
// (Eigentümerversammlungen) and Beschlüsse (Umlaufbeschlüsse). Both are
// property-scoped and reload when the active Liegenschaft changes; each owns a
// small ObservableObject for its fetch + loading/error state.
//
// Live sources: GET /me/properties/{id}/assemblies and GET /me/resolutions
// (filtered to the active property). Beschlüsse are read-only — voting happens
// via the e-mail link.

import SwiftUI

enum ETVSection: String, CaseIterable, Hashable {
    case versammlungen
    case beschluesse
}

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

@MainActor
final class ResolutionListStore: ObservableObject {
    @Published private(set) var resolutions: [ResolutionSummary] = []
    @Published private(set) var isLoading = false
    @Published var lastError: String?

    private(set) var loadedPropertyId: String?
    var onUnauthorized: (() -> Void)?
    private let api: APIClient

    init(api: APIClient = APIClient()) {
        self.api = api
    }

    func load(propertyId: String, force: Bool = false) async {
        if loadedPropertyId == propertyId, !resolutions.isEmpty, !force {
            return
        }
        lastError = nil
        isLoading = true
        defer { isLoading = false }
        do {
            resolutions = try await api.listMyResolutions(propertyId: propertyId)
            loadedPropertyId = propertyId
        } catch APIError.unauthorized {
            onUnauthorized?()
        } catch let error as APIError {
            lastError = error.errorDescription
        } catch {
            lastError = error.localizedDescription
        }
    }
}

struct VersammlungenTab: View {
    @EnvironmentObject var liegenschaftStore: LiegenschaftStore
    @EnvironmentObject var authStore: AuthStore
    @EnvironmentObject var deepLinkRouter: DeepLinkRouter
    @StateObject private var store = AssemblyListStore()
    @StateObject private var resolutionStore = ResolutionListStore()
    @State private var section: ETVSection = .versammlungen

    var body: some View {
        NavigationStack(path: $deepLinkRouter.etvPath) {
            content
                .navigationTitle(section == .beschluesse ? "Beschlüsse" : "Versammlungen")
                // Single String path: plain ids → assembly detail (also how
                // widget deep-links push); "res:"-prefixed tokens → Beschluss
                // detail. One destination keeps back-nav consistent.
                .navigationDestination(for: String.self) { token in
                    if let rid = resolutionToken(token) {
                        ResolutionDetailView(
                            id: rid,
                            fallback: resolutionStore.resolutions.first { $0.id == rid }
                        )
                    } else {
                        AssemblyDetailView(
                            assemblyId: token,
                            fallback: store.assemblies.first { $0.id == token }
                        )
                    }
                }
                .toolbar {
                    if let l = liegenschaftStore.selected {
                        ToolbarItem(placement: .topBarTrailing) {
                            Button {
                                Task {
                                    if section == .beschluesse {
                                        await resolutionStore.load(propertyId: l.id, force: true)
                                    } else {
                                        await store.load(propertyId: l.id, force: true)
                                    }
                                }
                            } label: {
                                Image(systemName: "arrow.clockwise")
                            }
                            .disabled(section == .beschluesse ? resolutionStore.isLoading : store.isLoading)
                        }
                    }
                }
                .onAppear {
                    store.onUnauthorized = { [weak authStore] in authStore?.signOut() }
                    resolutionStore.onUnauthorized = { [weak authStore] in authStore?.signOut() }
                }
        }
    }

    /// Returns the resolution id for a "res:"-prefixed nav token, else nil.
    private func resolutionToken(_ token: String) -> String? {
        token.hasPrefix("res:") ? String(token.dropFirst(4)) : nil
    }

    @ViewBuilder
    private var content: some View {
        if let l = liegenschaftStore.selected {
            VStack(spacing: 0) {
                Picker("", selection: $section) {
                    Text("Versammlungen").tag(ETVSection.versammlungen)
                    Text("Beschlüsse").tag(ETVSection.beschluesse)
                }
                .pickerStyle(.segmented)
                .padding(.horizontal)
                .padding(.vertical, 8)

                switch section {
                case .versammlungen:
                    AssemblyList(
                        assemblies: store.assemblies, isLoading: store.isLoading, error: store.lastError
                    ) {
                        Task { await store.load(propertyId: l.id, force: true) }
                    }
                    .task(id: l.id) { await store.load(propertyId: l.id) }
                case .beschluesse:
                    BeschluesseList(
                        resolutions: resolutionStore.resolutions,
                        isLoading: resolutionStore.isLoading,
                        error: resolutionStore.lastError
                    ) {
                        Task { await resolutionStore.load(propertyId: l.id, force: true) }
                    }
                    .task(id: l.id) { await resolutionStore.load(propertyId: l.id) }
                }
            }
        } else {
            ContentUnavailableView(
                "Keine Liegenschaft gewählt",
                systemImage: "building.2",
                description: Text("Versammlungen werden pro Liegenschaft angezeigt.")
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
                    description: Text("Sobald die Verwaltung eine Versammlung anlegt, erscheint sie hier.")
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
        NavigationLink(value: a.id) {
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

private struct BeschluesseList: View {
    let resolutions: [ResolutionSummary]
    let isLoading: Bool
    let error: String?
    let onReload: () -> Void

    private var open: [ResolutionSummary] {
        resolutions.filter { $0.status == .offen }.sorted { $0.closes_at < $1.closes_at }
    }
    private var decided: [ResolutionSummary] {
        resolutions.filter { $0.status != .offen }
            .sorted { ($0.decided_at ?? $0.closes_at) > ($1.decided_at ?? $1.closes_at) }
    }

    var body: some View {
        Group {
            if isLoading && resolutions.isEmpty {
                VStack(spacing: 12) {
                    ProgressView()
                    Text("Beschlüsse werden geladen …")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if let err = error, resolutions.isEmpty {
                errorView(err)
            } else if resolutions.isEmpty {
                ContentUnavailableView(
                    "Keine Beschlüsse",
                    systemImage: "doc.plaintext",
                    description: Text("Umlaufbeschlüsse erscheinen hier, sobald die Verwaltung sie startet.")
                )
            } else {
                List {
                    if !open.isEmpty {
                        Section("Offen") { ForEach(open) { row(for: $0) } }
                    }
                    if !decided.isEmpty {
                        Section("Entschieden") { ForEach(decided) { row(for: $0) } }
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
            Text("Beschlüsse konnten nicht geladen werden.")
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

    private func row(for r: ResolutionSummary) -> some View {
        NavigationLink(value: "res:\(r.id)") {
            HStack(alignment: .top, spacing: 12) {
                Image(systemName: "doc.plaintext.fill")
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(.white)
                    .frame(width: 36, height: 36)
                    .background(statusColor(r.status))
                    .clipShape(RoundedRectangle(cornerRadius: 8))
                VStack(alignment: .leading, spacing: 4) {
                    Text(r.title)
                        .font(.subheadline.weight(.semibold))
                        .lineLimit(2)
                    HStack(spacing: 8) {
                        Text(r.status.label)
                            .font(.caption2.weight(.semibold))
                            .padding(.horizontal, 7)
                            .padding(.vertical, 2)
                            .background(statusColor(r.status).opacity(0.18))
                            .foregroundStyle(statusColor(r.status))
                            .clipShape(Capsule())
                        if r.status == .offen {
                            Text("Frist: \(r.closes_at.formatted(.dateTime.day().month().year()))")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        } else if let d = r.decided_at {
                            Text(d.formatted(.dateTime.day().month().year()))
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .padding(.vertical, 4)
        }
    }
}

/// Locale-aware date-range formatter. Uses Foundation's
/// `formatted(.dateTime…)` which respects the current locale, so
/// English readers see "28 Apr 2026, 18:00 – 21:00" with their
/// regional ordering instead of the hardcoded German "dd.MM.yyyy".
private func formatDateRange(_ start: Date, _ end: Date) -> String {
    let sameDay = Calendar.current.isDate(start, inSameDayAs: end)
    if sameDay {
        let date = start.formatted(.dateTime.day().month().year())
        let s = start.formatted(.dateTime.hour().minute())
        let e = end.formatted(.dateTime.hour().minute())
        return "\(date), \(s) – \(e)"
    }
    let s = start.formatted(.dateTime.day().month().year().hour().minute())
    let e = end.formatted(.dateTime.day().month().year().hour().minute())
    return "\(s) – \(e)"
}

#Preview {
    VersammlungenTab()
        .environmentObject({
            let s = LiegenschaftStore()
            return s
        }())
}
