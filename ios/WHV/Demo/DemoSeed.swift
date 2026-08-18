// Seed dataset for demo mode. Two Liegenschaften, a handful of
// tickets / Mitteilungen / ETVs each. Timestamps anchored to
// DemoSeed.build() so a fresh demo session always feels current
// (no "2 years ago" rows).
//
// REQUIREMENTS §8.8: ≥2 Liegenschaften, 4-6 tickets each, 3-4
// Mitteilungen, 1 vergangene + 1 geplante ETV per. The fake user
// role is "beirat" (broad read scope) so every visible surface is
// populated when the App Store reviewer pokes around.

import Foundation

struct DemoSeed {
    let properties: [PropertyResponse]
    let assemblies: [AssemblySummary]
    let assemblyDetails: [Assembly]
    let comments: [String: [AssemblyComment]]  // keyed by assembly id
    let announcements: [AnnouncementSummary]
    let announcementDetails: [AnnouncementDetail]
    let tickets: [TicketSummary]
    let ticketDetails: [TicketDetail]
    /// Units keyed by property id — drives the Einheiten section
    /// inside PropertyDetailView (§8.3). UnitResponse uses a custom
    /// decoder so we round-trip via JSON like ticketSummary().
    let units: [String: [UnitResponse]]
    /// Vendors keyed by property id — populates the Dienstleister
    /// section of PropertyDetailView so App Store reviewers see a
    /// realistic owner-side view of who has worked on the building.
    let vendors: [String: [VendorSummary]]

