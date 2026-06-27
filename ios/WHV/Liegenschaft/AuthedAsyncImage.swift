// JWT-authed image loader for the WHV backend.
//
// Property hero photos are served auth-gated
// (`GET /admin/property-images/{id}.png`, JWT required), so a plain
// SwiftUI `AsyncImage` would 401. This view fetches the bytes through
// `APIClient.fetchImageData(path:)` — same Bearer token + one-shot
// 401-refresh-retry as every other authed call — and hands the decoded
// image to a caller-supplied builder. While loading (or on failure) the
// `placeholder` is shown, so the caller can fall back to its non-photo
// style without flicker.
//
// `path` is the relative `image_url` the API returns
// (e.g. "/admin/property-images/{id}.png?v=…"); the client prepends the
// API base. A nil/empty path renders the placeholder and never hits the
// network.

import SwiftUI

struct AuthedAsyncImage<Content: View, Placeholder: View>: View {
    /// Relative image path from the API (`image_url`). Nil/empty → placeholder.
    let path: String?
    @ViewBuilder let content: (Image) -> Content
    @ViewBuilder let placeholder: () -> Placeholder

    /// A plain struct value — cheap to construct per render; the token is
    /// pulled at request time so a fresh sign-in is always picked up.
    private let api = APIClient()

    @State private var loaded: Image?
    /// Guards against re-fetching the same path on every body re-eval.
    @State private var loadedPath: String?

    var body: some View {
        Group {
            if let loaded {
                content(loaded)
            } else {
                placeholder()
            }
        }
        .task(id: path) {
            await load()
        }
    }

    private func load() async {
        guard let path, !path.isEmpty else {
            loaded = nil
            loadedPath = nil
            return
        }
        // Already have this exact image — don't refetch.
        if loadedPath == path, loaded != nil { return }
        do {
            let data = try await api.fetchImageData(path: path)
            guard let uiImage = UIImage(data: data) else { return }
            loaded = Image(uiImage: uiImage)
            loadedPath = path
        } catch {
            // Silent: the placeholder (caller's non-photo style) stays up.
            // A failed hero photo must never blank the card.
        }
    }
}
