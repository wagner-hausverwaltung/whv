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
    @Published private(set) var meters: [MeterSummary] = []
    @Published private(set) var isLoading = false
    @Published var lastError: String?

    /// Per-category "something new/upcoming" hints for this property —
    /// drive the blue NEU badge on the Versammlungen / Anliegen /
    /// Mitteilungen / Dokumente quick-action rows. All four are computed
    /// from best-effort, silent-fail fetches (see `loadAttentionHints`):
    /// a failure leaves the flag false rather than blocking the Start tab.
    /// Blue NEU = "neu/anstehend"; the meter row's red "N fällig" accent
    /// (overdue) stays separate.
    @Published private(set) var hasNewAssembly = false
    @Published private(set) var hasNewTicket = false
    @Published private(set) var hasNewAnnouncement = false
    @Published private(set) var hasNewDocument = false

    /// Active meters whose reading is due soon — drives the red/orange
    /// accent on the Zähler quick-action row.
    var dueSoonMeterCount: Int {
        meters.filter { $0.isReadingDueSoon }.count
    }

    var onUnauthorized: (() -> Void)?
    private let api: APIClient

    init(api: APIClient = APIClient()) {
        self.api = api
    }

    func load(id: String) async {
        isLoading = true
        defer { isLoading = false }
        // Per-category NEU hints run alongside the section loads as an
        // independent, best-effort job: they must never block the Start
        // tab nor surface an error, so they're fired-and-not-awaited
        // here and self-contained in their own try?-per-call below.
        Task { await self.loadAttentionHints(id: id) }
        do {
            // Fetch detail + vendors in parallel — they share the
            // same scope check, so a failure in one doesn't tell us
            // anything about the other; we just want the screen up
            // fast.
            async let detailTask = api.getMyPropertyDetail(id: id)
            async let vendorsTask = api.getMyPropertyVendors(propertyId: id)
            async let accountTask = api.getMyAccount(propertyId: id)
            async let rentTask = api.getMyRentSettlements(propertyId: id)
            async let metersTask = api.listMeters(propertyId: id)
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
            // Zähler — only needed to drive the "due soon" accent on the
            // quick-action row; a failure just leaves the row un-accented.
            do {
                self.meters = try await metersTask
            } catch {
                self.meters = []
            }
        } catch APIError.unauthorized {
            onUnauthorized?()
        } catch let error as APIError {
            self.lastError = error.errorDescription
        } catch {
            self.lastError = error.localizedDescription
        }
    }

    /// Compute the four per-category NEU hints for the current property.
    /// Each fetch runs in parallel and fails silently — a thrown error
    /// (incl. unauthorized / demo / transient) just leaves that flag
    /// false; this job never touches `lastError` or `onUnauthorized` so
    /// it can't blank or bounce the Start tab. Reuses the shared 7-day
    /// `isRecentlyNew` window from NeuBadge.swift.
    private func loadAttentionHints(id: String) async {
        async let assembliesTask = (try? await api.listMyAssemblies(propertyId: id)) ?? []
        // listMyOpenTickets has no per-property filter (returns the
        // caller's open tickets across all properties), so scope to this
        // property client-side via TicketSummary.property_id.
        async let ticketsTask = (try? await api.listMyOpenTickets()) ?? []
        async let announcementsTask = (try? await api.listMyAnnouncementsForProperty(id)) ?? []
        async let documentsTask = (try? await api.getMyPropertyDocuments(propertyId: id)) ?? []

        let assemblies = await assembliesTask
        let tickets = await ticketsTask
        let announcements = await announcementsTask
        let documents = await documentsTask

        let now = Date()

        // Versammlungen: any upcoming assembly (scheduled_start >= now)
        // OR one that just arrived (Einladung-upload / creation within 7d).
        self.hasNewAssembly = assemblies.contains { a in
            a.scheduled_start >= now || isRecentlyNew(a.addedRecentlyDate)
        }

        // Anliegen: open tickets on THIS property whose status is NEU,
        // or whose last activity is within the last 7 days. listMyOpenTickets
        // already excludes closed/resolved (GESCHLOSSEN); we still guard
        // with isActive in case the endpoint shape changes.
        self.hasNewTicket = tickets.contains { t in
            guard t.property_id == id, t.status.isActive else { return false }
            return t.status == .neu || isRecentlyNew(t.last_message_at)
        }

        // Mitteilungen: any announcement published within the last 7 days
        // (notification_sent_at if sent, else the scheduled publish date).
        self.hasNewAnnouncement = announcements.contains { ann in
            isRecentlyNew(ann.notification_sent_at ?? ann.scheduled_publish_at)
        }

        // Dokumente: any document added/synced within the last 7 days.
        // uploaded_at is an ISO-8601 string on DocumentResponse — parse it
        // with the shared decoder's date strategy; unparsable → not new.
        self.hasNewDocument = documents.contains { doc in
            isRecentlyNew(Self.parseISODate(doc.uploaded_at))
        }
    }

    /// Parse the ISO-8601 `uploaded_at` string DocumentResponse carries
    /// (the list otherwise treats it as an opaque string). Tolerant of the
    /// fractional-seconds and plain `…Z` variants the API returns.
    private static func parseISODate(_ value: String?) -> Date? {
        guard let value, !value.isEmpty else { return nil }
        let withFractional = ISO8601DateFormatter()
        withFractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = withFractional.date(from: value) { return d }
        let plain = ISO8601DateFormatter()
        plain.formatOptions = [.withInternetDateTime]
        return plain.date(from: value)
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
    /// The Versammlungen / Anliegen / Mitteilungen quick-action rows route
    /// through the shell's deep-link path (which dismisses any open sheet,
    /// resets the feature's nav path, then presents) by setting pendingTarget.
    @EnvironmentObject var deepLinkRouter: DeepLinkRouter
    @State private var showEinheiten = false
    @State private var showDienstleister = false
    @State private var showDocuments = false
    @State private var showMeters = false
    @State private var showCalendar = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                headerCard
                if authStore.user?.role.lowercased() == "verwalter" {
                    FahrtenCard(propertyId: property.id)
                }
                AccountingProgressCard(propertyId: property.id)
                quickActionsSection()
                if let account = store.account, account.account_id != nil {
                    hausgeldkontoSection(account: account)
                }
                if !store.rentSettlements.isEmpty {
                    mietabrechnungSection(settlements: store.rentSettlements)
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
                // Cold-launch: a deep link may have set this before the
                // view mounted.
                consumePropertyTab(deepLinkRouter.pendingPropertyTab)
            }
            // Runtime: an activity-widget document / invoice / meter /
            // calendar tap routes here via DeepLinkRouter.
            .onChange(of: deepLinkRouter.pendingPropertyTab) { _, tab in
                consumePropertyTab(tab)
            }
            .task(id: property.id) {
                await store.load(id: property.id)
            }
            .refreshable { await store.load(id: property.id) }
            .sheet(isPresented: $showEinheiten) {
                EinheitenScreen(
                    units: store.detail?.units ?? [],
                    showMea: property.hasOwnershipShares
                )
                .environmentObject(authStore)
            }
            .sheet(isPresented: $showDienstleister) {
                DienstleisterScreen(vendors: store.vendors, propertyId: property.id)
                    .environmentObject(authStore)
            }
            .sheet(isPresented: $showDocuments) {
                DocumentsView(propertyId: property.id)
            }
            .sheet(isPresented: $showMeters) {
                MetersView(propertyId: property.id)
            }
            .sheet(isPresented: $showCalendar) {
                CalendarView(propertyId: property.id)
                    .environmentObject(authStore)
            }
    }

    /// Open the property sheet a deep link asked for, then clear the
    /// router slot so it doesn't re-fire. Mirrors the booleans the
    /// Schnellzugriff rows toggle, so widget taps and in-app taps land
    /// in the same place. Dismisses any other open property sheet first
    /// so SwiftUI reliably presents the new one.
    private func consumePropertyTab(_ tab: PropertyTab?) {
        guard let tab else { return }
        deepLinkRouter.consumePropertyTab()
        showDocuments = false
        showMeters = false
        showCalendar = false
        DispatchQueue.main.async {
            switch tab {
            case .documents: showDocuments = true
            case .meters: showMeters = true
            case .calendar: showCalendar = true
            }
        }
    }

    // MARK: - Header card

    /// The name already carries the address ("WEG Hasenbergstraße 32,
    /// 70176 Stuttgart"), so the card shows only name + WEG/MV pill.
    /// When the property has a hero photo (`image_url`, auth-gated) it
    /// becomes the card background under a bottom-weighted scrim so the
    /// white text stays legible; without one we keep the plain
    /// secondarySystemBackground card. Tapping opens Google Maps at the
    /// property address.
    private var headerCard: some View {
        Button {
            openInMaps()
        } label: {
            headerCardContent
        }
        .buttonStyle(.plain)
        // Only act as a tappable map link when we have an address to
        // search — otherwise it's a plain (inert-looking) card.
        .disabled(mapsURL == nil)
    }

    private var headerCardContent: some View {
        let hasPhoto = (store.detail?.image_url?.isEmpty == false)
        return VStack(alignment: .leading, spacing: 10) {
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
                Spacer(minLength: 0)
            }
            Text(property.name)
                .font(.title3.bold())
                // Force white over a photo (works in both light + dark);
                // fall back to the adaptive primary colour on the plain card.
                .foregroundStyle(hasPhoto ? Color.white : Color.primary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(16)
        // Photo cards reserve a bit more height so the image reads as a
        // hero, not a thin strip behind two text lines.
        .frame(maxWidth: .infinity, minHeight: hasPhoto ? 140 : nil, alignment: hasPhoto ? .bottomLeading : .leading)
        .background(headerBackground)
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .contentShape(RoundedRectangle(cornerRadius: 12))
    }

    /// Photo background (under a dark scrim) when `image_url` is present;
    /// otherwise the plain secondarySystemBackground fill.
    @ViewBuilder
    private var headerBackground: some View {
        if let imagePath = store.detail?.image_url, !imagePath.isEmpty {
            AuthedAsyncImage(path: imagePath) { image in
                image
                    .resizable()
                    .scaledToFill()
                    .overlay(scrim)
            } placeholder: {
                // While the authed fetch is in flight (or if it fails) keep
                // the plain card so the text never sits on a blank/illegible
                // surface.
                Color(.secondarySystemBackground)
            }
        } else {
            Color(.secondarySystemBackground)
        }
    }

    /// Bottom-weighted black scrim so the white name + pill stay legible
    /// over any photo, in both light and dark mode.
    private var scrim: some View {
        LinearGradient(
            colors: [
                Color.black.opacity(0.15),
                Color.black.opacity(0.55),
            ],
            startPoint: .top,
            endPoint: .bottom
        )
    }

    // MARK: - Maps deep link

    /// Full street + PLZ + city address for the Maps query. Prefers the
    /// structured fields from the fetched detail; falls back to the
    /// single-line address the picker collapsed onto `Liegenschaft`.
    private var fullAddress: String {
        if let d = store.detail {
            let streetLine = [d.street, d.number].compactMap { $0 }.joined(separator: " ")
            let cityLine = [d.postal_code, d.city].compactMap { $0 }.joined(separator: " ")
            let combined = [streetLine, cityLine]
                .filter { !$0.trimmingCharacters(in: .whitespaces).isEmpty }
                .joined(separator: ", ")
            if !combined.isEmpty { return combined }
        }
        return property.address
    }

    /// Google Maps universal search URL. Opens the Google Maps app when
    /// installed, otherwise the browser / Apple Maps. nil when we have no
    /// usable address (the card then renders as a plain, non-tappable card).
    private var mapsURL: URL? {
        let address = fullAddress.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !address.isEmpty, address != "—" else { return nil }
        guard let encoded = address.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) else {
            return nil
        }
        return URL(string: "https://www.google.com/maps/search/?api=1&query=\(encoded)")
    }

    private func openInMaps() {
        guard let url = mapsURL else { return }
        UIApplication.shared.open(url)
    }

    // MARK: - Quick actions

    private func quickActionsSection() -> some View {
        VStack(alignment: .leading, spacing: 8) {
            VStack(spacing: 8) {
                // Einheiten + Dienstleister open their own screens (the detail
                // lives behind the button, not inline below). Shown only when
                // there's data to open.
                if let units = store.detail?.units, !units.isEmpty {
                    Button {
                        showEinheiten = true
                    } label: {
                        quickRow(
                            title: "Einheiten",
                            systemImage: "building.2.fill",
                            color: .green,
                            trailingCount: units.count
                        )
                    }
                    .buttonStyle(.plain)
                }
                if !store.vendors.isEmpty {
                    Button {
                        showDienstleister = true
                    } label: {
                        quickRow(
                            title: "Dienstleister",
                            systemImage: "wrench.and.screwdriver.fill",
                            color: .gray,
                            trailingCount: store.vendors.count
                        )
                    }
                    .buttonStyle(.plain)
                }
                // Mitteilungen / Anliegen / Versammlungen — open their full
                // screens via the shell's deep-link path (reuse the existing tab
                // views; widget + push deep links land here too).
                Button {
                    deepLinkRouter.pendingTarget = .tab(.mitteilungen)
                } label: {
                    quickRow(
                        title: "Mitteilungen",
                        systemImage: "megaphone.fill",
                        color: .pink,
                        showNeu: store.hasNewAnnouncement
                    )
                }
                .buttonStyle(.plain)
                Button {
                    deepLinkRouter.pendingTarget = .tab(.tickets)
                } label: {
                    quickRow(
                        title: "Tickets",
                        systemImage: "tray.full.fill",
                        color: .orange,
                        showNeu: store.hasNewTicket
                    )
                }
                .buttonStyle(.plain)
                Button {
                    deepLinkRouter.pendingTarget = .tab(.etv)
                } label: {
                    quickRow(
                        title: "Versammlungen",
                        systemImage: "person.3.fill",
                        color: .purple,
                        showNeu: store.hasNewAssembly
                    )
                }
                .buttonStyle(.plain)
                // Documents — the iOS counterpart of the portal Dokumente tab.
                Button {
                    showDocuments = true
                } label: {
                    quickRow(
                        title: "Dokumente",
                        systemImage: "folder.fill",
                        color: .blue,
                        showNeu: store.hasNewDocument
                    )
                }
                .buttonStyle(.plain)
                // Zähler — meter list + reading capture (ADR-0016).
                // When readings are due soon, the row takes the same
                // red-frame / orange-fill accent as the Zähler list rows,
                // plus a count badge.
                Button {
                    showMeters = true
                } label: {
                    quickRow(
                        title: "Zähler",
                        systemImage: "gauge.medium",
                        color: .teal,
                        dueCount: store.dueSoonMeterCount
                    )
                }
                .buttonStyle(.plain)
                // Kalender — ETV + Winterdienst/Kehrwoche (ADR-0018).
                Button {
                    showCalendar = true
                } label: {
                    quickRow(title: "Kalender", systemImage: "calendar", color: .indigo)
                }
                .buttonStyle(.plain)
            }
        }
    }

    /// `dueCount > 0` lights the row with the meter "due soon" accent
    /// (orange fill + red frame) and shows a red count capsule. Default
    /// 0 keeps every other quick-action row visually unchanged.
    ///
    /// `showNeu` adds a trailing blue NEU badge (before the chevron) when
    /// the category has something new/upcoming for this property — kept
    /// visually distinct from the red "N fällig" overdue meter accent.
    /// Default false leaves the row unchanged.
    /// `trailingCount` shows a muted count (e.g. number of Einheiten /
    /// Dienstleister) just before the chevron — the at-a-glance hint that
    /// used to sit in the inline section headers.
    private func quickRow(
        title: LocalizedStringResource,
        systemImage: String,
        color: Color,
        dueCount: Int = 0,
        showNeu: Bool = false,
        trailingCount: Int? = nil
    ) -> some View {
        let isDue = dueCount > 0
        return HStack(spacing: 12) {
            Image(systemName: systemImage)
                .font(.title3)
                .foregroundStyle(.white)
                .frame(width: 36, height: 36)
                .background(color)
                .clipShape(RoundedRectangle(cornerRadius: 8))
            Text(title)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(.primary)
            if isDue {
                Text("\(dueCount) fällig")
                    .font(.caption2.weight(.bold))
                    .padding(.horizontal, 8)
                    .padding(.vertical, 3)
                    .background(Color.red)
                    .foregroundStyle(.white)
                    .clipShape(Capsule())
            }
            Spacer()
            if let trailingCount {
                Text("\(trailingCount)")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.tertiary)
            }
            if showNeu {
                NeuBadge()
            }
            Image(systemName: "chevron.right")
                .font(.caption.weight(.bold))
                .foregroundStyle(.tertiary)
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 10)
                .fill(isDue ? AnyShapeStyle(Color.orange.opacity(0.15)) : AnyShapeStyle(Color(.secondarySystemBackground)))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 10)
                .strokeBorder(Color.red, lineWidth: isDue ? 1.5 : 0)
        )
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