    static func build(now: Date = Date()) -> DemoSeed {
        let cal = Calendar.current

        // Two demo properties — mirrors REQUIREMENTS §8.8.
        let weg = PropertyResponse(
            id: "demo-weg-koenigstrasse",
            property_hr_id: "DEMO_K42",
            name: "WEG Königstraße 42",
            type: "WEG-Verwaltung",
            city: "Stuttgart",
            street: "Königstraße",
            number: "42",
            postal_code: "70173",
            image_url: nil
        )
        let mv = PropertyResponse(
            id: "demo-mv-hohewart",
            property_hr_id: "DEMO_H13",
            name: "MV Hohewartstraße 13",
            type: "Mietverwaltung",
            city: "Stuttgart",
            street: "Hohewartstraße",
            number: "13",
            postal_code: "70469",
            image_url: nil
        )

        // ETV per property: 1 past + 1 planned each.
        let pastStart = cal.date(byAdding: .month, value: -3, to: now) ?? now
        let pastEnd = cal.date(byAdding: .hour, value: 3, to: pastStart) ?? pastStart
        let plannedStart = cal.date(byAdding: .day, value: 18, to: now) ?? now
        let plannedEnd = cal.date(byAdding: .hour, value: 3, to: plannedStart) ?? plannedStart

        let assemblies = [
            // WEG
            assemblySummary(
                id: "demo-asm-weg-past",
                property: weg,
                title: "Ordentliche Eigentümerversammlung 2025",
                status: .abgehalten,
                start: pastStart,
                end: pastEnd,
                location: "Vereinsheim Königstraße 42",
                teamsUrl: nil,
                protocolUrl: "demo-protocol.pdf",
                protocolUploadedAt: cal.date(byAdding: .day, value: 7, to: pastEnd)
            ),
            assemblySummary(
                id: "demo-asm-weg-planned",
                property: weg,
                title: "Außerordentliche ETV — Tiefgaragenrampe",
                status: .eingeladen,
                start: plannedStart,
                end: plannedEnd,
                location: "Microsoft Teams (Link siehe Einladung)",
                teamsUrl: "https://teams.microsoft.com/l/meetup-join/demo",
                protocolUrl: nil,
                protocolUploadedAt: nil
            ),
            // MV
            assemblySummary(
                id: "demo-asm-mv-past",
                property: mv,
                title: "Eigentümerversammlung MV 2025",
                status: .abgehalten,
                start: cal.date(byAdding: .month, value: -4, to: now) ?? now,
                end: cal.date(byAdding: .month, value: -4, to: cal.date(byAdding: .hour, value: 2, to: now) ?? now) ?? now,
                location: "Büro Hausverwaltung",
                teamsUrl: nil,
                protocolUrl: "demo-protocol-mv.pdf",
                protocolUploadedAt: cal.date(byAdding: .day, value: 21, to: cal.date(byAdding: .month, value: -4, to: now) ?? now)
            ),
            assemblySummary(
                id: "demo-asm-mv-planned",
                property: mv,
                title: "Versammlung MV 2026",
                status: .geplant,
                start: cal.date(byAdding: .day, value: 45, to: now) ?? now,
                end: cal.date(byAdding: .day, value: 45, to: cal.date(byAdding: .hour, value: 2, to: now) ?? now) ?? now,
                location: "Vor Ort, Hohewartstraße 13",
                teamsUrl: nil,
                protocolUrl: nil,
                protocolUploadedAt: nil
            ),
        ]

        // Detail variant for tap-through.
        let assemblyDetails = assemblies.map { detailFor(summary: $0, pastEnd: pastEnd) }

        // Q&A comments — only on the past WEG assembly so the
        // demo shows the role-badged thread.
        let comments: [String: [AssemblyComment]] = [
            "demo-asm-weg-past": [
                AssemblyComment(
                    id: "demo-c1",
                    assembly_id: "demo-asm-weg-past",
                    author_user_id: "demo-mueller",
                    author_label: "h.mueller@example.com",
                    author_role: .eigentuemer,
                    body: "Wann werden die beschlossenen Dachsanierungsarbeiten konkret begonnen?",
                    created_at: cal.date(byAdding: .day, value: 9, to: pastEnd) ?? pastEnd,
                    edited_at: nil
                ),
                AssemblyComment(
                    id: "demo-c2",
                    assembly_id: "demo-asm-weg-past",
                    author_user_id: "demo-wagner",
                    author_label: "verwaltung@wagner-hausverwaltung.com",
                    author_role: .verwalter,
                    body: "Baubeginn ist Anfang Mai 2026 angedacht. Detailplanung läuft.",
                    created_at: cal.date(byAdding: .day, value: 10, to: pastEnd) ?? pastEnd,
                    edited_at: nil
                ),
            ],
        ]

        // Mitteilungen — 4 across the two properties.
        let announcements = [
            announcementSummary(
                id: "demo-ann-1",
                property: weg,
                title: "Wasserabstellung am 12.06.",
                body: "Wegen Wartungsarbeiten am Steigstrang ist das Wasser am 12.06. zwischen 08:00 und 14:00 Uhr abgestellt.",
                publishedAgo: cal.date(byAdding: .day, value: -2, to: now) ?? now
            ),
            announcementSummary(
                id: "demo-ann-2",
                property: weg,
                title: "Treppenhaus-Reinigung neue Firma",
                body: "Ab nächster Woche übernimmt die Firma Sauber GmbH die Treppenhausreinigung. Erster Termin: Donnerstag, 10:00 Uhr.",
                publishedAgo: cal.date(byAdding: .day, value: -6, to: now) ?? now
            ),
            announcementSummary(
                id: "demo-ann-3",
                property: mv,
                title: "Briefkasten-Beschriftung",
                body: "Bitte die Beschriftung Ihres Briefkastens bis zum 20.06. erneuern. Vorlage liegt im Hausflur aus.",
                publishedAgo: cal.date(byAdding: .day, value: -1, to: now) ?? now
            ),
        ]
        let announcementDetails = announcements.map { detailFor(announcement: $0) }

        // Tickets — 4 across the two properties. Mix of statuses
        // so the Aktuell / Geschlossen split + the chip colours
        // are exercised.
        let tickets: [TicketSummary] = [
            ticketSummary(
                id: "demo-tic-1",
                property: weg,
                subject: "Aufzug bleibt im 3. OG hängen",
                status: .offen,
                category: .schadenAllgemein,
                ageDays: 1
            ),
            ticketSummary(
                id: "demo-tic-2",
                property: weg,
                subject: "Beschluss-Umsetzung Dachsanierung",
                status: .wartetAufKunde,
                category: .sonstigesBeschlussumsetzung,
                ageDays: 4
            ),
            ticketSummary(
                id: "demo-tic-3",
                property: mv,
                subject: "Heizung in WE 4 zu warm",
                status: .neu,
                category: .schadenAllgemein,
                ageDays: 0
            ),
            ticketSummary(
                id: "demo-tic-4",
                property: mv,
                subject: "Schlüssel verloren",
                status: .geschlossen,
                category: .allgemeinSchluessel,
                ageDays: 24
            ),
        ]
        let ticketDetails = tickets.map { detailFor(ticket: $0) }

        // Units + vendors for the WEG property. The MV property gets
        // a thinner slice (1 unit, 1 vendor) so the demo still shows
        // the section on both Liegenschaften without duplicating
        // copy. PropertyDetailView gates each section on non-empty.
        let units: [String: [UnitResponse]] = [
            weg.id: [
                unitResponse(id: "demo-unit-weg-1", hrId: "WE 01", type: "Wohnung",
                             floor: "Erdgeschoss", position: "links",
                             areaM2: 78.4, heatedAreaM2: 74.2, persons: 2, mea: 142,
                             contracts: [
                                ("OWNER", "h.mueller@example.com", "Hans Müller"),
                             ]),
                unitResponse(id: "demo-unit-weg-2", hrId: "WE 02", type: "Wohnung",
                             floor: "1. OG", position: "rechts",
                             areaM2: 92.1, heatedAreaM2: 88.0, persons: 3, mea: 167,
                             contracts: [
                                ("OWNER", "k.schmidt@example.com", "Klara Schmidt"),
                                ("TENANT", "p.weber@example.com", "Paul Weber"),
                             ]),
                unitResponse(id: "demo-unit-weg-3", hrId: "WE 03", type: "Wohnung",
                             floor: "2. OG", position: "Mitte",
                             areaM2: 105.0, heatedAreaM2: 99.5, persons: 4, mea: 191,
                             contracts: [
                                ("OWNER", "a.becker@example.com", "Anna Becker"),
                             ]),
            ],
            mv.id: [
                unitResponse(id: "demo-unit-mv-1", hrId: "WE 04", type: "Wohnung",
                             floor: "Erdgeschoss", position: nil,
                             areaM2: 64.0, heatedAreaM2: 60.0, persons: 1, mea: nil,
                             contracts: [
                                ("TENANT", "l.koch@example.com", "Lisa Koch"),
                             ]),
            ],
        ]
        let vendors: [String: [VendorSummary]] = [
            weg.id: [
                VendorSummary(
                    contact_id: "demo-vendor-1",
                    name: "Schwarz Dachdeckerei GmbH",
                    kind: "COMPANY",
                    email: "info@schwarz-dach.example.com",
                    phone: "+49 711 1234567",
                    invoice_count: 4,
                    total_amount: 47_200.0,
                    first_service_date: "2025-03-12",
                    last_service_date: "2026-04-22",
                    recent_invoices: [
                        VendorInvoiceSummary(
                            id: "demo-inv-1",
                            name: "Dachsanierung Rechnung 04/2026",
                            issued_date: "2026-04-22",
                            amount: 18_400.0
                        ),
                    ]
                ),
                VendorSummary(
                    contact_id: "demo-vendor-2",
                    name: "Schorn Heizungstechnik",
                    kind: "COMPANY",
                    email: "service@schorn-heizung.example.com",
                    phone: "+49 711 9876543",
                    invoice_count: 7,
                    total_amount: 3_840.0,
                    first_service_date: "2024-10-04",
                    last_service_date: "2026-02-18",
                    recent_invoices: []
                ),
                VendorSummary(
                    contact_id: "demo-vendor-3",
                    name: "Sauber GmbH",
                    kind: "COMPANY",
                    email: "buero@sauber-reinigung.example.com",
                    phone: "+49 711 4422110",
                    invoice_count: 12,
                    total_amount: 5_760.0,
                    first_service_date: "2025-09-01",
                    last_service_date: "2026-05-26",
                    recent_invoices: []
                ),
            ],
            mv.id: [
                VendorSummary(
                    contact_id: "demo-vendor-4",
                    name: "Schlüsseldienst Schnell",
                    kind: "COMPANY",
                    email: nil,
                    phone: "+49 711 2233445",
                    invoice_count: 1,
                    total_amount: 220.0,
                    first_service_date: "2026-05-02",
                    last_service_date: "2026-05-02",
                    recent_invoices: []
                ),
            ],
        ]

        return DemoSeed(
            properties: [weg, mv],
            assemblies: assemblies,
            assemblyDetails: assemblyDetails,
            comments: comments,
            announcements: announcements,
            announcementDetails: announcementDetails,
            tickets: tickets,
            ticketDetails: ticketDetails,
            units: units,
            vendors: vendors
        )
    }

