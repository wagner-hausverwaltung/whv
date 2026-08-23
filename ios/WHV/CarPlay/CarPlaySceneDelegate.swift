//
//  CarPlaySceneDelegate.swift
//  WHV
//
//  Driving-Task CarPlay scene (ADR-0020). Templates only — Grid, List,
//  Information, Alert — and the Fahrt is the centre of it: connecting the
//  car starts a trip (if the driver opted in), disconnecting ends it, and
//  everything else is framed as part of the drive.
//
//  Two hard CarPlay limits shape the structure (both learned from crashes /
//  empty screens in the Simulator):
//   • Hierarchy depth: Driving-Task apps get a SHALLOW stack. Everything
//     here is at most two pushes below the root grid; anything deeper is an
//     Alert (modal), never another push.
//   • List size: a list shows at most `CPListTemplate.maximumItemCount`
//     rows (12 on the Simulator car) — 27 properties alphabetically cut off
//     after the 12 "MV …" ones. Lists are therefore grouped and trimmed.
//
//  Entitlement com.apple.developer.carplay-driving-task granted by Apple on
//  2026-08-23 (Case-ID 21774792) — it lives in WHV.entitlements for every
//  configuration, so this scene runs on devices, TestFlight and in the
//  Simulator (I/O → External Displays → CarPlay). Background + design notes:
//  infra/docs/carplay-entitlement-request.md.
//

import CarPlay
import MapKit
import OSLog
import UIKit

@MainActor
final class CarPlaySceneDelegate: UIResponder, CPTemplateApplicationSceneDelegate {
    private var interface: CPInterfaceController?
    private var scene: CPTemplateApplicationScene?
    private let api = APIClient()
    private var startedTripOnConnect = false

    private var maxItems: Int { max(1, CPListTemplate.maximumItemCount) }

    // MARK: Connect / disconnect = trip boundaries

    func templateApplicationScene(
        _ templateApplicationScene: CPTemplateApplicationScene,
        didConnect interfaceController: CPInterfaceController
    ) {
        interface = interfaceController
        scene = templateApplicationScene
        Task { await present() }
        let tracker = TripTracker.shared
        tracker.refreshLocation()
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
        Logger(subsystem: "com.wagner-hausverwaltung.portal", category: "carplay").info(
            "limits: items=\(CPListTemplate.maximumItemCount) sections=\(CPListTemplate.maximumSectionCount) alertActions=\(CPAlertTemplate.maximumActionCount)"
        )
        let me: UserResponse
        do {
            me = try await api.getMe()
        } catch {
            interface.setRootTemplate(infoTemplate("Bitte in der WHV-App anmelden", "Die CarPlay-Ansicht braucht eine aktive Anmeldung auf dem iPhone."), animated: false, completion: nil)
            return
        }
        if me.role.lowercased() != "verwalter" {
            interface.setRootTemplate(infoTemplate("Nur für Verwalter", "Die CarPlay-Ansicht ist für die Verwalterrolle gedacht."), animated: false, completion: nil)
            return
        }
        interface.setRootTemplate(rootGrid(), animated: false, completion: nil)
    }

    private func infoTemplate(_ title: String, _ detail: String) -> CPInformationTemplate {
        CPInformationTemplate(title: "WHV", layout: .leading, items: [CPInformationItem(title: title, detail: detail)], actions: [])
    }

    private func rootGrid() -> CPGridTemplate {
        let tracker = TripTracker.shared
        func button(_ title: String, _ symbol: String, _ action: @escaping () async -> Void) -> CPGridButton {
            CPGridButton(titleVariants: [title], image: UIImage(systemName: symbol) ?? UIImage()) { _ in
                Task { @MainActor in await action() }
            }
        }
        let buttons = [
            button(tracker.isRunning ? "Fahrt beenden" : "Fahrt starten",
                   tracker.isRunning ? "stop.circle.fill" : "car.fill") { [weak self] in await self?.toggleTrip() },
            button("Objekte", "building.2.fill") { [weak self] in await self?.showObjekte() },
            button("Besichtigung", "binoculars.fill") { [weak self] in await self?.showBesichtigungen() },
            button("Kontakte", "phone.fill") { [weak self] in await self?.showKontakteRoot() },
            button("Heute", "list.bullet.clipboard.fill") { [weak self] in await self?.showToday() },
        ]
        return CPGridTemplate(title: "WHV", gridButtons: buttons)
    }

