// Main app shell — visible only after the user has selected a
// Liegenschaft. Four tabs: News (= announcements) / Tickets / ETV /
// Einstellungen. Liegenschaft is *not* a tab — it's the startup
// screen + a switcher row at the top of Einstellungen.
//
// The Mitteilungen tab is labelled "News" in the tab bar because
// it fits the iOS tab-bar width better than "Mitteilungen" on
// smaller iPhones; the inner navigation title stays "News" too so
// the user doesn't read two different words for the same screen.
// The vermieter1x1.de RSS feed tab (`NewsTab.swift`) is currently
// hidden — see commit history if you want to restore it.
//
// Tab swipe: the user can swipe left/right anywhere on the screen
// to move between tabs. SwiftUI's TabView retains child views even
// when not selected, so the gesture only changes `selection` —
// per-tab state (scroll positions, open detail screens, in-flight
// fetches, draft comment text) carries over for free.

import SwiftUI

struct RootTabView: View {
    @EnvironmentObject var store: LiegenschaftStore
    @EnvironmentObject var deepLinkRouter: DeepLinkRouter
    @EnvironmentObject var authStore: AuthStore
    @State private var selection = 2  // start on ETV — the most
                                       // load-bearing tab today
    @State private var newTicketSheetOpen = false
    @State private var assistantOpen = false

    private let tabCount = 4

    var body: some View {
        // Demo banner now lives in WHVApp as a VStack sibling of
        // the whole rootView (LoginView / picker / tab shell) so
        // it sits ABOVE the navigation bar instead of fighting it
        // for safe-area space. Removed from here.
        tabs
            // Floating assistant bubble — bottom-right, pinned above the
            // tab bar on every tab. Opens the RAG document assistant; the
            // old standalone "Dirk Ullrich anrufen" button was folded into
            // that dialog's toolbar so the two affordances no longer collide.
            .overlay(alignment: .bottomTrailing) {
                AssistantBubble(isOpen: $assistantOpen)
                    .padding(.trailing, 16)
                    .padding(.bottom, 64)  // floats above the tab bar
            }
            // Deep-link consumer. Two firing paths so we catch both
            // a runtime URL (widget tap while app is running →
            // .onChange fires) AND a cold-launch URL (URL handed in
            // before this view is in the tree, so pendingTarget is
            // already set when .onAppear fires).
            .onChange(of: deepLinkRouter.pendingTarget) { _, target in
                consumeDeepLink(target)
            }
            .onAppear {
                consumeDeepLink(deepLinkRouter.pendingTarget)
            }
            .sheet(isPresented: $newTicketSheetOpen) {
                // No-op onCreated — the Tickets tab owns its store
                // and will refresh itself on next appear. The
                // deep-link sheet is purely an entry point.
                NewTicketSheet { _ in }
            }
            .sheet(isPresented: $assistantOpen) {
                AssistantView()
            }
    }

    /// Handle a (possibly-nil) DeepLinkTarget by mutating the
    /// tab selection / opening the right sheet / pushing onto
    /// the tab's own NavigationStack. Always consumes the router
    /// so a re-fire of the same URL is treated as a fresh request.
    private func consumeDeepLink(_ target: DeepLinkTarget?) {
        guard let target else { return }
        switch target {
        case .newTicket:
            selection = 1
            newTicketSheetOpen = true
        case .tab(let t):
            selection = t.selection
        case .assembly(let id):
            selection = 2
            // Replace rather than append so a re-tap of the same
            // widget item doesn't pile detail screens on the stack.
            deepLinkRouter.etvPath = [id]
        case .ticket(let id):
            selection = 1
            deepLinkRouter.ticketsPath = [id]
        case .announcement(let id):
            selection = 0
            deepLinkRouter.mitteilungenPath = [id]
        }
        deepLinkRouter.consume()
    }

    private var tabs: some View {
        TabView(selection: $selection) {
            MitteilungenTab()
                .tabItem {
                    Label("News", systemImage: "megaphone")
                }
                .tag(0)

            TicketsTab()
                .tabItem {
                    Label("Tickets", systemImage: "tray.full")
                }
                .tag(1)

            VersammlungenTab()
                .tabItem {
                    Label("ETV", systemImage: "person.3")
                }
                .tag(2)

            // RSS-feed `NewsTab()` removed from the bar — keep the
            // file in the bundle so re-enabling it is one tabItem
            // away. The "News" label on tab 0 is for our own
            // Mitteilungen now.

            EinstellungenView()
                .tabItem {
                    Label("Einstellungen", systemImage: "gear")
                }
                .tag(3)
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

// EinstellungenView moved to WHV/Settings/EinstellungenView.swift.

#Preview {
    RootTabView()
        .environmentObject({
            let s = LiegenschaftStore()
            s.select(Liegenschaft.demo[0])
            return s
        }())
        .environmentObject(SettingsStore())
}