    // MARK: - Unit builder

    /// JSON round-trip because UnitResponse owns a custom decoder
    /// (the `current_contracts` field falls back to [] when absent).
    /// Same pattern as ticketSummary() — direct memberwise init isn't
    /// available because the custom decoder hides the synthesized one.
    private static func unitResponse(
        id: String,
        hrId: String,
        type: String,
        floor: String?,
        position: String?,
        areaM2: Double?,
        heatedAreaM2: Double?,
        persons: Double?,
        mea: Double?,
        contracts: [(String, String, String)]
    ) -> UnitResponse {
        let contractsJSON: [[String: Any?]] = contracts.enumerated().map { idx, tup in
            let (type, email, label) = tup
            return [
                "contract_id": "\(id)-c\(idx)",
                "contract_number": nil,
                "type": type,
                "contact_id": "\(id)-contact-\(idx)",
                "contact_label": label,
                "role": email,
                "start_date": nil,
                "end_date": nil,
            ]
        }
        let dict: [String: Any?] = [
            "id": id,
            "unit_hr_id": hrId,
            "type": type,
            "floor": floor,
            "position": position,
            "unit_rank": nil,
            "is_owned_by_weg": false,
            "voting_share": mea,
            "area_m2": areaM2,
            "heated_area_m2": heatedAreaM2,
            "persons": persons,
            "rooms": nil,
            "current_contracts": contractsJSON.map { $0.compactMapValues { $0 } },
        ]
        let cleaned = dict.compactMapValues { $0 }
        let data = (try? JSONSerialization.data(withJSONObject: cleaned)) ?? Data()
        return (try? APIClient.jsonDecoder.decode(UnitResponse.self, from: data))!
    }

