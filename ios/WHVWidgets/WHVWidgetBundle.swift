// Widget bundle entry point. Today: one widget (Upcoming ETV).
// Phase 4 brings in open-tickets + Mitteilungen + a Live Activity
// for an in-progress ETV — each becomes another @WidgetBundleBuilder
// member, no changes to the host app side.

import SwiftUI
import WidgetKit

@main
struct WHVWidgetBundle: WidgetBundle {
    var body: some Widget {
        UpcomingEtvWidget()
        if #available(iOS 17.0, *) {
            ETVLiveActivity()
        }
    }
}
