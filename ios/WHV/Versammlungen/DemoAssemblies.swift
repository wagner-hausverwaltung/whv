// Demo assemblies for the Phase 2 scaffold. Two records that
// together cover every Tagesordnungspunkt-Typ the owner UI needs
// to render:
//
//   - 1 vergangene ETV (ABGEHALTEN) with INFORMATION + BESCHLUSS
//     (with tallies + result) + DISKUSSION + a signed protocol stub.
//   - 1 geplante ETV (GEPLANT) with the same Tagesordnung shape,
//     but no tallies, no protocol — just the invite + agenda.
//
// Phase 2.1 swaps these for the real
// /me/properties/{pid}/assemblies fetch via EtvService; the view
// layer stays untouched.

import Foundation

enum DemoAssemblies {
    /// Returns demo data for the given Liegenschaft id. Same set for
    /// any property — the iOS scaffold has only two demo properties
    /// and seeding both with the same agendas keeps the demo
    /// recognisable when switching between them.
    static func sample(for propertyId: String) -> [Assembly] {
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

        let past = Assembly(
            id: "demo-assembly-past-\(propertyId)",
            property_id: propertyId,
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
                    discussion: []
                ),
                AgendaItem(
                    id: "demo-it-2",
                    position: 2,
                    type: .beschluss,
                    title: "Beschluss über die Jahresabrechnung 2024",
                    body:
                        "Vorstellung der Abrechnung durch den Verwalter, "
                        + "Stellungnahme des Beirats.",
                    beschluss_text:
                        "Die Eigentümergemeinschaft beschließt die Jahresabrechnung "
                        + "2024 in der vorgelegten Fassung und erteilt der "
                        + "Verwaltung Entlastung.",
                    vote_yes: 13, vote_no: 0, vote_abstain: 1,
                    vote_required_quorum: nil,
                    vote_result: .angenommen,
                    discussion: [
                        DiscussionEntry(
                            id: "demo-d-2-1",
                            position: 1,
                            speaker_label: "Herr Müller (WE 4)",
                            content:
                                "Bitte um Erläuterung der Position "
                                + "\"Außenanlagen\" — Steigerung um 38% "
                                + "gegenüber Vorjahr."
                        ),
                        DiscussionEntry(
                            id: "demo-d-2-2",
                            position: 2,
                            speaker_label: "Frau Wagner (Verwaltung)",
                            content:
                                "Erhöhung erklärt sich durch zwei "
                                + "Sondermaßnahmen: Heckenschnitt nach "
                                + "Sturmschaden im April und Erneuerung der "
                                + "Pflasterung am Eingangsbereich."
                        ),
                    ]
                ),
                AgendaItem(
                    id: "demo-it-3",
                    position: 3,
                    type: .beschluss,
                    title: "Beschluss über die Sanierung der Dachfläche",
                    body:
                        "Drei Angebote liegen vor; Empfehlung der Verwaltung: "
                        + "Anbieter B (Dachdeckerei Schwarz, 47.200 €).",
                    beschluss_text:
                        "Die Eigentümergemeinschaft beschließt die Sanierung "
                        + "der Dachfläche zum Festpreis von 47.200 € durch die "
                        + "Firma Schwarz Dachdeckerei GmbH. Finanzierung "
                        + "anteilig nach MEA aus der Instandhaltungsrücklage.",
                    vote_yes: 10, vote_no: 3, vote_abstain: 1,
                    vote_required_quorum: 10,
                    vote_result: .angenommen,
                    discussion: [
                        DiscussionEntry(
                            id: "demo-d-3-1",
                            position: 1,
                            speaker_label: "Herr Schmidt (WE 7, Beirat)",
                            content:
                                "Empfehlung Beirat: Anbieter B. Solide "
                                + "Referenzen, fairer Preis, Garantie 15 Jahre."
                        ),
                    ]
                ),
                AgendaItem(
                    id: "demo-it-4",
                    position: 4,
                    type: .diskussion,
                    title: "Verschiedenes",
                    body:
                        "Offene Punkte aus dem Eigentümerkreis ohne "
                        + "Beschlusscharakter.",
                    beschluss_text: nil,
                    vote_yes: 0, vote_no: 0, vote_abstain: 0,
                    vote_required_quorum: nil,
                    vote_result: nil,
                    discussion: [
                        DiscussionEntry(
                            id: "demo-d-4-1",
                            position: 1,
                            speaker_label: "Frau Schneider (WE 12)",
                            content:
                                "Lärm durch Wäschetrockner in WE 10 spät "
                                + "abends — Bitte um Klärung."
                        ),
                        DiscussionEntry(
                            id: "demo-d-4-2",
                            position: 2,
                            speaker_label: "Verwaltung",
                            content:
                                "Wird im Nachgang separat mit beiden "
                                + "Parteien geklärt."
                        ),
                    ]
                ),
            ]
        )

        let planned = Assembly(
            id: "demo-assembly-planned-\(propertyId)",
            property_id: propertyId,
            title: "Außerordentliche Eigentümerversammlung 2026",
            description:
                "Außerordentliche Versammlung zur Klärung der "
                + "Sanierung Tiefgaragenrampe.",
            status: .geplant,
            scheduled_start: plannedStartFixed,
            scheduled_end: plannedEndFixed,
            actual_start: nil,
            actual_end: nil,
            location: "Online (Zoom) — Link per E-Mail eine Woche vor Termin",
            agenda_pdf_url: nil,
            protocol_pdf_url: nil,
            protocol_uploaded_at: nil,
            agenda_items: [
                AgendaItem(
                    id: "demo-pl-1",
                    position: 1,
                    type: .information,
                    title: "Begrüßung und Tagesordnung",
                    body: "Vorstellung der Tagesordnung; Feststellung der Beschlussfähigkeit.",
                    beschluss_text: nil,
                    vote_yes: 0, vote_no: 0, vote_abstain: 0,
                    vote_required_quorum: nil,
                    vote_result: nil,
                    discussion: []
                ),
                AgendaItem(
                    id: "demo-pl-2",
                    position: 2,
                    type: .beschluss,
                    title: "Sanierung Tiefgaragenrampe",
                    body:
                        "Sachstand: erhebliche Risse + Wassereintritt. "
                        + "Gutachten Tiefgaragen-Sanierungs GmbH liegt vor.",
                    beschluss_text:
                        "Die Eigentümergemeinschaft beschließt die Sanierung "
                        + "der Tiefgaragenrampe gemäß Gutachten vom "
                        + "März 2026 zum geprüften Preis von 28.500 €. "
                        + "Finanzierung aus der Instandhaltungsrücklage; "
                        + "Sonderumlage bei Bedarf nach MEA.",
                    vote_yes: 0, vote_no: 0, vote_abstain: 0,
                    vote_required_quorum: 10,
                    vote_result: nil,
                    discussion: []
                ),
                AgendaItem(
                    id: "demo-pl-3",
                    position: 3,
                    type: .diskussion,
                    title: "Verschiedenes",
                    body: "Offene Punkte.",
                    beschluss_text: nil,
                    vote_yes: 0, vote_no: 0, vote_abstain: 0,
                    vote_required_quorum: nil,
                    vote_result: nil,
                    discussion: []
                ),
            ]
        )

        return [planned, past]
    }
}
