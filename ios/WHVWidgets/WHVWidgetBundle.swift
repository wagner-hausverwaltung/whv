// Widget bundle entry point. Two members:
//   • ActivityWidget — the unified "Aktuelles" home/lock-screen widget
//     driven by GET /me/activity (App Group snapshot).
//   • ETVLiveActivity — the in-progress ETV Live Activity (unchanged).

import SwiftUI
import WidgetKit

@main
struct WHVWidgetBundle: WidgetBundle {
    var body: some Widget {
        ActivityWidget()
        ETVLiveActivity()
    }
}
