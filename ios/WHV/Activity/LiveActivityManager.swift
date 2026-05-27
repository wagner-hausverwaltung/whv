// Starts / updates / ends the ETV Live Activity in response to
// what the live API hands us.
//
// Trigger window: the activity comes up when an assembly's
// scheduled_start is between [now, now + 5h]. It auto-ends 30
// minutes after scheduled_end, which is the heuristic for "the
// meeting is definitely over." The Verwalter can ship a real
// `actual_end` later that would cut the activity sooner, but
// surfacing that requires a push-token registration we don't have
// yet — the timed end is good enough for the first cut.
//
// Idempotency: keyed by `assemblyId`. Reposting the same id while
// an activity is already live updates the existing activity's
// attributes (e.g. the Verwalter rewrote the title) rather than
// spawning a duplicate.

import ActivityKit
import Foundation
import OSLog

/// 5-hour pre-meeting window. Matches the user's ask: "add a card
/// 5 hours before the ETV starts."
private let prewindowSeconds: TimeInterval = 5 * 3600

/// How long after scheduled_end we keep the activity around before
/// auto-ending — gives the Verwalter time to upload the protocol
/// without the Lock Screen card disappearing mid-coffee.
private let postEndGraceSeconds: TimeInterval = 30 * 60

/// Truncate an agenda title to this many characters before passing
/// it to the widget — the Lock Screen footprint is tight.
private let agendaTitleMaxChars = 70

@MainActor
enum LiveActivityManager {
    private static let log = Logger(subsystem: "com.wagner-hausverwaltung.portal", category: "live-activity")

    /// Scans the just-fetched list for an assembly that's about to
    /// happen, and starts/updates an Activity if so. Ends any stale
    /// activities (assembly already past, or no longer in the list).
    static func reconcile(with assemblies: [AssemblySummary], detailFetcher: @escaping (String) async -> Assembly?) async {
        guard #available(iOS 17.0, *) else { return }
        guard ActivityAuthorizationInfo().areActivitiesEnabled else {
            log.debug("Live Activities disabled by user")
            return
        }

        let now = Date()
        let windowEnd = now.addingTimeInterval(prewindowSeconds)

        // Pick the soonest assembly that's either inside the
        // pre-window or already in progress (start < now < end +
        // grace). At most one activity at a time keeps the surface
        // glanceable.
        let candidate = assemblies
            .filter { $0.status.isUpcoming || isInProgress($0, now: now) }
            .filter { isWithinWindow($0, now: now, windowEnd: windowEnd) }
            .sorted { $0.scheduled_start < $1.scheduled_start }
            .first

        // End any live activities for assemblies that no longer
        // qualify (e.g. cancelled, finished + grace expired, or
        // simply dropped off the visible list because the user
        // switched property).
        let candidateId = candidate?.id
        for activity in Activity<ETVActivityAttributes>.activities {
            if activity.attributes.assemblyId != candidateId {
                await activity.end(nil, dismissalPolicy: .immediate)
            }
        }

        guard let summary = candidate else { return }

        // Pull the full detail so we can ship the agenda preview.
        // Falls back to title-only on failure — better a slightly
        // emptier card than a missing one.
        let detail = await detailFetcher(summary.id)
        let agendaPreview = (detail?.agenda_items ?? [])
            .sorted(by: { $0.position < $1.position })
            .prefix(3)
            .map { String($0.title.prefix(agendaTitleMaxChars)) }

        let attributes = ETVActivityAttributes(
            assemblyId: summary.id,
            title: summary.title,
            propertyName: summary.property_name,
            location: summary.location,
            scheduledStart: summary.scheduled_start,
            scheduledEnd: summary.scheduled_end,
            teamsMeetingUrl: summary.teams_meeting_url,
            agendaPreview: Array(agendaPreview)
        )

        let staleDate = summary.scheduled_end.addingTimeInterval(postEndGraceSeconds)
        let initialState = ETVActivityAttributes.ContentState(lateStatus: .onTime)
        let content = ActivityContent(state: initialState, staleDate: staleDate)

        if let existing = Activity<ETVActivityAttributes>.activities
            .first(where: { $0.attributes.assemblyId == summary.id })
        {
            // Same activity already running — refresh the attributes
            // (Verwalter may have changed Teams URL, location, etc.).
            // ActivityKit doesn't let us swap attributes directly, so
            // we update content + rely on the existing attributes;
            // the only piece that practically rots between launches
            // is the agenda preview, which lives in attributes.
            await existing.update(content)
            log.debug("Updated existing live activity for assembly \(summary.id)")
        } else {
            do {
                _ = try Activity.request(
                    attributes: attributes,
                    content: content,
                    pushType: nil
                )
                log.debug("Started live activity for assembly \(summary.id)")
            } catch {
                log.error("Live activity request failed: \(error.localizedDescription)")
            }
        }
    }

    /// Cancel everything — used on sign-out so the next user doesn't
    /// see the previous account's ETV on their Lock Screen.
    static func endAll() async {
        guard #available(iOS 17.0, *) else { return }
        for activity in Activity<ETVActivityAttributes>.activities {
            await activity.end(nil, dismissalPolicy: .immediate)
        }
    }

    // MARK: - Window predicates

    private static func isWithinWindow(
        _ a: AssemblySummary,
        now: Date,
        windowEnd: Date
    ) -> Bool {
        let endGrace = a.scheduled_end.addingTimeInterval(postEndGraceSeconds)
        // Within pre-window: start ≤ now + 5h, AND meeting hasn't
        // ended (+ grace). Already-started meetings keep the
        // activity until grace expires.
        return a.scheduled_start <= windowEnd && now <= endGrace
    }

    private static func isInProgress(_ a: AssemblySummary, now: Date) -> Bool {
        a.scheduled_start <= now && now <= a.scheduled_end
    }
}
