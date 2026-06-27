// Mitteilungen — list of published announcements for the active
// Liegenschaft. Same shape as VersammlungenTab: a per-tab store
// owns the fetch, the view layer renders loading/error/empty
// branches plus pull-to-refresh.
//
// Source: GET /me/properties/{id}/announcements. Soft-deleted +
// audience-mismatched rows are filtered server-side, so the
// client renders whatever the API hands back without further
// gating.

import SwiftUI

@MainActor
final class AnnouncementListStore: ObservableObject {
    @Published private(set) var announcements: [AnnouncementSummary] = []
    @Published private(set) var isLoading = false
    @Published var lastError: String?

    private(set) var loadedPropertyId: String?
    var onUnauthorized: (() -> Void)?
    private let api: APIClient

    init(api: APIClient = APIClient()) {
        self.api = api
    }

    func load(propertyId: String, force: Bool = false) async {
        if loadedPropertyId == propertyId, !announcements.isEmpty, !force {
            return
        }
        lastError = nil
        isLoading = true
        defer { isLoading = false }
        do {
            let rows = try await api.listMyAnnouncementsForProperty(propertyId)
            self.announcements = rows
            self.loadedPropertyId = propertyId
        } catch APIError.unauthorized {
            onUnauthorized?()
        } catch let error as APIError {
            self.lastError = error.errorDescription
        } catch {
            self.lastError = error.localizedDescription
        }
    }
}

struct MitteilungenTab: View {
    @EnvironmentObject var liegenschaftStore: LiegenschaftStore
    @EnvironmentObject var authStore: AuthStore
    @EnvironmentObject var deepLinkRouter: DeepLinkRouter
    @StateObject private var store = AnnouncementListStore()

    var body: some View {
        NavigationStack(path: $deepLinkRouter.mitteilungenPath) {
            content
                .navigationTitle("News")
                .navigationDestination(for: String.self) { announcementId in
                    AnnouncementDetailView(
                        announcementId: announcementId,
                        fallback: store.announcements.first { $0.id == announcementId }
                    )
                }
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
            AnnouncementList(
                announcements: store.announcements,
                isLoading: store.isLoading,
                error: store.lastError
            ) {
                Task { await store.load(propertyId: l.id, force: true) }
            }
            .task(id: l.id) {
                await store.load(propertyId: l.id)
            }
        } else {
            ContentUnavailableView(
                "Keine Liegenschaft gewählt",
                systemImage: "building.2",
                description: Text("Mitteilungen werden pro Liegenschaft angezeigt.")
            )
        }
    }
}

private struct AnnouncementList: View {
    let announcements: [AnnouncementSummary]
    let isLoading: Bool
    let error: String?
    let onReload: () -> Void

    /// Only ever show published rows. The server filters most
    /// unpublished ones already (notification_sent_at == null means
    /// scheduled-but-unsent), but we add a belt-and-braces check.
    private var published: [AnnouncementSummary] {
        announcements
            .filter { $0.notification_sent_at != nil }
            .sorted { ($0.notification_sent_at ?? .distantPast) > ($1.notification_sent_at ?? .distantPast) }
    }

    var body: some View {
        Group {
            if isLoading && announcements.isEmpty {
                VStack(spacing: 12) {
                    ProgressView()
                    Text("Mitteilungen werden geladen …")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if let err = error, announcements.isEmpty {
                errorView(err)
            } else if published.isEmpty {
                ContentUnavailableView(
                    "Keine Mitteilungen",
                    systemImage: "megaphone",
                    description: Text("Sobald die Verwaltung eine Mitteilung veröffentlicht, erscheint sie hier.")
                )
            } else {
                List {
                    ForEach(published) { row(for: $0) }
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
            Text("Mitteilungen konnten nicht geladen werden.")
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

    private func row(for a: AnnouncementSummary) -> some View {
        NavigationLink(value: a.id) {
            HStack(alignment: .center, spacing: 12) {
                Image(systemName: "megaphone.fill")
                    .font(.title3)
                    .foregroundStyle(.white)
                    .frame(width: 36, height: 36)
                    .background(Color.accentColor)
                    .clipShape(RoundedRectangle(cornerRadius: 8))
                VStack(alignment: .leading, spacing: 3) {
                    HStack(alignment: .firstTextBaseline, spacing: 6) {
                        Text(a.title)
                            .font(.subheadline.weight(.semibold))
                            .lineLimit(2)
                        // New = published (notification_sent_at) within the
                        // last neuBadgeWindowDays.
                        if isRecentlyNew(a.notification_sent_at) {
                            NeuBadge()
                        }
                    }
                    if let prop = a.property_name, !prop.isEmpty {
                        HStack(spacing: 6) {
                            Image(systemName: "building.2")
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                            Text(prop)
                                .font(.caption2.weight(.medium))
                                .foregroundStyle(.secondary)
                                .lineLimit(1)
                        }
                    }
                    Text(a.body)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                    if let sent = a.notification_sent_at {
                        Text(formatPublished(sent))
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .padding(.vertical, 4)
        }
    }
}

/// "Veröffentlicht am 28.04.2026, 18:00" — the date the
/// Mitteilung went out, matching how the portal labels it.
func formatPublished(_ date: Date) -> String {
    let df = DateFormatter()
    df.locale = Locale(identifier: "de_DE")
    df.dateFormat = "dd.MM.yyyy, HH:mm 'Uhr'"
    return "Veröffentlicht am \(df.string(from: date))"
}

#Preview {
    MitteilungenTab()
        .environmentObject({
            let s = LiegenschaftStore()
            return s
        }())
        .environmentObject(AuthStore())
}
