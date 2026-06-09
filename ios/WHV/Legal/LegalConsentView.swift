// First-launch legal & consent screen — mirrors casavi's "Rechtliche
// Informationen". Shown once (until the user taps "Bestätigen"), gated by
// @AppStorage("hasAcceptedLegalConsent") in WHVApp. Nutzungsbedingungen /
// Datenschutz open in an in-app browser (SafariView); "Kontaktieren Sie uns"
// opens Mail. No network/auth — it sits in front of the login flow.

import SwiftUI

struct LegalConsentView: View {
    var onConfirm: () -> Void

    @Environment(\.openURL) private var openURL
    @State private var webLink: WebLink?

    private struct WebLink: Identifiable {
        let id = UUID()
        let url: URL
    }

    // Marketing-site URLs. NOTE: confirm the Nutzungsbedingungen page exists at
    // this path (the site currently publishes /datenschutz, /impressum, /cookie).
    private static let termsURL = URL(string: "https://wagner-hausverwaltung.com/nutzungsbedingungen")!
    private static let privacyURL = URL(string: "https://wagner-hausverwaltung.com/datenschutz")!
    private static let contactURL = URL(string: "mailto:info@wagner-hausverwaltung.com")!

    var body: some View {
        VStack(spacing: 0) {
            header
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    // Single-line literals so Text(LocalizedStringKey) localises them
                    // (a "+"-concatenated String would hit the verbatim initializer).
                    Text("Mit der Nutzung unserer App erklären Sie sich ausschließlich mit unseren Nutzungsbedingungen und Datenschutzvereinbarungen einverstanden.")
                    Text("Für weitere Informationen oder Fragen zögern Sie bitte nicht, uns zu kontaktieren.")
                    docButton("Nutzungsbedingungen", url: Self.termsURL)
                    docButton("Datenschutz", url: Self.privacyURL)
                    Button {
                        openURL(Self.contactURL)
                    } label: {
                        Label("Kontaktieren Sie uns", systemImage: "bubble.left")
                            .font(.headline)
                    }
                    .padding(.top, 4)
                }
                .padding(20)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            Button(action: onConfirm) {
                Text("Bestätigen")
                    .font(.headline)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 6)
            }
            .buttonStyle(.borderedProminent)
            .padding(20)
        }
        .sheet(item: $webLink) { link in
            SafariView(url: link.url).ignoresSafeArea()
        }
    }

    private var header: some View {
        Text("Rechtliche Informationen")
            .font(.title2.weight(.bold))
            .foregroundStyle(.white)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 22)
            .background(Color.accentColor)
    }

    private func docButton(_ title: LocalizedStringResource, url: URL) -> some View {
        Button {
            webLink = WebLink(url: url)
        } label: {
            Text(title)
                .font(.headline)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 8)
        }
        .buttonStyle(.bordered)
    }
}
