// Demo Beschlüsse — two Umlaufbeschlüsse (one offen, one angenommen) so the
// Beschlüsse segment of the ETV tab is populated in Demo-Modus and App-Review.
// Served by DemoStore; property_id is stamped with the active demo property so
// the rows always show under whatever Liegenschaft is selected.

import Foundation

enum DemoResolutions {
    static func summaries(propertyId: String) -> [ResolutionSummary] {
        details(propertyId: propertyId).map {
            ResolutionSummary(
                id: $0.id, property_id: $0.property_id, title: $0.title, mode: $0.mode,
                status: $0.status, opens_at: $0.opens_at, closes_at: $0.closes_at,
                required_quorum: $0.required_quorum, decided_at: $0.decided_at,
                created_at: $0.created_at
            )
        }
    }

    static func detail(id: String) -> ResolutionDetail? {
        details(propertyId: "demo").first { $0.id == id }
    }

    private static func details(propertyId: String) -> [ResolutionDetail] {
        let now = Date()
        let day: TimeInterval = 86_400
        return [
            ResolutionDetail(
                id: "demo-res-1", property_id: propertyId,
                title: "Umlaufbeschluss: Treppenhausreinigung neu vergeben",
                mode: .mehrheits, status: .offen,
                opens_at: now.addingTimeInterval(-3 * day),
                closes_at: now.addingTimeInterval(7 * day),
                required_quorum: 5, decided_at: nil, created_at: now.addingTimeInterval(-3 * day),
                description: "Die Reinigung des Treppenhauses soll ab dem nächsten Quartal an die "
                    + "Firma Glanz & Co. vergeben werden. Die Kosten betragen 180 € pro Monat.",
                pdf_url: nil, result_pdf_url: nil, result: nil,
                tally: ResolutionTally(
                    eligible_voters: 8, cast: 3, ja: 2, nein: 1, enthaltung: 0,
                    quorum_met: false, unanimous_yes: false
                ),
                my_vote: nil, am_eligible: true
            ),
            ResolutionDetail(
                id: "demo-res-2", property_id: propertyId,
                title: "Umlaufbeschluss: Anschaffung neuer Fahrradständer",
                mode: .mehrheits, status: .angenommen,
                opens_at: now.addingTimeInterval(-40 * day),
                closes_at: now.addingTimeInterval(-26 * day),
                required_quorum: 5, decided_at: now.addingTimeInterval(-25 * day),
                created_at: now.addingTimeInterval(-40 * day),
                description: "Im Innenhof werden zwei überdachte Fahrradständer für insgesamt "
                    + "1.450 € aus der Instandhaltungsrücklage angeschafft.",
                pdf_url: nil, result_pdf_url: nil,
                result: "Angenommen mit 6 Ja-Stimmen bei 8 stimmberechtigten Eigentümern.",
                tally: ResolutionTally(
                    eligible_voters: 8, cast: 7, ja: 6, nein: 1, enthaltung: 0,
                    quorum_met: true, unanimous_yes: false
                ),
                my_vote: ResolutionVote(choice: .ja, voted_at: now.addingTimeInterval(-30 * day)),
                am_eligible: true
            ),
        ]
    }
}
