// Shared "library shelf" backdrop for rows that represent a
// Liegenschaft. Drops the source image in at low opacity so the row
// content (name, address) stays readable in both light + dark mode.
//
// Phase 2 will swap the asset for the real per-property image_url
// fetched from /me/properties — same view, different image source.
// Until then a single library photo gives every Liegenschaft the
// same warm, identifiable feel.

import SwiftUI

struct PropertyBackground: View {
    /// 0…1 — light mode tolerates a bit more saturation than dark.
    /// Defaults tuned so body text reads cleanly on either.
    var opacity: Double = 0.22

    @Environment(\.colorScheme) private var colorScheme

    var body: some View {
        ZStack {
            // Base fill so rows still have a solid sense of surface
            // when the image is dim or hasn't loaded.
            Color(.systemBackground)
            Image("PropertyBackground")
                .resizable()
                .scaledToFill()
                // Slight blur softens the high-frequency book spines
                // so foreground text doesn't fight competing edges.
                .blur(radius: 1.5)
                .opacity(colorScheme == .dark ? opacity * 0.55 : opacity)
            // A soft top-down dim in dark mode keeps the image from
            // glowing brighter than the rest of the list.
            if colorScheme == .dark {
                LinearGradient(
                    colors: [
                        Color(.systemBackground).opacity(0.35),
                        Color(.systemBackground).opacity(0.15),
                    ],
                    startPoint: .top,
                    endPoint: .bottom
                )
            }
        }
        .clipped()
    }
}
