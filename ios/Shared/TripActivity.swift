//
//  TripActivity.swift
//  Shared (WHV app + WHVWidgets)
//
//  Live Activity for a running Dienstfahrt: "Fahrt läuft · 12,3 km · seit
//  10:12 · Ziel WEG X" in the Dynamic Island / on the Lock Screen, with an
//  "Beenden" button. The button is a LiveActivityIntent, which iOS runs in
//  the APP process — so it can reach TripTracker through a hook the app
//  installs at launch (the widget process leaves the hook nil).
//

import ActivityKit
import AppIntents
import Foundation

public struct TripActivityAttributes: ActivityAttributes {
    public struct ContentState: Codable, Hashable {
        public var distanceM: Int
        public var destinationName: String?
        public var purposeLabel: String?
        public var updatedAt: Date

        public init(distanceM: Int, destinationName: String?, purposeLabel: String?, updatedAt: Date) {
            self.distanceM = distanceM
            self.destinationName = destinationName
            self.purposeLabel = purposeLabel
            self.updatedAt = updatedAt
        }
    }

    public let startedAt: Date
    public let source: String

    public init(startedAt: Date, source: String) {
        self.startedAt = startedAt
        self.source = source
    }
}

/// App-side hooks for intents that run in the app process. The app sets
/// `endTrip` at launch; the widget extension never does (nil → no-op).
public enum TripIntentHooks {
    @MainActor public static var endTrip: (() -> Void)?
}

/// "Beenden" on the Live Activity: ends the running trip in the app.
public struct EndTripIntent: LiveActivityIntent {
    public static var title: LocalizedStringResource = "Fahrt beenden"
    public static var openAppWhenRun = false

    public init() {}

    @MainActor
    public func perform() async throws -> some IntentResult {
        TripIntentHooks.endTrip?()
        return .result()
    }
}
