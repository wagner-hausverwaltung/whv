// Article detail: a WKWebView wrapped in a SwiftUI host. The
// user asked for an "iframe" — on iOS the closest equivalent is an
// in-app WebKit view (vs. handing off to Safari, which would feel
// like the user left the app).
//
// vermieter1x1.de serves the article pages with no X-Frame-Options
// and no restrictive CSP, so they render cleanly inside WKWebView.
// If a future article were to ship a CSP that blocks framing, the
// "In Safari öffnen" toolbar button is the escape hatch.

import SwiftUI
@preconcurrency import WebKit

struct ArticleDetailView: View {
    let item: RSSItem

    @State private var isLoading = true
    @State private var loadError: String?
    @State private var canGoBack = false
    @State private var canGoForward = false

    /// External handle to the underlying WKWebView so the toolbar
    /// can drive `goBack` / `goForward` without piping commands
    /// through a Coordinator. SwiftUI doesn't give us a built-in
    /// channel for this, so the WebViewRepresentable stores a
    /// reference via a binding.
    @State private var webView: WKWebView?

    var body: some View {
        ZStack {
            ArticleWebView(
                url: item.link,
                isLoading: $isLoading,
                loadError: $loadError,
                canGoBack: $canGoBack,
                canGoForward: $canGoForward,
                webViewRef: $webView
            )

            if isLoading {
                ProgressView()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .background(.background.opacity(0.6))
            }

            if let message = loadError {
                VStack(spacing: 12) {
                    Image(systemName: "wifi.exclamationmark")
                        .font(.system(size: 36))
                        .foregroundStyle(.orange)
                    Text("Seite konnte nicht geladen werden")
                        .font(.headline)
                    Text(message)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal)
                    Button("In Safari öffnen") {
                        UIApplication.shared.open(item.link)
                    }
                    .buttonStyle(.borderedProminent)
                }
                .padding()
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(.background)
            }
        }
        .navigationTitle("Fachinfo")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItemGroup(placement: .bottomBar) {
                Button {
                    webView?.goBack()
                } label: {
                    Image(systemName: "chevron.left")
                }
                .disabled(!canGoBack)

                Button {
                    webView?.goForward()
                } label: {
                    Image(systemName: "chevron.right")
                }
                .disabled(!canGoForward)

                Spacer()

                Button {
                    UIApplication.shared.open(item.link)
                } label: {
                    Image(systemName: "safari")
                }

                ShareLink(item: item.link) {
                    Image(systemName: "square.and.arrow.up")
                }
            }
        }
    }
}

/// UIKit bridge for `WKWebView`. The bindings let SwiftUI react to
/// load state changes (progress spinner + nav-button enablement).
private struct ArticleWebView: UIViewRepresentable {
    let url: URL
    @Binding var isLoading: Bool
    @Binding var loadError: String?
    @Binding var canGoBack: Bool
    @Binding var canGoForward: Bool
    @Binding var webViewRef: WKWebView?

    func makeCoordinator() -> Coordinator {
        Coordinator(self)
    }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        // Allow inline media + safe defaults. JS stays enabled —
        // the article pages depend on it for layout.
        let view = WKWebView(frame: .zero, configuration: config)
        view.navigationDelegate = context.coordinator
        view.allowsBackForwardNavigationGestures = true
        view.load(URLRequest(url: url))
        // Surface the live reference back to the host view so the
        // toolbar can fire goBack/goForward. Async to avoid the
        // SwiftUI "modifying state during view update" warning.
        DispatchQueue.main.async {
            self.webViewRef = view
        }
        return view
    }

    func updateUIView(_ uiView: WKWebView, context: Context) {
        // If the parent's `url` ever changes (it shouldn't — this
        // view is created fresh per article), reload.
        if uiView.url != url {
            uiView.load(URLRequest(url: url))
        }
    }

    final class Coordinator: NSObject, WKNavigationDelegate {
        var parent: ArticleWebView

        init(_ parent: ArticleWebView) {
            self.parent = parent
        }

        func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
            parent.isLoading = true
            parent.loadError = nil
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            parent.isLoading = false
            parent.canGoBack = webView.canGoBack
            parent.canGoForward = webView.canGoForward
        }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            parent.isLoading = false
            parent.loadError = error.localizedDescription
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            parent.isLoading = false
            parent.loadError = error.localizedDescription
        }
    }
}
