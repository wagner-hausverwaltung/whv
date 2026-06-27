// Small "NEU" capsule flagging recently-arrived list items
// (Mitteilungen + Versammlungen). Deliberately blue — distinct from the
// red/orange "Zähler fällig" meter accent so the two signals never read
// as the same kind of alert.

import SwiftUI

/// Window (in days) inside which a list item counts as "new".
let neuBadgeWindowDays = 7

/// True when `date` is non-nil and falls within the last
/// `neuBadgeWindowDays` (and is not in the future).
func isRecentlyNew(_ date: Date?) -> Bool {
    guard let date else { return false }
    let cal = Calendar.current
    let now = Date()
    guard date <= now else { return false }
    guard let cutoff = cal.date(byAdding: .day, value: -neuBadgeWindowDays, to: now) else {
        return false
    }
    return date >= cutoff
}

/// Blue "NEU" capsule. English readers see "NEW" via the String Catalog
/// (the literal here is auto-extracted and translatable).
struct NeuBadge: View {
    var body: some View {
        Text("NEU")
            .font(.caption2.weight(.bold))
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(Color.blue)
            .foregroundStyle(.white)
            .clipShape(Capsule())
            .accessibilityLabel(Text("Neu"))
    }
}

#Preview {
    HStack {
        Text("Mitteilung")
        NeuBadge()
    }
    .padding()
}
