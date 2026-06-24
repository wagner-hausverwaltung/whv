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
    @Published private(set) var vendors: [VendorSummary] = []
    @Published private(set) var account: HausgeldAccount?
    @Published private(set) var rentSettlements: [RentSettlement] = []
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
            // Fetch detail + vendors in parallel — they share the
            // same scope check, so a failure in one doesn't tell us
            // anything about the other; we just want the screen up
            // fast.
            async let detailTask = api.getMyPropertyDetail(id: id)
            async let vendorsTask = api.getMyPropertyVendors(propertyId: id)
            async let accountTask = api.getMyAccount(propertyId: id)
            async let rentTask = api.getMyRentSettlements(propertyId: id)
            self.detail = try await detailTask
            // A vendor-list failure shouldn't blank the property
            // detail. Swallow + log into lastError only if the detail
            // also fails; otherwise it's a non-fatal section error.
            do {
                self.vendors = try await vendorsTask
            } catch {
                self.vendors = []
            }
            // Hausgeldkonto is owner-only + demo-unavailable; a 404 /
            // demo / transient error just hides the section.
            do {
                self.account = try await accountTask
            } catch {
                self.account = nil
            }
            // Mietabrechnung (MV-owner only); empty otherwise.
            do {
                self.rentSettlements = try await rentTask
            } catch {
                self.rentSettlements = []
            }
        } catch APIError.unauthorized {
            onUnauthorized?()
        } catch let error as APIError {
            self.lastError = error.errorDescription
        } catch {
            self.lastError = error.localizedDescription
        }
    }
}

/// Target for the contact-detail sheet — set by tapping a contract
/// chip, cleared by the sheet's Fertig button. Identifiable so
/// `.sheet(item:)` can drive presentation.
struct ContactSheetTarget: Identifiable, Hashable {
    let contractId: String
    let contactId: String
    let fallbackLabel: String
    let contractType: String
    var id: String { contractId + ":" + contactId }
}

/// Target for the per-invoice detail sheet — set by tapping a
/// row inside a vendor's DisclosureGroup. Carries enough fallback
/// metadata that the sheet can render its header while the fetch
/// is in flight.
struct InvoiceSheetTarget: Identifiable, Hashable {
    let vendorName: String
    let invoice: VendorInvoiceSummary
    var id: String { invoice.id }
}

struct PropertyDetailView: View {
    let property: Liegenschaft

