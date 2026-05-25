// Bridge between the live assembly fetch and the Lock/Home Screen
// widget. Whenever AssemblyListStore pulls a fresh list from
// /me/properties/{id}/assemblies, we write the *next upcoming*
// assembly (≤ 14 days out) to the shared App Group UserDefaults,
// then ask WidgetKit to reload all timelines so the visible widget
// catches up immediately.
//
// Writing nil clears the slot (e.g. when the only upcoming ETV is
// cancelled or rolls into ABGEHALTEN). The widget then renders its
// quiet "Keine Versammlung geplant" empty state.

import Foundation
import WidgetKit

/// Wire shape mirrored by the widget target. Kept here as the
/// canonical source so the host app fully owns the schema; the
/// widget redeclares an identical struct privately (App Group
/// UserDefaults is just a JSON blob, no type sharing required).
struct WidgetUpcomingEtvSnapshot: Codable {
    let assemblyId: String
    let title: String
    let propertyName: String?
    let scheduledStart: Date
    let scheduledEnd: Date
    let location: String
    let teamsMeetingUrl: String?
    let status: String
}

enum WidgetSync {
    static let appGroup = "group.com.wagner-hausverwaltung.WHV"
    static let nextEtvKey = "WHV.widget.nextEtv"
    /// "Upcoming" cutoff. Matches REQUIREMENTS §8.9 — anything
    /// further out isn't actionable enough for a glance widget.
    static let lookaheadDays: TimeInterval = 14

    /// Picks the next upcoming assembly across the given list and
    /// hands it to the widget. Idempotent: writing the same payload
    /// twice is harmless; widget reloads pick up no diff and don't
    /// re-render.
    static func updateNextEtv(from list: [AssemblySummary]) {
        let now = Date()
        let horizon = now.addingTimeInterval(lookaheadDays * 86_400)
        let next = list
            .filter { $0.status.isUpcoming }
            .filter { $0.scheduled_start > now && $0.scheduled_start <= horizon }
            .sorted { $0.scheduled_start < $1.scheduled_start }
            .first

        guard let defaults = UserDefaults(suiteName: appGroup) else { return }

        if let next {
            let snapshot = WidgetUpcomingEtvSnapshot(
                assemblyId: next.id,
                title: next.title,
                propertyName: next.property_name,
                scheduledStart: next.scheduled_start,
                scheduledEnd: next.scheduled_end,
                location: next.location,
                teamsMeetingUrl: next.teams_meeting_url,
                status: next.status.rawValue
            )
            let encoder = JSONEncoder()
            encoder.dateEncodingStrategy = .iso8601
            if let data = try? encoder.encode(snapshot) {
                defaults.set(data, forKey: nextEtvKey)
            }
        } else {
            defaults.removeObject(forKey: nextEtvKey)
        }

        // Same call after both write + clear so the widget process
        // re-renders into the empty state too.
        WidgetCenter.shared.reloadAllTimelines()
    }

    /// Sign-out path — wipe the slot so the next user doesn't briefly
    /// see the previous account's ETV on their Home Screen.
    static func clear() {
        guard let defaults = UserDefaults(suiteName: appGroup) else { return }
        defaults.removeObject(forKey: nextEtvKey)
        WidgetCenter.shared.reloadAllTimelines()
    }
}
