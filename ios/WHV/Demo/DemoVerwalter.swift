//
//  DemoVerwalter.swift
//  WHV
//
//  Manager-side demo data: what an App Store reviewer sees when choosing
//  "Demo als Verwalter" — CarPlay (Objekte/Besichtigung/Kontakte/Heute),
//  Fahrtenbuch (trips are recorded locally, never uploaded), Siri,
//  Briefing, Anfragen, Watch. Pure builders; DemoStore owns the state.
//

import Foundation

enum DemoVerwalter {
    // MARK: Objects (the two owner-demo properties + two more, all geocoded
    // in Stuttgart so proximity ranking, arrival detection and navigation
    // have something to work with).

    static let fallbackProperty = PropertyResponse(
        id: "demo-weg-koenigstrasse", property_hr_id: "Stuttgart_K42", name: "WEG Königstraße 42",
        type: "OWNER", city: "Stuttgart", street: "Königstraße", number: "42", postal_code: "70173",
        image_url: nil, lat: 48.7785, lng: 9.1800
    )

    static func properties(seed: DemoSeed?) -> [PropertyResponse] {
        let base = seed?.properties ?? [fallbackProperty]
        let extra = [
            PropertyResponse(
                id: "demo-weg-hasenberg", property_hr_id: "Stuttgart_H32", name: "WEG Hasenbergstraße 32",
                type: "OWNER", city: "Stuttgart", street: "Hasenbergstraße", number: "32", postal_code: "70176",
                image_url: nil, lat: 48.7720, lng: 9.1620
            ),
            PropertyResponse(
                id: "demo-weg-burgstrasse", property_hr_id: "Ditzingen_B6/8", name: "WEG Burgstraße 6/8",
                type: "OWNER", city: "Ditzingen", street: "Burgstraße", number: "6/8", postal_code: "71254",
                image_url: nil, lat: 48.8270, lng: 9.0670
            ),
            PropertyResponse(
                id: "demo-sev-fichtelberg", property_hr_id: "Stuttgart_F63", name: "SEV Fichtelbergstraße 63",
                type: "STRATA", city: "Stuttgart", street: "Fichtelbergstraße", number: "63", postal_code: "70469",
                image_url: nil, lat: 48.8200, lng: 9.1700
            ),
        ]
        return base + extra
    }

    // MARK: Contacts per object (name · role · phone · e-mail)

    static func contacts(propertyId: String) -> [AdminPropertyContact] {
        let people: [(String, String, String, String)]
        switch propertyId {
        case "demo-weg-koenigstrasse":
            people = [("Franziska Fritz", "OWNER", "+49 711 2345678", "franziska.fritz@example.com"),
                      ("Dr. Markus Keller", "OWNER", "+49 171 9876543", "m.keller@example.com"),
                      ("Leonie Braun", "TENANT", "+49 176 5551234", "leonie.braun@example.com")]
        case "demo-mv-hohewart":
            people = [("Familie Yilmaz", "TENANT", "+49 711 8765432", "yilmaz@example.com"),
                      ("Jonas Richter", "PROPERTY_OWNER", "+49 160 1122334", "j.richter@example.com")]
        case "demo-weg-hasenberg":
            people = [("Beirat: Sabine Vogel", "OWNER", "+49 711 4455667", "s.vogel@example.com"),
                      ("Peter Lang", "OWNER", "+49 172 3344556", "p.lang@example.com")]
        default:
            people = [("Thomas Berger", "OWNER", "+49 711 1010101", "t.berger@example.com")]
        }
        return people.enumerated().map { i, p in
            AdminPropertyContact(
                contact_id: "demo-contact-\(propertyId)-\(i)", impower_id: nil,
                name: p.0, email: p.3, phone: p.2, contract_type: p.1
            )
        }
    }

    static func searchContacts(query: String, properties: [PropertyResponse]) -> [ContactSearchResult] {
        var out: [ContactSearchResult] = []
        for p in properties {
            for c in contacts(propertyId: p.id) {
                if query.isEmpty || c.name.localizedCaseInsensitiveContains(query) {
                    out.append(ContactSearchResult(
                        id: c.contact_id, name: c.name, email: c.email, phone: c.phone,
                        property_name: p.name,
                        role: c.contract_type == "TENANT" ? "Mieter" : "Eigentümer"
                    ))
                }
            }
        }
        return out
    }

    // MARK: Agenda (today's Termin + the seed's planned ETVs)

