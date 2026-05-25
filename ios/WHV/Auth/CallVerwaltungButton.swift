// Floating "Verwaltung anrufen" button — sits in the bottom-right
// across all tabs of RootTabView. Tap fires the system Phone app
// via the `tel:` URL scheme so the user can ring the
// Verwalter-Hotline without leaving the app, dialing manually, or
// hunting for a contact card.
//
// Mounted as an overlay on the tab shell, so the button stays
// pinned no matter which tab the user swipes to and no matter how
// deep into a NavigationStack they've drilled. We add bottom
// padding equal to a normal tab-bar height + safe area so the
// button floats just above the bar — never under it.

import SwiftUI

/// The Verwaltung-Hotline contact. One source of truth — change
/// the number here and the tel: URL follows automatically.
enum WHVContact {
    /// Shown on the floating button.
    static let displayName = "Dirk Ullrich"
    /// Dialed when the user taps the button. Not shown.
    static let phoneNumber = "+49 15679 062409"
    /// tel:-scheme variant. Only digits + the leading `+` survive,
    /// per RFC 3966; iOS otherwise rejects the URL silently.
    static let telURL: URL = {
        let digits = phoneNumber.filter { "0123456789+".contains($0) }
        return URL(string: "tel:\(digits)")!
    }()
}

struct CallVerwaltungButton: View {
    var body: some View {
        Link(destination: WHVContact.telURL) {
            HStack(spacing: 8) {
                Image(systemName: "phone.fill")
                    .font(.subheadline.weight(.bold))
                Text(WHVContact.displayName)
                    .font(.subheadline.weight(.semibold))
                    .lineLimit(1)
            }
            .foregroundStyle(.white)
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
            .background(
                Capsule()
                    .fill(Color.blue)
                    .shadow(color: .black.opacity(0.18), radius: 6, y: 3)
            )
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Dirk Ullrich anrufen")
        .accessibilityHint("Öffnet die Telefon-App mit der Nummer der Wagner Hausverwaltung")
    }
}

#Preview {
    ZStack(alignment: .bottomTrailing) {
        Color(.systemGroupedBackground).ignoresSafeArea()
        CallVerwaltungButton()
            .padding(.trailing, 16)
            .padding(.bottom, 80)
    }
}
