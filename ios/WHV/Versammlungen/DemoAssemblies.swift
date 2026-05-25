// Demo assemblies for Previews. The production flow fetches from
// the API; this scaffold only exists so SwiftUI #Preview blocks
// keep working without a server.

import Foundation

enum DemoAssemblies {
    static func sampleDetails(for property: Liegenschaft) -> [Assembly] {
        let propertyId = property.id
        let propertyName = property.name
        let propertyHrId: String = {
            let trimmed = property.name
                .uppercased()
                .replacingOccurrences(of: " ", with: "_")
                .replacingOccurrences(of: "Ä", with: "AE")
                .replacingOccurrences(of: "Ö", with: "OE")
                .replacingOccurrences(of: "Ü", with: "UE")
                .replacingOccurrences(of: "ß", with: "SS")
            return String(trimmed.prefix(24))
        }()

        let now = Date()
        let cal = Calendar.current
        let pastStart = cal.date(byAdding: .month, value: -3, to: now)!
        let pastStartFixed = cal.date(
            bySettingHour: 18, minute: 0, second: 0, of: pastStart
        ) ?? pastStart
        let pastEndFixed = cal.date(byAdding: .hour, value: 3, to: pastStartFixed) ?? pastStartFixed
        let plannedStart = cal.date(byAdding: .month, value: 2, to: now)!
        let plannedStartFixed = cal.date(
            bySettingHour: 18, minute: 30, second: 0, of: plannedStart
        ) ?? plannedStart
        let plannedEndFixed = cal.date(byAdding: .hour, value: 3, to: plannedStartFixed) ?? plannedStartFixed

        let pastAssemblyId = "demo-assembly-past-\(propertyId)"
        let past = Assembly(
            id: pastAssemblyId,
            property_id: propertyId,
            property_name: propertyName,
            property_hr_id: propertyHrId,
            title: "Ordentliche Eigentümerversammlung 2025",
            description:
                "Jährliche Versammlung der Eigentümergemeinschaft mit Beschluss "
                + "über Jahresabrechnung 2024, Wirtschaftsplan 2026 und "
                + "Sanierungsmaßnahmen.",
            status: .abgehalten,
            scheduled_start: pastStartFixed,
            scheduled_end: pastEndFixed,
            actual_start: pastStartFixed,
            actual_end: pastEndFixed,
            location: "Vereinsheim Königstraße 42, 70173 Stuttgart",
            teams_meeting_url: nil,
            agenda_pdf_url: nil,
            protocol_pdf_url: "demo-protokoll-2025.pdf",
            protocol_uploaded_at: cal.date(byAdding: .day, value: 7, to: pastEndFixed),
            agenda_items: [
                AgendaItem(
                    id: "demo-it-1",
                    position: 1,
                    type: .information,
                    title: "Begrüßung und Feststellung der Beschlussfähigkeit",
                    body:
                        "Frau Wagner begrüßt die anwesenden 14 von 18 stimmberechtigten "
                        + "Eigentümern (3 Vollmachten). Die Beschlussfähigkeit "
                        + "(50%-Quorum) ist erreicht.",
                    beschluss_text: nil,
                    vote_yes: 0, vote_no: 0, vote_abstain: 0,
                    vote_required_quorum: nil,
                    vote_result: nil,
                    voting_basis: nil,
                    present_count: 14,
                    discussion: []
                ),
                AgendaItem(
                    id: "demo-it-2",
                    position: 2,
                    type: .beschluss,
                    title: "Beschluss über die Jahresabrechnung 2024",
                    body: "Vorstellung der Abrechnung; Stellungnahme des Beirats.",
                    beschluss_text:
                        "Die Eigentümergemeinschaft beschließt die Jahresabrechnung "
                        + "2024 in der vorgelegten Fassung und erteilt der "
                        + "Verwaltung Entlastung.",
                    vote_yes: 13, vote_no: 0, vote_abstain: 1,
                    vote_required_quorum: nil,
                    vote_result: .angenommen,
                    voting_basis: .kopf,
                    present_count: 14,
                    discussion: []
                ),
            ]
        )

        let planned = Assembly(
            id: "demo-assembly-planned-\(propertyId)",
            property_id: propertyId,
            property_name: propertyName,
            property_hr_id: propertyHrId,
            title: "Außerordentliche Eigentümerversammlung 2026",
            description:
                "Außerordentliche Versammlung zur Klärung der "
                + "Sanierung Tiefgaragenrampe.",
            status: .geplant,
            scheduled_start: plannedStartFixed,
            scheduled_end: plannedEndFixed,
            actual_start: nil,
            actual_end: nil,
            location: "Online (Microsoft Teams) — Link siehe Einladung",
            teams_meeting_url:
                "https://teams.microsoft.com/l/meetup-join/19%3ameeting_demo%40thread.v2/0",
            agenda_pdf_url: nil,
            protocol_pdf_url: nil,
            protocol_uploaded_at: nil,
            agenda_items: [
                AgendaItem(
                    id: "demo-pl-1",
                    position: 1,
                    type: .beschluss,
                    title: "Sanierung Tiefgaragenrampe",
                    body: "Sachstand: erhebliche Risse + Wassereintritt.",
                    beschluss_text:
                        "Die Eigentümergemeinschaft beschließt die Sanierung "
                        + "der Tiefgaragenrampe zum geprüften Preis von 28.500 €.",
                    vote_yes: 0, vote_no: 0, vote_abstain: 0,
                    vote_required_quorum: 10,
                    vote_result: nil,
                    voting_basis: .mea,
                    present_count: nil,
                    discussion: []
                ),
            ]
        )

        return [planned, past]
    }

    /// List-shape summaries derived from the demo details.
    static func sampleSummaries(for property: Liegenschaft) -> [AssemblySummary] {
        sampleDetails(for: property).map { a in
            AssemblySummary(
                id: a.id,
                property_id: a.property_id,
                property_name: a.property_name,
                property_hr_id: a.property_hr_id,
                title: a.title,
                status: a.status,
                scheduled_start: a.scheduled_start,
                scheduled_end: a.scheduled_end,
                actual_start: a.actual_start,
                actual_end: a.actual_end,
                location: a.location,
                teams_meeting_url: a.teams_meeting_url,
                protocol_pdf_url: a.protocol_pdf_url,
                protocol_uploaded_at: a.protocol_uploaded_at
            )
        }
    }

    static func sampleComments(for assemblyId: String) -> [AssemblyComment] {
        let now = Date()
        return [
            AssemblyComment(
                id: "demo-c-1",
                assembly_id: assemblyId,
                author_user_id: "demo-user-mueller",
                author_label: "h.mueller@example.com",
                author_role: .eigentuemer,
                body: "Wann werden die Dachsanierungsarbeiten konkret begonnen?",
                created_at: now.addingTimeInterval(-3600 * 24 * 5),
                edited_at: nil
            ),
            AssemblyComment(
                id: "demo-c-2",
                assembly_id: assemblyId,
                author_user_id: "demo-user-wagner",
                author_label: "verwaltung@wagner-hausverwaltung.com",
                author_role: .verwalter,
                body: "Baubeginn ist Anfang Mai 2026 angedacht.",
                created_at: now.addingTimeInterval(-3600 * 24 * 4),
                edited_at: nil
            ),
        ]
    }
}
