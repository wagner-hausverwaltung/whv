// Single-screen ETV detail: header → agenda items → per-item
// Beschluss tally + Diskussion → signed-protocol PDF link → Fragen
// & Antworten thread.
//
// Fetches detail + comments live from
// GET /me/assemblies/{id} + GET /me/assemblies/{id}/comments. While
// the detail call is in flight we render the summary we already
// have (passed in by VersammlungenTab) so the user sees something
// immediately rather than a spinner.

import SwiftUI

@MainActor
final class AssemblyDetailStore: ObservableObject {
    @Published private(set) var detail: Assembly?
    @Published private(set) var comments: [AssemblyComment] = []
    @Published private(set) var isLoadingDetail = false
    @Published private(set) var isLoadingComments = false
    @Published private(set) var isPosting = false
    @Published private(set) var isDownloadingProtocol = false
    @Published private(set) var protocolFileURL: URL?
    /// Currently-downloading attachment id, so the tapped chip can
    /// render a spinner without affecting siblings. nil = none in
    /// flight.
    @Published private(set) var downloadingAttachmentId: String?
    /// File URL of the most recently downloaded attachment. Drives
    /// the separate `.sheet(item:)` for QuickLook preview.
    @Published var attachmentPreview: AttachmentPreviewURL?
    @Published var lastError: String?

    var onUnauthorized: (() -> Void)?
    private let api: APIClient

    init(api: APIClient = APIClient()) {
        self.api = api
    }

    func loadAll(assemblyId: String) async {
        await loadDetail(assemblyId: assemblyId)
        await loadComments(assemblyId: assemblyId)
    }

    func loadDetail(assemblyId: String) async {
        isLoadingDetail = true
        defer { isLoadingDetail = false }
        do {
            self.detail = try await api.getAssemblyDetail(id: assemblyId)
        } catch APIError.unauthorized {
            onUnauthorized?()
        } catch let error as APIError {
            self.lastError = error.errorDescription
        } catch {
            self.lastError = error.localizedDescription
        }
    }

    func loadComments(assemblyId: String) async {
        isLoadingComments = true
        defer { isLoadingComments = false }
        do {
            self.comments = try await api.listAssemblyComments(assemblyId: assemblyId)
        } catch APIError.unauthorized {
            onUnauthorized?()
        } catch let error as APIError {
            self.lastError = error.errorDescription
        } catch {
            self.lastError = error.localizedDescription
        }
    }

    /// Downloads the signed-protocol PDF to a temp file and surfaces
    /// the URL for QuickLook. No-op if a copy already exists for
    /// this session — re-pressing the button just re-opens the same
    /// file.
    func openProtocol(assemblyId: String) async {
        if protocolFileURL != nil { return }
        isDownloadingProtocol = true
        defer { isDownloadingProtocol = false }
        do {
            self.protocolFileURL = try await api.downloadAssemblyProtocol(id: assemblyId)
        } catch APIError.unauthorized {
            onUnauthorized?()
        } catch let error as APIError {
            self.lastError = error.errorDescription
        } catch {
            self.lastError = error.localizedDescription
        }
    }

    /// Clears the preview URL — bound to the sheet's onDismiss so a
    /// second open of the protocol triggers a fresh fetch (useful if
    /// the Verwalter has uploaded a corrected copy in the meantime).
    func dismissProtocol() {
        if let url = protocolFileURL {
            try? FileManager.default.removeItem(at: url)
        }
        protocolFileURL = nil
    }

    /// Downloads an agenda-item attachment to a temp file and
    /// surfaces the URL via `attachmentPreview`. Tap-spam-safe: if
    /// the same id is in flight we no-op, otherwise we record which
    /// chip the user pressed so the view can render a spinner.
    func openAttachment(agendaItemId: String, attachment: AgendaItemAttachment) async {
        if downloadingAttachmentId == attachment.id { return }
        downloadingAttachmentId = attachment.id
        defer { downloadingAttachmentId = nil }
        do {
            let url = try await api.downloadAgendaAttachment(
                agendaItemId: agendaItemId,
                attachmentId: attachment.id,
                filename: attachment.filename
            )
            attachmentPreview = AttachmentPreviewURL(url: url)
        } catch APIError.unauthorized {
            onUnauthorized?()
        } catch let error as APIError {
            self.lastError = error.errorDescription
        } catch {
            self.lastError = error.localizedDescription
        }
    }