    private func refreshRoot() {
        interface?.setRootTemplate(rootGrid(), animated: false, completion: nil)
    }

    /// Push at most two levels below the root; deeper = modal alert.
    private func push(_ template: CPTemplate) {
        guard let interface else { return }
        if interface.templates.count >= 3 {
            interface.popToRootTemplate(animated: false, completion: nil)
        }
        interface.pushTemplate(template, animated: true, completion: nil)
    }

    // MARK: Fahrt

    private func toggleTrip() async {
        let tracker = TripTracker.shared
        if tracker.isRunning {
            if let preset = tracker.presetPurpose {
                // Started FOR a destination (Fahrt hierhin / Besichtigung):
                // purpose + object are known, nothing to ask.
                let label = TripPurpose.label(for: preset)
                tracker.stopFromCarPlay()
                alert("Fahrt beendet", "\(label) — bestätigt gespeichert.")
                refreshRoot()
            } else {
                await showPurposePicker()
            }
        } else {
            tracker.startFromCarPlay()
            alert("Fahrt läuft", "Die Strecke wird aufgezeichnet.")
            refreshRoot()
        }
    }

    /// Ending a trip in the car: one tap on the purpose confirms it, the
    /// object is pre-filled from where the car is (nearest property within
    /// 300 m — the same rule as the phone's confirmation sheet). The preset
    /// is applied BEFORE the trip ends, so the upload is CONFIRMED in one go
    /// and the choice survives even when the phone is offline (queued body).
    private func showPurposePicker() async {
        let tracker = TripTracker.shared
        let props = (try? await api.getMyProperties()) ?? []
        var suggested: PropertyResponse?
        if let pid = tracker.presetPropertyId {
            suggested = props.first { $0.id == pid }
        } else if let here = tracker.currentCoordinate {
            var best: (PropertyResponse, Double)?
            for p in props {
                guard let lat = p.lat, let lng = p.lng else { continue }
                let d = haversineMeters(here, CLLocationCoordinate2D(latitude: lat, longitude: lng))
                if d <= 300, d < (best?.1 ?? .infinity) { best = (p, d) }
            }
            suggested = best?.0
        }

        let later = CPListItem(text: "Später in der App", detailText: "Fahrt beenden, Zweck offen lassen")
        later.setImage(UIImage(systemName: "clock"))
        later.handler = { [weak self] _, completion in
            self?.endTrip(purpose: nil, property: nil)
            completion()
        }
        let rows: [CPListItem] = TripPurpose.allCases.map { p in
            let detail: String? = p.wantsProperty
                ? (suggested.map { "Objekt: \($0.name)" } ?? "ohne Objekt — in der App nachtragen")
                : nil
            let item = CPListItem(text: p.label, detailText: detail)
            item.setImage(UIImage(systemName: p.systemImage))
            item.handler = { [weak self] _, completion in
                self?.endTrip(purpose: p, property: p.wantsProperty ? suggested : nil)
                completion()
            }
            return item
        }
        let sections = [
            CPListSection(items: [later]),
            CPListSection(items: rows, header: "Zweck der Fahrt", sectionIndexTitle: nil),
        ]
        push(CPListTemplate(title: "Fahrt beenden", sections: sections))
    }

    private func endTrip(purpose: TripPurpose?, property: PropertyResponse?) {
        let tracker = TripTracker.shared
        if let purpose {
            tracker.applyPreset(purpose: purpose.rawValue, propertyId: property?.id)
        }
        tracker.stopFromCarPlay()
        // No animation: the alert is presented right after, and CarPlay
        // rejects a second transition while one is in flight.
        interface?.popToRootTemplate(animated: false, completion: nil)
        refreshRoot()
        let detail = purpose.map { "\($0.label)\(property.map { " · \($0.name)" } ?? "") — bestätigt gespeichert." }
            ?? "Zweck und Objekt bestätigen Sie später in der App."
        alert("Fahrt beendet", detail)
    }

