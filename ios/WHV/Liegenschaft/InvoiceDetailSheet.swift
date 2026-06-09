// Per-invoice detail sheet — opened from a vendor row in the
// Dienstleister section of PropertyDetailView. Mirrors the portal's
// InvoiceDetailDialog: status chip + bank-order metadata + line
// items ("Primärenergie 01.01-31.12.2025 · 250 €") + the honest
// "Banktransaktionen via Impower-API nicht abrufbar" disclaimer.
//
// Sheet binding lives on PropertyDetailView (`invoiceSheetTarget`)
// and uses `.sheet(item:)` so swapping invoices unmounts + remounts
// this view, resetting the store's `detail` to nil for free.

import SwiftUI

@MainActor
final class InvoiceDetailStore: ObservableObject {
    @Published private(set) var detail: InvoiceDetailResponse?
    @Published private(set) var isLoading = false
    @Published var lastError: String?

    @Published private(set) var isDownloading = false

    var onUnauthorized: (() -> Void)?
    private let api: APIClient

    init(api: APIClient = APIClient()) {
        self.api = api
    }

    func load(propertyId: String, documentId: String) async {
        isLoading = true
        defer { isLoading = false }
        do {
            self.detail = try await api.getMyInvoiceDetail(
                propertyId: propertyId,
                documentId: documentId
            )
        } catch APIError.unauthorized {
            onUnauthorized?()
        } catch let e as APIError {
            self.lastError = e.errorDescription
        } catch {
            self.lastError = error.localizedDescription
        }
    }

    /// Download the invoice PDF to a temp URL for QuickLook — same
    /// auth-gated `/me/documents/{id}/file` the Dokumente list uses.
    /// Returns nil (and sets lastError) on failure.
    func downloadPDF(documentId: String) async -> URL? {
        guard !isDownloading else { return nil }
        isDownloading = true
        defer { isDownloading = false }
        do {
            return try await api.downloadDocument(id: documentId)
        } catch APIError.unauthorized {
            onUnauthorized?()
        } catch let e as APIError {
            self.lastError = e.errorDescription
        } catch {
            self.lastError = error.localizedDescription
        }
        return nil
    }
}

struct InvoiceDetailSheet: View {
    /// Property containing this invoice — needed for the
    /// `/me/properties/{id}/invoices/{doc_id}` URL.
    let propertyId: String
    /// Pre-rendered vendor name from the row, so the header reads
    /// useful even before the fetch returns.
    let vendorName: String
    /// Row metadata the sheet falls back on for header fields the
    /// detail fetch might miss (issued_date, amount).
    let invoice: VendorInvoiceSummary

    @StateObject private var store = InvoiceDetailStore()
    @EnvironmentObject var authStore: AuthStore
    @Environment(\.dismiss) private var dismiss
    @State private var preview: PreviewItem?

