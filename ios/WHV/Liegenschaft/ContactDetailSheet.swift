// Sheet reached by tapping a contract chip on PropertyDetailView.
// Mirrors the portal's ContactDetailDialog — full contact card +
// the contract context that wires the person to the property.
//
// Read-only on purpose. Owners and tenants tap their own name (or a
// neighbour's) to see what we have on file; the Verwalter has the
// admin SPA for edits.

import SwiftUI

@MainActor
final class ContactDetailStore: ObservableObject {
    @Published private(set) var detail: ContactDetailResponse?
    @Published private(set) var isLoading = false
    @Published var lastError: String?

    var onUnauthorized: (() -> Void)?
    private let api: APIClient

    init(api: APIClient = APIClient()) {
        self.api = api
    }

    func load(
        contractId: String,
        contactId: String,
        fallbackLabel: String,
        contractType: String
    ) async {
        isLoading = true
        defer { isLoading = false }
        do {
            self.detail = try await api.getMyContractContact(
                contractId: contractId,
                contactId: contactId,
                fallbackLabel: fallbackLabel,
                contractType: contractType
            )
        } catch APIError.unauthorized {
            onUnauthorized?()
        } catch let e as APIError {
            self.lastError = e.errorDescription
        } catch {
            self.lastError = error.localizedDescription
        }
    }
}

struct ContactDetailSheet: View {
    /// What the parent passes in — enough to fire the fetch + render
    /// a useful title before the network round-trip lands.
    let contractId: String
    let contactId: String
    let fallbackLabel: String
    let contractType: String

    @StateObject private var store = ContactDetailStore()
    @EnvironmentObject var authStore: AuthStore
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    if let d = store.detail {
                        contractSection(d)
                        if d.kind == "PERSON" {
                            personSection(d)
                        } else {
                            companySection(d)
                        }
                        contactSection(d)
                        addressSection(d)
                        if let mandate = d.mandate_number, !mandate.isEmpty {
                            mandateSection(mandate: mandate)
                        }
                    } else if store.isLoading {
                        ProgressView()
                            .frame(maxWidth: .infinity)
                            .padding(.top, 40)
                    } else if let err = store.lastError {
                        Text(err)
                            .font(.subheadline)
                            .foregroundStyle(.red)
                    }
                }
                .padding(.horizontal, 20)
                .padding(.vertical, 16)
            }
            .navigationTitle(store.detail.map(renderName) ?? fallbackLabel)
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
                await store.load(
                    contractId: contractId,
                    contactId: contactId,
                    fallbackLabel: fallbackLabel,
                    contractType: contractType
                )
            }
        }
    }

    // MARK: - Sections

    private func contractSection(_ d: ContactDetailResponse) -> some View {
        section(title: "Vertrag") {
            HStack(spacing: 8) {
                Text(contractTypeLabel(d.contract.type))
                    .font(.caption.weight(.semibold))
                    .padding(.horizontal, 8)
                    .padding(.vertical, 3)
                    .background(contractTypeColor(d.contract.type).opacity(0.18))
                    .foregroundStyle(contractTypeColor(d.contract.type))
                    .clipShape(Capsule())
                if let n = d.contract.contract_number, !n.isEmpty {
                    Text(n)
                        .font(.caption.monospaced())
                        .foregroundStyle(.secondary)
                }
            }
            row(label: "Bezeichnung", value: d.contract.name)
            row(label: "Beginn", value: formatDate(d.contract.start_date))
            row(label: "Ende", value: formatDate(d.contract.end_date))
            if let role = d.contract.role, !role.isEmpty {
                row(label: "Rolle", value: role)
            }
        }
    }

    private func personSection(_ d: ContactDetailResponse) -> some View {
        section(title: "Person") {
            row(label: "Anrede", value: d.salutation)
            row(label: "Titel", value: d.title)
            row(label: "Vorname", value: d.first_name)
            row(label: "Nachname", value: d.last_name)
            row(label: "Geburtsdatum", value: formatDate(d.date_of_birth))
        }
    }

    private func companySection(_ d: ContactDetailResponse) -> some View {
        section(title: "Unternehmen") {
            row(label: "Firma", value: d.company_name)
            row(label: "USt-IdNr.", value: d.vat_id)
            row(label: "Handelsregister-Nr.", value: d.trade_register_number)
        }
    }

    private func contactSection(_ d: ContactDetailResponse) -> some View {
        section(title: "Kontakt") {
            // Email/phone are tappable launches — mail compose +
            // tel scheme. Long-press still copies because Text
            // auto-derives the menu from the rendered string.
            if let email = d.email, !email.isEmpty {
                Link(destination: URL(string: "mailto:\(email)")!) {
                    row(label: "E-Mail", value: email)
                }
                .buttonStyle(.plain)
            }
            if let phone = d.phone, !phone.isEmpty,
               let url = URL(string: "tel:\(phone.replacingOccurrences(of: " ", with: ""))")
            {
                Link(destination: url) {
                    row(label: "Telefon", value: phone)
                }
                .buttonStyle(.plain)
            }
            row(label: "Bevorzugt", value: preferredChannelLabel(d.preferred_channel))
            row(label: "Empfänger", value: d.recipient_name)
            if let extras = d.additional_contacts, !extras.isEmpty {
                // Runtime keys (Impower-defined labels like "Mobil
                // Privat") need the dynamic-label variant — the
                // LocalizedStringResource overload is build-time only.
                ForEach(extras.sorted(by: { $0.key < $1.key }), id: \.key) { k, v in
                    dynamicRow(label: k, value: v)
                }
            }
        }
    }

    private func addressSection(_ d: ContactDetailResponse) -> some View {
        let line1 = [d.street, d.number].compactMap { $0 }.joined(separator: " ")
        let line2 = [d.postal_code, d.city].compactMap { $0 }.joined(separator: " ")
        let body = [line1, line2, d.country ?? ""]
            .filter { !$0.isEmpty }
            .joined(separator: "\n")
        return Group {
            if !body.isEmpty {
                section(title: "Anschrift") {
                    Text(body)
                        .font(.subheadline)
                        .foregroundStyle(.primary)
                }
            }
        }
    }

    private func mandateSection(mandate: String) -> some View {
        section(title: "Mandat") {
            row(label: "Mandat-Nr.", value: mandate)
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

    /// Row skipped when value is nil/empty — keeps the sheet compact.
    @ViewBuilder
    private func row(label: LocalizedStringResource, value: String?) -> some View {
        if let v = value, !v.isEmpty {
            rowBody(labelText: Text(label), value: v)
        }
    }

    /// Runtime-label variant for Impower-supplied keys (e.g.
    /// additional_contacts["Mobil Privat"]). Bypasses the catalog;
    /// the string is rendered verbatim.
    @ViewBuilder
    private func dynamicRow(label: String, value: String?) -> some View {
        if let v = value, !v.isEmpty {
            rowBody(labelText: Text(verbatim: label), value: v)
        }
    }

    private func rowBody(labelText: Text, value: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            labelText
                .font(.caption)
                .foregroundStyle(.secondary)
                .frame(minWidth: 110, alignment: .leading)
            Text(value)
                .font(.subheadline)
                .foregroundStyle(.primary)
                .frame(maxWidth: .infinity, alignment: .leading)
                .multilineTextAlignment(.leading)
            Spacer(minLength: 0)
        }
    }
}

