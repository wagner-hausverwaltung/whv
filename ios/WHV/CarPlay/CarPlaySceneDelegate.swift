//
//  CarPlaySceneDelegate.swift
//  WHV
//
//  Driving-Task CarPlay scene (ADR-0020). Templates only — Grid, List,
//  Information, Alert — and the Fahrt is the centre of it: connecting the
//  car starts a trip (if the driver opted in), disconnecting ends it, and the
//  other three tiles are framed as parts of the drive (pick a destination,
//  call someone at the destination, see what's next today). That framing is
//  what the CarPlay Addendum §3.10 demands of Driving-Task apps.
//
//  Until Apple grants the entitlement this runs only in the Simulator (the
//  Debug entitlements carry the key); see infra/docs/carplay-entitlement-request.md.
//

import CarPlay
import MapKit
import UIKit

@MainActor
final class CarPlaySceneDelegate: UIResponder, CPTemplateApplicationSceneDelegate {
    private var interface: CPInterfaceController?
    private var scene: CPTemplateApplicationScene?
    private let api = APIClient()
    private var startedTripOnConnect = false

    // MARK: Connect / disconnect = trip boundaries

    func templateApplicationScene(
        _ templateApplicationScene: CPTemplateApplicationScene,
        didConnect interfaceController: CPInterfaceController
    ) {
        interface = interfaceController
        scene = templateApplicationScene
        Task { await present() }
        let tracker = TripTracker.shared
        if tracker.autoDetectEnabled, !tracker.isRunning {
            tracker.startFromCarPlay()
            startedTripOnConnect = true
        }
    }

    func templateApplicationScene(
        _ templateApplicationScene: CPTemplateApplicationScene,
        didDisconnectInterfaceController interfaceController: CPInterfaceController
    ) {
        if startedTripOnConnect, TripTracker.shared.isRunning {
            TripTracker.shared.stopFromCarPlay()
        }
        startedTripOnConnect = false
        interface = nil
        scene = nil
    }

    // MARK: Root

    private func present() async {
        guard let interface else { return }
        // Verwalter only — owners never see a CarPlay UI.
        if let me = try? await api.getMe(), me.role.lowercased() != "verwalter" {
            let info = CPInformationTemplate(
                title: "WHV",
                layout: .leading,
                items: [CPInformationItem(title: "Nur für Verwalter", detail: "Die CarPlay-Ansicht ist für die Verwalterrolle gedacht.")],
                actions: []
            )
            interface.setRootTemplate(info, animated: false, completion: nil)
            return
        }
        interface.setRootTemplate(rootGrid(), animated: false, completion: nil)
    }

    private func rootGrid() -> CPGridTemplate {
        let tracker = TripTracker.shared
        let fahrt = CPGridButton(
            titleVariants: [tracker.isRunning ? "Fahrt beenden" : "Fahrt starten"],
            image: UIImage(systemName: tracker.isRunning ? "stop.circle.fill" : "car.fill") ?? UIImage()
        ) { [weak self] _ in
            Task { @MainActor in await self?.toggleTrip() }
        }
        let ziel = CPGridButton(
            titleVariants: ["Ziel wählen"],
            image: UIImage(systemName: "map.fill") ?? UIImage()
        ) { [weak self] _ in
            Task { @MainActor in await self?.showDestinations() }
        }
        let heute = CPGridButton(
            titleVariants: ["Heute"],
            image: UIImage(systemName: "list.bullet.clipboard.fill") ?? UIImage()
        ) { [weak self] _ in
            Task { @MainActor in await self?.showToday() }
        }
        let kontakte = CPGridButton(
            titleVariants: ["Am Ziel anrufen"],
            image: UIImage(systemName: "phone.fill") ?? UIImage()
        ) { [weak self] _ in
            Task { @MainActor in await self?.showContactProperties() }
        }
        let grid = CPGridTemplate(title: "WHV", gridButtons: [fahrt, ziel, heute, kontakte])
        return grid
    }

    private func refreshRoot() {
        guard let interface else { return }
        // Rebuild the grid so the Fahrt button reflects the tracker state.
        interface.setRootTemplate(rootGrid(), animated: false, completion: nil)
    }

    // MARK: Fahrt

    private func toggleTrip() async {
        let tracker = TripTracker.shared
        if tracker.isRunning {
            tracker.stopFromCarPlay()
            alert("Fahrt beendet", "Zweck und Objekt bestätigen Sie später in der App.")
        } else {
            tracker.startFromCarPlay()
            alert("Fahrt läuft", "Die Strecke wird aufgezeichnet.")
        }
        refreshRoot()
    }

