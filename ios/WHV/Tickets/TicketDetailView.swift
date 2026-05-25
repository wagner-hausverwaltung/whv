// Ticket detail — subject + status header, message thread, reply
// composer at the bottom. Mirrors the ETV + Mitteilungen detail
// scaffolding: a per-screen store owns the fetch + posts; the view
// renders loading/error/data branches.
//
// Attachments per message: tap → authed download → FilePreview
// sheet. Same QuickLook wrapper used by signed protocols and
// announcement attachments.

import SwiftUI

@MainActor
final class TicketDetailStore: ObservableObject {
    @Published private(set) var detail: TicketDetail?
    @Published private(set) var isLoading = false
    @Published private(set) var isPosting = false
    @Published private(set) var isDownloading = false
    @Published private(set) var previewURL: URL?
    @Published var lastError: String?

    var onUnauthorized: (() -> Void)?
    private let api: APIClient

    init(api: APIClient = APIClient()) {
        self.api = api
    }

    func load(id: String) async {
        isLoading = true
        defer { isLoading = false }
        do {
            self.detail = try await api.getMyTicket(id: id)
        } catch APIError.unauthorized {
            onUnauthorized?()
        } catch let err as APIError {
            self.lastError = err.errorDescription
        } catch {
            self.lastError = error.localizedDescription
        }
    }

    @discardableResult
    func postMessage(ticketId: String, body: String) async -> Bool {
        let trimmed = body.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return false }
        isPosting = true
        defer { isPosting = false }
        do {
            _ = try await api.postMyTicketMessage(
                ticketId: ticketId,
                body: trimmed
            )
            // Refetch the whole detail so we pick up the
            // server-rendered author label + any status flip the
            // backend applied on commit (e.g. NEU → OFFEN).
            await load(id: ticketId)
            return true
        } catch APIError.unauthorized {
            onUnauthorized?()
            return false
        } catch let err as APIError {
            self.lastError = err.errorDescription
            return false
        } catch {
            self.lastError = error.localizedDescription
            return false
        }
    }

    func openAttachment(
        ticketId: String,
        attachment: TicketMessageAttachment
    ) async {
        isDownloading = true
        defer { isDownloading = false }
        do {
            self.previewURL = try await api.downloadTicketAttachment(
                ticketId: ticketId,
                attachmentId: attachment.id,
                filename: attachment.filename
            )
        } catch APIError.unauthorized {
            onUnauthorized?()
        } catch let err as APIError {
            self.lastError = err.errorDescription
        } catch {
            self.lastError = error.localizedDescription
        }
    }

    func dismissPreview() {
        if let url = previewURL {
            try? FileManager.default.removeItem(at: url)
        }
        previewURL = nil
    }
}

struct TicketDetailView: View {
    let ticketId: String
    let fallback: TicketSummary?

    @StateObject private var store = TicketDetailStore()
    @State private var replyDraft = ""
    @EnvironmentObject var authStore: AuthStore

