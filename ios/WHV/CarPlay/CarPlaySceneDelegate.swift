//
//  CarPlaySceneDelegate.swift
//  WHV
//
//  Driving-Task CarPlay scene (ADR-0020). Templates only — Grid, List,
//  Information, Alert — and the Fahrt is the centre of it: connecting the
//  car starts a trip (if the driver opted in), disconnecting ends it, and
//  everything else is framed as part of the drive: pick a destination, start
//  a Besichtigung there, call someone at the destination, tell them you're
//  late, see what's open there. That framing is what the CarPlay Addendum
//  §3.10 demands of Driving-Task apps.
//
//  Until Apple grants the entitlement this runs only in the Simulator (the
//  Simulator-SDK entitlements carry the key); see
//  infra/docs/carplay-entitlement-request.md.
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
        // Gate explicitly on the THREE outcomes. Swallowing a failed /me and
        // showing the grid anyway produced an empty-looking app for a driver
        // who simply wasn't signed in.
        let me: UserResponse
        do {
            me = try await api.getMe()
        } catch {
            let info = CPInformationTemplate(
                title: "WHV",
                layout: .leading,
                items: [CPInformationItem(title: "Bitte in der WHV-App anmelden", detail: "Die CarPlay-Ansicht braucht eine aktive Anmeldung auf dem iPhone.")],
                actions: []
            )
            interface.setRootTemplate(info, animated: false, completion: nil)
            return
        }
        if me.role.lowercased() != "verwalter" {
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
            titleVariants: ["Objekte"],
            image: UIImage(systemName: "building.2.fill") ?? UIImage()
        ) { [weak self] _ in
            Task { @MainActor in await self?.showProperties() }
        }
        let heute = CPGridButton(
            titleVariants: ["Heute"],
            image: UIImage(systemName: "list.bullet.clipboard.fill") ?? UIImage()
        ) { [weak self] _ in
            Task { @MainActor in await self?.showToday() }
        }
        let kontakte = CPGridButton(
            titleVariants: ["Kontakte"],
            image: UIImage(systemName: "phone.fill") ?? UIImage()
        ) { [weak self] _ in
            Task { @MainActor in await self?.showProperties(forContacts: true) }
        }
        return CPGridTemplate(title: "WHV", gridButtons: [fahrt, ziel, heute, kontakte])
    }

    private func refreshRoot() {
        interface?.setRootTemplate(rootGrid(), animated: false, completion: nil)
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
        interface.presentTemplate(CPAlertTemplate(titleVariants: [title, detail], actions: [ok]), animated: true, completion: nil)
    }

    // MARK: Objekte — by visit frequency; tap → object page

    private func showProperties(forContacts: Bool = false) async {
        guard let interface else { return }
        let props = (try? await api.getMyProperties()) ?? []
        let trips = (try? await api.getMyTrips()) ?? []
        var freq: [String: Int] = [:]
        for t in trips { if let p = t.property_id { freq[p, default: 0] += 1 } }
        let sorted = props.sorted { a, b in
            let fa = freq[a.id] ?? 0, fb = freq[b.id] ?? 0
            return fa != fb ? fa > fb : a.name < b.name
        }
        let items: [CPListItem] = sorted.map { p in
            let item = CPListItem(text: p.name, detailText: Self.address(p))
            item.accessoryType = .disclosureIndicator
            item.handler = { [weak self] _, completion in
                Task { @MainActor in
                    if forContacts { await self?.showContacts(for: p) } else { await self?.showObject(p) }
                    completion()
                }
            }
            return item
        }
        let list = CPListTemplate(
            title: forContacts ? "Kontakte" : "Objekte",
            sections: [CPListSection(items: items.isEmpty ? [CPListItem(text: "Keine Objekte geladen", detailText: nil)] : items)]
        )
        interface.pushTemplate(list, animated: true, completion: nil)
    }

    /// The object page: the drive-related actions for one property, then its
    /// open tickets (read-only). "Besichtigung hier starten" opens a trip
    /// that already knows purpose + property, so no confirmation follows.
    private func showObject(_ p: PropertyResponse) async {
        guard let interface else { return }
        let tracker = TripTracker.shared

        let navi = CPListItem(text: "Navigation starten", detailText: Self.address(p))
        navi.setImage(UIImage(systemName: "location.fill"))
        navi.handler = { [weak self] _, completion in self?.navigate(to: p); completion() }

        let besichtigung = CPListItem(
            text: tracker.isRunning ? "Fahrt läuft bereits" : "Besichtigung hier starten",
            detailText: tracker.isRunning ? "Erst die laufende Fahrt beenden." : "Fahrt mit Zweck Besichtigung für dieses Objekt"
        )
        besichtigung.setImage(UIImage(systemName: "binoculars.fill"))
        besichtigung.handler = { [weak self] _, completion in
            guard let self else { completion(); return }
            if !tracker.isRunning {
                tracker.startWithPreset(purpose: "BESICHTIGUNG", propertyId: p.id, source: "CARPLAY")
                self.alert("Besichtigung läuft", "\(p.name) — die Fahrt wird aufgezeichnet.")
                self.refreshRoot()
            }
            completion()
        }

        let kontakte = CPListItem(text: "Kontakte", detailText: "Eigentümer und Dienstleister anrufen")
        kontakte.setImage(UIImage(systemName: "phone.fill"))
        kontakte.accessoryType = .disclosureIndicator
        kontakte.handler = { [weak self] _, completion in
            Task { @MainActor in await self?.showContacts(for: p); completion() }
        }

        var sections = [CPListSection(items: [navi, besichtigung, kontakte], header: "Fahrt", sectionIndexTitle: nil)]

        // Open tickets of this property — read-only rows, details stay on the phone.
        let tickets = (try? await api.getAdminTickets(propertyId: p.id)) ?? []
        let open = tickets.filter { $0.closed_at == nil }.prefix(8)
        if !open.isEmpty {
            let rows: [CPListItem] = open.map { t in
                let item = CPListItem(text: t.subject, detailText: t.status.rawValue.replacingOccurrences(of: "_", with: " ").capitalized)
                item.setImage(UIImage(systemName: "tray.full.fill"))
                return item
            }
            sections.append(CPListSection(items: rows, header: "Offene Tickets", sectionIndexTitle: nil))
        }

        interface.pushTemplate(CPListTemplate(title: p.name, sections: sections), animated: true, completion: nil)
    }

    private func navigate(to p: PropertyResponse) {
        guard let lat = p.lat, let lng = p.lng else {
            alert("Keine Koordinaten", "Für dieses Objekt fehlt die Geoposition.")
            return
        }
        let item = MKMapItem(placemark: MKPlacemark(coordinate: CLLocationCoordinate2D(latitude: lat, longitude: lng)))
        item.name = p.name
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
        let items: [CPListItem] = feed.map { a in CPListItem(text: a.title, detailText: a.subtitle) }
        let list = CPListTemplate(
            title: "Heute",
            sections: [CPListSection(items: items.isEmpty ? [CPListItem(text: "Nichts Offenes", detailText: nil)] : items)]
        )
        interface.pushTemplate(list, animated: true, completion: nil)
    }

    // MARK: Kontakte — owners + Dienstleister; tap → call / "verspäte mich"

    private struct Person {
        let id: String?  // contact id (owners) — needed for the delay notice
        let name: String
        let phone: String?
        let email: String?
        let kind: String
    }

    private func showContacts(for p: PropertyResponse) async {
        guard let interface else { return }
        async let ownersTask = api.getAdminPropertyContacts(propertyId: p.id)
        async let vendorsTask = api.getMyPropertyVendors(propertyId: p.id)
        let owners = (try? await ownersTask) ?? []
        let vendors = (try? await vendorsTask) ?? []

        var people: [Person] = owners.map {
            Person(id: $0.contact_id, name: $0.name, phone: $0.phone, email: $0.email,
                   kind: $0.contract_type.lowercased().contains("tenant") ? "Mieter" : "Eigentümer")
        }
        people += vendors.map { Person(id: nil, name: $0.name, phone: $0.phone, email: $0.email, kind: "Dienstleister") }

        func section(_ title: String, _ list: [Person]) -> CPListSection? {
            guard !list.isEmpty else { return nil }
            let items: [CPListItem] = list.map { person in
                let detail = [person.phone, person.email].compactMap { $0 }.joined(separator: " · ")
                let item = CPListItem(text: person.name, detailText: detail.isEmpty ? "keine Kontaktdaten" : detail)
                item.accessoryType = .disclosureIndicator
                item.handler = { [weak self] _, completion in
                    self?.showPersonActions(person, property: p)
                    completion()
                }
                return item
            }
            return CPListSection(items: items, header: title, sectionIndexTitle: nil)
        }
        let sections = [
            section("Eigentümer / Mieter", people.filter { $0.kind != "Dienstleister" }),
            section("Dienstleister", people.filter { $0.kind == "Dienstleister" }),
        ].compactMap { $0 }

        let list = CPListTemplate(
            title: p.name,
            sections: sections.isEmpty ? [CPListSection(items: [CPListItem(text: "Keine Kontakte hinterlegt", detailText: nil)])] : sections
        )
        interface.pushTemplate(list, animated: true, completion: nil)
    }

    /// Call, or send the one-tap "Ich verspäte mich" (our backend e-mails the
    /// contact with an ETA and, when the phone has a fix, a Maps link).
    private func showPersonActions(_ person: Person, property: PropertyResponse) {
        guard let interface else { return }
        var actions: [CPAlertAction] = []
        if let phone = person.phone, !phone.isEmpty {
            actions.append(CPAlertAction(title: "Anrufen", style: .default) { [weak self] _ in
                self?.interface?.dismissTemplate(animated: true, completion: nil)
                self?.call(phone)
            })
        }
        if person.id != nil, person.email != nil {
            for minutes in [10, 20, 30] {
                actions.append(CPAlertAction(title: "Verspäte mich \(minutes) Min", style: .default) { [weak self] _ in
                    self?.interface?.dismissTemplate(animated: true, completion: nil)
                    Task { @MainActor in await self?.sendDelay(person, minutes: minutes, property: property) }
                })
            }
        }
        actions.append(CPAlertAction(title: "Abbrechen", style: .cancel) { [weak self] _ in
            self?.interface?.dismissTemplate(animated: true, completion: nil)
        })
        let subtitle = [person.kind, person.phone ?? person.email ?? ""].filter { !$0.isEmpty }.joined(separator: " · ")
        interface.presentTemplate(CPAlertTemplate(titleVariants: [person.name, subtitle], actions: actions), animated: true, completion: nil)
    }

    private func sendDelay(_ person: Person, minutes: Int, property: PropertyResponse) async {
        guard let cid = person.id else { return }
        let loc = TripTracker.shared.currentCoordinate
        do {
            let r = try await api.sendDelayNotice(
                DelayNoticeBody(contact_id: cid, minutes: minutes, lat: loc?.latitude, lng: loc?.longitude, property_id: property.id)
            )
            alert(r.sent ? "Mitteilung gesendet" : "Nicht gesendet", r.detail)
        } catch {
            alert("Nicht gesendet", "Die Mitteilung konnte nicht verschickt werden.")
        }
    }

    private func call(_ phone: String) {
        let digits = phone.filter { "+0123456789".contains($0) }
        guard let url = URL(string: "tel://\(digits)"), let scene else { return }
        scene.open(url, options: nil, completionHandler: nil)
    }
}