    // MARK: - Builders

    private static func assemblySummary(
        id: String,
        property: PropertyResponse,
        title: String,
        status: AssemblyStatus,
        start: Date,
        end: Date,
        location: String,
        teamsUrl: String?,
        protocolUrl: String?,
        protocolUploadedAt: Date?
    ) -> AssemblySummary {
        AssemblySummary(
            id: id,
            property_id: property.id,
            property_name: property.name,
            property_hr_id: property.property_hr_id,
            title: title,
            status: status,
            scheduled_start: start,
            scheduled_end: end,
            actual_start: status == .abgehalten ? start : nil,
            actual_end: status == .abgehalten ? end : nil,
            location: location,
            teams_meeting_url: teamsUrl,
            protocol_pdf_url: protocolUrl,
            protocol_uploaded_at: protocolUploadedAt
        )
    }

    private static func detailFor(summary s: AssemblySummary, pastEnd: Date) -> Assembly {
        let items: [AgendaItem] = s.status == .abgehalten
            ? [
                AgendaItem(
                    id: "\(s.id)-top-1",
                    position: 1,
                    type: .information,
                    title: "TOP 1: Begrüßung und Beschlussfähigkeit",
                    body: "Begrüßung der anwesenden Eigentümer durch die Verwaltung; Feststellung der Beschlussfähigkeit (Quorum: 50 %).",
                    beschluss_text: nil,
                    vote_yes: 0, vote_no: 0, vote_abstain: 0,
                    vote_required_quorum: nil,
                    vote_result: nil,
                    voting_basis: nil,
                    present_count: 14,
                    discussion: []
                ),
                AgendaItem(
                    id: "\(s.id)-top-2",
                    position: 2,
                    type: .beschluss,
                    title: "TOP 2: Beschluss Jahresabrechnung 2024",
                    body: "Vorstellung der Abrechnung 2024 + Bericht des Beirats.",
                    beschluss_text: "Die Eigentümergemeinschaft beschließt die Jahresabrechnung 2024 in der vorgelegten Fassung und erteilt der Verwaltung Entlastung.",
                    vote_yes: 13, vote_no: 0, vote_abstain: 1,
                    vote_required_quorum: nil,
                    vote_result: .angenommen,
                    voting_basis: .kopf,
                    present_count: 14,
                    discussion: []
                ),
                AgendaItem(
                    id: "\(s.id)-top-3",
                    position: 3,
                    type: .beschluss,
                    title: "TOP 3: Sanierung Dachfläche",
                    body: "Drei Angebote vorgelegt; Empfehlung des Beirats.",
                    beschluss_text: "Die Eigentümergemeinschaft beschließt die Sanierung der Dachfläche zum Festpreis von 47.200 € durch die Firma Schwarz Dachdeckerei GmbH.",
                    vote_yes: 10, vote_no: 3, vote_abstain: 1,
                    vote_required_quorum: 10,
                    vote_result: .angenommen,
                    voting_basis: .mea,
                    present_count: 14,
                    discussion: []
                ),
            ]
            : [
                AgendaItem(
                    id: "\(s.id)-top-1",
                    position: 1,
                    type: .information,
                    title: "TOP 1: Begrüßung und Tagesordnung",
                    body: "Begrüßung, Feststellung der Beschlussfähigkeit, Genehmigung der Tagesordnung.",
                    beschluss_text: nil,
                    vote_yes: 0, vote_no: 0, vote_abstain: 0,
                    vote_required_quorum: nil,
                    vote_result: nil,
                    voting_basis: nil,
                    present_count: nil,
                    discussion: []
                ),
                AgendaItem(
                    id: "\(s.id)-top-2",
                    position: 2,
                    type: .beschluss,
                    title: "TOP 2: Sanierung Tiefgaragenrampe",
                    body: "Sachstand: erhebliche Risse + Wassereintritt. Gutachten liegt vor.",
                    beschluss_text: "Die Eigentümergemeinschaft beschließt die Sanierung der Tiefgaragenrampe gemäß Gutachten zum geprüften Preis von 28.500 € aus der Instandhaltungsrücklage.",
                    vote_yes: 0, vote_no: 0, vote_abstain: 0,
                    vote_required_quorum: 10,
                    vote_result: nil,
                    voting_basis: .mea,
                    present_count: nil,
                    discussion: []
                ),
            ]
        return Assembly(
            id: s.id,
            property_id: s.property_id,
            property_name: s.property_name,
            property_hr_id: s.property_hr_id,
            title: s.title,
            description: "",
            status: s.status,
            scheduled_start: s.scheduled_start,
            scheduled_end: s.scheduled_end,
            actual_start: s.actual_start,
            actual_end: s.actual_end,
            location: s.location,
            teams_meeting_url: s.teams_meeting_url,
            agenda_pdf_url: nil,
            protocol_pdf_url: s.protocol_pdf_url,
            protocol_uploaded_at: s.protocol_uploaded_at,
            agenda_items: items
        )
    }