    private func alert(_ title: String, _ detail: String, actions extra: [CPAlertAction] = []) {
        guard let interface else { return }
        let dismiss = CPAlertAction(title: extra.isEmpty ? "OK" : "Abbrechen", style: .cancel) { [weak self] _ in
            self?.interface?.dismissTemplate(animated: true, completion: nil)
        }
        // Respect the system cap on alert actions; the dismiss action is the
        // one we drop first (any action dismisses the alert anyway).
        var actions = extra + [dismiss]
        let cap = max(1, CPAlertTemplate.maximumActionCount)
        if actions.count > cap { actions = Array(actions.prefix(cap)) }
        interface.presentTemplate(CPAlertTemplate(titleVariants: [title, detail], actions: actions), animated: true, completion: nil)
    }

    // MARK: Data helpers

    private struct Ranked {
        let props: [PropertyResponse]
        let freq: [String: Int]
    }

    private func rankedProperties() async -> Ranked {
        let props = (try? await api.getMyProperties()) ?? []
        let trips = (try? await api.getMyTrips()) ?? []
        var freq: [String: Int] = [:]
        for t in trips { if let p = t.property_id { freq[p, default: 0] += 1 } }
        let sorted = props.sorted { a, b in
            let fa = freq[a.id] ?? 0, fb = freq[b.id] ?? 0
            return fa != fb ? fa > fb : a.name < b.name
        }
        return Ranked(props: sorted, freq: freq)
    }

    private static func typeLabel(_ p: PropertyResponse) -> String {
        let n = p.name.uppercased()
        if n.hasPrefix("WEG") { return "WEG" }
        if n.hasPrefix("SEV") { return "SEV" }
        if n.hasPrefix("MV") { return "MV" }
        return "Weitere"
    }

    private static func address(_ p: PropertyResponse) -> String {
        let street = [p.street, p.number].compactMap { $0 }.joined(separator: " ")
        let city = [p.postal_code, p.city].compactMap { $0 }.joined(separator: " ")
        return [street, city].filter { !$0.isEmpty }.joined(separator: ", ")
    }

    // MARK: Objekte (level 1): frequent ones → object page (level 2);
    //       the long tail by type → plain list (level 2) that navigates.

    private func showObjekte() async {
        let ranked = await rankedProperties()
        var sections: [CPListSection] = []

        // Frequent / recent first — these get the full object page.
        let frequent = Array(ranked.props.prefix(6))
        if !frequent.isEmpty {
            let rows: [CPListItem] = frequent.map { p in
                let item = CPListItem(text: p.name, detailText: Self.address(p))
                item.accessoryType = .disclosureIndicator
                item.handler = { [weak self] _, completion in
                    Task { @MainActor in await self?.showObjectPage(p); completion() }
                }
                return item
            }
            sections.append(CPListSection(items: rows, header: ranked.freq.isEmpty ? "Objekte" : "Häufig besucht", sectionIndexTitle: nil))
        }

        // Everything, grouped by type — each group fits the item cap.
        var byType: [String: [PropertyResponse]] = [:]
        for p in ranked.props { byType[Self.typeLabel(p), default: []].append(p) }
        let order = ["WEG", "MV", "SEV", "Weitere"]
        let typeRows: [CPListItem] = order.compactMap { key in
            guard let list = byType[key], !list.isEmpty else { return nil }
            let item = CPListItem(text: "Alle \(key)", detailText: "\(list.count) Objekte · tippen = Navigation")
            item.accessoryType = .disclosureIndicator
            item.handler = { [weak self] _, completion in
                self?.showTypeList(key, list)
                completion()
            }
            return item
        }
        if !typeRows.isEmpty {
            sections.append(CPListSection(items: typeRows, header: "Nach Typ", sectionIndexTitle: nil))
        }
        if sections.isEmpty {
            sections = [CPListSection(items: [CPListItem(text: "Keine Objekte geladen", detailText: nil)])]
        }
        push(CPListTemplate(title: "Objekte", sections: sections))
    }

    private func showTypeList(_ key: String, _ list: [PropertyResponse]) {
        let rows: [CPListItem] = list.prefix(maxItems).map { p in
            let item = CPListItem(text: p.name, detailText: Self.address(p))
            item.setImage(UIImage(systemName: "location.fill"))
            item.handler = { [weak self] _, completion in self?.navigate(to: p); completion() }
            return item
        }
        push(CPListTemplate(title: "Alle \(key)", sections: [CPListSection(items: rows)]))
    }