    /// Cleans up the downloaded file when the user dismisses the
    /// preview — keeps tmp lean across many opens during one visit.
    func dismissAttachmentPreview() {
        if let url = attachmentPreview?.url {
            try? FileManager.default.removeItem(at: url)
        }
        attachmentPreview = nil
    }

    /// Posts the comment and appends the server-returned row to the
    /// thread. Returns true on success so the input field can clear.
    @discardableResult
    func postComment(assemblyId: String, body: String) async -> Bool {
        let trimmed = body.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return false }
        isPosting = true
        defer { isPosting = false }
        do {
            let created = try await api.postAssemblyComment(
                assemblyId: assemblyId,
                body: trimmed
            )
            self.comments.append(created)
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
}

struct AssemblyDetailView: View {
    let assemblyId: String
    /// List-row summary passed in so we can render the header
    /// instantly while the detail call is in flight. Optional so the
    /// view also works from a Preview or push-notification
    /// deep-link where no summary is available.
    let fallback: AssemblySummary?

    @StateObject private var store = AssemblyDetailStore()
    @State private var commentDraft = ""
    @EnvironmentObject var authStore: AuthStore

    init(assemblyId: String, fallback: AssemblySummary? = nil) {
        self.assemblyId = assemblyId
        self.fallback = fallback
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                headerCard
                if let url = teamsURL {
                    teamsJoinButton(url: url)
                }
                if let detail = store.detail, !detail.description.isEmpty {
                    Text(detail.description)
                        .font(.body)
                        .foregroundStyle(.primary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                agendaSection
                protocolSection
                commentsSection
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 16)
        }
        .navigationTitle("Versammlung")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            store.onUnauthorized = { [weak authStore] in
                authStore?.signOut()
            }
        }
        .task(id: assemblyId) {
            await store.loadAll(assemblyId: assemblyId)
        }
        .refreshable {
            await store.loadAll(assemblyId: assemblyId)
        }
        .sheet(
            isPresented: Binding(
                get: { store.protocolFileURL != nil },
                set: { open in if !open { store.dismissProtocol() } }
            )
        ) {
            if let url = store.protocolFileURL {
                FilePreview(url: url)
                    .ignoresSafeArea()
            }
        }
        // Separate sheet for per-TOP attachment preview so opening
        // one doesn't fight the protocol sheet's binding.
        .sheet(
            item: Binding(
                get: { store.attachmentPreview },
                set: { v in if v == nil { store.dismissAttachmentPreview() } }
            )
        ) { preview in
            FilePreview(url: preview.url)
                .ignoresSafeArea()
        }
    }

    // MARK: - Convenience views over the merged summary+detail

    /// Header fields come from detail when available, else fall back
    /// to the summary the list row passed in. Keeps the screen useful
    /// during the brief detail-fetch flight.
    private var displayTitle: String {
        store.detail?.title ?? fallback?.title ?? "—"
    }
    private var displayStatus: AssemblyStatus? {
        store.detail?.status ?? fallback?.status
    }
    private var displayLocation: String {
        store.detail?.location ?? fallback?.location ?? "—"
    }
    private var displayStart: Date? {
        store.detail?.scheduled_start ?? fallback?.scheduled_start
    }
    private var displayEnd: Date? {
        store.detail?.scheduled_end ?? fallback?.scheduled_end
    }
    private var displayPropertyName: String? {
        store.detail?.property_name ?? fallback?.property_name
    }
    private var displayPropertyHrId: String? {
        store.detail?.property_hr_id ?? fallback?.property_hr_id
    }
    private var displayProtocolUploaded: Date? {
        store.detail?.protocol_uploaded_at ?? fallback?.protocol_uploaded_at
    }
    private var hasProtocol: Bool {
        (store.detail?.protocol_pdf_url ?? fallback?.protocol_pdf_url) != nil
    }
    private var teamsURL: URL? {
        let raw = store.detail?.teams_meeting_url ?? fallback?.teams_meeting_url
        guard let raw, !raw.isEmpty else { return nil }
        return URL(string: raw)
    }