    private static func announcementSummary(
        id: String,
        property: PropertyResponse,
        title: String,
        body: String,
        publishedAgo: Date
    ) -> AnnouncementSummary {
        AnnouncementSummary(
            id: id,
            property_id: property.id,
            title: title,
            body: body,
            scheduled_publish_at: publishedAgo,
            notification_sent_at: publishedAgo,
            property_name: property.name
        )
    }

    private static func detailFor(announcement a: AnnouncementSummary) -> AnnouncementDetail {
        AnnouncementDetail(
            id: a.id,
            organization_id: "demo-org",
            property_id: a.property_id,
            created_by_user_id: "demo-wagner",
            title: a.title,
            body: a.body,
            audience_eigentuemer: true,
            audience_mieter: true,
            audience_beirat: true,
            created_at: a.scheduled_publish_at,
            updated_at: a.scheduled_publish_at,
            scheduled_publish_at: a.scheduled_publish_at,
            notification_sent_at: a.notification_sent_at,
            property_name: a.property_name,
            creator_email: "verwaltung@wagner-hausverwaltung.com",
            is_edited: false,
            attachment_count: 0,
            comment_count: 0,
            attachments: [],
            comments: []
        )
    }

    private static func ticketSummary(
        id: String,
        property: PropertyResponse,
        subject: String,
        status: TicketStatus,
        category: TicketCategory,
        ageDays: Int
    ) -> TicketSummary {
        let now = Date()
        let cal = Calendar.current
        let lastMessage = cal.date(byAdding: .day, value: -ageDays, to: now) ?? now
        let created = cal.date(byAdding: .day, value: -ageDays - 1, to: now) ?? now
        let closed: Date? = status == .geschlossen
            ? cal.date(byAdding: .day, value: -ageDays + 2, to: now)
            : nil
        // TicketSummary's decoder is custom — easiest construction
        // is via JSON round-trip with the wire shape.
        let dict: [String: Any?] = [
            "id": id,
            "property_id": property.id,
            "subject": subject,
            "status": status.rawValue,
            "category": category.rawValue,
            "last_message_at": ISO8601DateFormatter().string(from: lastMessage),
            "created_at": ISO8601DateFormatter().string(from: created),
            "closed_at": closed.map { ISO8601DateFormatter().string(from: $0) },
            "property_name": property.name,
            "property_address": "\(property.street ?? "") \(property.number ?? ""), \(property.postal_code ?? "") \(property.city ?? "")",
            "creator_email": "demo@example.com",
        ]
        let cleaned = dict.compactMapValues { $0 }
        let data = (try? JSONSerialization.data(withJSONObject: cleaned)) ?? Data()
        return (try? APIClient.jsonDecoder.decode(TicketSummary.self, from: data))
            ?? fallbackTicketSummary(id: id, subject: subject, status: status, category: category)
    }

