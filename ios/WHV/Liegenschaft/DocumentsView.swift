// Owner-facing documents browser for one property — the iOS counterpart of
// the portal's Dokumente tab. A flat, newest-first list grouped by year; tap a
// row to download (authed) and preview in QuickLook. The Verwalter folder tree
// stays portal-only — owners just want to find a document. Reached from the
// Property screen's Quick Access.

import SwiftUI

/// One document row from GET /me/properties/{id}/documents — the subset the
/// iOS list needs (mirrors the backend DocumentResponse).
struct DocumentResponse: Codable, Identifiable, Hashable {
    let id: String
    let name: String
    let kind: String
    let amount: String?
    let issued_date: String?
    let size_bytes: Int?
    let mime_type: String?
    let unit_id: String?
    let contract_id: String?
    let contact_id: String?
    let uploaded_at: String?
}

struct DocumentsView: View {
    let propertyId: String

    @Environment(\.dismiss) private var dismiss
    @State private var documents: [DocumentResponse] = []
    @State private var isLoading = true
    @State private var loadError: String?
    @State private var downloadingId: String?
    @State private var preview: PreviewItem?
    @State private var searchText = ""

    private let api = APIClient()

    private struct PreviewItem: Identifiable {
        let id = UUID()
        let url: URL
    }

    var body: some View {
        NavigationStack {
            content
                .navigationTitle("Dokumente")
                .navigationBarTitleDisplayMode(.inline)
                .searchable(text: $searchText, prompt: "Name, Art, Jahr …")
                .toolbar {
                    ToolbarItem(placement: .confirmationAction) {
                        Button("Fertig") { dismiss() }
                    }
                }
                .task { await load() }
                .sheet(item: $preview) { p in
                    FilePreview(url: p.url).ignoresSafeArea()
                }
        }
    }

    @ViewBuilder
    private var content: some View {
        if isLoading {
            ProgressView("Wird geladen…")
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if let loadError {
            ContentUnavailableView(
                "Konnte nicht geladen werden",
                systemImage: "exclamationmark.triangle",
                description: Text(loadError)
            )
        } else if documents.isEmpty {
            ContentUnavailableView(
                "Keine Dokumente",
                systemImage: "doc",
                description: Text("Für diese Liegenschaft sind keine Dokumente hinterlegt.")
            )
        } else if groupedByYear.isEmpty {
            ContentUnavailableView.search(text: searchText)
        } else {
            List {
                ForEach(groupedByYear, id: \.0) { year, docs in
                    Section(year) {
                        ForEach(docs) { doc in row(doc) }
                    }
                }
            }
        }
    }

    private func row(_ doc: DocumentResponse) -> some View {
        Button {
            Task { await open(doc) }
        } label: {
            HStack(spacing: 12) {
                Image(systemName: "doc.text").foregroundStyle(.secondary)
                VStack(alignment: .leading, spacing: 4) {
                    HStack(spacing: 8) {
                        Text(kindLabel(doc.kind))
                            .font(.caption2.weight(.semibold))
                            .padding(.horizontal, 6)
                            .padding(.vertical, 2)
                            .background(Color(.secondarySystemFill))
                            .clipShape(Capsule())
                        Text(title(doc))
                            .font(.subheadline)
                            .foregroundStyle(.primary)
                            .lineLimit(2)
                    }
                    if let date = doc.issued_date {
                        Text(date).font(.caption).foregroundStyle(.secondary)
                    }
                }
                Spacer(minLength: 8)
                if downloadingId == doc.id {
                    ProgressView()
                } else {
                    Image(systemName: "arrow.down.circle").foregroundStyle(.secondary)
                }
            }
        }
        .buttonStyle(.plain)
    }

    // MARK: - Data

    private func load() async {
        isLoading = true
        loadError = nil
        defer { isLoading = false }
        do {
            documents = try await api.getMyPropertyDocuments(propertyId: propertyId)
        } catch let err as APIError {
            loadError = err.errorDescription
        } catch {
            loadError = error.localizedDescription
        }
    }

    private func open(_ doc: DocumentResponse) async {
        guard downloadingId == nil else { return }
        downloadingId = doc.id
        defer { downloadingId = nil }
        do {
            let url = try await api.downloadDocument(id: doc.id)
            preview = PreviewItem(url: url)
        } catch let err as APIError {
            loadError = err.errorDescription
        } catch {
            loadError = "Download fehlgeschlagen."
        }
    }

    // MARK: - Presentation helpers

    /// Token AND-search over title, kind label and year — mirrors the
    /// portal's document search.
    private var filteredDocuments: [DocumentResponse] {
        let tokens = searchText.lowercased().split(separator: " ").map(String.init)
        guard !tokens.isEmpty else { return documents }
        return documents.filter { doc in
            let haystack = "\(title(doc)) \(kindLabel(doc.kind)) \(year(doc)) \(doc.name)"
                .lowercased()
            return tokens.allSatisfy { haystack.contains($0) }
        }
    }

    /// Newest-first, grouped by year (issued date, else upload time).
    private var groupedByYear: [(String, [DocumentResponse])] {
        let sorted = filteredDocuments.sorted { sortKey($0) > sortKey($1) }
        var groups: [(String, [DocumentResponse])] = []
        for doc in sorted {
            let y = year(doc)
            if groups.last?.0 == y {
                groups[groups.count - 1].1.append(doc)
            } else {
                groups.append((y, [doc]))
            }
        }
        return groups
    }

    private func sortKey(_ d: DocumentResponse) -> String {
        d.issued_date ?? d.uploaded_at ?? ""
    }

    private func year(_ d: DocumentResponse) -> String {
        let head = String((d.issued_date ?? d.uploaded_at ?? "").prefix(4))
        return head.count == 4 ? head : "Ohne Datum"
    }

    /// Invoice names from Impower are bare numbers — lead with the amount.
    /// Collapse Impower's doubled words ("Sonderumlage Sonderumlage …").
    private func title(_ d: DocumentResponse) -> String {
        let name = collapseRepeatedWords(d.name)
        if d.kind == "RECHNUNG", let raw = d.amount, let value = Double(raw) {
            let f = NumberFormatter()
            f.numberStyle = .currency
            f.currencyCode = "EUR"
            f.locale = Locale(identifier: "de_DE")
            if let money = f.string(from: NSNumber(value: value)) {
                return name.isEmpty ? money : "\(money) · \(name)"
            }
        }
        return name
    }

    private func kindLabel(_ kind: String) -> String {
        switch kind {
        case "RECHNUNG": return "Rechnung"
        case "JAHRESABRECHNUNG": return "Abrechnung"
        case "WIRTSCHAFTSPLAN": return "Wirtschaftsplan"
        case "PROTOKOLL": return "Protokoll"
        case "VERTRAG": return "Vertrag"
        case "UMLAUFBESCHLUSS": return "Umlaufbeschluss"
        case "HAUSORDNUNG": return "Hausordnung"
        case "SIGNATUR": return "Signatur"
        default: return "Sonstiges"
        }
    }
}

/// Collapse runs of the same consecutive word ("Sonderumlage Sonderumlage X" →
/// "Sonderumlage X"); Impower composes some names with a doubled leading word.
private func collapseRepeatedWords(_ s: String) -> String {
    var out: [String] = []
    for word in s.split(separator: " ").map(String.init) where !word.isEmpty {
        if out.last?.lowercased() != word.lowercased() { out.append(word) }
    }
    return out.joined(separator: " ")
}