    static func agenda(seed: DemoSeed?, properties: [PropertyResponse], days: Int, propertyId: String?) -> [AgendaEntry] {
        let cal = Calendar.current
        let now = Date()
        var items: [AgendaEntry] = []
        func entry(kind: String, id: String, title: String, start: Date, allDay: Bool, p: PropertyResponse, location: String?) -> AgendaEntry {
            AgendaEntry(
                kind: kind, source: kind == "ETV" ? "etv" : "event", id: id, title: title,
                starts_at: start, ends_at: nil, all_day: allDay, property_id: p.id, property_name: p.name,
                property_address: "\(p.street ?? "") \(p.number ?? ""), \(p.postal_code ?? "") \(p.city ?? "")",
                lat: p.lat, lng: p.lng, location: location, note: nil, assigned_label: nil,
                assembly_id: kind == "ETV" ? id : nil
            )
        }
        if let weg = properties.first(where: { $0.id == "demo-weg-hasenberg" }) {
            // Handwerkertermin today at 14:30.
            let today = cal.date(bySettingHour: 14, minute: 30, second: 0, of: now) ?? now
            items.append(entry(kind: "TERMIN", id: "demo-agenda-hw", title: "Handwerkertermin Dachrinne", start: today, allDay: true, p: weg, location: nil))
        }
        for a in seed?.assemblies ?? [] where a.scheduled_start > now {
            if let p = properties.first(where: { $0.id == a.property_id }) {
                items.append(entry(kind: "ETV", id: a.id, title: a.title, start: a.scheduled_start, allDay: false, p: p, location: a.location))
            }
        }
        if let mv = properties.first(where: { $0.id == "demo-mv-hohewart" }) {
            let inTwo = cal.date(byAdding: .day, value: 2, to: now) ?? now
            let start = cal.date(bySettingHour: 10, minute: 0, second: 0, of: inTwo) ?? inTwo
            items.append(entry(kind: "TERMIN", id: "demo-agenda-uebergabe", title: "Wohnungsübergabe 2. OG", start: start, allDay: false, p: mv, location: nil))
        }
        let horizon = cal.date(byAdding: .day, value: days + 1, to: cal.startOfDay(for: now)) ?? now
        return items
            .filter { $0.starts_at < horizon && (propertyId == nil || $0.property_id == propertyId) }
            .sorted { $0.starts_at < $1.starts_at }
    }

    // MARK: Anfragen (prospects in the offer phase → Besichtigung)

    static func inquiries() -> [OfferInquirySummary] {
        let iso = ISO8601DateFormatter()
        let now = Date()
        func inq(_ id: String, _ name: String, _ address: String, _ art: String, _ units: Int, daysAgo: Int, visited: Bool) -> OfferInquirySummary {
            OfferInquirySummary(
                id: id, sender_email: "\(name.lowercased().replacingOccurrences(of: " ", with: "."))@example.com",
                sender_name: name, subject: "Anfrage Hausverwaltung", status: "SENT", lead_status: "OPEN",
                art: art, object_address: address, units: units,
                desired_start: "2027-01-01", confidence: 0.92,
                sent_at: iso.string(from: now.addingTimeInterval(-Double(daysAgo) * 86400)),
                created_at: iso.string(from: now.addingTimeInterval(-Double(daysAgo + 1) * 86400)),
                generated_offer_filename: "Angebot-\(art)-demo.pdf", last_reminder_at: nil, reminder_count: 0,
                visited_at: visited ? iso.string(from: now.addingTimeInterval(-86400)) : nil,
                visit_count: visited ? 1 : 0
            )
        }
        return [
            inq("demo-inq-1", "Roman Klassen", "Hermann-Essig-Str. 5, 71701 Schwieberdingen", "WEG", 6, daysAgo: 3, visited: false),
            inq("demo-inq-2", "Anna Schreiber", "Marienstraße 12, 70178 Stuttgart", "MV", 4, daysAgo: 9, visited: true),
        ]
    }

    // MARK: Trips (the Verwalter's own log; more get recorded live)

    static func seedTrips(properties: [PropertyResponse]) -> [TripResponse] {
        let cal = Calendar.current
        let now = Date()
        func trip(id: String, daysAgo: Int, hour: Int, minutes: Int, km: Double, purpose: String?, p: PropertyResponse?, source: String = "AUTO") -> TripResponse {
            let day = cal.date(byAdding: .day, value: -daysAgo, to: now) ?? now
            let start = cal.date(bySettingHour: hour, minute: 0, second: 0, of: day) ?? day
            let end = start.addingTimeInterval(Double(minutes) * 60)
            let m = Int(km * 1000)
            let cents = purpose == "PRIVAT" ? 0 : Int((Double(m) / 1000 * 30).rounded())
            return TripResponse(
                id: id, user_id: "demo-verwalter", user_email: "demo-verwalter@example.com",
                property_id: p?.id, property_name: p?.name, inquiry_id: nil, inquiry_address: nil, invoice_id: nil,
                status: purpose == nil ? "OPEN" : "CONFIRMED", source: source, purpose: purpose,
                started_at: start, ended_at: end,
                start_lat: 48.8120, start_lng: 9.1720, end_lat: p?.lat, end_lng: p?.lng,
                distance_m: m, distance_km: String(format: "%.1f", km), route_polyline: nil,
                rate_cents_per_km: 30, amount_cents: cents, note: nil
            )
        }
        let k42 = properties.first { $0.id == "demo-weg-koenigstrasse" }
        let h32 = properties.first { $0.id == "demo-weg-hasenberg" }
        let b68 = properties.first { $0.id == "demo-weg-burgstrasse" }
        return [
            trip(id: "demo-trip-1", daysAgo: 0, hour: 8, minutes: 25, km: 11.4, purpose: "HANDWERKERTERMIN", p: h32, source: "CARPLAY"),
            trip(id: "demo-trip-2", daysAgo: 1, hour: 17, minutes: 40, km: 23.1, purpose: "ETV", p: b68, source: "CARPLAY"),
            trip(id: "demo-trip-3", daysAgo: 2, hour: 9, minutes: 30, km: 7.9, purpose: nil, p: nil),
            trip(id: "demo-trip-4", daysAgo: 3, hour: 13, minutes: 20, km: 5.2, purpose: "EIGENTUEMERTERMIN", p: k42),
            trip(id: "demo-trip-5", daysAgo: 5, hour: 18, minutes: 35, km: 14.0, purpose: "PRIVAT", p: nil, source: "MANUAL"),
        ]
    }

