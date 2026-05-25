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
    @Published var lastError: String?

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
        } catch let error as APIError {
            self.lastError = error.errorDescription
        } catch {
            self.lastError = error.localizedDescription
        }
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
        .task(id: assemblyId) {
            await store.loadAll(assemblyId: assemblyId)
        }
        .refreshable {
            await store.loadAll(assemblyId: assemblyId)
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

    private func dateRange(start: Date, end: Date) -> String {
        let cal = Calendar.current
        let sameDay = cal.isDate(start, inSameDayAs: end)
        let date = DateFormatter()
        date.locale = Locale(identifier: "de_DE")
        date.dateFormat = "EEEE, d. MMMM yyyy"
        let time = DateFormatter()
        time.locale = Locale(identifier: "de_DE")
        time.dateFormat = "HH:mm"
        if sameDay {
            return "\(date.string(from: start)), \(time.string(from: start))–\(time.string(from: end)) Uhr"
        }
        return "\(date.string(from: start)) – \(date.string(from: end))"
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
                    AgendaItemCard(item: item)
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
                Text(
                    "Hier können Sie Rückfragen zu dieser Versammlung "
                    + "stellen. Antworten erscheinen direkt unter der "
                    + "Frage."
                )
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

            Text(
                "Kommentare dienen Rückfragen — formale Anfechtungen "
                + "erfolgen außerhalb des Portals."
            )
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
                    // Authenticated download lands in a follow-up
                    // task; for now we surface that the file is on
                    // the server and the portal/admin can serve it.
                    print("Would open protocol for assembly \(assemblyId)")
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
                        Image(systemName: "arrow.up.right.square")
                            .font(.caption)
                            .foregroundStyle(.tertiary)
                    }
                    .padding(12)
                    .background(
                        RoundedRectangle(cornerRadius: 10)
                            .fill(Color(.secondarySystemBackground))
                    )
                }
                .buttonStyle(.plain)
            } else {
                Text(
                    "Das Protokoll wird in der Regel innerhalb von "
                    + "vier Wochen nach der Versammlung hochgeladen."
                )
                .font(.subheadline)
                .foregroundStyle(.secondary)
            }
        }
    }
}

// MARK: - Agenda item card

private struct AgendaItemCard: View {
    let item: AgendaItem

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Text("TOP \(item.position)")
                    .font(.caption.weight(.semibold))
                    .padding(.horizontal, 8)
                    .padding(.vertical, 2)
                    .background(Color(.tertiarySystemFill))
                    .clipShape(Capsule())
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
            Text(item.title)
                .font(.subheadline.weight(.semibold))
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
            if item.voting_basis != nil || item.present_count != nil {
                votingMeta
            }
            if item.type == .beschluss && item.voteTotal > 0 {
                voteTally
            }
            if !item.discussion.isEmpty {
                discussion
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 12)
                .fill(Color(.secondarySystemBackground))
        )
    }

    @ViewBuilder
    private var votingMeta: some View {
        HStack(spacing: 8) {
            if let basis = item.voting_basis {
                metaChip(label: "Stimmrecht", value: basis.label, tint: .accentColor)
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
                if !comment.author_role.label.isEmpty {
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
