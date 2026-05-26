// §8.3 Property detail. Address card + Verwaltung-Kontakt +
// Einheiten + Quick Actions. Reached by tapping the active
// Liegenschaft row in Einstellungen.
//
// The screen is read-only — mutations (creating tickets, switching
// property) are quick-action shortcuts that route through the
// existing tab + sheet infrastructure rather than reimplementing
// flows here.

import SwiftUI

@MainActor
final class PropertyDetailStore: ObservableObject {
    @Published private(set) var detail: PropertyDetailResponse?
    @Published private(set) var isLoading = false
    @Published var lastError: String?

    var onUnauthorized: (() -> Void)?
    private let api: APIClient

    init(api: APIClient = APIClient()) {
        self.api = api
    }

    func load(id: String) async {
        isLoading = true
        defer { isLoading = false }
        do {
            self.detail = try await api.getMyPropertyDetail(id: id)
        } catch APIError.unauthorized {
            onUnauthorized?()
        } catch let error as APIError {
            self.lastError = error.errorDescription
        } catch {
            self.lastError = error.localizedDescription
        }
    }
}

struct PropertyDetailView: View {
    let property: Liegenschaft

    @StateObject private var store = PropertyDetailStore()
    @EnvironmentObject var authStore: AuthStore
    @EnvironmentObject var liegenschaftStore: LiegenschaftStore
    @EnvironmentObject var deepLinkRouter: DeepLinkRouter

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                headerCard
                if !quickActions.isEmpty {
                    quickActionsSection
                }
                kontaktSection
                if let units = store.detail?.units, !units.isEmpty {
                    einheitenSection(units: units)
                }
                wechselnSection
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 16)
        }
        .navigationTitle("Liegenschaft")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            store.onUnauthorized = { [weak authStore] in
                authStore?.signOut()
            }
        }
        .task(id: property.id) {
            await store.load(id: property.id)
        }
        .refreshable { await store.load(id: property.id) }
    }

    // MARK: - Header card

    private var headerCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Text(property.type ?? "Liegenschaft")
                    .font(.caption.weight(.semibold))
                    .padding(.horizontal, 10)
                    .padding(.vertical, 4)
                    .background(Color.accentColor)
                    .foregroundStyle(.white)
                    .clipShape(Capsule())
                if store.isLoading {
                    ProgressView().controlSize(.small)
                }
            }
            Text(property.name)
                .font(.title3.bold())
            Label(property.address, systemImage: "mappin.and.ellipse")
                .font(.subheadline)
                .foregroundStyle(.secondary)
            if let hrId = store.detail?.property_hr_id, !hrId.isEmpty {
                Label(hrId, systemImage: "number")
                    .font(.caption)
                    .foregroundStyle(.tertiary)
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 12)
                .fill(Color(.secondarySystemBackground))
        )
    }

    // MARK: - Quick actions

    /// Returns the actions that make sense for the active property —
    /// jumps to existing tabs rather than reimplementing flows.
    private var quickActions: [QuickAction] {
        [
            QuickAction(
                title: "Neues Ticket",
                systemImage: "plus.bubble",
                color: .orange,
                url: URL(string: "whv://new-ticket")!
            ),
            QuickAction(
                title: "ETV ansehen",
                systemImage: "person.3.fill",
                color: .accentColor,
                url: URL(string: "whv://etv")!
            ),
            QuickAction(
                title: "Mitteilungen",
                systemImage: "megaphone.fill",
                color: .green,
                url: URL(string: "whv://mitteilungen")!
            ),
        ]
    }

    private var quickActionsSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Schnellzugriff")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(.secondary)
                .textCase(.uppercase)
            VStack(spacing: 8) {
                ForEach(quickActions) { action in
                    Button {
                        deepLinkRouter.handle(action.url)
                    } label: {
                        HStack(spacing: 12) {
                            Image(systemName: action.systemImage)
                                .font(.title3)
                                .foregroundStyle(.white)
                                .frame(width: 36, height: 36)
                                .background(action.color)
                                .clipShape(RoundedRectangle(cornerRadius: 8))
                            Text(action.title)
                                .font(.subheadline.weight(.semibold))
                                .foregroundStyle(.primary)
                            Spacer()
                            Image(systemName: "chevron.right")
                                .font(.caption.weight(.bold))
                                .foregroundStyle(.tertiary)
                        }
                        .padding(12)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(
                            RoundedRectangle(cornerRadius: 10)
                                .fill(Color(.secondarySystemBackground))
                        )
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }

    // MARK: - Verwaltung contact

    private var kontaktSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Verwaltung")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(.secondary)
                .textCase(.uppercase)
            Link(destination: WHVContact.telURL) {
                HStack(spacing: 12) {
                    Image(systemName: "phone.fill")
                        .font(.title3)
                        .foregroundStyle(.white)
                        .frame(width: 36, height: 36)
                        .background(Color.blue)
                        .clipShape(RoundedRectangle(cornerRadius: 8))
                    VStack(alignment: .leading, spacing: 2) {
                        Text(WHVContact.displayName)
                            .font(.subheadline.weight(.semibold))
                            .foregroundStyle(.primary)
                        Text("Wagner Hausverwaltung")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    Image(systemName: "chevron.right")
                        .font(.caption.weight(.bold))
                        .foregroundStyle(.tertiary)
                }
                .padding(12)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(
                    RoundedRectangle(cornerRadius: 10)
                        .fill(Color(.secondarySystemBackground))
                )
            }
            .buttonStyle(.plain)
        }
    }

    // MARK: - Einheiten

    private func einheitenSection(units: [UnitResponse]) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .lastTextBaseline) {
                Text("Einheiten")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(.secondary)
                    .textCase(.uppercase)
                Spacer()
                Text("\(units.count)")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.tertiary)
            }
            VStack(spacing: 0) {
                ForEach(units) { unit in
                    UnitRow(unit: unit)
                    if unit.id != units.last?.id {
                        Divider().padding(.leading, 56)
                    }
                }
            }
            .background(
                RoundedRectangle(cornerRadius: 10)
                    .fill(Color(.secondarySystemBackground))
            )
        }
    }

    // MARK: - Wechseln

    private var wechselnSection: some View {
        Button(role: .destructive) {
            liegenschaftStore.clear()
        } label: {
            Label("Liegenschaft wechseln", systemImage: "arrow.left.arrow.right")
                .font(.subheadline.weight(.semibold))
                .frame(maxWidth: .infinity)
                .padding(.vertical, 12)
        }
        .buttonStyle(.bordered)
    }
}