    /// Object page (level 2): drive actions, contacts (→ alert), open tickets.
    /// `purpose` presets the trip purpose for "Fahrt hierhin starten" — ETV
    /// when the page was opened from an ETV appointment, else Eigentümertermin.
    /// Item budget (list cap, 12 in the Simulator car): 2 drive actions +
    /// 3 Termine + 4 contacts + 3 tickets.
    private func showObjectPage(_ p: PropertyResponse, purpose: String = "EIGENTUEMERTERMIN") async {
        let tracker = TripTracker.shared
        let purposeLabel = TripPurpose(rawValue: purpose)?.label ?? purpose
        let navi = CPListItem(text: "Navigation starten", detailText: Self.address(p))
        navi.setImage(UIImage(systemName: "location.fill"))
        navi.handler = { [weak self] _, completion in self?.navigate(to: p); completion() }

        let fahrt = CPListItem(
            text: tracker.isRunning ? "Fahrt läuft bereits" : "Fahrt hierhin starten",
            detailText: tracker.isRunning ? "Erst die laufende Fahrt beenden." : "Zweck: \(purposeLabel), Objekt vorbelegt"
        )
        fahrt.setImage(UIImage(systemName: "car.fill"))
        fahrt.handler = { [weak self] _, completion in
            if !tracker.isRunning {
                tracker.startWithPreset(purpose: purpose, propertyId: p.id, source: "CARPLAY")
                self?.alert("Fahrt läuft", "\(p.name) — die Fahrt wird aufgezeichnet.")
                self?.refreshRoot()
            }
            completion()
        }
        var sections = [CPListSection(items: [navi, fahrt], header: "Fahrt", sectionIndexTitle: nil)]

        async let contactsTask = loadPeople(for: p)
        async let ticketsTask = api.getAdminTickets(propertyId: p.id)
        async let agendaTask = api.getMyAgenda(days: 30, propertyId: p.id)
        let people = await contactsTask
        let tickets = (try? await ticketsTask) ?? []
        let agenda = (try? await agendaTask) ?? []

        // Upcoming appointments at this object (30 days) — tap = details.
        let agendaRows: [CPListItem] = agenda.prefix(3).map { a in
            let item = CPListItem(text: "\(a.whenLabel) · \(a.title)", detailText: a.location ?? a.assigned_label ?? (a.kind == "ETV" ? "Eigentümerversammlung" : "Termin"))
            item.setImage(UIImage(systemName: a.kind == "ETV" ? "person.3.fill" : "calendar"))
            item.handler = { [weak self] _, completion in
                let detail = [a.whenLabel, a.location, a.assigned_label, a.note].compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " · ")
                self?.alert(a.title, detail.isEmpty ? p.name : detail)
                completion()
            }
            return item
        }
        if !agendaRows.isEmpty {
            sections.append(CPListSection(items: agendaRows, header: "Termine", sectionIndexTitle: nil))
        }