    @StateObject private var store = PropertyDetailStore()
    @EnvironmentObject var authStore: AuthStore
    @EnvironmentObject var liegenschaftStore: LiegenschaftStore
    /// Sheet binding. nil = closed.
    @State private var contactSheetTarget: ContactSheetTarget?
    @State private var invoiceSheetTarget: InvoiceSheetTarget?
    @State private var showDocuments = false
    @State private var showMeters = false

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    headerCard
                    quickActionsSection(scroll: proxy)
                    if let units = store.detail?.units, !units.isEmpty {
                        einheitenSection(units: units)
                    }
                    if let account = store.account, account.account_id != nil {
                        hausgeldkontoSection(account: account)
                    }
                    if !store.rentSettlements.isEmpty {
                        mietabrechnungSection(settlements: store.rentSettlements)
                    }
                    if !store.vendors.isEmpty {
                        dienstleisterSection(vendors: store.vendors)
                            .id("dienstleister")
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
            .sheet(item: $contactSheetTarget) { target in
                ContactDetailSheet(
                    contractId: target.contractId,
                    contactId: target.contactId,
                    fallbackLabel: target.fallbackLabel,
                    contractType: target.contractType
                )
                .environmentObject(authStore)
            }
            .sheet(item: $invoiceSheetTarget) { target in
                InvoiceDetailSheet(
                    propertyId: property.id,
                    vendorName: target.vendorName,
                    invoice: target.invoice
                )
                .environmentObject(authStore)
            }
            .sheet(isPresented: $showDocuments) {
                DocumentsView(propertyId: property.id)
            }
            .sheet(isPresented: $showMeters) {
                MetersView(propertyId: property.id)
            }
        }
    }

    // MARK: - Header card

    private var headerCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                // Show the German-correspondence label (WEG / MV /
                // SEV) rather than Impower's raw OWNER/RENTAL/STRATA
                // enum — owners speak the German short forms; the
                // enum values are jargon-leakage.
                Text(property.typeLabel)
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

    private func quickActionsSection(scroll: ScrollViewProxy) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Schnellzugriff")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(.secondary)
                .textCase(.uppercase)
            VStack(spacing: 8) {
                // Documents — the iOS counterpart of the portal Dokumente tab.
                Button {
                    showDocuments = true
                } label: {
                    quickRow(title: "Dokumente", systemImage: "folder.fill", color: .blue)
                }
                .buttonStyle(.plain)
                // Zähler — meter list + reading capture (ADR-0016).
                Button {
                    showMeters = true
                } label: {
                    quickRow(title: "Zähler", systemImage: "gauge.medium", color: .teal)
                }
                .buttonStyle(.plain)
                // Jump to the Dienstleister section below (only when present).
                if !store.vendors.isEmpty {
                    Button {
                        withAnimation { scroll.scrollTo("dienstleister", anchor: .top) }
                    } label: {
                        quickRow(
                            title: "Dienstleister",
                            systemImage: "wrench.and.screwdriver.fill",
                            color: .gray
                        )
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }

    private func quickRow(title: LocalizedStringResource, systemImage: String, color: Color)
        -> some View
    {
        HStack(spacing: 12) {
            Image(systemName: systemImage)
                .font(.title3)
                .foregroundStyle(.white)
                .frame(width: 36, height: 36)
                .background(color)
                .clipShape(RoundedRectangle(cornerRadius: 8))
            Text(title)
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
                    // hasOwnershipShares gates the MEA metric — on MV
                    // (Mietverwaltung) rentals there's no Anteil, so
                    // suppressing the metric entirely is the honest
                    // render. WEG and SEV keep it.
                    UnitRow(
                        unit: unit,
                        showMea: property.hasOwnershipShares,
                        onContactTap: { target in
                            contactSheetTarget = target
                        }
                    )
                    if unit.id != units.last?.id {
                        Divider().padding(.leading, 48)
                    }
                }
            }
            .background(
                RoundedRectangle(cornerRadius: 10)
                    .fill(Color(.secondarySystemBackground))
            )
        }
    }

    // MARK: - Dienstleister

    /// Per-vendor cards aggregating every invoice on the property,
    /// keyed by contact_id. The actionable bits — name + phone +
    /// email + "letzte Tätigkeit am …" — let owners call back the
    /// firm that fixed their last problem without paging the
    /// Verwalter. Backend assembles the aggregate; we just render.
    private func dienstleisterSection(vendors: [VendorSummary]) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .lastTextBaseline) {
                Text("Dienstleister")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(.secondary)
                    .textCase(.uppercase)
                Spacer()
                Text("\(vendors.count)")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.tertiary)
            }
            VStack(spacing: 0) {
                ForEach(vendors) { vendor in
                    VendorRow(
                        vendor: vendor,
                        onInvoiceTap: { invoice in
                            invoiceSheetTarget = InvoiceSheetTarget(
                                vendorName: vendor.name,
                                invoice: invoice
                            )
                        }
                    )
                    if vendor.contact_id != vendors.last?.contact_id {
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

    // MARK: - Hausgeldkonto

    /// The owner's own account balance + recent bookings, pulled live
    /// from Impower. Balance shown neutrally as "Saldo" (no
    /// Guthaben/Forderung claim until the sign is confirmed). Capped to
    /// the most recent bookings inline; the full history lives in the
    /// portal.
    private func hausgeldkontoSection(account: HausgeldAccount) -> some View {
        let shown = Array(account.bookings.prefix(12))
        return VStack(alignment: .leading, spacing: 8) {
            Text("Hausgeldkonto")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(.secondary)
                .textCase(.uppercase)

            VStack(alignment: .leading, spacing: 4) {
                Text("Saldo")
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(.tertiary)
                    .textCase(.uppercase)
                Text(formatEuro(account.balance))
                    .font(.title2.bold())
                if let label = account.name ?? account.account_hr_id {
                    Text(label).font(.caption).foregroundStyle(.secondary)
                }
                Text("Live aus Impower, ohne Gewähr.")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: 10).fill(Color(.secondarySystemBackground))
            )

            if !shown.isEmpty {
                VStack(spacing: 0) {
                    ForEach(Array(shown.enumerated()), id: \.offset) { idx, booking in
                        HStack(alignment: .top, spacing: 10) {
                            Text(formatBookingDate(booking.post_date))
                                .font(.caption2)
                                .foregroundStyle(.tertiary)
                                .frame(width: 60, alignment: .leading)
                            Text(booking.booking_text ?? "—")
                                .font(.caption)
                                .foregroundStyle(.primary)
                                .frame(maxWidth: .infinity, alignment: .leading)
                            Text(formatEuro(booking.amount))
                                .font(.caption.weight(.medium))
                                .foregroundStyle(.secondary)
                                .monospacedDigit()
                        }
                        .padding(.horizontal, 12)
                        .padding(.vertical, 8)
                        if idx != shown.count - 1 {
                            Divider().padding(.leading, 12)
                        }
                    }
                    if account.bookings.count > shown.count {
                        Text("+ \(account.bookings.count - shown.count) weitere Buchungen")
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.horizontal, 12)
                            .padding(.vertical, 8)
                    }
                }
                .background(
                    RoundedRectangle(cornerRadius: 10).fill(Color(.secondarySystemBackground))
                )
            }
        }
    }

    // MARK: - Mietabrechnung (MV owner)

    /// MV-property owner payout statements per period. Shown only when
    /// Impower returns settlements (i.e. a rented-out object the caller
    /// owns). Amounts neutral.
    private func mietabrechnungSection(settlements: [RentSettlement]) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Mietabrechnung")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(.secondary)
                .textCase(.uppercase)
            VStack(spacing: 0) {
                ForEach(Array(settlements.prefix(12).enumerated()), id: \.offset) { idx, s in
                    VStack(alignment: .leading, spacing: 2) {
                        HStack {
                            Text("\(formatBookingDate(s.period_from)) – \(formatBookingDate(s.period_until))")
                                .font(.caption.weight(.semibold))
                                .foregroundStyle(.primary)
                            Spacer()
                            Text(formatEuro(s.payout))
                                .font(.caption.weight(.bold))
                                .foregroundStyle(.primary)
                                .monospacedDigit()
                        }
                        Text("Mieteinnahmen \(formatEuro(s.rent_income))")
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                    }
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)
                    if idx != min(settlements.count, 12) - 1 {
                        Divider().padding(.leading, 12)
                    }
                }
            }
            .background(
                RoundedRectangle(cornerRadius: 10).fill(Color(.secondarySystemBackground))
            )
            Text("Auszahlung = Betrag an Sie als Eigentümer. Ohne Gewähr.")
                .font(.caption2)
                .foregroundStyle(.tertiary)
        }
    }

    private func formatEuro(_ value: Double?) -> String {
        guard let value else { return "—" }
        let f = NumberFormatter()
        f.numberStyle = .currency
        f.currencyCode = "EUR"
        f.locale = Locale(identifier: "de_DE")
        return f.string(from: NSNumber(value: value)) ?? String(format: "%.2f €", value)
    }

    private func formatBookingDate(_ iso: String?) -> String {
        guard let iso else { return "" }
        let parts = iso.split(separator: "-")
        guard parts.count >= 3 else { return iso }
        let day = parts[2].prefix(2)
        return "\(day).\(parts[1]).\(parts[0])"
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

private struct UnitRow: View {
    let unit: UnitResponse
    /// Property-level gate from the parent: WEG / SEV → true; MV →
    /// false. When false the MEA metric is suppressed entirely.
    let showMea: Bool
    /// Closure invoked when a contract chip is tapped. PropertyDetailView
    /// flips this into a sheet binding to present ContactDetailSheet.
    let onContactTap: (ContactSheetTarget) -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: iconName)
                .font(.caption)
                .foregroundStyle(.tint)
                .frame(width: 26, height: 26)
                .background(Color.accentColor.opacity(0.15))
                .clipShape(RoundedRectangle(cornerRadius: 6))
            VStack(alignment: .leading, spacing: 3) {
                // Heading + location on one line (HR-ID, then floor / position).
                HStack(spacing: 6) {
                    Text(unit.unit_hr_id ?? unit.type)
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(.primary)
                    if !geoText.isEmpty {
                        Text(geoText)
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                    Spacer(minLength: 0)
                }

                // Master-table metrics. Each shows only when the
                // backend actually populated it so empty stub
                // properties don't drown the row in dashes. MEA is
                // further gated by property administration type —
                // hidden entirely on MV (no Anteil concept).
                HStack(spacing: 10) {
                    if let area = unit.area_m2 {
                        metric(label: "Fläche",
                               value: area.formatted(.number.precision(.fractionLength(0...1))) + " m²")
                    }
                    if let heated = unit.heated_area_m2 {
                        metric(label: "Heizfl.",
                               value: heated.formatted(.number.precision(.fractionLength(0...1))) + " m²")
                    }
                    if let persons = unit.persons {
                        // Personen — typically integer-ish; render
                        // 0–1 fractional digits so "2,5" still works
                        // for shared apartments while plain "2" stays
                        // tidy.
                        metric(label: "Personen",
                               value: persons.formatted(.number.precision(.fractionLength(0...1))))
                    }
                    if showMea, let mea = unit.voting_share {
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

                // Role-tagged contracts (one chip per Eigentümer /
                // Mieter / Objekteigentümer currently on the unit).
                // Backend renders contact_label, we just chip it.
                // Each chip is a Button — tapping opens the full
                // contact card via the parent's sheet binding.
                if !unit.current_contracts.isEmpty {
                    VStack(alignment: .leading, spacing: 2) {
                        ForEach(unit.current_contracts) { c in
                            // Rows without a contact_id (rare data-
                            // hygiene case) can't open the sheet —
                            // they'd 404 on the backend. Render as
                            // non-tappable text in that case.
                            if let contactId = c.contact_id {
                                Button {
                                    onContactTap(
                                        ContactSheetTarget(
                                            contractId: c.contract_id,
                                            contactId: contactId,
                                            fallbackLabel: c.contact_label ?? "—",
                                            contractType: c.type
                                        )
                                    )
                                } label: {
                                    ContractChip(contract: c)
                                }
                                .buttonStyle(.plain)
                            } else {
                                ContractChip(contract: c)
                            }
                        }
                    }
                }
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 7)
    }

    /// Location label shown next to the unit number. Position ("EG" / "1. OG"
    /// / "DG") reads best; fall back to the raw floor when there's no position.
    /// Showing both alongside the unit number just produced "1 · 1 · EG".
    private var geoText: String {
        if let p = unit.position, !p.isEmpty { return p }
        if let f = unit.floor, !f.isEmpty { return f }
        return ""
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

/// One row in the Dienstleister section. Header (icon + name +
/// last-service date), tap-to-call / tap-to-email if we have those,
/// then a compact recent-invoices list. Owners use this to answer
/// "who fixed the boiler last time?" — same shape as the portal's
/// VendorCard.
/// One vendor row in the Dienstleister section — DisclosureGroup
/// collapsed by default. Header (always visible) carries the
/// summary chips; expanded body shows tap-to-call/mail + the
/// recent-invoices list, each row a button that opens
/// InvoiceDetailSheet via the parent's sheet binding.
private struct VendorRow: View {
    let vendor: VendorSummary
    let onInvoiceTap: (VendorInvoiceSummary) -> Void

    /// Per-row expand state. SwiftUI's `DisclosureGroup` keeps it
    /// for free if we use the parameterless init, but we want the
    /// chevron animation under our own control so the screen
    /// doesn't reset state when the parent re-fetches vendors.
    @State private var expanded = false

    var body: some View {
        DisclosureGroup(isExpanded: $expanded) {
            VStack(alignment: .leading, spacing: 10) {
                if vendor.phone != nil || vendor.email != nil {
                    contactRow
                }
                if !vendor.recent_invoices.isEmpty {
                    invoicesBlock
                }
            }
            .padding(.top, 6)
        } label: {
            header
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
    }

    private var header: some View {
        // NB: absolute Color.primary/.secondary (not the hierarchical
        // .primary/.tertiary ShapeStyles). DisclosureGroup tints its label
        // with the accent colour, and hierarchical styles resolve *against*
        // that tint — so .tertiary rendered as a near-invisible dim blue in
        // dark mode. Absolute label colours ignore the tint and stay legible.
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: vendor.kind == "COMPANY" ? "briefcase.fill" : "person.fill")
                .font(.body)
                .foregroundStyle(Color.accentColor)
                .frame(width: 32, height: 32)
                .background(Color.accentColor.opacity(0.15))
                .clipShape(RoundedRectangle(cornerRadius: 6))
            VStack(alignment: .leading, spacing: 4) {
                Text(vendor.name)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(Color.primary)
                HStack(spacing: 6) {
                    if let last = vendor.last_service_date,
                       let formatted = formatDate(last)
                    {
                        Text("Zuletzt \(formatted)")
                            .font(.caption2)
                            .foregroundStyle(Color.secondary)
                    }
                    // Split singular/plural into clean localizable keys (the old
                    // inline "Rechnung\(…)" suffix couldn't translate to English).
                    Text(vendor.invoice_count == 1
                        ? "· \(vendor.invoice_count) Rechnung"
                        : "· \(vendor.invoice_count) Rechnungen")
                        .font(.caption2)
                        .foregroundStyle(Color.secondary)
                    if let total = vendor.total_amount {
                        // Backend now reports the CURRENT calendar year's
                        // total only — label it with the year so it's not
                        // mistaken for the all-time figure.
                        Text("· \(formatAmount(total)) € (\(Calendar.current.component(.year, from: Date())))")
                            .font(.caption2)
                            .foregroundStyle(Color.secondary)
                    }
                }
            }
            Spacer(minLength: 0)
        }
    }

    private var contactRow: some View {
        HStack(spacing: 14) {
            if let phone = vendor.phone, !phone.isEmpty,
               let url = URL(string: "tel:\(phone.replacingOccurrences(of: " ", with: ""))")
            {
                Link(destination: url) {
                    Label(phone, systemImage: "phone.fill")
                        .font(.caption.weight(.medium))
                }
                .buttonStyle(.plain)
            }
            if let email = vendor.email, !email.isEmpty,
               let url = URL(string: "mailto:\(email)")
            {
                Link(destination: url) {
                    Label(email, systemImage: "envelope.fill")
                        .font(.caption.weight(.medium))
                        .lineLimit(1)
                }
                .buttonStyle(.plain)
            }
        }
    }

    /// Invoices bucketed by issued-date year, newest year first,
    /// undated last. `recent_invoices` already arrives newest-first, so
    /// order within a year is preserved.
    private var invoicesByYear: [(year: String, items: [VendorInvoiceSummary])] {
        var buckets: [String: [VendorInvoiceSummary]] = [:]
        for inv in vendor.recent_invoices {
            let head = inv.issued_date.map { String($0.prefix(4)) } ?? ""
            let year = (head.count == 4 && Int(head) != nil) ? head : "Ohne Datum"
            buckets[year, default: []].append(inv)
        }
        let years = buckets.keys.sorted { a, b in
            if a == "Ohne Datum" { return false }
            if b == "Ohne Datum" { return true }
            return a > b
        }
        return years.map { (year: $0, items: buckets[$0] ?? []) }
    }

    private var invoicesBlock: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Rechnungen")
                .font(.caption2.weight(.semibold))
                .foregroundStyle(.tertiary)
                .textCase(.uppercase)
            // Grouped by year so old invoices sit under their own
            // heading instead of mixed into one flat list.
            ForEach(invoicesByYear, id: \.year) { group in
                Text(group.year)
                    .font(.caption2.weight(.bold))
                    .foregroundStyle(.secondary)
                    .padding(.top, 2)
                ForEach(group.items) { inv in
                    invoiceRow(inv)
                }
            }
        }
    }

    /// One tappable invoice row — opens InvoiceDetailSheet via the
    /// parent's sheet binding.
    @ViewBuilder
    private func invoiceRow(_ inv: VendorInvoiceSummary) -> some View {
        Button {
            onInvoiceTap(inv)
        } label: {
            HStack(spacing: 6) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(inv.name)
                        .font(.caption.weight(.medium))
                        .foregroundStyle(.primary)
                        .lineLimit(1)
                    if let date = inv.issued_date,
                       let formatted = formatDate(date)
                    {
                        Text(formatted)
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                    }
                }
                Spacer(minLength: 0)
                if let amount = inv.amount {
                    Text(formatAmount(amount) + " €")
                        .font(.caption.weight(.medium))
                        .foregroundStyle(.secondary)
                }
                Image(systemName: "chevron.right")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
            .padding(.vertical, 4)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    private func formatDate(_ iso: String) -> String? {
        let parts = iso.split(separator: "-")
        guard parts.count >= 3 else { return nil }
        return "\(parts[2]).\(parts[1]).\(parts[0])"
    }

    private func formatAmount(_ v: Double) -> String {
        let f = NumberFormatter()
        f.numberStyle = .decimal
        f.minimumFractionDigits = 2
        f.maximumFractionDigits = 2
        f.locale = Locale(identifier: "de_DE")
        return f.string(from: NSNumber(value: v)) ?? String(format: "%.2f", v)
    }
}
