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
}

@MainActor
final class DeepLinkRouter: ObservableObject {
    /// Set when an incoming URL arrives, cleared by the consumer
    /// once it's handled the navigation. Optional so the consumer
    /// can use `.onChange(of:)` to react.
    @Published var pendingTarget: DeepLinkTarget?

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
        let target = (url.host?.lowercased() ?? "").isEmpty
            ? url.path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
            : url.host!.lowercased()
        switch target {
        case "new-ticket":
            pendingTarget = .newTicket
            return true
        default:
            return false
        }
    }

    func consume() {
        pendingTarget = nil
    }
}
