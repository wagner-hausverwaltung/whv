// App Intent backing the "Ich komme später" button on the Live
// Activity. Tapping the button while the activity is live flips
// the ContentState.lateStatus, which the widget re-renders
// instantly (chip turns amber + title gets a small "verspätet"
// hint). The host app sees the update next time it reads the
// activity (e.g. when foregrounding).

import ActivityKit
import AppIntents
import Foundation

struct RunningLateIntent: LiveActivityIntent {
    static var title: LocalizedStringResource = "Ich komme später"
    static var description: IntentDescription = IntentDescription(
        "Markiert die anstehende Eigentümerversammlung als verspätet."
    )

    @Parameter(title: "Activity ID")
    var activityID: String

    init() {}

    init(activityID: String) {
        self.activityID = activityID
    }

    func perform() async throws -> some IntentResult {
        guard let activity = Activity<ETVActivityAttributes>.activities
            .first(where: { $0.id == activityID })
        else {
            return .result()
        }
        var state = activity.content.state
        state.lateStatus = .runningLate
        await activity.update(
            ActivityContent(
                state: state,
                staleDate: activity.content.staleDate
            )
        )
        return .result()
    }
}
