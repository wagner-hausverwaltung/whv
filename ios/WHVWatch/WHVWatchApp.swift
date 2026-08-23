//
//  WHVWatchApp.swift
//  WHVWatch
//
//  Companion app for the Verwalter's wrist: start/stop/arrive for the
//  Fahrtenbuch, a dictated ticket, and the live trip status. Everything is
//  relayed to the iPhone over WatchConnectivity (sendMessage wakes the iOS
//  app in the background), so the phone stays the single source of truth
//  and the watch never needs credentials.
//

import SwiftUI

@main
struct WHVWatchApp: App {
    @StateObject private var bridge = WatchBridge.shared

    var body: some Scene {
        WindowGroup {
            WatchHomeView()
                .environmentObject(bridge)
        }
    }
}
