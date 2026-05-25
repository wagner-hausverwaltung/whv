// Main app shell — visible only after the user has selected a
// Liegenschaft. Four tabs: Mitteilungen / Tickets / News /
// Einstellungen. Liegenschaft is *not* a tab — it's the startup
// screen + a switcher row at the top of Einstellungen.
//
// News is the only tab fully wired up; the other property-scoped
// ones render `ComingSoonView` placeholders that show the active
// Liegenschaft as context so the user can see which property
// they'd be acting on once Phase 2 fills these in.

import SwiftUI

struct RootTabView: View {
    @EnvironmentObject var store: LiegenschaftStore

    var body: some View {
        TabView {
            ComingSoonView(
                title: "Mitteilungen",
                subtitle: "Verwalter-Mitteilungen",
                contextLiegenschaft: store.selected
            )
            .tabItem {
                Label("Mitteilungen", systemImage: "megaphone")
            }

            ComingSoonView(
                title: "Tickets",
                subtitle: "Schaden- und Anfrage-Tickets",
                contextLiegenschaft: store.selected
            )
            .tabItem {
                Label("Tickets", systemImage: "tray.full")
            }

            NewsTab()
                .tabItem {
                    Label("News", systemImage: "newspaper")
                }

            EinstellungenView()
                .tabItem {
                    Label("Einstellungen", systemImage: "gear")
                }
        }
    }
}

/// Placeholder for tabs not yet wired up. Optionally renders the
/// active Liegenschaft as a context line so the user knows which
/// property the tab will operate on once Phase 2 fills it in.
struct ComingSoonView: View {
    let title: String
    let subtitle: String
    let contextLiegenschaft: Liegenschaft?

    init(title: String, subtitle: String, contextLiegenschaft: Liegenschaft? = nil) {
        self.title = title
        self.subtitle = subtitle
        self.contextLiegenschaft = contextLiegenschaft
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 12) {
                Image(systemName: "hourglass.bottomhalf.filled")
                    .font(.system(size: 56))
                    .foregroundStyle(.tertiary)
                Text(title)
                    .font(.title2.bold())
                Text(subtitle)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                Text("Folgt in Phase 2.")
                    .font(.footnote)
                    .foregroundStyle(.tertiary)
                    .padding(.top, 4)
                if let l = contextLiegenschaft {
                    Divider().padding(.vertical, 8).padding(.horizontal, 40)
                    VStack(spacing: 2) {
                        Text("Aktive Liegenschaft")
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                            .textCase(.uppercase)
                        Text(l.name)
                            .font(.subheadline.weight(.medium))
                        Text(l.address)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
            .padding()
            .navigationTitle(title)
        }
    }
}

/// Settings — top row is the active Liegenschaft (compact, no
/// explainer copy; the user knows what it is). Tapping the
/// trailing arrow-swap icon clears the selection and bounces back
/// to the picker. Below: Erscheinungsbild + Sprache (both default
/// System), then the marketing-site legal links opened in Safari.
struct EinstellungenView: View {
    @EnvironmentObject var liegenschaftStore: LiegenschaftStore
    @EnvironmentObject var settings: SettingsStore

    var body: some View {
        NavigationStack {
            List {
                // Liegenschaft pinned to the top — bare row, no
                // section header / footer copy. Users rarely
                // switch; we want a clean tap target rather than a
                // mini-tutorial.
                if let l = liegenschaftStore.selected {
                    Button {
                        liegenschaftStore.clear()
                    } label: {
                        HStack(spacing: 12) {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(l.name)
                                    .font(.headline)
                                    .foregroundStyle(.primary)
                                Text(l.address)
                                    .font(.subheadline)
                                    .foregroundStyle(.secondary)
                            }
                            Spacer(minLength: 8)
                            Image(systemName: "arrow.left.arrow.right")
                                .font(.body)
                                .foregroundStyle(.tint)
                        }
                        .padding(.vertical, 2)
                    }
                }

                Section("Erscheinungsbild") {
                    Picker("Modus", selection: $settings.appearance) {
                        ForEach(AppearancePreference.allCases) { p in
                            Text(p.label).tag(p)
                        }
                    }
                    .pickerStyle(.segmented)
                }

                Section("Sprache") {
                    Picker("Sprache", selection: $settings.language) {
                        ForEach(LanguagePreference.allCases) { p in
                            Text(p.label).tag(p)
                        }
                    }
                    .pickerStyle(.segmented)
                }

                Section("Rechtliches") {
                    legalLink(
                        "Impressum",
                        url: "https://wagner-hausverwaltung.com/impressum"
                    )
                    legalLink(
                        "Datenschutzerklärung",
                        url: "https://wagner-hausverwaltung.com/datenschutz"
                    )
                    legalLink(
                        "Cookie-Richtlinie (EU)",
                        url: "https://wagner-hausverwaltung.com/cookie"
                    )
                }
            }
            .navigationTitle("Einstellungen")
        }
    }

    private func legalLink(_ label: String, url: String) -> some View {
        // Link opens the URL in the system browser (Safari). For an
        // in-app web view we'd use WKWebView like ArticleDetailView,
        // but for legal pages the convention is to hand off to
        // Safari so the user can bookmark / share / read in their
        // own tab session.
        Link(destination: URL(string: url)!) {
            HStack {
                Text(label)
                    .foregroundStyle(.primary)
                Spacer()
                Image(systemName: "arrow.up.right.square")
                    .font(.caption)
                    .foregroundStyle(.tertiary)
            }
        }
    }
}

#Preview {
    RootTabView()
        .environmentObject({
            let s = LiegenschaftStore()
            s.select(Liegenschaft.demo[0])
            return s
        }())
        .environmentObject(SettingsStore())
}