    /// Last-resort fallback in case the JSON-round-trip path ever
    /// breaks — keeps the demo seed building rather than crashing.
    private static func fallbackTicketSummary(
        id: String,
        subject: String,
        status: TicketStatus,
        category: TicketCategory
    ) -> TicketSummary {
        let dict: [String: Any] = [
            "id": id, "subject": subject,
            "status": status.rawValue, "category": category.rawValue,
            "last_message_at": "2026-01-01T00:00:00Z",
            "created_at": "2026-01-01T00:00:00Z",
        ]
        let data = try! JSONSerialization.data(withJSONObject: dict)
        return try! APIClient.jsonDecoder.decode(TicketSummary.self, from: data)
    }

    private static func detailFor(ticket t: TicketSummary) -> TicketDetail {
        let body: String
        switch t.id {
        case "demo-tic-1":
            body = "Der Aufzug bleibt seit gestern Morgen im 3. OG hängen. Mehrere Bewohner betroffen, bitte um schnelle Reaktion."
        case "demo-tic-2":
            body = "Wir warten auf die Detailplanung der Dachdeckerei. Baubeginn voraussichtlich Anfang Mai."
        case "demo-tic-3":
            body = "Die Heizung in der Wohnung lässt sich nicht herunterregeln. Ventil scheint defekt."
        case "demo-tic-4":
            body = "Schlüssel zur Haustür verloren. Ersatz wurde übergeben."
        default:
            body = "Demo-Ticket."
        }
        let firstMessage = TicketMessage(
            id: "\(t.id)-msg-1",
            ticket_id: t.id,
            author_user_id: "demo-user",
            author_email: "demo@example.com",
            body: body,
            visible_body: body,
            quoted_body: nil,
            is_internal_note: false,
            created_at: t.created_at,
            attachments: []
        )
        return TicketDetail(
            id: t.id,
            property_id: t.property_id,
            created_by_user_id: "demo-user",
            assignee_user_id: nil,
            category: t.category,
            status: t.status,
            share_scope: .privateScope,
            subject: t.subject,
            last_message_at: t.last_message_at,
            created_at: t.created_at,
            closed_at: t.closed_at,
            property_name: t.property_name,
            property_address: t.property_address,
            creator_email: t.creator_email,
            creator_contact_label: nil,
            creator_contact_id_impower: nil,
            external_sender_email: nil,
            messages: [firstMessage],
            participants: []
        )
    }
}
