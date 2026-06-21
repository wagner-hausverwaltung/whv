// Beschluss (Umlaufbeschluss) detail — read-only owner view. Loads
// /me/resolutions/{id} and shows status, Frist, Beschlusstext, the tally
// (Ja/Nein/Enthaltung + Quorum), the caller's own vote and the result.
// Voting itself happens via the e-mail link, so there are no actions here —
// mirrors the portal's ResolutionDetailPage for owners.

import SwiftUI

@MainActor
final class ResolutionDetailStore: ObservableObject {
    @Published private(set) var detail: ResolutionDetail?
    @Published private(set) var isLoading = false
    @Published var lastError: String?

    var onUnauthorized: (() -> Void)?
    private let api: APIClient
    init(api: APIClient = APIClient()) { self.api = api }

    func load(id: String) async {
        isLoading = true
        defer { isLoading = false }
        do {
            detail = try await api.getResolutionDetail(id: id)
        } catch APIError.unauthorized {
            onUnauthorized?()
        } catch let e as APIError {
            lastError = e.errorDescription
        } catch {
            lastError = error.localizedDescription
        }
    }
}

struct ResolutionDetailView: View {
    let id: String
    let fallback: ResolutionSummary?

    @StateObject private var store = ResolutionDetailStore()
    @EnvironmentObject var authStore: AuthStore

    init(id: String, fallback: ResolutionSummary? = nil) {
        self.id = id
        self.fallback = fallback
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                header
                if let d = store.detail {
                    if !d.description.isEmpty {
                        section("Beschlusstext") { Text(d.description).font(.subheadline) }
                    }
                    if d.status != .offen || d.tally.cast > 0 { tallySection(d.tally) }
                    if let mv = d.my_vote { myVoteSection(mv) }
                    if let result = d.result, !result.isEmpty {
                        section("Ergebnis") { Text(result).font(.subheadline) }
                    }
                } else if store.isLoading {
                    ProgressView().frame(maxWidth: .infinity).padding(.top, 40)
                } else if let err = store.lastError {
                    Text(err).font(.subheadline).foregroundStyle(.red)
                }
                Text("Die Abstimmung erfolgt per E-Mail über den Link in Ihrer Einladung.")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
                    .italic()
            }
            .padding(20)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .navigationTitle("Beschluss")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear { store.onUnauthorized = { [weak authStore] in authStore?.signOut() } }
        .task { await store.load(id: id) }
    }

    // MARK: - Header

    private var resolvedTitle: String { store.detail?.title ?? fallback?.title ?? "—" }
    private var resolvedStatus: ResolutionStatus { store.detail?.status ?? fallback?.status ?? .offen }

    private var header: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(resolvedTitle).font(.title3.bold())
            HStack(spacing: 8) {
                statusChip(resolvedStatus)
                if let mode = store.detail?.mode {
                    Text(mode.label).font(.caption).foregroundStyle(.secondary)
                }
                Spacer(minLength: 0)
            }
            if resolvedStatus.isOpen, let c = store.detail?.closes_at ?? fallback?.closes_at {
                row(icon: "clock", text: "Frist: \(c.formatted(.dateTime.day().month().year()))")
            } else if let d = store.detail?.decided_at ?? fallback?.decided_at {
                row(icon: "checkmark.seal", text: "Entschieden: \(d.formatted(.dateTime.day().month().year()))")
            }
        }
    }

    private func row(icon: String, text: String) -> some View {
        Label { Text(text) } icon: { Image(systemName: icon) }
            .font(.caption)
            .foregroundStyle(.secondary)
    }

    // MARK: - Sections

    private func tallySection(_ t: ResolutionTally) -> some View {
        section("Abstimmung") {
            VStack(alignment: .leading, spacing: 6) {
                tallyRow("Ja", t.ja)
                tallyRow("Nein", t.nein)
                tallyRow("Enthaltung", t.enthaltung)
                Divider()
                HStack {
                    Text("Abgegeben").font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    Text("\(t.cast) / \(t.eligible_voters)").font(.subheadline.monospacedDigit())
                }
                HStack {
                    Text("Quorum").font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    Text(t.quorum_met ? "erfüllt" : "nicht erfüllt")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(t.quorum_met ? .green : .orange)
                }
            }
        }
    }

    private func tallyRow(_ label: LocalizedStringResource, _ count: Int) -> some View {
        HStack {
            Text(label).font(.subheadline)
            Spacer()
            Text("\(count)").font(.subheadline.monospacedDigit().weight(.semibold))
        }
    }

    private func myVoteSection(_ v: ResolutionVote) -> some View {
        section("Ihre Stimme") {
            HStack(spacing: 8) {
                Image(systemName: "checkmark.circle.fill").foregroundStyle(.green)
                Text(v.choice.label).font(.subheadline.weight(.semibold))
                Spacer()
                Text(v.voted_at.formatted(.dateTime.day().month().year()))
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
    }

    @ViewBuilder
    private func section<Content: View>(
        _ title: LocalizedStringResource, @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
                .textCase(.uppercase)
            VStack(alignment: .leading, spacing: 6) { content() }
                .padding(12)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(RoundedRectangle(cornerRadius: 10).fill(Color(.secondarySystemBackground)))
        }
    }

    @ViewBuilder
    private func statusChip(_ status: ResolutionStatus) -> some View {
        Text(status.label)
            .font(.caption2.weight(.semibold))
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(statusColor(status).opacity(0.18))
            .foregroundStyle(statusColor(status))
            .clipShape(Capsule())
    }
}

/// Shared status → colour mapping (used by the detail chip + the list badge).
func statusColor(_ status: ResolutionStatus) -> Color {
    switch status {
    case .angenommen: return .green
    case .abgelehnt: return .red
    case .offen: return .accentColor
    case .geschlossen: return .orange
    case .entwurf: return .secondary
    }
}
