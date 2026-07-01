// RAG document assistant (ADR-0013) — the iOS counterpart of the web
// assistant. Presented as a sheet from the floating bubble in RootTabView.
//
// Harmonisation note: the app used to carry a standalone floating
// "Dirk Ullrich anrufen" button across every tab. To avoid two competing
// floating affordances, that button is gone and the call action now lives
// in THIS dialog's toolbar (the phone icon, top-left) — so "ask the
// assistant" and "ring a human" share one entry point.
//
// The backend resolves the caller's ACL scope from the JWT, so we only
// send the question. Citations open via /me/documents/{id}/file, which
// re-checks access server-side, then render in QuickLook (FilePreview).

import SwiftUI
import UIKit

// MARK: - Model

struct AssistantChatMessage: Identifiable {
    enum Role { case user, assistant }
    let id = UUID()
    let role: Role
    let text: String
    var sources: [AssistantCitation] = []
}

@MainActor
final class AssistantChatModel: ObservableObject {
    @Published var messages: [AssistantChatMessage] = []
    @Published var input: String = ""
    @Published var isLoading = false
    @Published var errorText: String?
    /// Set when a citation has been downloaded — drives the QuickLook sheet.
    @Published var previewURL: URL?
    /// Document id currently downloading, so its chip can show progress.
    @Published var openingDocumentId: String?

    private let api = APIClient()
    /// The active Liegenschaft (set by AssistantView from LiegenschaftStore) —
    /// scopes retrieval to that property's documents. nil = whole visible scope.
    var propertyId: String?
    /// One id per chat session → threads turns in the admin overview.
    private let conversationId = UUID().uuidString

    var canSend: Bool {
        !isLoading && !input.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    func send() {
        let question = input.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !question.isEmpty, !isLoading else { return }
        errorText = nil
        // History = the turns so far (before this question), last 8 — so the
        // backend can answer follow-ups like "fass das zusammen".
        let history = messages.suffix(8).map {
            AssistantHistoryTurn(role: $0.role == .user ? "user" : "assistant", content: $0.text)
        }
        messages.append(AssistantChatMessage(role: .user, text: question))
        input = ""
        isLoading = true
        Task {
            do {
                let res = try await api.askAssistant(
                    question: question,
                    history: history,
                    propertyId: propertyId,
                    conversationId: conversationId
                )
                messages.append(
                    AssistantChatMessage(role: .assistant, text: res.answer, sources: res.sources)
                )
            } catch {
                errorText = Self.message(for: error)
            }
            isLoading = false
        }
    }

    func openCitation(_ citation: AssistantCitation) {
        guard openingDocumentId == nil else { return }
        errorText = nil
        openingDocumentId = citation.document_id
        Task {
            do {
                previewURL = try await api.downloadDocument(id: citation.document_id)
            } catch {
                errorText = String(localized: "Das Dokument konnte nicht geöffnet werden.")
            }
            openingDocumentId = nil
        }
    }

    /// Map transport errors to a friendly German line. A 503 means the
    /// assistant is switched off server-side (rag_enabled=false).
    private static func message(for error: Error) -> String {
        if let api = error as? APIError {
            switch api {
            case .http(let status, _) where status == 503:
                return String(localized: "Der Assistent ist derzeit nicht verfügbar.")
            case .demoReadOnly:
                return String(localized: "Im Demo-Modus nicht verfügbar.")
            default:
                break
            }
        }
        return String(localized: "Die Anfrage ist fehlgeschlagen. Bitte erneut versuchen.")
    }
}

// MARK: - Sheet

struct AssistantView: View {
    /// The active Liegenschaft id — scopes the assistant to that property.
    var propertyId: String? = nil
    /// Owned by RootTabView (not this sheet) so the conversation survives
    /// closing + reopening the assistant within the session.
    @ObservedObject var model: AssistantChatModel
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject private var deepLinkRouter: DeepLinkRouter
    @FocusState private var inputFocused: Bool