    /// True when the signed-in user is the Verwalter — gates the
    /// per-agenda-item "Aufgabe erstellen" action (mirrors the admin
    /// SPA, which is Verwalter-only by route).
    private var isVerwalter: Bool {
        authStore.user?.role.lowercased() == "verwalter"
    }

    // MARK: - Header

    private var headerCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 8) {
                if let s = displayStatus {
                    Text(s.label)
                        .font(.caption.weight(.semibold))
                        .padding(.horizontal, 10)
                        .padding(.vertical, 4)
                        .background(statusBackground(s))
                        .foregroundStyle(.white)
                        .clipShape(Capsule())
                }
                if hasProtocol {
                    Text("Protokoll vorhanden")
                        .font(.caption.weight(.medium))
                        .padding(.horizontal, 10)
                        .padding(.vertical, 4)
                        .background(Color.green.opacity(0.15))
                        .foregroundStyle(.green)
                        .clipShape(Capsule())
                }
                if store.isLoadingDetail {
                    ProgressView().controlSize(.small)
                }
            }
            if let propertyLine = propertyHeaderLine {
                Label {
                    Text(propertyLine)
                        .font(.caption.weight(.medium))
                        .foregroundStyle(.secondary)
                } icon: {
                    Image(systemName: "building.2")
                        .foregroundStyle(.secondary)
                }
            }
            Text(displayTitle)
                .font(.title3.bold())
            VStack(alignment: .leading, spacing: 6) {
                if let start = displayStart, let end = displayEnd {
                    Label {
                        Text(dateRange(start: start, end: end))
                            .font(.subheadline)
                    } icon: {
                        Image(systemName: "calendar")
                    }
                }
                Label {
                    Text(displayLocation)
                        .font(.subheadline)
                } icon: {
                    Image(systemName: "mappin.and.ellipse")
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

    private func statusBackground(_ s: AssemblyStatus) -> Color {
        switch s {
        case .geplant: return .gray
        case .eingeladen: return .blue
        case .abgehalten: return .green
        case .abgesagt: return .red
        }
    }

    private var propertyHeaderLine: String? {
        let parts = [displayPropertyName, displayPropertyHrId]
            .compactMap { $0 }
            .filter { !$0.isEmpty }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    /// Microsoft Teams purple — matches the admin SPA + portal CTA
    /// so the button reads as the same "Teams thing" across surfaces.
    private static let teamsPurple = Color(red: 0.36, green: 0.32, blue: 0.78)

    private func teamsJoinButton(url: URL) -> some View {
        Link(destination: url) {
            HStack(spacing: 12) {
                Image(systemName: "video.fill")
                    .font(.title3)
                Text("Teams-Meeting beitreten")
                    .font(.headline)
                Spacer(minLength: 0)
                Image(systemName: "arrow.up.right.square")
                    .font(.subheadline)
                    .opacity(0.8)
            }
            .foregroundStyle(.white)
            .padding(.horizontal, 16)
            .padding(.vertical, 14)
            .frame(maxWidth: .infinity)
            .background(
                RoundedRectangle(cornerRadius: 10)
                    .fill(Self.teamsPurple)
            )
        }
        .buttonStyle(.plain)
    }

    /// Locale-aware "Wednesday, 28 April 2026, 18:00–21:00" /
    /// "Mittwoch, 28. April 2026, 18:00–21:00 Uhr". Uses
    /// Foundation's locale-aware formatters so swapping the
    /// app language (or device language) flips the rendering
    /// without hand-coded German fallbacks.
    private func dateRange(start: Date, end: Date) -> String {
        let sameDay = Calendar.current.isDate(start, inSameDayAs: end)
        if sameDay {
            let date = start.formatted(
                .dateTime.weekday(.wide).day().month(.wide).year()
            )
            let s = start.formatted(.dateTime.hour().minute())
            let e = end.formatted(.dateTime.hour().minute())
            return "\(date), \(s) – \(e)"
        }
        let s = start.formatted(
            .dateTime.weekday(.wide).day().month(.wide).year()
        )
        let e = end.formatted(
            .dateTime.weekday(.wide).day().month(.wide).year()
        )
        return "\(s) – \(e)"
    }

    // MARK: - Agenda

    private var agendaSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Tagesordnung")
                .font(.title3.bold())
                .frame(maxWidth: .infinity, alignment: .leading)
            if store.isLoadingDetail && store.detail == nil {
                ProgressView()
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 24)
            } else if let detail = store.detail, !detail.agenda_items.isEmpty {
                ForEach(detail.agenda_items.sorted(by: { $0.position < $1.position })) { item in
                    AgendaItemCard(
                        item: item,
                        isVerwalter: isVerwalter,
                        assemblyTitle: detail.title,
                        propertyId: detail.property_id,
                        downloadingAttachmentId: store.downloadingAttachmentId,
                        onAttachmentTap: { att in
                            Task {
                                await store.openAttachment(
                                    agendaItemId: item.id,
                                    attachment: att
                                )
                            }
                        }
                    )
                }
            } else {
                Text("Tagesordnung wird vom Verwalter ergänzt.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
        }
    }

    // MARK: - Comments (Q&A thread)

    @ViewBuilder
    private var commentsSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Fragen & Antworten")
                .font(.title3.bold())
                .frame(maxWidth: .infinity, alignment: .leading)

            if store.isLoadingComments && store.comments.isEmpty {
                ProgressView()
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 12)
            } else if store.comments.isEmpty {
                // Single-literal Text so the build-time string
                // extractor sees the key. `+`-concatenated strings
                // are invisible to it and never reach the catalog.
                Text("Hier können Sie Rückfragen zu dieser Versammlung stellen. Antworten erscheinen direkt unter der Frage.")
                .font(.subheadline)
                .foregroundStyle(.secondary)
            } else {
                ForEach(
                    store.comments.sorted(by: { $0.created_at < $1.created_at })
                ) { c in
                    CommentRow(comment: c)
                }
            }

            commentComposer

            Text("Kommentare dienen Rückfragen — formale Anfechtungen erfolgen außerhalb des Portals.")
            .font(.caption2)
            .foregroundStyle(.tertiary)
            .padding(.top, 4)
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
                            assemblyId: assemblyId,
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

    // MARK: - Protocol

    @ViewBuilder
    private var protocolSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Signiertes Protokoll")
                .font(.title3.bold())
                .frame(maxWidth: .infinity, alignment: .leading)
            if hasProtocol {
                Button {
                    Task { await store.openProtocol(assemblyId: assemblyId) }
                } label: {
                    HStack(spacing: 12) {
                        Image(systemName: "doc.text.fill")
                            .font(.title3)
                            .foregroundStyle(.tint)
                            .frame(width: 36, height: 36)
                            .background(Color.accentColor.opacity(0.12))
                            .clipShape(RoundedRectangle(cornerRadius: 8))
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Protokoll als PDF öffnen")
                                .font(.subheadline.weight(.semibold))
                                .foregroundStyle(.primary)
                            if let uploaded = displayProtocolUploaded {
                                Text("Hochgeladen am \(uploaded.formatted(.dateTime.day().month().year()))")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                        Spacer()
                        if store.isDownloadingProtocol {
                            ProgressView()
                        } else {
                            Image(systemName: "arrow.up.right.square")
                                .font(.caption)
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
                .disabled(store.isDownloadingProtocol)
            } else {
                Text("Das Protokoll wird in der Regel innerhalb von vier Wochen nach der Versammlung hochgeladen.")
                .font(.subheadline)
                .foregroundStyle(.secondary)
            }
        }
    }
}

// MARK: - Agenda item card

private struct AgendaItemCard: View {
    let item: AgendaItem
    /// Gates the Verwalter-only "Aufgabe erstellen" action below.
    let isVerwalter: Bool
    /// Carried into the pre-filled task sheet for the default body text.
    let assemblyTitle: String
    /// The assembly's property — the created ticket is scoped to it.
    let propertyId: String
    /// Mirrors `AssemblyDetailStore.downloadingAttachmentId` — when
    /// it matches an attachment.id the chip renders a spinner.
    let downloadingAttachmentId: String?
    /// Closure invoked on tap. Parent fires the download + presents
    /// QuickLook via the page-level sheet binding.
    let onAttachmentTap: (AgendaItemAttachment) -> Void

    @State private var taskOpen = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(item.title)
                .font(.subheadline.weight(.semibold))
            // Type + result chips live UNDER the title — the title
            // already carries the TOP number ("TOP 1: Begrüßung …")
            // so a separate position chip is redundant. Hiding it
            // also stops the row from wrapping awkwardly on small
            // widths.
            HStack(spacing: 8) {
                Text(item.type.label)
                    .font(.caption.weight(.medium))
                    .padding(.horizontal, 8)
                    .padding(.vertical, 2)
                    .background(typeBackground(item.type))
                    .foregroundStyle(typeForeground(item.type))
                    .clipShape(Capsule())
                if let result = item.vote_result {
                    Text(result.label)
                        .font(.caption.weight(.bold))
                        .padding(.horizontal, 8)
                        .padding(.vertical, 2)
                        .background(result == .angenommen ? Color.green.opacity(0.18) : Color.red.opacity(0.18))
                        .foregroundStyle(result == .angenommen ? .green : .red)
                        .clipShape(Capsule())
                }
                Spacer(minLength: 0)
            }
            if !item.body.isEmpty {
                Text(item.body)
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
            if let beschluss = item.beschluss_text {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Beschlusstext")
                        .font(.caption2.weight(.semibold))
                        .textCase(.uppercase)
                        .foregroundStyle(.tertiary)
                    Text(beschluss)
                        .font(.callout)
                        .foregroundStyle(.primary)
                }
                .padding(10)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(
                    RoundedRectangle(cornerRadius: 8)
                        .fill(Color.accentColor.opacity(0.08))
                )
                .overlay(
                    Rectangle()
                        .fill(Color.accentColor)
                        .frame(width: 3),
                    alignment: .leading
                )
            }
            if !item.attachments.isEmpty {
                attachmentsBlock
            }
            if item.voting_basis != nil || item.present_count != nil {
                votingMeta
            }
            if item.type == .beschluss && item.voteTotal > 0 {
                voteTally
            }
            if !item.discussion.isEmpty {
                discussion
            }
            if isVerwalter {
                createTaskButton
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 12)
                .fill(Color(.secondarySystemBackground))
        )
        .sheet(isPresented: $taskOpen) {
            CreateTaskFromAgendaSheet(
                item: item,
                assemblyTitle: assemblyTitle,
                propertyId: propertyId
            )
        }
    }

    /// Verwalter-only: turn this TOP into an internal task (a Ticket
    /// with category SONSTIGES_ETV). Mirrors the admin SPA's
    /// "Aufgabe erstellen" button on each agenda row.
    private var createTaskButton: some View {
        Button {
            taskOpen = true
        } label: {
            Label("Aufgabe erstellen", systemImage: "plus.circle")
                .font(.subheadline.weight(.medium))
                .frame(maxWidth: .infinity)
        }
        .buttonStyle(.bordered)
        .padding(.top, 4)
    }

    /// Supporting docs attached to this TOP. Each chip is a Button —
    /// tapping calls back into the parent which fires the download
    /// and presents QuickLook. We use a wrap-friendly HStack instead
    /// of FlowLayout (iOS 16 doesn't have it) — for 1-4 attachments
    /// the single line is fine; longer rows wrap by SwiftUI's
    /// HStack-in-VStack default.
    private var attachmentsBlock: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Anhänge")
                .font(.caption2.weight(.semibold))
                .textCase(.uppercase)
                .foregroundStyle(.tertiary)
            VStack(alignment: .leading, spacing: 6) {
                ForEach(item.attachments) { att in
                    Button {
                        onAttachmentTap(att)
                    } label: {
                        HStack(spacing: 8) {
                            if downloadingAttachmentId == att.id {
                                ProgressView()
                                    .controlSize(.small)
                            } else {
                                Image(systemName: "doc.fill")
                                    .font(.caption)
                                    .foregroundStyle(.tint)
                            }
                            Text(att.filename)
                                .font(.callout)
                                .foregroundStyle(.primary)
                                .lineLimit(1)
                            Spacer(minLength: 0)
                            Text(formatBytes(att.size_bytes))
                                .font(.caption2)
                                .foregroundStyle(.tertiary)
                        }
                        .padding(.horizontal, 10)
                        .padding(.vertical, 8)
                        .background(
                            RoundedRectangle(cornerRadius: 8)
                                .fill(Color(.tertiarySystemFill))
                        )
                    }
                    .buttonStyle(.plain)
                    .disabled(downloadingAttachmentId == att.id)
                }
            }
        }
    }

    @ViewBuilder
    private var votingMeta: some View {
        HStack(spacing: 8) {
            if let basis = item.voting_basis {
                metaChip(label: "Stimmrecht", value: String(localized: basis.label), tint: .accentColor)
            }
            if let present = item.present_count {
                metaChip(label: "Anwesend", value: "\(present)", tint: .secondary)
            }
            Spacer(minLength: 0)
        }
    }

    private func metaChip(label: String, value: String, tint: Color) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(label)
                .font(.caption2)
                .foregroundStyle(.tertiary)
            Text(value)
                .font(.caption.weight(.semibold))
                .foregroundStyle(tint)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(
            RoundedRectangle(cornerRadius: 8)
                .fill(Color(.tertiarySystemFill))
        )
    }

    private var voteTally: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Abstimmungsergebnis")
                .font(.caption2.weight(.semibold))
                .textCase(.uppercase)
                .foregroundStyle(.tertiary)
            HStack(spacing: 12) {
                voteCell("Ja", value: item.vote_yes, color: .green)
                voteCell("Nein", value: item.vote_no, color: .red)
                voteCell("Enth.", value: item.vote_abstain, color: .gray)
                if let quorum = item.vote_required_quorum {
                    Spacer(minLength: 0)
                    Text("Quorum: \(quorum)")
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }
            }
        }
    }

    private func voteCell(_ label: String, value: Int, color: Color) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label)
                .font(.caption2)
                .foregroundStyle(.secondary)
            Text("\(value)")
                .font(.title3.bold())
                .foregroundStyle(color)
        }
    }

    private var discussion: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Diskussion")
                .font(.caption2.weight(.semibold))
                .textCase(.uppercase)
                .foregroundStyle(.tertiary)
            ForEach(item.discussion.sorted(by: { $0.position < $1.position })) { d in
                VStack(alignment: .leading, spacing: 2) {
                    Text(d.speaker_label)
                        .font(.caption.weight(.medium))
                        .foregroundStyle(.secondary)
                    Text(d.content)
                        .font(.callout)
                        .foregroundStyle(.primary)
                }
                .padding(10)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(
                    RoundedRectangle(cornerRadius: 8)
                        .fill(Color(.tertiarySystemBackground))
                )
            }
        }
    }

    private func typeBackground(_ t: AgendaItemType) -> Color {
        switch t {
        case .information: return Color.gray.opacity(0.15)
        case .beschluss: return Color.accentColor.opacity(0.18)
        case .diskussion: return Color.orange.opacity(0.18)
        }
    }
    private func typeForeground(_ t: AgendaItemType) -> Color {
        switch t {
        case .information: return .secondary
        case .beschluss: return .accentColor
        case .diskussion: return .orange
        }
    }
}

