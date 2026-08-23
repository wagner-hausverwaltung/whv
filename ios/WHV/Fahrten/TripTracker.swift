//
//  TripTracker.swift
//  WHV
//
//  Records Dienstfahrten for the Verwalter's Fahrtenbuch (ADR-0020).
//
//  Two ways a trip starts: the driver taps "Fahrt starten", or — when the
//  driver has opted in — the phone notices it is in a moving car (Core
//  Motion `automotive`) and starts on its own. Either way the phone collects
//  GPS points while driving, stops after a few minutes of standstill, and
//  uploads ONE finished trip. The driver then confirms purpose + property
//  from a suggestion (nearest property to where the trip ended).
//
//  Privacy: nothing is recorded until the driver enables it in Einstellungen;
//  the route polyline is optional; only Verwalter see any of this.
//

import Combine
import CoreLocation
import CoreMotion
import Foundation
import UIKit

@MainActor
final class TripTracker: NSObject, ObservableObject {
    static let shared = TripTracker()

    // MARK: Published state

    @Published private(set) var isRunning = false
    @Published private(set) var startedAt: Date?
    @Published private(set) var liveDistanceM: Int = 0
    @Published private(set) var source: String = "MANUAL"
    @Published private(set) var openTrips: [TripResponse] = []
    @Published private(set) var authorization: CLAuthorizationStatus = .notDetermined
    @Published private(set) var lastError: String?
    @Published private(set) var pendingUploads: Int = 0
    /// Preset for the running trip when it was started FOR a destination
    /// ("Besichtigung hier starten" from CarPlay): uploaded with the trip so
    /// no confirmation is needed afterwards. Cleared when the trip ends.
    @Published private(set) var presetPurpose: String?
    @Published private(set) var presetPropertyId: String?
    @Published private(set) var presetNote: String?
    /// Besichtigung of a prospect: the anfragen@ inquiry this drive is for.
    @Published private(set) var presetInquiryId: String?

    /// Opt-in for automatic drive detection (Core Motion + significant
    /// location changes). Off by default — this is the consent switch.
    @Published var autoDetectEnabled: Bool {
        didSet {
            defaults.set(autoDetectEnabled, forKey: Keys.autoDetect)
            autoDetectEnabled ? enableAutoDetection() : disableAutoDetection()
        }
    }
    /// Keep the driven route (polyline) with the trip. Off = start/end only.
    @Published var storeRoute: Bool {
        didSet { defaults.set(storeRoute, forKey: Keys.storeRoute) }
    }

    // MARK: Private

    private let api = APIClient()
    private let defaults = UserDefaults.standard
    private let location = CLLocationManager()
    private let motion = CMMotionActivityManager()
    private var coords: [CLLocationCoordinate2D] = []
    private var lastLocation: CLLocation?
    private var lastMovementAt: Date?
    private var stillnessTimer: Timer?

    private enum Keys {
        static let autoDetect = "trips.autoDetect"
        static let storeRoute = "trips.storeRoute"
        static let running = "trips.running"
        static let pending = "trips.pendingUploads"
    }

    /// Standstill after which a running trip is closed automatically.
    private let stillnessLimit: TimeInterval = 4 * 60
    /// Minimum for a detected drive to count — filters parking-lot shuffles.
    private let minimumTripMeters = 300

    private override init() {
        autoDetectEnabled = defaults.bool(forKey: Keys.autoDetect)
        storeRoute = defaults.object(forKey: Keys.storeRoute) as? Bool ?? true
        super.init()
        location.delegate = self
        location.pausesLocationUpdatesAutomatically = false
        location.activityType = .automotiveNavigation
        authorization = location.authorizationStatus
    }

    // MARK: Lifecycle

    /// Call once at app start (also on a background relaunch triggered by a
    /// significant location change): restores a trip that was running when
    /// the app was killed, re-arms detection, and retries failed uploads.
    func bootstrap() {
        restoreRunningIfAny()
        if autoDetectEnabled { enableAutoDetection() }
        Task { await flushPending(); await refreshOpen() }
    }

