// Main app shell — visible only after the user has selected a
// Liegenschaft. Five tabs: Mitteilungen / Tickets / ETV / News /
// Einstellungen. Liegenschaft is *not* a tab — it's the startup
// screen + a switcher row at the top of Einstellungen.
//
// Tab swipe: the user can swipe left/right anywhere on the screen
// to move between tabs. SwiftUI's TabView retains child views even
// when not selected, so the gesture only changes `selection` —
// per-tab state (scroll positions, open detail screens, in-flight
// fetches, draft comment text) carries over for free.

import SwiftUI

struct RootTabView: View {
    @EnvironmentObject var store: LiegenschaftStore
    @State private var selection = 2  // start on ETV — the most
                                       // load-bearing tab today

    private let tabCount = 5

    var body: some View {
        tabs
            // Floating Verwaltung-Hotline button — bottom-right,
            // pinned above the tab bar via .safeAreaInset so it
            // never collides with the tab bar items and never sits
            // under the home indicator. Same shape on every tab.
            .overlay(alignment: .bottomTrailing) {
                CallVerwaltungButton()
                    .padding(.trailing, 16)
                    .padding(.bottom, 64)  // floats above the tab bar
            }
    }

    private var tabs: some View {
        TabView(selection: $selection) {
            ComingSoonView(
                title: "Mitteilungen",
                subtitle: "Verwalter-Mitteilungen",
                contextLiegenschaft: store.selected
            )
            .tabItem {
                Label("Mitteilungen", systemImage: "megaphone")
            }
            .tag(0)

            ComingSoonView(
                title: "Tickets",
                subtitle: "Schaden- und Anfrage-Tickets",
                contextLiegenschaft: store.selected
            )
            .tabItem {
                Label("Tickets", systemImage: "tray.full")
            }
            .tag(1)

            VersammlungenTab()
                .tabItem {
                    Label("ETV", systemImage: "person.3")
                }
                .tag(2)

            NewsTab()
                .tabItem {
                    Label("News", systemImage: "newspaper")
                }
                .tag(3)

            EinstellungenView()
                .tabItem {
                    Label("Einstellungen", systemImage: "gear")
                }
                .tag(4)
        }
        // Horizontal swipe → flip selection. simultaneousGesture so
        // it cohabits with vertical ScrollViews inside each tab; the
        // axis filter (horizontal-dominant motion + 60pt threshold)
        // keeps it from interfering with reading-direction scroll.
        .simultaneousGesture(
            DragGesture(minimumDistance: 30)
                .onEnded { value in
                    let h = value.translation.width
                    let v = value.translation.height
                    let threshold: CGFloat = 60
                    guard abs(h) > abs(v) * 1.5, abs(h) > threshold else { return }
                    withAnimation(.easeInOut(duration: 0.2)) {
                        if h < 0, selection < tabCount - 1 {
                            selection += 1
                        } else if h > 0, selection > 0 {
                            selection -= 1
                        }
                    }
                }
        )
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
                    // Same library backdrop the picker uses — the
                    // active-Liegenschaft row in Settings should feel
                    // like the same entity, just compacted.
                    .listRowBackground(PropertyBackground())
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
