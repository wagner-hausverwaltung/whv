// Lightweight deep-link router. The widget's quiet state pings
// whv://new-ticket; WHVApp's `.onOpenURL` parses the URL and flips
// state on this router; RootTabView observes it and acts (switch
// tab + present the relevant sheet).
//
// Adding a new deep link is two steps:
//   1. Add a case to `DeepLinkTarget`
//   2. Map the URL host/path → that case in `parse(_:)`
//   3. React in RootTabView.onChange(of: router.pendingTarget)
//
// We keep the router state coarse — just "go here next" — rather
// than embedding navigation logic. SwiftUI views own the actual
// presentation; this is the message bus.

import Foundation

enum DeepLinkTarget: Equatable {
    /// Switch to the Tickets tab and present the new-ticket sheet.
    case newTicket
    /// Switch to a specific tab without presenting a sheet — used
    /// by the widget's ETV / Mitteilungen / Tickets cards.
    case tab(WHVTab)
    /// Switch to ETV tab and push the assembly's detail view.
    case assembly(id: String)
    /// Switch to ETV tab (Beschlüsse) and push the Umlaufbeschluss
    /// detail view. Routed via the "res:"-prefixed nav token that
    /// VersammlungenTab's NavigationStack already understands.
    case resolution(id: String)
    /// Switch to Tickets tab and push the ticket's detail view.
    case ticket(id: String)
    /// Switch to Mitteilungen tab and push the announcement's
    /// detail view.
    case announcement(id: String)
    /// Open the Start (Liegenschaft) tab and present one of its
    /// property-scoped sheets (Dokumente / Zähler / Kalender). Used by
    /// the activity widget's document / invoice / meter / calendar
    /// rows — there's no by-id detail screen for these on iOS yet, so
    /// we land the user on the relevant property tab.
    ///
    /// `propertyId` (from the deep link's `?property=` query) is the
    /// item's OWN Liegenschaft. The feed is cross-property, so the
    /// shell switches the active property to it BEFORE opening the tab
    /// — falling back to the currently-active property when it's nil or
    /// not in the user's list.
    case propertyTab(PropertyTab, propertyId: String?)
}

/// The property-scoped sheets PropertyDetailView can present. A deep
/// link to one flips `DeepLinkRouter.pendingPropertyTab`, which
/// PropertyDetailView observes to open the matching sheet.
enum PropertyTab: Equatable {
    case documents  // whv://document/{id}, whv://invoice/{id}
    case meters     // whv://meter/{id}
    case calendar   // whv://calendar/{id}
}

/// One enum per feature a widget / push might deep-link to. The shell
/// (`RootTabView.consumeDeepLink`) maps these onto its feature sheets;
/// `news` is treated as Mitteilungen.
enum WHVTab {
    case mitteilungen
    case tickets
    case etv
    case news
    case einstellungen
}

@MainActor
final class DeepLinkRouter: ObservableObject {
    /// Set when an incoming URL arrives, cleared by the consumer
    /// once it's handled the navigation. Optional so the consumer
    /// can use `.onChange(of:)` to react.
    @Published var pendingTarget: DeepLinkTarget?

    /// Set when a deep link wants one of PropertyDetailView's
    /// property-scoped sheets (Dokumente / Zähler / Kalender). The
    /// shell selects the Start tab + dismisses any feature sheet, and
    /// PropertyDetailView observes this to open the matching sheet,
    /// then clears it via `consumePropertyTab()`.
    @Published var pendingPropertyTab: PropertyTab?

    /// Per-tab navigation paths so external code (deep links,
    /// widget taps) can push detail views from outside the tab's
    /// own UI. Each tab's NavigationStack binds to its path here.
    @Published var etvPath: [String] = []
    @Published var ticketsPath: [String] = []
    @Published var mitteilungenPath: [String] = []

    /// Parse + register an incoming URL. Returns true if we
    /// recognised it (so the caller can decide whether to flag
    /// unknown URLs to the user); false otherwise.
    @discardableResult
    func handle(_ url: URL) -> Bool {
        guard url.scheme == "whv" else { return false }
        // whv://new-ticket → host is "new-ticket"; whv:///new-ticket
        // → host is empty + path is "/new-ticket". Accept both
        // since iOS doesn't agree with itself on which form widgets
        // emit.
        let rawHost = url.host?.lowercased() ?? ""
        let path = url.path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        // Optional `?property=<uuid>` query — only the property-scoped
        // fallback hosts (document / invoice / meter / calendar) use it,
        // so the shell can switch the active Liegenschaft to the item's
        // own property first. Ignored for the by-id detail hosts.
        let propertyId: String? = URLComponents(url: url, resolvingAgainstBaseURL: false)?
            .queryItems?
            .first(where: { $0.name == "property" })?
            .value
            .flatMap { $0.isEmpty ? nil : $0 }
        let host: String
        let id: String?
        if rawHost.isEmpty {
            // whv:///foo/abc → path is "foo/abc"
            let parts = path.split(separator: "/", maxSplits: 1, omittingEmptySubsequences: true)
            host = parts.first.map { String($0).lowercased() } ?? ""
            id = parts.count > 1 ? String(parts[1]) : nil
        } else {
            host = rawHost
            id = path.isEmpty ? nil : path
        }

        switch (host, id) {
        case ("new-ticket", _):
            pendingTarget = .newTicket
        case ("etv", .some(let aid)), ("assembly", .some(let aid)):
            pendingTarget = .assembly(id: aid)
        case ("resolution", .some(let rid)), ("beschluss", .some(let rid)):
            pendingTarget = .resolution(id: rid)
        case ("ticket", .some(let tid)):
            pendingTarget = .ticket(id: tid)
        case ("announcement", .some(let anid)), ("mitteilung", .some(let anid)):
            pendingTarget = .announcement(id: anid)
        // Document / invoice / meter / calendar have no by-id detail
        // screen on iOS yet — route to the relevant property tab. The
        // id is intentionally ignored (the tab opens its own list); the
        // `?property=` query is carried so the shell can switch to the
        // item's own Liegenschaft before opening the tab.
        case ("document", _), ("invoice", _):
            pendingTarget = .propertyTab(.documents, propertyId: propertyId)
        case ("meter", _):
            pendingTarget = .propertyTab(.meters, propertyId: propertyId)
        case ("calendar", _):
            pendingTarget = .propertyTab(.calendar, propertyId: propertyId)
        case ("tickets", _):
            pendingTarget = .tab(.tickets)
        case ("etv", _), ("assembly", _):
            pendingTarget = .tab(.etv)
        case ("mitteilungen", _), ("announcement", _):
            pendingTarget = .tab(.mitteilungen)
        case ("news", _):
            pendingTarget = .tab(.news)
        case ("einstellungen", _), ("settings", _):
            pendingTarget = .tab(.einstellungen)
        default:
            return false
        }
        return true
    }

    func consume() {
        pendingTarget = nil
    }

    func consumePropertyTab() {
        pendingPropertyTab = nil
    }
}
