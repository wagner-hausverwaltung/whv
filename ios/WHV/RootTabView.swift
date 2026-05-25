// Main app shell — visible only after the user has selected a
// Liegenschaft. Four tabs: Tickets / Mitteilungen / Fachinfos /
// Einstellungen. Liegenschaften is *not* a tab — it's the startup
// screen + a switch action on Einstellungen.
//
// Fachinfos is the only tab fully wired up; the other property-
// scoped ones render `ComingSoonView` placeholders that show the
// active Liegenschaft as context so the user can see which property
// they'd be acting on once Phase 2 fills these in.

import SwiftUI

struct RootTabView: View {
    @EnvironmentObject var store: LiegenschaftStore

    var body: some View {
        TabView {
            ComingSoonView(
                title: "Tickets",
                subtitle: "Schaden- und Anfrage-Tickets",
                contextLiegenschaft: store.selected
            )
            .tabItem {
                Label("Tickets", systemImage: "tray.full")
            }

            ComingSoonView(
                title: "Mitteilungen",
                subtitle: "Verwalter-Mitteilungen",
                contextLiegenschaft: store.selected
            )
            .tabItem {
                Label("Mitteilungen", systemImage: "megaphone")
            }

            FachinfosTab()
                .tabItem {
                    Label("Fachinfos", systemImage: "newspaper")
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

/// Settings — minimal v1 shape. Currently exposes only the active
/// Liegenschaft + a "wechseln" action that drops the selection and
/// kicks the user back to the picker. Phase 2 grows this into the
/// full Profile/Sprache/Biometrie/Konto löschen surface from
/// REQUIREMENTS.md §8.3.
struct EinstellungenView: View {
    @EnvironmentObject var store: LiegenschaftStore

    var body: some View {
        NavigationStack {
            List {
                if let l = store.selected {
                    Section {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(l.name).font(.headline)
                            Text(l.address)
                                .font(.subheadline)
                                .foregroundStyle(.secondary)
                            if let type = l.type {
                                Text(type)
                                    .font(.caption)
                                    .foregroundStyle(.tertiary)
                                    .padding(.top, 2)
                            }
                        }
                        .padding(.vertical, 4)
                        Button(role: .destructive) {
                            store.clear()
                        } label: {
                            Label("Liegenschaft wechseln", systemImage: "arrow.triangle.2.circlepath")
                        }
                    } header: {
                        Text("Aktive Liegenschaft")
                    } footer: {
                        Text(
                            "Wechseln startet die Liegenschaft-Auswahl neu. "
                                + "Andere Einstellungen bleiben erhalten."
                        )
                    }
                }

                Section {
                    placeholderRow("Profil", systemImage: "person.crop.circle")
                    placeholderRow("Sprache", systemImage: "globe")
                    placeholderRow("Benachrichtigungen", systemImage: "bell")
                    placeholderRow("Biometrische Sperre", systemImage: "faceid")
                } header: {
                    Text("Folgt in Phase 2")
                }
            }
            .navigationTitle("Einstellungen")
        }
    }

    private func placeholderRow(_ label: String, systemImage: String) -> some View {
        HStack {
            Label(label, systemImage: systemImage)
                .foregroundStyle(.secondary)
            Spacer()
            Text("noch nicht verfügbar")
                .font(.caption)
                .foregroundStyle(.tertiary)
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
}