private struct QuickAction: Identifiable {
    let id = UUID()
    let title: LocalizedStringResource
    let systemImage: String
    let color: Color
    let url: URL
}

private struct UnitRow: View {
    let unit: UnitResponse

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: iconName)
                .font(.body)
                .foregroundStyle(.tint)
                .frame(width: 32, height: 32)
                .background(Color.accentColor.opacity(0.15))
                .clipShape(RoundedRectangle(cornerRadius: 6))
            VStack(alignment: .leading, spacing: 6) {
                // Heading: HR-ID first, fallback to type.
                Text(unit.unit_hr_id ?? unit.type)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(.primary)

                // Master-table metrics. Each shows only when the
                // backend actually populated it so empty stub
                // properties don't drown the row in dashes.
                HStack(spacing: 10) {
                    if let area = unit.area_m2 {
                        metric(label: "Fläche",
                               value: area.formatted(.number.precision(.fractionLength(0...1))) + " m²")
                    }
                    if let mea = unit.voting_share {
                        // MEA / Miteigentumsanteile — typically a
                        // fraction-of-1000 or fraction-of-10000.
                        // Render with 0-4 fractional digits so 5,4321
                        // shows but 100 doesn't grow a useless ".00".
                        metric(label: "MEA",
                               value: mea.formatted(.number.precision(.fractionLength(0...4))))
                    }
                    if let rooms = unit.rooms {
                        metric(label: "Zimmer",
                               value: rooms.formatted(.number.precision(.fractionLength(0...1))))
                    }
                }

                // Secondary: floor + position. The kind of thing
                // you'd skim if you don't recognise the HR-ID.
                if hasGeo {
                    HStack(spacing: 6) {
                        if let floor = unit.floor, !floor.isEmpty {
                            Text(floor)
                        }
                        if let pos = unit.position, !pos.isEmpty {
                            Text("·").foregroundStyle(.tertiary)
                            Text(pos)
                        }
                    }
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
                }

                // Role-tagged contracts (one chip per Eigentümer /
                // Mieter / Objekteigentümer currently on the unit).
                // Backend renders contact_label, we just chip it.
                if !unit.current_contracts.isEmpty {
                    VStack(alignment: .leading, spacing: 4) {
                        ForEach(unit.current_contracts) { c in
                            ContractChip(contract: c)
                        }
                    }
                    .padding(.top, 2)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
    }

    private var hasGeo: Bool {
        let f = unit.floor?.isEmpty == false
        let p = unit.position?.isEmpty == false
        return f || p
    }

    private func metric(label: LocalizedStringResource, value: String) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(label)
                .font(.caption2)
                .foregroundStyle(.tertiary)
                .textCase(.uppercase)
            Text(value)
                .font(.caption.weight(.semibold))
                .foregroundStyle(.primary)
        }
    }

    private var iconName: String {
        switch unit.type.uppercased() {
        case "GARAGE", "STELLPLATZ": return "car.fill"
        case "KELLER": return "tray.fill"
        case "GEWERBE": return "briefcase.fill"
        default: return "house.fill"
        }
    }
}

/// One contract chip — role-tinted (green = Eigentümer, accent =
/// Mieter, orange = Objekteigentümer) with the rendered contact
/// label to the right.
private struct ContractChip: View {
    let contract: UnitContractSummary

    var body: some View {
        HStack(spacing: 6) {
            Text(contract.typeLabel)
                .font(.caption2.weight(.semibold))
                .padding(.horizontal, 6)
                .padding(.vertical, 2)
                .background(chipColor.opacity(0.18))
                .foregroundStyle(chipColor)
                .clipShape(Capsule())
            Text(contract.contact_label ?? "—")
                .font(.caption)
                .foregroundStyle(.primary)
                .lineLimit(1)
        }
    }

    private var chipColor: Color {
        switch contract.type {
        case "OWNER": return .green
        case "TENANT": return .accentColor
        case "PROPERTY_OWNER": return .orange
        default: return .secondary
        }
    }
}
