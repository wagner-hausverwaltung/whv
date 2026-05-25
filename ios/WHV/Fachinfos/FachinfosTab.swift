// The Fachinfos tab: a list of cards rendered from the
// vermieter1x1.de RSS feed. Tapping a card pushes
// `ArticleDetailView`, which opens the article in a WKWebView (iOS
// equivalent of an HTML iframe, per the request).

import SwiftUI

@MainActor
final class FachinfosViewModel: ObservableObject {
    @Published var items: [RSSItem] = []
    @Published var isLoading = false
    @Published var errorMessage: String?

    private let service: RSSService

    init(service: RSSService = RSSService()) {
        self.service = service
    }

    func load() async {
        // De-bounce: don't kick off a second fetch while one is
        // already in flight. Pull-to-refresh ignores this because
        // SwiftUI's `.refreshable` only fires once per gesture.
        guard !isLoading else { return }
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            items = try await service.fetch()
        } catch {
            errorMessage = (error as? RSSError)?.errorDescription
                ?? error.localizedDescription
        }
    }
}

struct FachinfosTab: View {
    @StateObject private var vm = FachinfosViewModel()

    var body: some View {
        NavigationStack {
            content
                .navigationTitle("Fachinfos")
                .toolbar {
                    ToolbarItem(placement: .topBarTrailing) {
                        Button {
                            Task { await vm.load() }
                        } label: {
                            Image(systemName: "arrow.clockwise")
                        }
                        .disabled(vm.isLoading)
                    }
                }
                .task {
                    if vm.items.isEmpty {
                        await vm.load()
                    }
                }
                .refreshable {
                    await vm.load()
                }
        }
    }

    @ViewBuilder
    private var content: some View {
        if vm.isLoading && vm.items.isEmpty {
            ProgressView("Lade…")
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if let message = vm.errorMessage, vm.items.isEmpty {
            errorState(message)
        } else if vm.items.isEmpty {
            emptyState
        } else {
            list
        }
    }

    private var list: some View {
        ScrollView {
            LazyVStack(spacing: 12) {
                ForEach(vm.items) { item in
                    NavigationLink(value: item) {
                        RSSItemCard(item: item)
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding()
        }
        .navigationDestination(for: RSSItem.self) { item in
            ArticleDetailView(item: item)
        }
    }

    private func errorState(_ message: String) -> some View {
        VStack(spacing: 12) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 40))
                .foregroundStyle(.orange)
            Text("Konnte Fachinfos nicht laden")
                .font(.headline)
            Text(message)
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal)
            Button("Erneut versuchen") {
                Task { await vm.load() }
            }
            .buttonStyle(.borderedProminent)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding()
    }

    private var emptyState: some View {
        VStack(spacing: 8) {
            Image(systemName: "newspaper")
                .font(.system(size: 40))
                .foregroundStyle(.tertiary)
            Text("Keine Fachinfos verfügbar.")
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

/// Single-card row. Title + summary (3-line clamp) + date + category
/// chip. Text-only by design — `RSSItem.imageURL` is still parsed
/// from `<enclosure>` for forward-compat, but we don't render it
/// (cards stay scannable, AsyncImage doesn't compete with the text,
/// and load is faster on cellular).
struct RSSItemCard: View {
    let item: RSSItem

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 6) {
                Text(item.title)
                    .font(.headline)
                    .multilineTextAlignment(.leading)
                Text(item.summary)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .lineLimit(3)
                    .multilineTextAlignment(.leading)
                HStack(spacing: 8) {
                    Text(item.pubDate.formatted(date: .abbreviated, time: .omitted))
                        .font(.caption)
                        .foregroundStyle(.tertiary)
                    if let category = item.category {
                        Text(category.replacingOccurrences(of: "/", with: ""))
                            .font(.caption2.bold())
                            .padding(.horizontal, 8)
                            .padding(.vertical, 3)
                            .background(.tint.opacity(0.15), in: Capsule())
                            .foregroundStyle(.tint)
                    }
                    Spacer(minLength: 0)
                    Image(systemName: "chevron.right")
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }
                .padding(.top, 2)
            }
            .padding()
        }
        .background(.background)
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .overlay(
            RoundedRectangle(cornerRadius: 12)
                .stroke(.quaternary, lineWidth: 0.5)
        )
        .shadow(color: .black.opacity(0.04), radius: 4, y: 2)
    }
}

#Preview {
    FachinfosTab()
}