    private struct PreviewItem: Identifiable {
        let id = UUID()
        let url: URL
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    pdfButton
                    if let d = store.detail {
                        rechnungSection(d)
                        if hasBankFields(d) {
                            bankSection(d)
                        }
                        if !d.items.isEmpty {
                            buchungssection(d)
                        }
                        Text(
                            "Einzelne Banktransaktionen pro Rechnung sind über die "
                            + "Impower-API derzeit nicht abrufbar. Der oben angezeigte "
                            + "Status spiegelt den Buchungsstand wider — nicht den "
                            + "tatsächlichen Geldfluss."
                        )
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                        .italic()
                    } else if store.isLoading {
                        ProgressView()
                            .frame(maxWidth: .infinity)
                            .padding(.top, 40)
                    } else if let err = store.lastError {
                        Text(err)
                            .font(.subheadline)
                            .foregroundStyle(.red)
                    } else {
                        fallbackHeader
                    }
                }
                .padding(.horizontal, 20)
                .padding(.vertical, 16)
            }
            .navigationTitle(vendorName)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Fertig") { dismiss() }
                }
            }
            .onAppear {
                store.onUnauthorized = { [weak authStore] in
                    authStore?.signOut()
                }
            }
            .task {
                await store.load(propertyId: propertyId, documentId: invoice.id)
            }
            .sheet(item: $preview) { p in
                FilePreview(url: p.url).ignoresSafeArea()
            }
        }
    }

    // MARK: - Actions

    /// Opens the actual invoice PDF in QuickLook — the action the
    /// portal's vendor dialog had but the app was missing.
    private var pdfButton: some View {
        Button {
            Task {
                if let url = await store.downloadPDF(documentId: invoice.id) {
                    preview = PreviewItem(url: url)
                }
            }
        } label: {
            HStack(spacing: 8) {
                if store.isDownloading {
                    ProgressView()
                } else {
                    Image(systemName: "arrow.down.doc")
                }
                Text("Rechnung als PDF öffnen")
            }
            .frame(maxWidth: .infinity)
        }
        .buttonStyle(.borderedProminent)
        .disabled(store.isDownloading)
    }

    // MARK: - Sections

    private var fallbackHeader: some View {
        section(title: "Rechnung") {
            row(label: "Bezeichnung", value: invoice.name)
            row(label: "Datum", value: formatDate(invoice.issued_date ?? ""))
            if let amount = invoice.amount {
                row(label: "Betrag", value: "\(formatAmount(amount)) €")
            }
            Text("Buchungsdetails werden geladen …")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    private func rechnungSection(_ d: InvoiceDetailResponse) -> some View {
        section(title: "Rechnung") {
            row(label: "Rechnungs-Nr.", value: d.invoice_number)
            row(label: "Datum", value: formatDate(d.issued_date ?? invoice.issued_date ?? ""))
            if let amount = d.amount ?? invoice.amount {
                row(label: "Betrag", value: "\(formatAmount(amount)) €")
            }
            HStack(spacing: 6) {
                Text("Status")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .frame(minWidth: 110, alignment: .leading)
                if let state = d.state {
                    statusChip(state)
                } else {
                    Text("—").font(.caption)
                }
                // "An Bank übermittelt" badge — the strongest signal
                // the public API gives us. See InvoiceDialog comments
                // in the portal counterpart for why this isn't a
                // settlement-confirmation.
                if d.state == "BOOKED", d.order_required == true {
                    Text("An Bank übermittelt")
                        .font(.caption2.weight(.semibold))
                        .padding(.horizontal, 6)
                        .padding(.vertical, 2)
                        .background(Color.green.opacity(0.18))
                        .foregroundStyle(.green)
                        .clipShape(Capsule())
                }
                Spacer(minLength: 0)
            }
            if let statement = d.order_statement {
                row(label: "Verwendungszweck", value: statement)
            }
            if let off = d.order_day_offset, d.order_required == true {
                row(
                    label: "Ausführung",
                    value: off == 0
                        ? "Sofort am Buchungstag"
                        : "Buchungstag + \(off) Tage"
                )
            }
        }
    }

    private func bankSection(_ d: InvoiceDetailResponse) -> some View {
        section(title: "Bankverbindung") {
            row(label: "Vom Konto (IBAN)", value: d.property_iban)
            row(label: "Vom Konto (BIC)", value: d.property_bic)
            row(label: "Zum Konto (IBAN)", value: d.counterpart_iban)
            row(label: "Zum Konto (BIC)", value: d.counterpart_bic)
        }
    }

    private func buchungssection(_ d: InvoiceDetailResponse) -> some View {
        section(title: "Buchungsdetails") {
            VStack(alignment: .leading, spacing: 10) {
                ForEach(d.items) { item in
                    lineItemRow(item)
                    if item.id != d.items.last?.id {
                        Divider()
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func lineItemRow(_ item: InvoiceLineItemResponse) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(item.account_name ?? "Buchungsposition")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(.primary)
                Spacer(minLength: 0)
                if let amt = item.amount {
                    Text("\(formatAmount(amt)) €")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(.primary)
                }
            }
            if let booking = item.booking_text {
                Text(booking)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            HStack(spacing: 8) {
                if let code = item.account_code {
                    Text("Konto \(code)")
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }
                if let vatPct = item.vat_percentage {
                    let vatExtra =
                        item.vat_amount.map { " · \(formatAmount($0)) €" } ?? ""
                    Text("MwSt. \(formatPercent(vatPct)) %\(vatExtra)")
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }
            }
        }
    }

    // MARK: - Reusable bits

    @ViewBuilder
    private func section<Content: View>(
        title: LocalizedStringResource,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
                .textCase(.uppercase)
            VStack(alignment: .leading, spacing: 6) {
                content()
            }
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: 10)
                    .fill(Color(.secondarySystemBackground))
            )
        }
    }

    @ViewBuilder
    private func row(label: LocalizedStringResource, value: String?) -> some View {
        if let v = value, !v.isEmpty {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(label)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .frame(minWidth: 110, alignment: .leading)
                Text(v)
                    .font(.subheadline)
                    .foregroundStyle(.primary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                Spacer(minLength: 0)
            }
        }
    }

    /// State chip styled inline — matches the portal's color
    /// scheme (BOOKED=green, DRAFT=yellow, REVERSED=red, …) so the
    /// two clients render the same signal.
    @ViewBuilder
    private func statusChip(_ state: String) -> some View {
        let (label, color) = statusStyle(state)
        Text(label)
            .font(.caption2.weight(.semibold))
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(color.opacity(0.18))
            .foregroundStyle(color)
            .clipShape(Capsule())
    }

    private func statusStyle(_ state: String) -> (String, Color) {
        switch state {
        case "DRAFT": return ("Entwurf", .orange)
        case "READY": return ("Bereit", .accentColor)
        case "BOOKED": return ("Gebucht", .green)
        case "SCHEDULED": return ("Geplant", .secondary)
        case "REVERSED": return ("Storniert", .red)
        default: return (state, .secondary)
        }
    }

    private func hasBankFields(_ d: InvoiceDetailResponse) -> Bool {
        d.property_iban != nil
            || d.property_bic != nil
            || d.counterpart_iban != nil
            || d.counterpart_bic != nil
    }

    private func formatDate(_ iso: String) -> String? {
        guard !iso.isEmpty else { return nil }
        let parts = iso.split(separator: "-")
        guard parts.count >= 3 else { return iso }
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

    private func formatPercent(_ v: Double) -> String {
        let f = NumberFormatter()
        f.numberStyle = .decimal
        f.minimumFractionDigits = 0
        f.maximumFractionDigits = 2
        f.locale = Locale(identifier: "de_DE")
        return f.string(from: NSNumber(value: v)) ?? String(format: "%g", v)
    }
}