    private func alert(_ title: String, _ detail: String) {
        guard let interface else { return }
        let ok = CPAlertAction(title: "OK", style: .default) { [weak self] _ in
            self?.interface?.dismissTemplate(animated: true, completion: nil)
        }
        let a = CPAlertTemplate(titleVariants: [title, detail], actions: [ok])
        interface.presentTemplate(a, animated: true, completion: nil)
    }

    // MARK: Ziel wählen — properties by visit frequency → Apple Maps

    private func showDestinations() async {
        guard let interface else { return }
        let props = (try? await api.getMyProperties()) ?? []
        let trips = (try? await api.getMyTrips()) ?? []
        var freq: [String: Int] = [:]
        for t in trips { if let p = t.property_id { freq[p, default: 0] += 1 } }
        let sorted = props.sorted { (freq[$0.id] ?? 0, $1.name) > (freq[$1.id] ?? 0, $0.name) }

        let items: [CPListItem] = sorted.map { p in
            let item = CPListItem(text: p.name, detailText: Self.address(p))
            item.accessoryType = .disclosureIndicator
            item.handler = { [weak self] _, completion in
                self?.navigate(to: p)
                completion()
            }
            return item
        }
        let section = CPListSection(items: items)
        let list = CPListTemplate(title: "Ziel wählen", sections: [section])
        interface.pushTemplate(list, animated: true, completion: nil)
    }

    private func navigate(to p: PropertyResponse) {
        guard let lat = p.lat, let lng = p.lng else {
            alert("Keine Koordinaten", "Für dieses Objekt fehlt die Geoposition.")
            return
        }
        let placemark = MKPlacemark(coordinate: CLLocationCoordinate2D(latitude: lat, longitude: lng))
        let item = MKMapItem(placemark: placemark)
        item.name = p.name
        // Hands off to Apple Maps, which takes over the CarPlay display.
        item.openInMaps(launchOptions: [MKLaunchOptionsDirectionsModeKey: MKLaunchOptionsDirectionsModeDriving])
    }

    private static func address(_ p: PropertyResponse) -> String {
        let street = [p.street, p.number].compactMap { $0 }.joined(separator: " ")
        let city = [p.postal_code, p.city].compactMap { $0 }.joined(separator: " ")
        return [street, city].filter { !$0.isEmpty }.joined(separator: ", ")
    }

    // MARK: Heute — read-only list of what's next

    private func showToday() async {
        guard let interface else { return }
        let feed = (try? await api.getMyActivity(limit: 12)) ?? []
        let items: [CPListItem] = feed.map { a in
            let item = CPListItem(text: a.title, detailText: a.subtitle)
            // Deliberately no handler: details stay on the phone (Addendum §3.10).
            return item
        }
        let list = CPListTemplate(
            title: "Heute",
            sections: [CPListSection(items: items.isEmpty ? [CPListItem(text: "Nichts Offenes", detailText: nil)] : items)]
        )
        interface.pushTemplate(list, animated: true, completion: nil)
    }

    // MARK: Am Ziel anrufen — property → Dienstleister with phone

    private func showContactProperties() async {
        guard let interface else { return }
        let props = (try? await api.getMyProperties()) ?? []
        let items: [CPListItem] = props.sorted { $0.name < $1.name }.map { p in
            let item = CPListItem(text: p.name, detailText: nil)
            item.accessoryType = .disclosureIndicator
            item.handler = { [weak self] _, completion in
                Task { @MainActor in
                    await self?.showContacts(for: p)
                    completion()
                }
            }
            return item
        }
        let list = CPListTemplate(title: "Am Ziel anrufen", sections: [CPListSection(items: items)])
        interface.pushTemplate(list, animated: true, completion: nil)
    }

    private func showContacts(for p: PropertyResponse) async {
        guard let interface else { return }
        let vendors = (try? await api.getMyPropertyVendors(propertyId: p.id)) ?? []
        var items: [CPListItem] = []
        for v in vendors {
            guard let phone = v.phone, !phone.isEmpty else { continue }
            let item = CPListItem(text: v.name, detailText: phone)
            item.accessoryType = .disclosureIndicator
            item.handler = { [weak self] _, completion in
                self?.call(phone)
                completion()
            }
            items.append(item)
        }
        if items.isEmpty {
            items = [CPListItem(text: "Keine Telefonnummern hinterlegt", detailText: nil)]
        }
        let list = CPListTemplate(title: p.name, sections: [CPListSection(items: items)])
        interface.pushTemplate(list, animated: true, completion: nil)
    }

    private func call(_ phone: String) {
        let digits = phone.filter { "+0123456789".contains($0) }
        guard let url = URL(string: "tel://\(digits)"), let scene else { return }
        scene.open(url, options: nil, completionHandler: nil)
    }
}
