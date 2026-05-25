// Live Activity attributes for an upcoming Eigentümerversammlung.
//
// Static fields ("ETVActivityAttributes") never change for the
// lifetime of the activity — they're set when the host app calls
// Activity.request and remain fixed. Dynamic state ("ContentState")
// is what app intents and host-app updates mutate, e.g. the user
// tapping "Ich komme später" on the Live Activity flips
// `lateStatus` and the widget re-renders.
//
// Lives in ios/Shared/ rather than under either target's folder so
// both WHV (app) and WHVWidgets (extension) compile against the
// same type without cross-target import gymnastics. The xcodeproj
// installer script adds this file to both targets' Sources phases.

import ActivityKit
import Foundation

public struct ETVActivityAttributes: ActivityAttributes {
    public struct ContentState: Codable, Hashable {
        /// The user's RSVP self-report. Mutated by RunningLateIntent
        /// (the App Intent attached to the "Ich komme später" button
        /// in the Lock Screen / Dynamic Island view). Defaults to
        /// `.onTime` when the activity is created.
        public var lateStatus: LateStatus

        public init(lateStatus: LateStatus = .onTime) {
            self.lateStatus = lateStatus
        }
    }

    /// Reported attendance state. .runningLate flips the widget
    /// chip + tints the title amber so the user (and a passenger
    /// glancing at the device) can see at a glance.
    public enum LateStatus: String, Codable, Hashable {
        case onTime
        case runningLate
    }

    /// Backend assembly id — used as the deep-link payload so a tap
    /// on the Lock Screen card bounces the user straight to the
    /// detail view via `whv://assembly/{id}`.
    public let assemblyId: String
    public let title: String
    public let propertyName: String?
    public let location: String
    public let scheduledStart: Date
    public let scheduledEnd: Date
    public let teamsMeetingUrl: String?
    /// Up to 3 TOPs surfaced as a teaser on the Lock Screen card.
    /// Truncated host-side so the widget never has to deal with
    /// rendering long lists in a 4-line lock area.
    public let agendaPreview: [String]

    public init(
        assemblyId: String,
        title: String,
        propertyName: String?,
        location: String,
        scheduledStart: Date,
        scheduledEnd: Date,
        teamsMeetingUrl: String?,
        agendaPreview: [String]
    ) {
        self.assemblyId = assemblyId
        self.title = title
        self.propertyName = propertyName
        self.location = location
        self.scheduledStart = scheduledStart
        self.scheduledEnd = scheduledEnd
        self.teamsMeetingUrl = teamsMeetingUrl
        self.agendaPreview = agendaPreview
    }
}