    static func trip(from body: TripCompleteBody, properties: [PropertyResponse]) -> TripResponse {
        let p = properties.first { $0.id == body.property_id }
        let km = Double(body.distance_m) / 1000
        let cents = body.purpose == "PRIVAT" ? 0 : Int((km * 30).rounded())
        return TripResponse(
            id: "demo-trip-\(UUID().uuidString.prefix(8).lowercased())", user_id: "demo-verwalter",
            user_email: "demo-verwalter@example.com", property_id: p?.id, property_name: p?.name,
            inquiry_id: body.inquiry_id, inquiry_address: body.inquiry_id != nil ? inquiries().first { $0.id == body.inquiry_id }?.object_address : nil,
            invoice_id: nil, status: body.purpose == nil ? "OPEN" : "CONFIRMED", source: body.source,
            purpose: body.purpose, started_at: body.started_at, ended_at: body.ended_at,
            start_lat: body.start_lat, start_lng: body.start_lng, end_lat: body.end_lat, end_lng: body.end_lng,
            distance_m: body.distance_m, distance_km: String(format: "%.1f", km), route_polyline: body.route_polyline,
            rate_cents_per_km: 30, amount_cents: cents, note: body.note
        )
    }

    static func apply(_ body: TripUpdateBody, to t: TripResponse, properties: [PropertyResponse]) -> TripResponse {
        let purpose = body.purpose ?? t.purpose
        let pid = body.clearProperty ? nil : (body.property_id ?? t.property_id)
        let p = properties.first { $0.id == pid }
        let km = Double(t.distance_m ?? 0) / 1000
        let cents = purpose == "PRIVAT" ? 0 : Int((km * 30).rounded())
        return TripResponse(
            id: t.id, user_id: t.user_id, user_email: t.user_email, property_id: p?.id, property_name: p?.name,
            inquiry_id: t.inquiry_id, inquiry_address: t.inquiry_address, invoice_id: t.invoice_id,
            status: purpose == nil ? "OPEN" : "CONFIRMED", source: t.source, purpose: purpose,
            started_at: t.started_at, ended_at: t.ended_at, start_lat: t.start_lat, start_lng: t.start_lng,
            end_lat: t.end_lat, end_lng: t.end_lng, distance_m: t.distance_m, distance_km: t.distance_km,
            route_polyline: t.route_polyline, rate_cents_per_km: t.rate_cents_per_km, amount_cents: cents,
            note: body.note ?? t.note
        )
    }

    // MARK: Briefing

    static func briefing(for p: PropertyResponse, tickets: [TicketSummary], agenda: [AgendaEntry]) -> BriefingResponse {
        let open = tickets.filter { $0.property_id == p.id && $0.closed_at == nil }
        var spoken: [String] = ["Briefing \(p.name)."]
        var sections: [BriefingSection] = [BriefingSection(title: "Objekt", lines: ["\(contacts(propertyId: p.id).count) Kontakte"])]
        if open.isEmpty {
            spoken.append("Keine offenen Tickets.")
            sections.append(BriefingSection(title: "Offene Tickets", lines: ["keine"]))
        } else {
            let top = open.prefix(3).map(\.subject)
            spoken.append("\(open.count == 1 ? "Ein offenes Ticket" : "\(open.count) offene Tickets"): " + top.joined(separator: "; ") + ".")
            sections.append(BriefingSection(title: "Offene Tickets (\(open.count))", lines: top))
        }
        if agenda.isEmpty {
            spoken.append("Keine Termine in den nächsten zwei Wochen.")
        } else {
            let lines = agenda.prefix(3).map { a in
                a.all_day ? "\(a.title) \(a.isToday ? "heute" : a.whenLabel)" : "\(a.title) \(a.isToday ? "heute um" : "am") \(a.whenLabel)"
            }
            spoken.append("Termine: " + lines.joined(separator: "; ") + ".")
            sections.append(BriefingSection(title: "Termine", lines: lines))
        }
        spoken.append("Jahresabrechnung 2025: 6 von 9 Schritten erledigt.")
        sections.append(BriefingSection(title: "Jahresabrechnung 2025", lines: ["6 von 9 Schritten erledigt"]))
        return BriefingResponse(property_id: p.id, property_name: p.name, spoken: spoken.joined(separator: " "), sections: sections, generated_at: Date())
    }
}
