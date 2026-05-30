// WHV Verwaltung contact (Dirk Ullrich) — the single source of truth for
// the Verwalter-Hotline name + number, and the tel: URL derived from it.
//
// History: a floating "Dirk Ullrich anrufen" capsule used to sit across
// every tab (RootTabView overlay). When the RAG assistant bubble took the
// bottom-right slot, the two floating affordances would have collided, so
// the call action was folded INTO the assistant dialog's toolbar (see
// AssistantView). This enum stays because that toolbar — and any future
// contact card — dials from it.

import Foundation

/// The Verwaltung-Hotline contact. One source of truth — change the number
/// here and the tel: URL follows automatically.
enum WHVContact {
    /// Shown wherever we surface the call action.
    static let displayName = "Dirk Ullrich"
    /// Dialed when the user taps to call. Not shown.
    static let phoneNumber = "+49 15679 062409"
    /// tel:-scheme variant. Only digits + the leading `+` survive,
    /// per RFC 3966; iOS otherwise rejects the URL silently.
    static let telURL: URL = {
        let digits = phoneNumber.filter { "0123456789+".contains($0) }
        return URL(string: "tel:\(digits)")!
    }()
}
