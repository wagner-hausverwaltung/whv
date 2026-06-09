// In-app browser (the iOS equivalent of an HTML iframe) for showing a web
// page — Datenschutz / Nutzungsbedingungen — without leaving the app.
// SFSafariViewController gives system-grade rendering + a Done/Share bar.

import SafariServices
import SwiftUI

struct SafariView: UIViewControllerRepresentable {
    let url: URL

    func makeUIViewController(context: Context) -> SFSafariViewController {
        SFSafariViewController(url: url)
    }

    func updateUIViewController(_ controller: SFSafariViewController, context: Context) {}
}