// MARK: - Comment row

private struct CommentRow: View {
    let comment: AssemblyComment

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(comment.author_label)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.primary)
                if comment.author_role.hasLabel {
                    Text(comment.author_role.label)
                        .font(.caption2.weight(.semibold))
                        .padding(.horizontal, 7)
                        .padding(.vertical, 2)
                        .background(roleBackground)
                        .foregroundStyle(roleForeground)
                        .clipShape(Capsule())
                }
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

    private var roleBackground: Color {
        switch comment.author_role {
        case .verwalter: return Color.accentColor
        case .beirat: return Color.green.opacity(0.18)
        default: return Color(.tertiarySystemFill)
        }
    }

    private var roleForeground: Color {
        switch comment.author_role {
        case .verwalter: return .white
        case .beirat: return .green
        default: return .secondary
        }
    }
}

#Preview {
    NavigationStack {
        AssemblyDetailView(assemblyId: "demo-assembly-past-x")
    }
}

/// Wrapper so we can drive `.sheet(item:)` from a URL — `URL` itself
/// isn't `Identifiable`. The id is the file's path, which is stable
/// per download and uniquely identifies the sheet target.
struct AttachmentPreviewURL: Identifiable, Hashable {
    let url: URL
    var id: String { url.path }
}

/// Short human-readable byte string for chip subtitles. Matches the
/// "150 KB" / "1.4 MB" rounding the portal uses so the two clients
/// don't disagree on the same file's reported size.
private func formatBytes(_ b: Int) -> String {
    if b < 1024 { return "\(b) B" }
    if b < 1024 * 1024 { return "\(b / 1024) KB" }
    let mb = Double(b) / (1024.0 * 1024.0)
    return String(format: "%.1f MB", mb)
}

