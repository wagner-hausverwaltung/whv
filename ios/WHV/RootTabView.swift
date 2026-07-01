// Main app shell — visible only after the user has selected a
// Liegenschaft. TWO tabs:
//   • Start — the active Liegenschaft as one scroll (PropertyDetailView):
//     header, Schnellzugriff (Versammlungen / Anliegen / Mitteilungen /
//     Dokumente / Zähler / Kalender), Einheiten + Kontakte, Hausgeldkonto,
//     Mietabrechnung, Dienstleister, „Liegenschaft wechseln".
//   • Einstellungen — Konto / Erscheinungsbild / Datenschutz / Rechtliches.
//
// Versammlungen / Anliegen / Mitteilungen still own their proven screens
// (VersammlungenTab / TicketsTab / MitteilungenTab) — they're presented as
// sheets from the Start cards and from widget/push deep links, so the existing
// per-tab NavigationStacks + deepLinkRouter paths keep working unchanged.
//
// The assistant stays a floating chat bubble pinned across the app.

import SwiftUI

/// Which feature screen to present over the shell (sheet). Driven by the
/// Start cards and by deep links so both reuse one presentation path.
enum FeatureSheet: Int, Identifiable {
    case etv, tickets, mitteilungen
    var id: Int { rawValue }
}

struct RootTabView: View {
    @EnvironmentObject var store: LiegenschaftStore
    @EnvironmentObject var deepLinkRouter: DeepLinkRouter
    @EnvironmentObject var authStore: AuthStore
    @State private var selection = 0  // Start
    @State private var newTicketSheetOpen = false
    @State private var assistantOpen = false
    // Owned here (not in the sheet) so the assistant conversation is preserved
    // across closing + reopening the chat within the session.
    @StateObject private var assistantModel = AssistantChatModel()
    @State private var featureSheet: FeatureSheet?

    var body: some View {
        tabs
            // Floating assistant bubble — bottom-right, pinned above the tab
            // bar on every tab. Opens the RAG document assistant (the
            // „Verwaltung anrufen" affordance lives in its toolbar).
            .overlay(alignment: .bottomTrailing) {
                AssistantBubble(isOpen: $assistantOpen)
                    .padding(.trailing, 16)
                    .padding(.bottom, 64)
            }
            // Deep-link consumer — runtime URL (.onChange) + cold-launch
            // (.onAppear, pendingTarget already set).
            .onChange(of: deepLinkRouter.pendingTarget) { _, target in
                consumeDeepLink(target)
            }
            .onAppear {
                consumeDeepLink(deepLinkRouter.pendingTarget)
            }
            .sheet(isPresented: $newTicketSheetOpen) {
                NewTicketSheet { _ in }
                    .environmentObject(authStore)
                    .environmentObject(store)
            }
            .sheet(isPresented: $assistantOpen) {
                AssistantView(propertyId: store.selected?.id, model: assistantModel)
                    .environmentObject(deepLinkRouter)
            }
            // The three feature screens, reused unchanged. Env objects are
            // injected because sheet content doesn't reliably inherit them.
            .sheet(item: $featureSheet) { which in
                featureScreen(which)
                    .environmentObject(store)
                    .environmentObject(authStore)
                    .environmentObject(deepLinkRouter)
                    .presentationDragIndicator(.visible)
            }
    }

    @ViewBuilder
    private func featureScreen(_ which: FeatureSheet) -> some View {
        switch which {
        case .etv: VersammlungenTab()
        case .tickets: TicketsTab()
        case .mitteilungen: MitteilungenTab()
        }
    }