    var isAvailable: Bool { !DemoFlag.isActive }

    /// Last known position — while tracking it updates continuously; when
    /// idle `refreshLocation()` asks for a single fix. Used for the "Ich
    /// verspäte mich" Maps link and for ranking CarPlay lists by proximity.
    var currentCoordinate: CLLocationCoordinate2D? { lastLocation?.coordinate }

    /// One-shot fix when no trip is running (CarPlay connect, contact list).
    func refreshLocation() {
        guard isAvailable, !isRunning else { return }
        switch location.authorizationStatus {
        case .authorizedAlways, .authorizedWhenInUse:
            location.requestLocation()
        case .notDetermined:
            location.requestWhenInUseAuthorization()
        default:
            break
        }
    }

    // MARK: Manual control

    func startManually() {
        guard !isRunning else { return }
        requestAuthorization()
        begin(source: "MANUAL")
    }

    func stopManually() {
        guard isRunning else { return }
        finish()
    }

    // MARK: CarPlay hooks

    /// Start a trip that is already known to be, e.g., a Besichtigung at a
    /// given property — or at a prospect (`inquiryId`) that has no property
    /// yet. The trip uploads CONFIRMED with these values.
    func startWithPreset(
        purpose: String, propertyId: String?, source: String, note: String? = nil,
        inquiryId: String? = nil
    ) {
        guard !isRunning else { return }
        presetPurpose = purpose
        presetPropertyId = propertyId
        presetNote = note
        presetInquiryId = inquiryId
        requestAuthorization()
        begin(source: source)
    }


    /// Confirm purpose/object for the RUNNING trip (CarPlay "Fahrt beenden"
    /// asks before stopping) so the upload goes out CONFIRMED. Persisted with
    /// the running snapshot so an app kill between choice and upload keeps it.
    func applyPreset(purpose: String?, propertyId: String?) {
        guard isRunning else { return }
        presetPurpose = purpose
        presetPropertyId = propertyId
        persistRunning()
    }

    /// Connecting the car = the drive begins. Source CARPLAY so the log shows
    /// how the trip was captured.
    func startFromCarPlay() {
        guard !isRunning else { return }
        begin(source: "CARPLAY")
    }

    func stopFromCarPlay() {
        guard isRunning else { return }
        finish()
    }

    // MARK: Permissions

    func requestAuthorization() {
        switch location.authorizationStatus {
        case .notDetermined:
            location.requestWhenInUseAuthorization()
        case .authorizedWhenInUse:
            // Background continuation needs Always; iOS shows the prompt at
            // most once, afterwards the user must flip it in Settings.
            location.requestAlwaysAuthorization()
        default:
            break
        }
    }

    var needsAlwaysForAutoDetect: Bool {
        autoDetectEnabled && authorization != .authorizedAlways
    }

    // MARK: Automatic detection

    private func enableAutoDetection() {
        guard isAvailable else { return }
        requestAuthorization()
        // Wakes the app (even from terminated) on ~500 m moves; cheap on battery.
        location.startMonitoringSignificantLocationChanges()
        guard CMMotionActivityManager.isActivityAvailable() else { return }
        motion.startActivityUpdates(to: .main) { [weak self] activity in
            guard let self, let a = activity else { return }
            Task { @MainActor in self.handle(activity: a) }
        }
    }

    private func disableAutoDetection() {
        location.stopMonitoringSignificantLocationChanges()
        motion.stopActivityUpdates()
    }

    private func handle(activity a: CMMotionActivity) {
        if a.automotive, a.confidence != .low {
            lastMovementAt = Date()
            if !isRunning { begin(source: "AUTO") }
        } else if isRunning, a.stationary, a.confidence == .high {
            // Standstill — the timer decides whether it's a red light or the end.
            armStillnessTimer()
        }
    }

    // MARK: Trip state machine