// MARK: - Create task (ticket) from an agenda item — Verwalter only

/// Pre-filled sheet that turns an ETV agenda point into an internal
/// Ticket (category SONSTIGES_ETV, share scope PRIVATE) via
/// POST /me/tickets — the same flow the admin SPA uses, so a Verwalter
/// gets identical behaviour on the web portal and in the app. The
/// ticket-create already notifies the Verwalter team server-side, so
/// there's no extra wiring here. Subject + body are pre-filled from
/// the TOP and stay editable before sending.
private struct CreateTaskFromAgendaSheet: View {
    let item: AgendaItem
    let assemblyTitle: String
    let propertyId: String

    @Environment(\.dismiss) private var dismiss
    @State private var subject: String
    @State private var draftBody: String
    @State private var busy = false
    @State private var errorText: String?
    @State private var done = false

    private let api = APIClient()

    init(item: AgendaItem, assemblyTitle: String, propertyId: String) {
        self.item = item
        self.assemblyTitle = assemblyTitle
        self.propertyId = propertyId
        _subject = State(initialValue: String(item.title.prefix(200)))
        let trimmed = item.body.trimmingCharacters(in: .whitespacesAndNewlines)
        _draftBody = State(
            initialValue: trimmed.isEmpty
                ? String(localized: "Aufgabe aus der Eigentümerversammlung „\(assemblyTitle)“, Tagesordnungspunkt „\(item.title)“.")
                : item.body
        )
    }

