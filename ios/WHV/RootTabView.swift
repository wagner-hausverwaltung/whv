// Top-level navigation. iOS 17+ TabView with five intended tabs.
//
// `Fachinfos` is the only fully-implemented tab in this scaffold —
// it reads the vermieter1x1.de RSS feed and shows clickable cards.
// The other tabs render `ComingSoonView` placeholders that match
// the final app's information architecture so the Verwalter can
// poke around the simulator while Phase 2 lands the real screens.

import SwiftUI

struct RootTabView: View {
    var body: some View {
        TabView {
            ComingSoonView(
                title: "Liegenschaften",
                subtitle: "Eigentümer-/Mieter-Portal"
            )
            .tabItem {
                Label("Liegenschaften", systemImage: "building.2")
            }

            ComingSoonView(
                title: "Tickets",
                subtitle: "Schaden- und Anfrage-Tickets"
            )
            .tabItem {
                Label("Tickets", systemImage: "tray.full")
            }

            ComingSoonView(
                title: "Mitteilungen",
                subtitle: "Verwalter-Mitteilungen"
            )
            .tabItem {
                Label("Mitteilungen", systemImage: "megaphone")
            }

            FachinfosTab()
                .tabItem {
                    Label("Fachinfos", systemImage: "newspaper")
                }

            ComingSoonView(
                title: "Einstellungen",
                subtitle: "Konto und Benachrichtigungen"
            )
            .tabItem {
                Label("Einstellungen", systemImage: "gear")
            }
        }
    }
}

/// Placeholder for tabs not yet wired up. Renders a friendly empty
/// state so the tab bar shape is realistic without crashing when
/// the user taps an unfinished section.
struct ComingSoonView: View {
    let title: String
    let subtitle: String

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
            }
            .padding()
            .navigationTitle(title)
        }
    }
}

#Preview {
    RootTabView()
}