    private func begin(source: String) {
        isRunning = true
        self.source = source
        startedAt = Date()
        coords = []
        liveDistanceM = 0
        lastLocation = nil
        lastMovementAt = Date()
        lastError = nil
        location.desiredAccuracy = kCLLocationAccuracyNearestTenMeters
        location.distanceFilter = 25
        if location.authorizationStatus == .authorizedAlways {
            location.allowsBackgroundLocationUpdates = true
        }
        location.startUpdatingLocation()
        persistRunning()
    }

    /// Ends the running trip SYNCHRONOUSLY — state flips before this returns,
    /// so a caller that re-renders right away (CarPlay root grid) sees the
    /// stopped state. Only the upload runs detached.
    private func finish() {
        guard isRunning, let started = startedAt else { return }
        location.stopUpdatingLocation()
        location.allowsBackgroundLocationUpdates = false
        stillnessTimer?.invalidate()
        stillnessTimer = nil
        let ended = lastMovementAt ?? Date()
        let distance = liveDistanceM
        let route = storeRoute ? coords : []
        let src = source
        let purpose = presetPurpose
        let propertyId = presetPropertyId
        let note = presetNote
        let inquiryId = presetInquiryId
        presetPurpose = nil
        presetPropertyId = nil
        presetNote = nil
        presetInquiryId = nil
        isRunning = false
        startedAt = nil
        liveDistanceM = 0
        clearRunning()

        // Auto-detected shuffles below the threshold are dropped silently;
        // a manual trip is always kept (the driver meant it).
        if src == "AUTO", distance < minimumTripMeters { return }

        let body = TripCompleteBody(
            started_at: started,
            ended_at: max(ended, started.addingTimeInterval(60)),
            start_lat: route.first?.latitude ?? coords.first?.latitude,
            start_lng: route.first?.longitude ?? coords.first?.longitude,
            end_lat: coords.last?.latitude,
            end_lng: coords.last?.longitude,
            distance_m: distance,
            route_polyline: route.isEmpty ? nil : Polyline.encode(route),
            source: src,
            purpose: purpose,
            property_id: propertyId,
            note: note,
            inquiry_id: inquiryId
        )
        Task { @MainActor in
            await self.upload(body)
            await self.refreshOpen()
        }
    }

    private func armStillnessTimer() {
        guard stillnessTimer == nil else { return }
        stillnessTimer = Timer.scheduledTimer(withTimeInterval: stillnessLimit, repeats: false) {
            [weak self] _ in
            Task { @MainActor in
                guard let self, self.isRunning else { return }
                if let last = self.lastMovementAt, Date().timeIntervalSince(last) >= self.stillnessLimit {
                    self.finish()
                } else {
                    self.stillnessTimer = nil
                }
            }
        }
    }

    // MARK: Upload + pending queue

    private func upload(_ body: TripCompleteBody) async {
        do {
            _ = try await api.completeTrip(body)
        } catch {
            // Offline or server hiccup: keep it, retry on next bootstrap/stop.
            var queue = loadPending()
            queue.append(body)
            savePending(queue)
            lastError = "Fahrt gespeichert, Upload folgt bei Verbindung."
        }
    }

    func flushPending() async {
        var queue = loadPending()
        guard !queue.isEmpty else { return }
        var remaining: [TripCompleteBody] = []
        for body in queue {
            do { _ = try await api.completeTrip(body) } catch { remaining.append(body) }
        }
        queue = remaining
        savePending(queue)
    }

    private func loadPending() -> [TripCompleteBody] {
        guard let data = defaults.data(forKey: Keys.pending),
              let list = try? JSONDecoder.iso.decode([TripCompleteBody].self, from: data)
        else { return [] }
        return list
    }

    private func savePending(_ list: [TripCompleteBody]) {
        defaults.set(try? JSONEncoder.iso.encode(list), forKey: Keys.pending)
        pendingUploads = list.count
    }

    // MARK: Open trips (need purpose/property)

    func refreshOpen() async {
        guard isAvailable else { return }
        do {
            openTrips = try await api.getMyTrips(status: "OPEN")
        } catch {
            // Not worth surfacing — the badge just stays stale.
        }
    }