    private var canSubmit: Bool {
        subject.trimmingCharacters(in: .whitespacesAndNewlines).count >= 3
            && draftBody.trimmingCharacters(in: .whitespacesAndNewlines).count >= 3
    }

    var body: some View {
        NavigationStack {
            Form {
                if done {
                    Section {
                        Label("Aufgabe wurde erstellt und das Verwalter-Team benachrichtigt.", systemImage: "checkmark.circle.fill")
                            .foregroundStyle(.green)
                    }
                } else {
                    if let errorText {
                        Section {
                            Text(errorText)
                                .font(.subheadline)
                                .foregroundStyle(.red)
                        }
                    }
                    Section("Betreff") {
                        TextField("Betreff", text: $subject)
                    }
                    Section("Beschreibung") {
                        TextField("Beschreibung", text: $draftBody, axis: .vertical)
                            .lineLimit(4...10)
                    }
                    Section {
                        Text("Wird als internes Ticket (Kategorie „Eigentümerversammlung“) angelegt und an das Verwalter-Team gemeldet.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
            .navigationTitle("Neue Aufgabe")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(done ? "Schließen" : "Abbrechen") { dismiss() }
                }
                if !done {
                    ToolbarItem(placement: .confirmationAction) {
                        if busy {
                            ProgressView()
                        } else {
                            Button("Erstellen") { Task { await submit() } }
                                .disabled(!canSubmit)
                        }
                    }
                }
            }
        }
    }

    private func submit() async {
        guard canSubmit else { return }
        busy = true
        errorText = nil
        defer { busy = false }
        do {
            _ = try await api.createMyTicket(
                subject: subject.trimmingCharacters(in: .whitespacesAndNewlines),
                body: draftBody.trimmingCharacters(in: .whitespacesAndNewlines),
                category: .sonstigesEtv,
                propertyId: propertyId
            )
            done = true
        } catch let e as APIError {
            errorText = e.errorDescription
        } catch {
            errorText = error.localizedDescription
        }
    }
}