/// Einheiten list — opened from the Liegenschaft "Schnellzugriff" button (the
/// detail lives behind the button, not inline). Owns its own contact sheet.
private struct EinheitenScreen: View {
    let units: [UnitResponse]
    /// WEG / SEV → true (show MEA); MV → false. Passed from the parent.
    let showMea: Bool
    @EnvironmentObject var authStore: AuthStore
    @Environment(\.dismiss) private var dismiss
    @State private var contactSheetTarget: ContactSheetTarget?
    @State private var query = ""

    /// Filter by unit number / position / type / any owner-or-tenant name.
    private var filteredUnits: [UnitResponse] {
        let q = query.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !q.isEmpty else { return units }
        return units.filter { unit in
            let haystack =
                [unit.unit_hr_id, unit.position, unit.type].compactMap { $0 }
                + unit.current_contracts.compactMap { $0.contact_label }
            return haystack.contains { $0.lowercased().contains(q) }
        }
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 0) {
                    ForEach(filteredUnits) { unit in
                        UnitRow(
                            unit: unit,
                            showMea: showMea,
                            onContactTap: { contactSheetTarget = $0 }
                        )
                        if unit.id != filteredUnits.last?.id {
                            Divider().padding(.leading, 48)
                        }
                    }
                }
                .background(
                    RoundedRectangle(cornerRadius: 10)
                        .fill(Color(.secondarySystemBackground))
                )
                .padding(20)
            }
            .searchable(text: $query, prompt: "Einheit oder Name suchen")
            .navigationTitle("Einheiten")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Fertig") { dismiss() }
                }
            }
            .sheet(item: $contactSheetTarget) { target in
                ContactDetailSheet(
                    contractId: target.contractId,
                    contactId: target.contactId,
                    fallbackLabel: target.fallbackLabel,
                    contractType: target.contractType
                )
                .environmentObject(authStore)
            }
        }
    }
}

