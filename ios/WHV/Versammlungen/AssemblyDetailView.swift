// Single-screen ETV detail: header → agenda items → per-item
// Beschluss tally + Diskussion → signed-protocol PDF link.
//
// One screen rather than a tabbed sub-navigation because the
// document the Verwalter actually produces (protocol) is read top
// to bottom in one pass — the iOS layout mirrors that reading flow.

import SwiftUI

struct AssemblyDetailView: View {
    let assembly: Assembly

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                headerCard
                if let url = teamsURL {
                    teamsJoinButton(url: url)
                }
                if !assembly.description.isEmpty {
                    Text(assembly.description)
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
    }

    private var teamsURL: URL? {
        guard let raw = assembly.teams_meeting_url, !raw.isEmpty else { return nil }
        return URL(string: raw)
    }

    // MARK: - Header

    private var headerCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 8) {
                Text(assembly.status.label)
                    .font(.caption.weight(.semibold))
                    .padding(.horizontal, 10)
                    .padding(.vertical, 4)
                    .background(statusBackground)
                    .foregroundStyle(.white)
                    .clipShape(Capsule())
                if assembly.protocol_pdf_url != nil {
                    Text("Protokoll vorhanden")
                        .font(.caption.weight(.medium))
                        .padding(.horizontal, 10)
                        .padding(.vertical, 4)
                        .background(Color.green.opacity(0.15))
                        .foregroundStyle(.green)
                        .clipShape(Capsule())
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
            Text(assembly.title)
                .font(.title3.bold())
            VStack(alignment: .leading, spacing: 6) {
                Label {
                    Text(dateRange)
                        .font(.subheadline)
                } icon: {
                    Image(systemName: "calendar")
                }
                Label {
                    Text(assembly.location)
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

    /// "WEG Königstr. 42 · STUTTGART_K42" — both parts are optional;
    /// we only render the line if at least one is set.
    private var propertyHeaderLine: String? {
        let parts = [assembly.property_name, assembly.property_hr_id]
            .compactMap { $0 }
            .filter { !$0.isEmpty }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    /// Microsoft Teams purple matches the admin SPA + portal CTA so
    /// the button reads as "the same Teams thing" across all three
    /// surfaces.
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

    private var statusBackground: Color {
        switch assembly.status {
        case .geplant: return .gray
        case .eingeladen: return .blue
        case .abgehalten: return .green
        case .abgesagt: return .red
        }
    }

    private var dateRange: String {
        let cal = Calendar.current
        let sameDay = cal.isDate(
            assembly.scheduled_start,
            inSameDayAs: assembly.scheduled_end
        )
        let date = DateFormatter()
        date.locale = Locale(identifier: "de_DE")
        date.dateFormat = "EEEE, d. MMMM yyyy"
        let time = DateFormatter()
        time.locale = Locale(identifier: "de_DE")
        time.dateFormat = "HH:mm"
        if sameDay {
            return "\(date.string(from: assembly.scheduled_start)), \(time.string(from: assembly.scheduled_start))–\(time.string(from: assembly.scheduled_end)) Uhr"
        }
        return "\(date.string(from: assembly.scheduled_start)) – \(date.string(from: assembly.scheduled_end))"
    }

    // MARK: - Agenda

    private var agendaSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Tagesordnung")
                .font(.title3.bold())
                .frame(maxWidth: .infinity, alignment: .leading)
            if assembly.agenda_items.isEmpty {
                Text("Tagesordnung wird vom Verwalter ergänzt.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            } else {
                ForEach(assembly.agenda_items.sorted(by: { $0.position < $1.position })) { item in
                    AgendaItemCard(item: item)
                }
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
            if assembly.comments.isEmpty {
                Text(
                    "Hier können Sie Rückfragen zu dieser Versammlung "
                    + "stellen. Antworten erscheinen direkt unter der "
                    + "Frage."
                )
                .font(.subheadline)
                .foregroundStyle(.secondary)
            } else {
                ForEach(
                    assembly.comments.sorted(by: { $0.created_at < $1.created_at })
                ) { c in
                    CommentRow(comment: c)
                }
            }
            Text(
                "Kommentare dienen Rückfragen — formale Anfechtungen "
                + "erfolgen außerhalb des Portals."
            )
            .font(.caption2)
            .foregroundStyle(.tertiary)
            .padding(.top, 4)
        }
    }

    // MARK: - Protocol

    @ViewBuilder
    private var protocolSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Signiertes Protokoll")
                .font(.title3.bold())
                .frame(maxWidth: .infinity, alignment: .leading)
            if let url = assembly.protocol_pdf_url {
                Button {
                    // Phase 2.1 wires the authenticated GET
                    // /me/assemblies/{id}/protocol and opens the
                    // returned PDF via UIDocumentInteractionController
                    // (or QuickLook). For the scaffold we render a
                    // stub so the layout is testable.
                    print("Would open protocol: \(url)")
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
                            if let uploaded = assembly.protocol_uploaded_at {
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
            // Top row: TOP number + type chip + (optional) result chip
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

    /// Stimmrecht (KOPF/MEA/OBJEKT) + Anwesend tile. Rendered as a
    /// pair of small chips above the tally so a glance tells you
    /// what counting rule applied + how many heads were in the room.
    @ViewBuilder
    private var votingMeta: some View {
        HStack(spacing: 8) {
            if let basis = item.voting_basis {
                metaChip(
                    label: "Stimmrecht",
                    value: basis.label,
                    tint: .accentColor
                )
            }
            if let present = item.present_count {
                metaChip(
                    label: "Anwesend",
                    value: "\(present)",
                    tint: .secondary
                )
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

/// One Q&A entry. Matches the portal's AssemblyComments component:
/// role badge to the right of the author label, body below,
/// "(bearbeitet)" hint when edited_at is set.
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
        AssemblyDetailView(
            assembly: DemoAssemblies.sample(for: Liegenschaft.demo[0]).first(
                where: { $0.status == .abgehalten }
            )!
        )
    }
}