    /// Route a tapped citation. Documents download + preview inline; an ETV
    /// master-data card deep-links to the Versammlungen tab (the property's
    /// assemblies — same target the web assistant uses). Contact/Dienstleister
    /// cards have no dedicated iOS screen yet, so they stay inert.
    private func handleSource(_ source: AssistantCitation) {
        if source.isMasterData {
            if source.source_type == "etv" {
                deepLinkRouter.pendingTarget = .tab(.etv)
                dismiss()
            }
            return
        }
        model.openCitation(source)
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                conversation
                Divider()
                composer
            }
            .onAppear { model.propertyId = propertyId }
            .navigationTitle("Assistent")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                // Harmonised call action — ring Dirk Ullrich without leaving
                // the assistant. tel: opens the system Phone app.
                ToolbarItem(placement: .topBarLeading) {
                    Link(destination: WHVContact.telURL) {
                        Image(systemName: "phone.fill")
                    }
                    .accessibilityLabel("Dirk Ullrich anrufen")
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Fertig") { dismiss() }
                }
            }
            .sheet(
                isPresented: Binding(
                    get: { model.previewURL != nil },
                    set: { if !$0 { model.previewURL = nil } }
                )
            ) {
                if let url = model.previewURL {
                    FilePreview(url: url).ignoresSafeArea()
                }
            }
        }
    }

    private var conversation: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 12) {
                    if model.messages.isEmpty && !model.isLoading {
                        emptyState
                    }
                    ForEach(model.messages) { message in
                        MessageBubble(message: message) { handleSource($0) }
                            .id(message.id)
                    }
                    if model.isLoading {
                        HStack(spacing: 8) {
                            ProgressView()
                            Text("Suche in Ihren Dokumenten…")
                                .font(.subheadline)
                                .foregroundStyle(.secondary)
                        }
                        .id("loading")
                    }
                    if let errorText = model.errorText {
                        Label(errorText, systemImage: "exclamationmark.triangle")
                            .font(.subheadline)
                            .foregroundStyle(.orange)
                            .padding(.top, 4)
                    }
                }
                .padding()
            }
            .scrollDismissesKeyboard(.interactively)
            // Tap anywhere in the conversation (empty space, a bubble) to drop
            // the keyboard. Simultaneous so it doesn't steal taps from the
            // citation buttons or text selection inside a bubble.
            .simultaneousGesture(TapGesture().onEnded { inputFocused = false })
            .onChange(of: model.messages.count) { _, _ in
                if let last = model.messages.last {
                    withAnimation { proxy.scrollTo(last.id, anchor: .bottom) }
                }
            }
            .onChange(of: model.isLoading) { _, loading in
                if loading { withAnimation { proxy.scrollTo("loading", anchor: .bottom) } }
            }
        }
    }

    private var emptyState: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("Fragen Sie zu Ihren Dokumenten", systemImage: "sparkles")
                .font(.headline)
            Text("z. B. „Wie hoch war die Heizungsrechnung 2025?“ — mit Quellenangaben.")
                .font(.subheadline)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding()
        .background(RoundedRectangle(cornerRadius: 12).fill(Color(.secondarySystemBackground)))
    }

    private var composer: some View {
        VStack(spacing: 6) {
            HStack(alignment: .bottom, spacing: 8) {
                TextField("Ihre Frage…", text: $model.input, axis: .vertical)
                    .lineLimit(1...4)
                    .textFieldStyle(.roundedBorder)
                    .focused($inputFocused)
                    .onSubmit { model.send() }
                Button {
                    model.send()
                } label: {
                    Image(systemName: "arrow.up.circle.fill")
                        .font(.title)
                        .symbolRenderingMode(.hierarchical)
                }
                .disabled(!model.canSend)
            }
            Text("Antworten können Fehler enthalten — maßgeblich sind die verlinkten Dokumente.")
                .font(.caption2)
                .foregroundStyle(.tertiary)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.horizontal)
        .padding(.vertical, 8)
    }
}

// MARK: - Selectable, data-detecting message text

/// A read-only but SELECTABLE text view that auto-detects phone numbers,
/// addresses and links and makes them tappable (Phone / Maps / Safari) —
/// SwiftUI's `Text` does neither. A self-sizing `UITextView` with data
/// detectors, sized to its content so it drops straight into the bubble.
private struct DetectingText: UIViewRepresentable {
    let text: String

    func makeUIView(context: Context) -> UITextView {
        let tv = UITextView()
        tv.isEditable = false
        tv.isSelectable = true
        tv.isScrollEnabled = false
        tv.dataDetectorTypes = [.phoneNumber, .address, .link]
        tv.backgroundColor = .clear
        tv.textContainerInset = .zero
        tv.textContainer.lineFragmentPadding = 0
        tv.font = .preferredFont(forTextStyle: .body)
        tv.adjustsFontForContentSizeCategory = true
        tv.textColor = .label
        tv.setContentHuggingPriority(.required, for: .vertical)
        return tv
    }