    // MARK: Running-state persistence (survives app kill)

    private struct RunningSnapshot: Codable {
        var startedAt: Date
        var source: String
        var distanceM: Int
        var coords: [[Double]]
        // Presets survive an app kill too (optional: older snapshots lack them).
        var presetPurpose: String? = nil
        var presetPropertyId: String? = nil
        var presetNote: String? = nil
        var presetInquiryId: String? = nil
    }

    private func persistRunning() {
        guard let started = startedAt else { return }
        let snap = RunningSnapshot(
            startedAt: started,
            source: source,
            distanceM: liveDistanceM,
            coords: coords.map { [$0.latitude, $0.longitude] },
            presetPurpose: presetPurpose,
            presetPropertyId: presetPropertyId,
            presetNote: presetNote,
            presetInquiryId: presetInquiryId
        )
        defaults.set(try? JSONEncoder.iso.encode(snap), forKey: Keys.running)
    }

    private func clearRunning() {
        defaults.removeObject(forKey: Keys.running)
    }

    private func restoreRunningIfAny() {
        guard let data = defaults.data(forKey: Keys.running),
              let snap = try? JSONDecoder.iso.decode(RunningSnapshot.self, from: data)
        else { return }
        // Older than 6 h = the app died mid-trip long ago; close it as-is.
        if Date().timeIntervalSince(snap.startedAt) > 6 * 3600 {
            clearRunning()
            return
        }
        isRunning = true
        startedAt = snap.startedAt
        source = snap.source
        liveDistanceM = snap.distanceM
        presetPurpose = snap.presetPurpose
        presetPropertyId = snap.presetPropertyId
        presetNote = snap.presetNote
        presetInquiryId = snap.presetInquiryId
        coords = snap.coords.compactMap { $0.count == 2 ? CLLocationCoordinate2D(latitude: $0[0], longitude: $0[1]) : nil }
        lastMovementAt = Date()
        location.desiredAccuracy = kCLLocationAccuracyNearestTenMeters
        location.distanceFilter = 25
        if location.authorizationStatus == .authorizedAlways {
            location.allowsBackgroundLocationUpdates = true
        }
        location.startUpdatingLocation()
    }
}

// MARK: - CLLocationManagerDelegate

extension TripTracker: CLLocationManagerDelegate {
    nonisolated func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        let status = manager.authorizationStatus
        Task { @MainActor in
            self.authorization = status
            if status == .authorizedAlways, self.isRunning {
                self.location.allowsBackgroundLocationUpdates = true
            }
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        Task { @MainActor in
            for loc in locations where loc.horizontalAccuracy >= 0 && loc.horizontalAccuracy <= 65 {
                guard self.isRunning else {
                    // Idle: keep the latest fix (proximity ranking, delay
                    // notice) but accumulate nothing — motion decides if a
                    // drive starts.
                    self.lastLocation = loc
                    continue
                }
                if let prev = self.lastLocation {
                    let d = loc.distance(from: prev)
                    if d >= 10 {
                        self.liveDistanceM += Int(d.rounded())
                        self.lastMovementAt = loc.timestamp
                        self.stillnessTimer?.invalidate()
                        self.stillnessTimer = nil
                    }
                } else {
                    self.lastMovementAt = loc.timestamp
                }
                self.lastLocation = loc
                self.coords.append(loc.coordinate)
                if self.coords.count % 10 == 0 { self.persistRunning() }
            }
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        Task { @MainActor in self.lastError = error.localizedDescription }
    }
}

// MARK: - ISO coders for local persistence

extension JSONEncoder {
    static let iso: JSONEncoder = {
        let e = JSONEncoder()
        e.dateEncodingStrategy = .iso8601
        return e
    }()
}

extension JSONDecoder {
    static let iso: JSONDecoder = {
        let d = JSONDecoder()
        d.dateDecodingStrategy = .iso8601
        return d
    }()
}