    /// Map a DeepLinkTarget onto the 2-tab shell: open the right feature
    /// sheet (pushing its detail via the existing per-feature nav path) or
    /// the new-ticket sheet. Drives BOTH widget/push deep links and the Start
    /// quick-action rows (which set `pendingTarget`), so the dismiss/clear
    /// logic lives in one place. Always consumes so a re-fire is fresh.
    private func consumeDeepLink(_ target: DeepLinkTarget?) {
        guard let target else { return }
        deepLinkRouter.consume()
        // SwiftUI won't swap one open sheet for another (.sheet(item:) ignores
        // a non-nil→non-nil change), so dismiss whatever is showing, then
        // present the new target on the next runloop tick. Also reset the
        // per-feature nav path so a list request doesn't reopen a stale detail.
        featureSheet = nil
        newTicketSheetOpen = false
        DispatchQueue.main.async {
            switch target {
            case .newTicket:
                newTicketSheetOpen = true
            case .tab(let t):
                switch t {
                case .etv: deepLinkRouter.etvPath = []; featureSheet = .etv
                case .tickets: deepLinkRouter.ticketsPath = []; featureSheet = .tickets
                case .mitteilungen, .news:
                    deepLinkRouter.mitteilungenPath = []; featureSheet = .mitteilungen
                case .einstellungen: selection = 2
                }
            case .assembly(let id):
                deepLinkRouter.etvPath = [id]; featureSheet = .etv
            case .resolution(let id):
                // VersammlungenTab's NavigationStack maps a "res:"-prefixed
                // token to the Beschluss detail view.
                deepLinkRouter.etvPath = ["res:\(id)"]; featureSheet = .etv
            case .ticket(let id):
                deepLinkRouter.ticketsPath = [id]; featureSheet = .tickets
            case .announcement(let id):
                deepLinkRouter.mitteilungenPath = [id]; featureSheet = .mitteilungen
            case .propertyTab(let tab, let propertyId):
                // No feature sheet — land on the Start tab and let
                // PropertyDetailView open the matching property sheet.
                // The activity feed is cross-property, so first switch
                // the active Liegenschaft to the item's own property
                // (by id, when it's in the user's list); if it's nil or
                // unknown, keep the currently-active property. Then ask
                // PropertyDetailView to open the requested tab.
                if let pid = propertyId,
                   pid != store.selected?.id,
                   let match = store.available.first(where: { $0.id == pid })
                {
                    store.select(match)
                }
                selection = 0
                deepLinkRouter.pendingPropertyTab = tab
            }
        }
    }

    /// Anfragen is a Verwalter-only tab (the offer-inquiry queue); members
    /// never see it. Tags stay stable (Start 0, Anfragen 1, Einstellungen 2) so
    /// the `.einstellungen` deep link lands correctly whether or not tab 1 is
    /// mounted.
    private var isVerwalter: Bool {
        authStore.user?.role.lowercased() == "verwalter"
    }

    private var tabs: some View {
        TabView(selection: $selection) {
            HomeTab()
                .tabItem {
                    Label("Start", systemImage: "house")
                }
                .tag(0)

            if isVerwalter {
                AnfragenTab()
                    .tabItem {
                        Label("Anfragen", systemImage: "envelope.badge")
                    }
                    .tag(1)
            }

            EinstellungenView()
                .tabItem {
                    Label("Einstellungen", systemImage: "gear")
                }
                .tag(2)
        }
    }
}

/// The Start tab — the active Liegenschaft rendered as one scroll. Wraps
/// PropertyDetailView in a NavigationStack (it has none of its own). Its
/// Schnellzugriff cards open Versammlungen / Anliegen / Mitteilungen by
/// setting `deepLinkRouter.pendingTarget`, so the shell's single
/// `consumeDeepLink` path handles dismissing/clearing + presenting.
struct HomeTab: View {
    @EnvironmentObject var store: LiegenschaftStore

    var body: some View {
        NavigationStack {
            if let l = store.selected {
                PropertyDetailView(property: l)
            } else {
                ContentUnavailableView(
                    "Keine Liegenschaft", systemImage: "building.2",
                    description: Text("Wähle eine Liegenschaft aus."))
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