/// Dienstleister list — opened from the Liegenschaft "Schnellzugriff" button.
/// Per-vendor accordion (call/mail + recent invoices); owns its invoice sheet.
private struct DienstleisterScreen: View {
    let vendors: [VendorSummary]
    let propertyId: String
    @EnvironmentObject var authStore: AuthStore
    @Environment(\.dismiss) private var dismiss
    @State private var invoiceSheetTarget: InvoiceSheetTarget?
    @State private var query = ""

    private var filteredVendors: [VendorSummary] {
        let q = query.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !q.isEmpty else { return vendors }
        return vendors.filter { $0.name.lowercased().contains(q) }
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 0) {
                    ForEach(filteredVendors) { vendor in
                        VendorRow(
                            vendor: vendor,
                            onInvoiceTap: { invoice in
                                invoiceSheetTarget = InvoiceSheetTarget(
                                    vendorName: vendor.name,
                                    invoice: invoice
                                )
                            }
                        )
                        if vendor.contact_id != filteredVendors.last?.contact_id {
                            Divider().padding(.leading, 56)
                        }
                    }
                }
                .background(
                    RoundedRectangle(cornerRadius: 10)
                        .fill(Color(.secondarySystemBackground))
                )
                .padding(20)
            }
            .searchable(text: $query, prompt: "Dienstleister suchen")
            .navigationTitle("Dienstleister")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Fertig") { dismiss() }
                }
            }
            .sheet(item: $invoiceSheetTarget) { target in
                InvoiceDetailSheet(
                    propertyId: propertyId,
                    vendorName: target.vendorName,
                    invoice: target.invoice
                )
                .environmentObject(authStore)
            }
        }
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
            // Collapsed row shows only the name — the per-year invoice
            // list (with dates + amounts) is the "detail" revealed on
            // expand, so the summary subtitle (Zuletzt / N Rechnungen /
            // Jahressumme) was redundant noise here.
            Text(vendor.name)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(Color.primary)
                .frame(maxWidth: .infinity, alignment: .leading)
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