// MARK: - Pure helpers (file-private)

private func renderName(_ d: ContactDetailResponse) -> String {
    if d.kind == "COMPANY" { return d.company_name ?? "—" }
    let parts = [d.title, d.first_name, d.last_name]
        .compactMap { $0 }
        .filter { !$0.isEmpty }
    return parts.isEmpty ? "—" : parts.joined(separator: " ")
}

private func formatDate(_ iso: String?) -> String? {
    guard let iso, !iso.isEmpty else { return nil }
    // Backend returns ISO YYYY-MM-DD. Render German DD.MM.YYYY —
    // matches what the rest of the app (and Verwalter correspondence)
    // uses.
    let parts = iso.split(separator: "-")
    guard parts.count >= 3 else { return iso }
    return "\(parts[2]).\(parts[1]).\(parts[0])"
}

private func contractTypeLabel(_ t: String) -> String {
    switch t {
    case "OWNER": return "Eigentümer"
    case "TENANT": return "Mieter"
    case "PROPERTY_OWNER": return "Objekteigentümer"
    default: return t
    }
}

private func contractTypeColor(_ t: String) -> Color {
    switch t {
    case "OWNER": return .green
    case "TENANT": return .accentColor
    case "PROPERTY_OWNER": return .orange
    default: return .secondary
    }
}

private func preferredChannelLabel(_ c: String) -> String {
    switch c {
    case "PORTAL": return "Portal"
    case "EMAIL": return "E-Mail"
    case "WHATSAPP": return "WhatsApp"
    case "EPOST": return "E-Post"
    default: return c
    }
}