        let contactRows: [CPListItem] = people.prefix(4).map { person in
            let item = CPListItem(text: person.name, detailText: [person.kind, person.phone ?? person.email ?? ""].filter { !$0.isEmpty }.joined(separator: " · "))
            item.setImage(UIImage(systemName: person.kind == "Dienstleister" ? "wrench.and.screwdriver.fill" : "person.fill"))
            item.handler = { [weak self] _, completion in self?.personAlert(person, property: p); completion() }
            return item
        }
        if !contactRows.isEmpty {
            sections.append(CPListSection(items: contactRows, header: "Kontakte", sectionIndexTitle: nil))
        }
        let open = tickets.filter { $0.closed_at == nil }.prefix(3)
        if !open.isEmpty {
            let rows: [CPListItem] = open.map { t in
                let item = CPListItem(text: t.subject, detailText: t.status.rawValue.replacingOccurrences(of: "_", with: " ").capitalized)
                item.setImage(UIImage(systemName: "tray.full.fill"))
                return item
            }
            sections.append(CPListSection(items: rows, header: "Offene Tickets", sectionIndexTitle: nil))
        }
        push(CPListTemplate(title: p.name, sections: sections))
    }

    private func navigate(to p: PropertyResponse) {
        guard let lat = p.lat, let lng = p.lng else {
            alert("Keine Koordinaten", "Für dieses Objekt fehlt die Geoposition.")
            return
        }
        openMaps(CLLocationCoordinate2D(latitude: lat, longitude: lng), name: p.name)
    }

    private func openMaps(_ coord: CLLocationCoordinate2D, name: String) {
        let item = MKMapItem(placemark: MKPlacemark(coordinate: coord))
        item.name = name
        item.openInMaps(launchOptions: [MKLaunchOptionsDirectionsModeKey: MKLaunchOptionsDirectionsModeDriving])
    }

    // MARK: Besichtigung (level 1): inquiries in the offer phase — objects
    //       that are NOT yet in the master data. Tap → level 2 actions.

    private func showBesichtigungen() async {
        let all = (try? await api.listOfferInquiries()) ?? []
        // Not-yet-visited prospects first (that's the to-do), then newest.
        let open = all
            .filter { ($0.object_address ?? "").isEmpty == false && ["OPEN", "ON_HOLD"].contains($0.lead_status.uppercased()) }
            .sorted { a, b in
                if a.isVisited != b.isVisited { return !a.isVisited }
                return a.created_at > b.created_at
            }
            .prefix(maxItems)
        let rows: [CPListItem] = open.map { inq in
            let who = inq.sender_name ?? inq.sender_email
            var meta = [inq.art, inq.units.map { "\($0) Einheiten" }].compactMap { $0 }.joined(separator: " · ")
            if inq.isVisited { meta += (meta.isEmpty ? "" : " · ") + "besichtigt \(offerDateDE(inq.visited_at))" }
            let item = CPListItem(text: inq.object_address ?? "—", detailText: [who, meta].filter { !$0.isEmpty }.joined(separator: " · "))
            if inq.isVisited { item.setImage(UIImage(systemName: "checkmark.circle")) }
            item.accessoryType = .disclosureIndicator
            item.handler = { [weak self] _, completion in
                self?.showBesichtigungActions(inq)
                completion()
            }
            return item
        }
        let sections = [CPListSection(
            items: rows.isEmpty ? [CPListItem(text: "Keine offenen Anfragen", detailText: "Anfragen in der Angebotsphase erscheinen hier.")] : rows
        )]
        push(CPListTemplate(title: "Besichtigung", sections: sections))
    }

    private func showBesichtigungActions(_ inq: OfferInquirySummary) {
        let address = inq.object_address ?? ""
        let tracker = TripTracker.shared
        let navi = CPListItem(text: "Navigation starten", detailText: address)
        navi.setImage(UIImage(systemName: "location.fill"))
        navi.handler = { [weak self] _, completion in
            Task { @MainActor in await self?.navigate(toAddress: address); completion() }
        }
        let fahrt = CPListItem(
            text: tracker.isRunning ? "Fahrt läuft bereits" : "Besichtigung starten",
            detailText: tracker.isRunning ? "Erst die laufende Fahrt beenden." : "Fahrt mit Zweck Besichtigung, Adresse in der Notiz"
        )
        fahrt.setImage(UIImage(systemName: "binoculars.fill"))
        fahrt.handler = { [weak self] _, completion in
            if !tracker.isRunning {
                // Linked to the inquiry: the Anfrage shows "besichtigt am …"
                // in the app and the admin portal once the trip is uploaded.
                tracker.startWithPreset(
                    purpose: "BESICHTIGUNG", propertyId: nil, source: "CARPLAY",
                    note: "Besichtigung (Anfrage): \(address)", inquiryId: inq.id
                )
                self?.alert("Besichtigung läuft", "\(address) — die Fahrt wird aufgezeichnet.")
                self?.refreshRoot()
            }
            completion()
        }
        var rows = [navi, fahrt]
        if let n = inq.visit_count, n > 0 {
            let seen = CPListItem(
                text: n > 1 ? "Bereits \(n)× besichtigt" : "Bereits besichtigt",
                detailText: "zuletzt am \(offerDateDE(inq.visited_at)) — laut Fahrtenbuch"
            )
            seen.setImage(UIImage(systemName: "checkmark.circle"))
            seen.handler = { _, completion in completion() }
            rows.append(seen)
        }
        push(CPListTemplate(title: address, sections: [CPListSection(items: rows)]))
    }

    private func navigate(toAddress address: String) async {
        // Prospective objects have no stored coordinates — geocode on the fly.
        let placemarks = try? await CLGeocoder().geocodeAddressString(address)
        guard let loc = placemarks?.first?.location else {
            alert("Adresse nicht gefunden", address)
            return
        }
        openMaps(loc.coordinate, name: address)
    }

    // MARK: Heute — read-only list of what's next

    /// "Heute" = the next destination: today's appointments (ETV/Termine
    /// across the org) first, then what's open from the activity feed. A
    /// tap opens the object page (navigation, trip, contacts) — the list is
    /// level 1, so the object page is the allowed level 2.
    private func showToday() async {
        async let agendaTask = api.getMyAgenda(days: 7)
        async let feedTask = api.getMyActivity(limit: maxItems)
        async let propsTask = api.getMyProperties()
        let agenda = (try? await agendaTask) ?? []
        let feed = (try? await feedTask) ?? []
        let props = Dictionary(uniqueKeysWithValues: ((try? await propsTask) ?? []).map { ($0.id, $0) })

        var sections: [CPListSection] = []
        let todays = agenda.filter(\.isToday)
        // Today's appointments; when the day is empty, the next ones instead
        // so the driver still sees what's coming.
        let shown = Array((todays.isEmpty ? agenda : todays).prefix(6))
        if !shown.isEmpty {
            let rows: [CPListItem] = shown.map { a in
                let detail = [a.property_name, a.location ?? a.property_address ?? ""].filter { !$0.isEmpty }.joined(separator: " · ")
                let item = CPListItem(text: "\(a.whenLabel) · \(a.title)", detailText: detail)
                item.setImage(UIImage(systemName: a.kind == "ETV" ? "person.3.fill" : "calendar"))
                if let p = props[a.property_id] {
                    item.accessoryType = .disclosureIndicator
                    item.handler = { [weak self] _, completion in
                        Task { @MainActor in
                            await self?.showObjectPage(p, purpose: a.kind == "ETV" ? "ETV" : "EIGENTUEMERTERMIN")
                            completion()
                        }
                    }
                } else {
                    item.handler = { [weak self] _, completion in
                        self?.alert(a.title, [a.whenLabel, a.property_name, a.location ?? ""].filter { !$0.isEmpty }.joined(separator: " · "))
                        completion()
                    }
                }
                return item
            }
            sections.append(CPListSection(items: rows, header: todays.isEmpty ? "Nächste Termine" : "Termine heute", sectionIndexTitle: nil))
        }

        // What's open — tap jumps to the object it belongs to.
        let room = max(0, maxItems - shown.count)
        let openRows: [CPListItem] = feed.prefix(room).map { a in
            let item = CPListItem(text: a.title, detailText: a.subtitle)
            if let pid = a.propertyId, let p = props[pid] {
                item.accessoryType = .disclosureIndicator
                item.handler = { [weak self] _, completion in
                    Task { @MainActor in await self?.showObjectPage(p); completion() }
                }
            }
            return item
        }
        if !openRows.isEmpty {
            sections.append(CPListSection(items: openRows, header: "Offen", sectionIndexTitle: nil))
        }
        if sections.isEmpty {
            sections = [CPListSection(items: [CPListItem(text: "Nichts Offenes", detailText: "Keine Termine in den nächsten 7 Tagen.")])]
        }
        push(CPListTemplate(title: "Heute", sections: sections))
    }

    // MARK: Kontakte (level 1): properties by frequency → contacts (level 2)
    //       → person alert (modal): Anrufen / Verspäte mich.

    private struct Person {
        let id: String?  // contact id (owners/tenants) — needed for the delay notice
        let name: String
        let phone: String?
        let email: String?
        let kind: String
    }

    private func loadPeople(for p: PropertyResponse) async -> [Person] {
        async let ownersTask = api.getAdminPropertyContacts(propertyId: p.id)
        async let vendorsTask = api.getMyPropertyVendors(propertyId: p.id)
        let owners = (try? await ownersTask) ?? []
        let vendors = (try? await vendorsTask) ?? []
        var people: [Person] = owners.map {
            Person(id: $0.contact_id, name: $0.name, phone: $0.phone, email: $0.email,
                   kind: $0.contract_type.lowercased().contains("tenant") ? "Mieter" : "Eigentümer")
        }
        people += vendors.map { Person(id: nil, name: $0.name, phone: $0.phone, email: $0.email, kind: "Dienstleister") }
        return people
    }

    private func showKontakteRoot() async {
        TripTracker.shared.refreshLocation()
        let ranked = await rankedProperties()
        // In the car you want the contacts of where you ARE or are heading:
        // the running trip's property first, then by distance when the phone
        // has a fix, then by visit frequency. The list cap makes this
        // selection matter — alphabetical would just show the first twelve.
        let tracker = TripTracker.shared
        var props = ranked.props
        if let here = tracker.currentCoordinate {
            props.sort { a, b in
                let da = a.lat.flatMap { la in a.lng.map { haversineMeters(here, .init(latitude: la, longitude: $0)) } } ?? .infinity
                let db = b.lat.flatMap { lb in b.lng.map { haversineMeters(here, .init(latitude: lb, longitude: $0)) } } ?? .infinity
                return da < db
            }
        }
        if let target = tracker.presetPropertyId, let i = props.firstIndex(where: { $0.id == target }) {
            props.insert(props.remove(at: i), at: 0)
        }
        let rows: [CPListItem] = props.prefix(maxItems).map { p in
            let item = CPListItem(text: p.name, detailText: Self.address(p))
            item.accessoryType = .disclosureIndicator
            item.handler = { [weak self] _, completion in
                Task { @MainActor in await self?.showContacts(for: p); completion() }
            }
            return item
        }
        let title = tracker.currentCoordinate != nil ? "Kontakte · in der Nähe" : "Kontakte"
        push(CPListTemplate(title: title, sections: [CPListSection(items: rows.isEmpty ? [CPListItem(text: "Keine Objekte geladen", detailText: nil)] : rows)]))
    }

    private func showContacts(for p: PropertyResponse) async {
        let people = await loadPeople(for: p)
        func rows(_ list: [Person]) -> [CPListItem] {
            list.map { person in
                let detail = [person.phone, person.email].compactMap { $0 }.joined(separator: " · ")
                let item = CPListItem(text: person.name, detailText: detail.isEmpty ? "keine Kontaktdaten" : detail)
                item.setImage(UIImage(systemName: person.kind == "Dienstleister" ? "wrench.and.screwdriver.fill" : "person.fill"))
                item.handler = { [weak self] _, completion in self?.personAlert(person, property: p); completion() }
                return item
            }
        }
        let owners = people.filter { $0.kind != "Dienstleister" }
        let vendors = people.filter { $0.kind == "Dienstleister" }
        // Keep the whole template under the item cap: owners first.
        let ownerRows = rows(Array(owners.prefix(maxItems)))
        let vendorRows = rows(Array(vendors.prefix(max(0, maxItems - ownerRows.count))))
        var sections: [CPListSection] = []
        if !ownerRows.isEmpty { sections.append(CPListSection(items: ownerRows, header: "Eigentümer / Mieter", sectionIndexTitle: nil)) }
        if !vendorRows.isEmpty { sections.append(CPListSection(items: vendorRows, header: "Dienstleister", sectionIndexTitle: nil)) }
        if sections.isEmpty { sections = [CPListSection(items: [CPListItem(text: "Keine Kontakte hinterlegt", detailText: nil)])] }
        push(CPListTemplate(title: p.name, sections: sections))
    }

    /// Modal (no push): call, or one-tap "Ich verspäte mich ~15 Min".
    private func personAlert(_ person: Person, property: PropertyResponse) {
        var actions: [CPAlertAction] = []
        if let phone = person.phone, !phone.isEmpty {
            actions.append(CPAlertAction(title: "Anrufen", style: .default) { [weak self] _ in
                self?.interface?.dismissTemplate(animated: true, completion: nil)
                self?.call(phone)
            })
        }
        if person.id != nil, person.email != nil {
            actions.append(CPAlertAction(title: "Verspäte mich ~15 Min", style: .default) { [weak self] _ in
                self?.interface?.dismissTemplate(animated: true, completion: nil)
                Task { @MainActor in await self?.sendDelay(person, minutes: 15, property: property) }
            })
        }
        let subtitle = [person.kind, person.phone ?? person.email ?? "keine Kontaktdaten"].joined(separator: " · ")
        alert(person.name, subtitle, actions: actions)
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
