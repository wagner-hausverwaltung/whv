// Host-app feeder for the unified activity widget.
//
// Fetches GET /me/activity (authed), writes an ActivitySnapshot into
// App Group UserDefaults, and asks WidgetKit to reload. The widget
// process reads the snapshot back — it never talks to the network or
// Keychain. This supersedes the older ETV-only WidgetSync.refresh
// feeder (the Live Activity path in LiveActivityManager is unaffected
// and stays as-is).
//
// Refresh trigger: ActivitySync.refresh runs after every successful
// AssemblyListStore.load — same call site as the old WidgetSync, so
// the widget stays fresh whenever the user opens the ETV surface.
// Sign-out clears the slot. The widget's own 30-min fallback timeline
// covers stretches where the user doesn't open the app.

import Foundation
import WidgetKit

enum ActivitySync {
    /// Fetch the feed and republish the widget snapshot. Best-effort:
    /// a failing fetch leaves the previous snapshot in place rather
    /// than blanking the widget. Demo mode is handled inside the
    /// APIClient (getMyActivity short-circuits to the canned seed).
    static func refresh(api: APIClient, limit: Int = 10) async {
        guard let items = try? await api.getMyActivity(limit: limit) else { return }
        let snapshot = ActivitySnapshot(updatedAt: Date(), items: items)
        ActivityStorage.write(snapshot)
        WidgetCenter.shared.reloadAllTimelines()
    }

    /// Sign-out path — wipe the slot so the next user doesn't briefly
    /// see the previous account's feed on their Home Screen.
    static func clear() {
        ActivityStorage.clear()
        WidgetCenter.shared.reloadAllTimelines()
    }
}
