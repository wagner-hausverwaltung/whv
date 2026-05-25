// Detail screen for a single Mitteilung.
//
// Single fetch: GET /me/announcements/{id} returns header + body +
// attachments + comments in one round-trip. The view renders the
// summary (passed in from the list row) immediately while the
// detail call is in flight, then swaps in the richer fields.
//
// Same Q&A pattern as ETV — composer at the bottom POSTs to
// /me/announcements/{id}/comments; server fans out an email to
// Verwalter + prior commenters.

import SwiftUI

@MainActor
final class AnnouncementDetailStore: ObservableObject {
    @Published private(set) var detail: AnnouncementDetail?
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
            self.detail = try await api.getAnnouncementDetail(id: id)
        } catch APIError.unauthorized {
            onUnauthorized?()
        } catch let error as APIError {
            self.lastError = error.errorDescription
        } catch {
            self.lastError = error.localizedDescription
        }
    }

    @discardableResult
    func postComment(announcementId: String, body: String) async -> Bool {
        let trimmed = body.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return false }
        isPosting = true
        defer { isPosting = false }
        do {
            let created = try await api.postAnnouncementComment(
                announcementId: announcementId,
                body: trimmed
            )
            // Append optimistically — backend round-trip already
            // succeeded, so the new row is real. The detail object
            // is immutable so we rebuild with the new comment
            // appended.
            if let d = detail {
                let merged = d.comments + [created]
                self.detail = AnnouncementDetail(
                    id: d.id,
                    organization_id: d.organization_id,
                    property_id: d.property_id,
                    created_by_user_id: d.created_by_user_id,
                    title: d.title,
                    body: d.body,
                    audience_eigentuemer: d.audience_eigentuemer,
                    audience_mieter: d.audience_mieter,
                    audience_beirat: d.audience_beirat,
                    created_at: d.created_at,
                    updated_at: d.updated_at,
                    scheduled_publish_at: d.scheduled_publish_at,
                    notification_sent_at: d.notification_sent_at,
                    property_name: d.property_name,
                    creator_email: d.creator_email,
                    is_edited: d.is_edited,
                    attachment_count: d.attachment_count,
                    comment_count: merged.count,
                    attachments: d.attachments,
                    comments: merged
                )
            }
            return true
        } catch APIError.unauthorized {
            onUnauthorized?()
            return false
        } catch let error as APIError {
            self.lastError = error.errorDescription
            return false
        } catch {
            self.lastError = error.localizedDescription
            return false
        }
    }

    func openAttachment(announcementId: String, attachment: AnnouncementAttachment) async {
        isDownloading = true
        defer { isDownloading = false }
        do {
            self.previewURL = try await api.downloadAnnouncementAttachment(
                announcementId: announcementId,
                attachmentId: attachment.id,
                filename: attachment.filename
            )
        } catch APIError.unauthorized {
            onUnauthorized?()
        } catch let error as APIError {
            self.lastError = error.errorDescription
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

struct AnnouncementDetailView: View {
    let announcementId: String
    let fallback: AnnouncementSummary?

    @StateObject private var store = AnnouncementDetailStore()
    @State private var commentDraft = ""
    @EnvironmentObject var authStore: AuthStore

    init(announcementId: String, fallback: AnnouncementSummary? = nil) {
        self.announcementId = announcementId
        self.fallback = fallback
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                headerCard
                bodySection
                attachmentsSection
                commentsSection
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 16)
        }
        .navigationTitle("Mitteilung")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            store.onUnauthorized = { [weak authStore] in
                authStore?.signOut()
            }
        }
        .task(id: announcementId) {
            await store.load(id: announcementId)
        }
        .refreshable {
            await store.load(id: announcementId)
        }
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

    private var displayTitle: String {
        store.detail?.title ?? fallback?.title ?? "—"
    }

    private var displayPropertyName: String? {
        store.detail?.property_name ?? fallback?.property_name
    }

    private var displayPublished: Date? {
        store.detail?.notification_sent_at ?? fallback?.notification_sent_at
    }

    private var displayBody: String {
        store.detail?.body ?? fallback?.body ?? ""
    }

    private var headerCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 8) {
                Label("Mitteilung", systemImage: "megaphone.fill")
                    .font(.caption.weight(.semibold))
                    .padding(.horizontal, 10)
                    .padding(.vertical, 4)
                    .background(Color.accentColor)
                    .foregroundStyle(.white)
                    .clipShape(Capsule())
                if store.isLoading {
                    ProgressView().controlSize(.small)
                }
                if store.detail?.is_edited == true {
                    Text("bearbeitet")
                        .font(.caption2)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 3)
                        .background(Color(.tertiarySystemFill))
                        .foregroundStyle(.secondary)
                        .clipShape(Capsule())
                }
            }
            if let propertyName = displayPropertyName, !propertyName.isEmpty {
                Label {
                    Text(propertyName)
                        .font(.caption.weight(.medium))
                        .foregroundStyle(.secondary)
                } icon: {
                    Image(systemName: "building.2")
                        .foregroundStyle(.secondary)
                }
            }
            Text(displayTitle)
                .font(.title3.bold())
            VStack(alignment: .leading, spacing: 4) {
                if let sent = displayPublished {
                    Label {
                        Text(formatPublished(sent))
                            .font(.caption)
                    } icon: {
                        Image(systemName: "calendar")
                    }
                }
                if let email = store.detail?.creator_email {
                    Label {
                        Text(email)
                            .font(.caption)
                    } icon: {
                        Image(systemName: "person")
                    }
                }
                if let labels = store.detail?.audienceLabels, !labels.isEmpty {
                    Label {
                        Text(labels.joined(separator: ", "))
                            .font(.caption)
                    } icon: {
                        Image(systemName: "person.3")
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

    private var bodySection: some View {
        Group {
            if !displayBody.isEmpty {
                Text(displayBody)
                    .font(.body)
                    .foregroundStyle(.primary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }

    @ViewBuilder
    private var attachmentsSection: some View {
        if let attachments = store.detail?.attachments, !attachments.isEmpty {
            VStack(alignment: .leading, spacing: 12) {
                Text("Anhänge")
                    .font(.title3.bold())
                    .frame(maxWidth: .infinity, alignment: .leading)
                ForEach(attachments) { attachment in
                    Button {
                        Task {
                            await store.openAttachment(
                                announcementId: announcementId,
                                attachment: attachment
                            )
                        }
                    } label: {
                        HStack(spacing: 12) {
                            Image(systemName: iconName(for: attachment))
                                .font(.title3)
                                .foregroundStyle(.tint)
                                .frame(width: 36, height: 36)
                                .background(Color.accentColor.opacity(0.12))
                                .clipShape(RoundedRectangle(cornerRadius: 8))
                            VStack(alignment: .leading, spacing: 2) {
                                Text(attachment.filename)
                                    .font(.subheadline.weight(.semibold))
                                    .foregroundStyle(.primary)
                                    .lineLimit(1)
                                Text(formatSize(attachment.size_bytes))
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                            Spacer()
                            if store.isDownloading {
                                ProgressView()
                            } else {
                                Image(systemName: "arrow.down.circle")
                                    .font(.body)
                                    .foregroundStyle(.tertiary)
                            }
                        }
                        .padding(12)
                        .background(
                            RoundedRectangle(cornerRadius: 10)
                                .fill(Color(.secondarySystemBackground))
                        )
                    }
                    .buttonStyle(.plain)
                    .disabled(store.isDownloading)
                }
            }
        }
    }

    private func iconName(for attachment: AnnouncementAttachment) -> String {
        let mime = attachment.mime_type ?? ""
        if mime.contains("pdf") { return "doc.text.fill" }
        if mime.hasPrefix("image/") { return "photo.fill" }
        if mime.contains("word") || attachment.filename.lowercased().hasSuffix(".docx") {
            return "doc.fill"
        }
        return "paperclip"
    }

    private func formatSize(_ bytes: Int) -> String {
        ByteCountFormatter.string(fromByteCount: Int64(bytes), countStyle: .file)
    }

    @ViewBuilder
    private var commentsSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Fragen & Antworten")
                .font(.title3.bold())
                .frame(maxWidth: .infinity, alignment: .leading)
            if let comments = store.detail?.comments, !comments.isEmpty {
                ForEach(comments.sorted(by: { $0.created_at < $1.created_at })) { c in
                    CommentRow(comment: c)
                }
            } else if store.isLoading {
                ProgressView()
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 12)
            } else {
                Text(
                    "Hier können Sie Rückfragen zu dieser Mitteilung "
                    + "stellen. Antworten erscheinen direkt unter der "
                    + "Frage."
                )
                .font(.subheadline)
                .foregroundStyle(.secondary)
            }
            commentComposer
        }
    }

    private var commentComposer: some View {
        VStack(alignment: .leading, spacing: 8) {
            TextField(
                "Frage oder Antwort verfassen …",
                text: $commentDraft,
                axis: .vertical
            )
            .lineLimit(2...6)
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
                        let ok = await store.postComment(
                            announcementId: announcementId,
                            body: commentDraft
                        )
                        if ok { commentDraft = "" }
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
                    || commentDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                )
            }
        }
        .padding(.top, 4)
    }
}

private struct CommentRow: View {
    let comment: AnnouncementComment

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(comment.author_email ?? "—")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.primary)
                Spacer(minLength: 0)
                Text(comment.created_at.formatted(.dateTime.day().month().year().hour().minute()))
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
            Text(comment.body)
                .font(.callout)
                .foregroundStyle(.primary)
                .frame(maxWidth: .infinity, alignment: .leading)
            if comment.edited_at != nil {
                Text("bearbeitet")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 10)
                .fill(Color(.secondarySystemBackground))
        )
    }
}
