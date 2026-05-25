// Tickets — list of every ticket the signed-in user can see,
// grouped into Aktuell vs. Geschlossen. Mirrors Versammlungen +
// Mitteilungen scaffolding: per-tab store owns the fetch, view
// layer renders loading/error/empty branches plus pull-to-refresh
// + a "Neues Ticket" toolbar action.

import SwiftUI

@MainActor
final class TicketsListStore: ObservableObject {
    @Published private(set) var tickets: [TicketSummary] = []
    @Published private(set) var isLoading = false
    @Published var lastError: String?

    var onUnauthorized: (() -> Void)?
    private let api: APIClient

    init(api: APIClient = APIClient()) {
        self.api = api
    }

    func load(force: Bool = false) async {
        if !tickets.isEmpty, !force, !isLoading { return }
        lastError = nil
        isLoading = true
        defer { isLoading = false }
        do {
            self.tickets = try await api.listMyTickets()
        } catch APIError.unauthorized {
            onUnauthorized?()
        } catch let error as APIError {
            self.lastError = error.errorDescription
        } catch {
            self.lastError = error.localizedDescription
        }
    }

    /// After creating a ticket via the New-Ticket sheet, refetch
    /// from the server so the new row appears with whatever joins +
    /// timestamps the backend computed. Cheaper than building an
    /// optimistic summary by hand for a list endpoint that's
    /// already fast.
    func reload() async {
        await load(force: true)
    }
}

struct TicketsTab: View {
    @EnvironmentObject var authStore: AuthStore
    @StateObject private var store = TicketsListStore()
    @State private var newTicketOpen = false

    var body: some View {
        NavigationStack {
            content
                .navigationTitle("Tickets")
                .toolbar {
                    ToolbarItem(placement: .topBarTrailing) {
                        Button {
                            newTicketOpen = true
                        } label: {
                            Image(systemName: "square.and.pencil")
                        }
                    }
                    ToolbarItem(placement: .topBarLeading) {
                        Button {
                            Task { await store.load(force: true) }
                        } label: {
                            Image(systemName: "arrow.clockwise")
                        }
                        .disabled(store.isLoading)
                    }
                }
                .onAppear {
                    store.onUnauthorized = { [weak authStore] in
                        authStore?.signOut()
                    }
                }
                .task { await store.load() }
                .sheet(isPresented: $newTicketOpen) {
                    NewTicketSheet { _ in
                        Task { await store.reload() }
                    }
                }
        }
    }

    @ViewBuilder
    private var content: some View {
        if store.isLoading && store.tickets.isEmpty {
            ProgressView("Tickets werden geladen …")
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if let err = store.lastError, store.tickets.isEmpty {
            VStack(spacing: 12) {
                Image(systemName: "exclamationmark.triangle")
                    .font(.system(size: 48))
                    .foregroundStyle(.tertiary)
                Text("Tickets konnten nicht geladen werden.")
                    .font(.headline)
                Text(err)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                Button("Erneut versuchen") {
                    Task { await store.load(force: true) }
                }
                .buttonStyle(.borderedProminent)
            }
            .padding()
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if store.tickets.isEmpty {
            ContentUnavailableView(
                "Keine Tickets",
                systemImage: "tray",
                description: Text(
                    "Hier erscheinen Ihre Anfragen + Schadensmeldungen "
                    + "an die Verwaltung."
                )
            )
        } else {
            TicketsList(tickets: store.tickets) {
                Task { await store.load(force: true) }
            }
        }
    }
}

private struct TicketsList: View {
    let tickets: [TicketSummary]
    let onReload: () -> Void

    /// Closed tickets are noise once they're done — start collapsed
    /// so the user lands on the active queue. Tap the header to
    /// expand. Tickets that close while the screen is open stay
    /// hidden until the user opts in, which is the right default
    /// for an "Aktuell" focused list.
    @State private var closedExpanded = false

    private var active: [TicketSummary] {
        tickets
            .filter { $0.status.isActive }
            .sorted { $0.last_message_at > $1.last_message_at }
    }
    private var closed: [TicketSummary] {
        tickets
            .filter { !$0.status.isActive }
            .sorted { ($0.closed_at ?? $0.last_message_at) > ($1.closed_at ?? $1.last_message_at) }
    }

    var body: some View {
        List {
            if !active.isEmpty {
                Section("Aktuell") {
                    ForEach(active) { row(for: $0) }
                }
            }
            if !closed.isEmpty {
                Section {
                    if closedExpanded {
                        ForEach(closed) { row(for: $0) }
                    }
                } header: {
                    Button {
                        withAnimation(.easeInOut(duration: 0.2)) {
                            closedExpanded.toggle()
                        }
                    } label: {
                        HStack {
                            Text("Geschlossen (\(closed.count))")
                                .font(.subheadline.weight(.semibold))
                                .textCase(nil)  // override the SwiftUI uppercase default
                                .foregroundStyle(.primary)
                            Spacer()
                            Image(systemName: "chevron.right")
                                .font(.caption.weight(.semibold))
                                .foregroundStyle(.secondary)
                                .rotationEffect(.degrees(closedExpanded ? 90 : 0))
                        }
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                }
            }
        }
        .listStyle(.insetGrouped)
        .listSectionSpacing(20)  // a bit more breathing room between Aktuell + Geschlossen
        .refreshable { onReload() }
    }

    private func row(for t: TicketSummary) -> some View {
        NavigationLink {
            TicketDetailView(ticketId: t.id, fallback: t)
        } label: {
            HStack(alignment: .center, spacing: 12) {
                Image(systemName: "tray.full.fill")
                    .font(.title3)
                    .foregroundStyle(.white)
                    .frame(width: 36, height: 36)
                    .background(statusColor(t.status))
                    .clipShape(RoundedRectangle(cornerRadius: 8))
                VStack(alignment: .leading, spacing: 3) {
                    Text(t.subject)
                        .font(.subheadline.weight(.semibold))
                        .lineLimit(2)
                    HStack(spacing: 6) {
                        Text(t.status.label)
                            .font(.caption2.weight(.semibold))
                            .padding(.horizontal, 6)
                            .padding(.vertical, 2)
                            .background(statusBackground(t.status))
                            .foregroundStyle(statusForeground(t.status))
                            .clipShape(Capsule())
                        Text(t.category.label)
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                    if let prop = t.property_name, !prop.isEmpty {
                        HStack(spacing: 6) {
                            Image(systemName: "building.2")
                                .font(.caption2)
                                .foregroundStyle(.tertiary)
                            Text(prop)
                                .font(.caption2)
                                .foregroundStyle(.tertiary)
                                .lineLimit(1)
                        }
                    }
                    Text(t.last_message_at.formatted(.dateTime.day().month().year().hour().minute()))
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .padding(.vertical, 4)
        }
    }

    private func statusColor(_ status: TicketStatus) -> Color {
        switch status {
        case .neu: return .blue
        case .offen: return .orange
        case .wartetAufKunde: return .purple
        case .geschlossen: return .secondary
        }
    }
    private func statusBackground(_ status: TicketStatus) -> Color {
        switch status {
        case .neu: return .blue.opacity(0.15)
        case .offen: return .orange.opacity(0.15)
        case .wartetAufKunde: return .purple.opacity(0.15)
        case .geschlossen: return Color(.tertiarySystemFill)
        }
    }
    private func statusForeground(_ status: TicketStatus) -> Color {
        switch status {
        case .neu: return .blue
        case .offen: return .orange
        case .wartetAufKunde: return .purple
        case .geschlossen: return .secondary
        }
    }
}

#Preview {
    TicketsTab()
        .environmentObject(AuthStore())
}