    init(ticketId: String, fallback: TicketSummary? = nil) {
        self.ticketId = ticketId
        self.fallback = fallback
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                headerCard
                thread
                replyComposer
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 16)
        }
        .navigationTitle("Ticket")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            store.onUnauthorized = { [weak authStore] in
                authStore?.signOut()
            }
        }
        .task(id: ticketId) {
            await store.load(id: ticketId)
        }
        .refreshable { await store.load(id: ticketId) }
        .sheet(
            isPresented: Binding(
                get: { store.previewURL != nil },
                set: { open in if !open { store.dismissPreview() } }
            )
        ) {
            if let url = store.previewURL {
                FilePreview(url: url)
                    .ignoresSafeArea()
            }
        }
    }

    private var displaySubject: String {
        store.detail?.subject ?? fallback?.subject ?? "—"
    }
    private var displayStatus: TicketStatus {
        store.detail?.status ?? fallback?.status ?? .neu
    }
    private var displayCategory: TicketCategory {
        store.detail?.category ?? fallback?.category ?? .sonstigesOther
    }
    private var displayPropertyName: String? {
        store.detail?.property_name ?? fallback?.property_name
    }

    private var headerCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Text(displayStatus.label)
                    .font(.caption.weight(.semibold))
                    .padding(.horizontal, 10)
                    .padding(.vertical, 4)
                    .background(statusBackground(displayStatus))
                    .foregroundStyle(statusForeground(displayStatus))
                    .clipShape(Capsule())
                if store.isLoading {
                    ProgressView().controlSize(.small)
                }
            }
            Text(displaySubject)
                .font(.title3.bold())
            VStack(alignment: .leading, spacing: 4) {
                Label {
                    Text(displayCategory.label)
                        .font(.caption)
                } icon: {
                    Image(systemName: "tag")
                }
                if let prop = displayPropertyName, !prop.isEmpty {
                    Label {
                        Text(prop)
                            .font(.caption)
                    } icon: {
                        Image(systemName: "building.2")
                    }
                }
            }
            .foregroundStyle(.secondary)
        }
        .padding(16)
        .background(
            RoundedRectangle(cornerRadius: 12)
                .fill(Color(.secondarySystemBackground))
        )
    }

    @ViewBuilder
    private var thread: some View {
        if let messages = store.detail?.messages, !messages.isEmpty {
            VStack(alignment: .leading, spacing: 12) {
                Text("Verlauf")
                    .font(.title3.bold())
                    .frame(maxWidth: .infinity, alignment: .leading)
                ForEach(messages.sorted(by: { $0.created_at < $1.created_at })) { m in
                    messageRow(m)
                }
            }
        } else if store.isLoading {
            ProgressView()
                .frame(maxWidth: .infinity)
                .padding(.vertical, 24)
        }
    }

    private func messageRow(_ m: TicketMessage) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(m.author_email ?? "—")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.primary)
                Spacer(minLength: 0)
                Text(m.created_at.formatted(.dateTime.day().month().year().hour().minute()))
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
            Text(m.body)
                .font(.callout)
                .foregroundStyle(.primary)
                .frame(maxWidth: .infinity, alignment: .leading)
            if !m.attachments.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(m.attachments) { att in
                        Button {
                            Task {
                                await store.openAttachment(
                                    ticketId: ticketId,
                                    attachment: att
                                )
                            }
                        } label: {
                            HStack(spacing: 8) {
                                Image(systemName: "paperclip")
                                    .font(.caption)
                                    .foregroundStyle(.tint)
                                Text(att.filename)
                                    .font(.caption)
                                    .lineLimit(1)
                                Spacer(minLength: 0)
                                Text(ByteCountFormatter.string(
                                    fromByteCount: Int64(att.size_bytes),
                                    countStyle: .file
                                ))
                                .font(.caption2)
                                .foregroundStyle(.tertiary)
                            }
                            .padding(.horizontal, 10)
                            .padding(.vertical, 6)
                            .background(
                                RoundedRectangle(cornerRadius: 8)
                                    .fill(Color(.tertiarySystemBackground))
                            )
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 10)
                .fill(Color(.secondarySystemBackground))
        )
    }

    private var replyComposer: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Antworten")
                .font(.subheadline.weight(.semibold))
            TextField(
                "Ihre Antwort …",
                text: $replyDraft,
                axis: .vertical
            )
            .lineLimit(2...8)
            .textFieldStyle(.roundedBorder)
            HStack {
                if let err = store.lastError {
                    Text(err)
                        .font(.caption2)
                        .foregroundStyle(.red)
                        .lineLimit(2)
                }
                Spacer(minLength: 0)
                Button {
                    Task {
                        let ok = await store.postMessage(
                            ticketId: ticketId,
                            body: replyDraft
                        )
                        if ok { replyDraft = "" }
                    }
                } label: {
                    if store.isPosting {
                        ProgressView()
                    } else {
                        Label("Senden", systemImage: "paperplane.fill")
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(
                    store.isPosting
                    || replyDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                    || displayStatus == .geschlossen
                )
            }
            if displayStatus == .geschlossen {
                Text("Dieses Ticket ist geschlossen.")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
        }
        .padding(.top, 4)
    }

    private func statusBackground(_ status: TicketStatus) -> Color {
        switch status {
        case .neu: return .blue.opacity(0.18)
        case .offen: return .orange.opacity(0.18)
        case .wartetAufKunde: return .purple.opacity(0.18)
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
