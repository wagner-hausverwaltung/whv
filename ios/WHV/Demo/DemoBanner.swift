// Persistent yellow strip shown across every tab while demo mode
// is active. Tapping "Beenden" deactivates the demo + signs the
// fake user out, sending the App back to LoginView.

import SwiftUI

struct DemoBanner: View {
    let onExit: () -> Void

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "sparkles")
                .font(.subheadline.weight(.semibold))
            Text("Demo-Modus — keine echten Daten")
                .font(.caption.weight(.semibold))
                .lineLimit(1)
            Spacer(minLength: 8)
            Button("Beenden", role: .destructive, action: onExit)
                .font(.caption.weight(.semibold))
                .buttonStyle(.bordered)
                .controlSize(.mini)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
        .background(Color.yellow.opacity(0.92))
        .foregroundStyle(.black)
        .accessibilityElement(children: .combine)
    }
}
