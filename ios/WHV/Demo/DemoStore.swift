// Demo mode lifecycle. Singleton consulted by APIClient + the
// LoginView entry button. When `isActive == true`, APIClient's
// authed* helpers short-circuit to seed data and return without
// touching the network.
//
// Why singleton vs. env injection: APIClient is a value type that
// every Store re-instantiates by default. Threading an instance
// through would mean changing every Store and View; the singleton
// keeps the demo gate a 2-line check inside each APIClient method.
// The trade-off is acknowledged tight coupling between APIClient
// and DemoStore.shared, which is fine because demo mode is an
// app-level feature, not a unit-test concern.

import Foundation

@MainActor
final class DemoStore: ObservableObject {
    static let shared = DemoStore()

    @Published private(set) var isActive: Bool = false

    /// The fake user that AuthStore presents while demo is active.
    /// Role "beirat" gives the broadest read scope so every visible
    /// surface (ETV, Tickets, Mitteilungen) is populated.
    let demoUser = UserResponse(
        id: "00000000-demo-demo-demo-000000000001",
        email: "demo@example.com",
        role: "beirat",
        organization_id: "00000000-demo-org-demo-000000000001",
        contact_id_impower: nil,
        avatar_url: nil
    )

    private(set) var seed: DemoSeed?

    private init() {}

    func activate() {
        seed = DemoSeed.build()
        DemoFlag.isActive = true
        isActive = true
    }

    func deactivate() {
        seed = nil
        DemoFlag.isActive = false
        isActive = false
    }

    // MARK: - Data accessors used by APIClient short-circuits

    var properties: [PropertyResponse] {
        seed?.properties ?? []
    }

    func assemblies(for propertyId: String) -> [AssemblySummary] {
        seed?.assemblies.filter { $0.property_id == propertyId } ?? []
    }

    func assemblyDetail(id: String) -> Assembly? {
        seed?.assemblyDetails.first { $0.id == id }
    }

    func resolutions(for propertyId: String) -> [ResolutionSummary] {
        DemoResolutions.summaries(propertyId: propertyId)
    }

    func resolutionDetail(id: String) -> ResolutionDetail? {
        DemoResolutions.detail(id: id)
    }

    func comments(for assemblyId: String) -> [AssemblyComment] {
        seed?.comments[assemblyId] ?? []
    }

    func announcements(for propertyId: String) -> [AnnouncementSummary] {
        seed?.announcements.filter { $0.property_id == propertyId } ?? []
    }

    func announcementDetail(id: String) -> AnnouncementDetail? {
        seed?.announcementDetails.first { $0.id == id }
    }

    var tickets: [TicketSummary] {
        seed?.tickets ?? []
    }

    func openTickets() -> [TicketSummary] {
        tickets.filter { $0.status == .offen || $0.status == .neu }
    }

    func ticketDetail(id: String) -> TicketDetail? {
        seed?.ticketDetails.first { $0.id == id }
    }

    func units(for propertyId: String) -> [UnitResponse] {
        seed?.units[propertyId] ?? []
    }

    func vendors(for propertyId: String) -> [VendorSummary] {
        seed?.vendors[propertyId] ?? []
    }
}

/// Synchronous mirror of DemoStore.shared.isActive for APIClient,
/// which runs off the main actor and can't easily await the
/// @MainActor singleton. Updated by DemoStore.activate/deactivate
/// at the same instant so the two never disagree past one tick.
enum DemoFlag {
    nonisolated(unsafe) static var isActive: Bool = false
}