    func updateUIView(_ uiView: UITextView, context: Context) {
        if uiView.text != text { uiView.text = text }
    }

    func sizeThatFits(_ proposal: ProposedViewSize, uiView: UITextView, context: Context) -> CGSize? {
        let proposed = proposal.width ?? 300
        let width = proposed.isFinite ? proposed : 300
        let fit = uiView.sizeThatFits(CGSize(width: width, height: .greatestFiniteMagnitude))
        return CGSize(width: fit.width, height: fit.height)
    }
}

// MARK: - Message bubble

private struct MessageBubble: View {
    let message: AssistantChatMessage
    let onOpenCitation: (AssistantCitation) -> Void

    var body: some View {
        VStack(alignment: message.role == .user ? .trailing : .leading, spacing: 6) {
            DetectingText(text: message.text)
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .background(bubbleBackground)
                .clipShape(RoundedRectangle(cornerRadius: 14))
                .frame(maxWidth: 300, alignment: message.role == .user ? .trailing : .leading)
            if !message.sources.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    ForEach(message.sources) { source in
                        if source.isMasterData && source.source_type != "etv" {
                            // Kontakt / Dienstleister cards have no dedicated iOS
                            // screen yet → labelled but inert.
                            citationChip(label: label(for: source), icon: icon(for: source))
                        } else {
                            // Documents open in QuickLook; an ETV card deep-links
                            // to the Versammlungen tab (handled by the parent).
                            Button { onOpenCitation(source) } label: {
                                citationChip(label: label(for: source), icon: icon(for: source))
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: message.role == .user ? .trailing : .leading)
    }

    private var bubbleBackground: Color {
        message.role == .user ? Color.accentColor.opacity(0.15) : Color(.secondarySystemBackground)
    }

    private func label(for source: AssistantCitation) -> String {
        let body: String
        // Name master-data cards by kind — a contact card must NOT read
        // "Dienstleister"; owners/tenants are Kontakte.
        switch source.source_type {
        case "dienstleister":
            body = "Dienstleister: \(source.contact_name ?? "?")"
        case "contact":
            body = "Kontakt: \(source.contact_name ?? "?")"
        case "etv":
            body = "Eigentümerversammlung"
        default:
            let parts = [source.source_kind, source.contact_name].compactMap { $0 }
            let base = parts.isEmpty ? "Dokument" : parts.joined(separator: " · ")
            body = source.page.map { "\(base) · S.\($0)" } ?? base
        }
        // Prefix the cited number so it maps to the inline [n] in the answer.
        return "[\(source.index)] \(body)"
    }

    private func icon(for source: AssistantCitation) -> String {
        switch source.source_type {
        case "dienstleister": return "wrench.and.screwdriver.fill"
        case "contact": return "person.fill"
        case "etv": return "person.3.fill"
        default: return "doc.text"
        }
    }

    private func citationChip(label: String, icon: String) -> some View {
        Label(label, systemImage: icon)
            .font(.caption)
            .lineLimit(1)
            .padding(.horizontal, 10)
            .padding(.vertical, 5)
            .background(Capsule().fill(Color(.tertiarySystemFill)))
    }
}

// MARK: - Floating launcher

/// Bottom-right floating bubble that opens the assistant. Replaces the old
/// standalone CallVerwaltungButton overlay (the call action moved into the
/// dialog). Mounted once in RootTabView so it rides above every tab.
struct AssistantBubble: View {
    @Binding var isOpen: Bool

    var body: some View {
        Button {
            isOpen = true
        } label: {
            Image(systemName: "bubble.left.and.bubble.right.fill")
                .font(.title2)
                .foregroundStyle(.white)
                .frame(width: 56, height: 56)
                .background(Circle().fill(Color.accentColor))
                .shadow(color: .black.opacity(0.18), radius: 6, y: 3)
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Assistent öffnen")
        .accessibilityHint("Fragen zu Ihren Dokumenten — oder die Verwaltung anrufen")
    }
}

#Preview {
    AssistantView(model: AssistantChatModel())
        .environmentObject(DeepLinkRouter())
}
