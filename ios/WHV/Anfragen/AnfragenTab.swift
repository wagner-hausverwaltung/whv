// Anfragen — Verwalter-only tab (between Start and Einstellungen) mirroring the
// admin portal's Anfragen review queue (ADR-0019). Lists every inbound
// anfragen@ offer inquiry with its status; tapping one opens the detail with the
// full email body, editable extracted fields, a shared note, and the actions
// (send offer, re-download, friendly reminder). VERWALTER-only — RootTabView
// only mounts this tab for that role; the endpoints are admin-scoped anyway.

import SwiftUI

// MARK: - API models

struct OfferInquirySummary: Codable, Identifiable, Hashable {
    let id: String
    let sender_email: String
    let sender_name: String?
    let subject: String
    let status: String
    let lead_status: String
    let art: String?
    let object_address: String?
    let units: Int?
    let desired_start: String?  // yyyy-MM-dd
    let confidence: Double?
    let sent_at: String?
    let created_at: String
    let generated_offer_filename: String?
    let last_reminder_at: String?
    let reminder_count: Int
    /// Besichtigungen from the Fahrtenbuch (trips linked to this inquiry).
    let visited_at: String?
    let visit_count: Int?

    var isVisited: Bool { (visit_count ?? 0) > 0 }
}

struct OfferInquiryDetail: Codable, Identifiable, Hashable {
    let id: String
    let sender_email: String
    let sender_name: String?
    let subject: String
    let status: String
    let lead_status: String
    let art: String?
    let object_address: String?
    let units: Int?
    let desired_start: String?
    let confidence: Double?
    let sent_at: String?
    let created_at: String
    let generated_offer_filename: String?
    let last_reminder_at: String?
    let reminder_count: Int
    let visited_at: String?
    let visit_count: Int?
    let body: String
    let review_note: String?
    let error: String?
    let sent_message_id: String?
}

struct OfferLeadStatusBody: Encodable { let lead_status: String }
struct OfferNoteBody: Encodable { let review_note: String? }
struct EmptyJSONBody: Encodable {}

struct OfferFieldsBody: Encodable {
    let art: String?
    let object_address: String?
    let units: Int?
    let desired_start: String?
}

struct OfferGenerateBody: Encodable {
    let art: String
    // MV/SEV only: VDIV-2026 contract variant ("verbraucher" | "unternehmer").
    let variant: String?
    let units: Int
    let start_date: String?
    let end_date: String?
    let monthly_fee_net_override: Double?
    let object_street: String?
    let object_plz_city: String?
    let recipient_name: String?
    let recipient_street: String?
    let recipient_plz_city: String?
    let salutation: String?
    let objects: [String]?
}

// MARK: - Display helpers

enum OfferStatus {
    /// Processing status → German short label + chip colour.
    static func label(_ s: String) -> String {
        switch s {
        case "NEW": return "Neu"
        case "EXTRACTED": return "Erkannt"
        case "NEEDS_REVIEW": return "Prüfen"
        case "SENT": return "Gesendet"
        case "FAILED": return "Fehler"
        case "IGNORED": return "Ignoriert"
        default: return s
        }
    }
    static func color(_ s: String) -> Color {
        switch s {
        case "SENT": return .green
        case "NEEDS_REVIEW": return .orange
        case "FAILED": return .red
        case "EXTRACTED": return .blue
        default: return .secondary
        }
    }
}

let offerLeadStatuses = ["OPEN", "ON_HOLD", "ACCEPTED", "DECLINED"]

/// Lead state → the word the Verwalter sees. `String(localized:)` rather than
/// a bare literal so the labels land in the String Catalog and follow the
/// app's language — the tab titles and the row badges must not disagree.
func offerLeadLabel(_ s: String) -> String {
    switch s {
    case "OPEN": return String(localized: "Offen")
    case "ON_HOLD": return String(localized: "Wartend")
    case "ACCEPTED": return String(localized: "Angenommen")
    case "DECLINED": return String(localized: "Abgelehnt")
    default: return s
    }
}

enum OfferLead {
    /// Lead state → traffic-light colour (the state the Verwalter tracks
    /// once an offer is out: open · parked · won · lost).
    static func color(_ s: String) -> Color {
        switch s {
        case "OPEN": return .orange       // needs a decision
        case "ON_HOLD": return .secondary // parked
        case "ACCEPTED": return .green     // won
        case "DECLINED": return .red       // lost
        default: return .secondary
        }
    }
}

/// "2027-01-01" or a full ISO datetime → "01.01.2027".
func offerDateDE(_ s: String?) -> String {
    guard let s, s.count >= 10 else { return "—" }
    let parts = s.prefix(10).split(separator: "-")
    guard parts.count == 3 else { return String(s.prefix(10)) }
    return "\(parts[2]).\(parts[1]).\(parts[0])"
}

private let offerISODateFormatter: DateFormatter = {
    let f = DateFormatter()
    f.locale = Locale(identifier: "en_US_POSIX")
    f.calendar = Calendar(identifier: .gregorian)
    f.timeZone = TimeZone(identifier: "Europe/Berlin")
    f.dateFormat = "yyyy-MM-dd"
    return f
}()

func offerDate(from iso: String?) -> Date? {
    guard let iso, iso.count >= 10 else { return nil }
    return offerISODateFormatter.date(from: String(iso.prefix(10)))
}

func offerISO(from date: Date) -> String { offerISODateFormatter.string(from: date) }

func offerDefaultStartISO() -> String {
    let y = Calendar.current.component(.year, from: Date()) + 1
    return String(format: "%04d-01-01", y)
}

/// start + 4 years − 1 day (mirrors the backend pricing default).
func offerComputedEndISO(start: String) -> String {
    guard let d = offerDate(from: start) else { return "" }
    let cal = Calendar(identifier: .gregorian)
    guard let plus = cal.date(byAdding: .year, value: 4, to: d),
          let end = cal.date(byAdding: .day, value: -1, to: plus)
    else { return "" }
    return offerISO(from: end)
}

/// Live price preview mirroring the backend pricing engine.
func offerComputedMonthlyNet(art: String, units: Int) -> Double? {
    guard units >= 1 else { return nil }
    if art == "MV" || art == "SEV" { return Double(units) * 30 }
    let rate = units > 15 ? 35.0 : 45.0
    return max(Double(units) * rate, 270)
}

/// Split a combined "Straße 1, 70123 Stadt" on the 5-digit PLZ.
func offerSplitAddress(_ address: String?) -> (street: String, plzCity: String) {
    guard let a = address?.trimmingCharacters(in: .whitespacesAndNewlines), !a.isEmpty else {
        return ("", "")
    }
    if a.range(of: #"^\d{5}\s+\S"#, options: .regularExpression) != nil { return ("", a) }
    if let m = a.range(of: #"^(.*?)[,\s]+(\d{5}\s+.+)$"#, options: .regularExpression) {
        _ = m
        // Capture groups via NSRegularExpression for reliability.
        if let re = try? NSRegularExpression(pattern: #"^(.*?)[,\s]+(\d{5}\s+.+)$"#),
           let match = re.firstMatch(in: a, range: NSRange(a.startIndex..., in: a)),
           let r1 = Range(match.range(at: 1), in: a), let r2 = Range(match.range(at: 2), in: a)
        {
            let street = a[r1].trimmingCharacters(in: CharacterSet(charactersIn: ", "))
            return (street, String(a[r2]).trimmingCharacters(in: .whitespaces))
        }
    }
    return (a, "")
}

struct OfferPreviewItem: Identifiable { let id = UUID(); let url: URL }

// MARK: - Store

@MainActor
final class AnfragenStore: ObservableObject {
    @Published var items: [OfferInquirySummary] = []
    @Published var loading = false
    @Published var error: String?

    private let api: APIClient
    init(api: APIClient = APIClient()) { self.api = api }

    func load() async {
        loading = true
        error = nil
        do {
            items = try await api.listOfferInquiries()
        } catch {
            self.error = "Anfragen konnten nicht geladen werden."
        }
        loading = false
    }

    /// Hard delete (DSGVO erasure) — removes the row locally on success.
    func delete(id: String) async {
        error = nil
        do {
            try await api.deleteOfferInquiry(id: id)
            items.removeAll { $0.id == id }
        } catch {
            self.error = "Anfrage konnte nicht gelöscht werden."
        }
    }
}

// MARK: - Tab (list)

struct AnfragenTab: View {
    /// The two states a Verwalter still has to act on. Won and lost deals are
    /// deliberately absent: in the car and on the phone this list is a to-do
    /// list, and the full history stays in the admin portal (Luis 2026-08-28).
    enum LeadFilter: String, CaseIterable, Identifiable {
        case open = "OPEN"
        case onHold = "ON_HOLD"

        var id: String { rawValue }
        var label: String { offerLeadLabel(rawValue) }
    }

    @StateObject private var store = AnfragenStore()
    @State private var searchText = ""
    @State private var deleteCandidate: OfferInquirySummary?
    // Survives a tab switch and an app restart, so the Verwalter comes back to
    // the list he was working in.
    @SceneStorage("anfragen.leadFilter") private var leadFilterRaw = LeadFilter.open.rawValue

    private var leadFilter: LeadFilter { LeadFilter(rawValue: leadFilterRaw) ?? .open }

    /// Everything in the selected state — the count on the segment shows this,
    /// so it stays honest while a search narrows the list below.
    private func items(in filter: LeadFilter) -> [OfferInquirySummary] {
        store.items.filter { $0.lead_status == filter.rawValue }
    }

    /// Token AND-search over sender, subject, address and Art — mirrors the
    /// admin portal's search field.
    private var visibleItems: [OfferInquirySummary] {
        let inTab = items(in: leadFilter)
        let tokens = searchText.lowercased().split(separator: " ").map(String.init)
        guard !tokens.isEmpty else { return inTab }
        return inTab.filter { item in
            let haystack = [
                item.sender_name, item.sender_email, item.subject,
                item.object_address, item.art,
            ]
            .compactMap { $0 }
            .joined(separator: " ")
            .lowercased()
            return tokens.allSatisfy { haystack.contains($0) }
        }
    }

    var body: some View {
        NavigationStack {
            List {
                if let error = store.error {
                    Section { Text(error).foregroundStyle(.red).font(.callout) }
                }

                Section {
                    Picker("Status", selection: $leadFilterRaw) {
                        ForEach(LeadFilter.allCases) { filter in
                            Text("\(filter.label) (\(items(in: filter).count))").tag(filter.rawValue)
                        }
                    }
                    .pickerStyle(.segmented)
                    .listRowInsets(EdgeInsets(top: 4, leading: 12, bottom: 4, trailing: 12))
                }
                .listRowBackground(Color.clear)

                Section {
                    if visibleItems.isEmpty, !store.loading {
                        Text(
                            searchText.isEmpty
                                ? (leadFilter == .open
                                    ? "Keine offenen Anfragen."
                                    : "Keine Anfragen auf Wiedervorlage.")
                                : "Keine Treffer für die Suche."
                        )
                        .foregroundStyle(.secondary)
                    }
                    ForEach(visibleItems) { item in
                        NavigationLink(value: item.id) { AnfrageRow(item: item) }
                            .swipeActions(edge: .trailing) {
                                Button(role: .destructive) {
                                    deleteCandidate = item
                                } label: {
                                    Label("Löschen", systemImage: "trash")
                                }
                            }
                    }
                } header: {
                    Text("\(visibleItems.count) \(leadFilter.label)")
                }
            }
            .searchable(text: $searchText, prompt: "Absender, Betreff, Objekt …")
            .confirmationDialog(
                "Diese Anfrage endgültig löschen? Das kann nicht rückgängig gemacht werden.",
                isPresented: Binding(
                    get: { deleteCandidate != nil },
                    set: { if !$0 { deleteCandidate = nil } }
                ),
                titleVisibility: .visible
            ) {
                Button("Anfrage löschen", role: .destructive) {
                    if let item = deleteCandidate {
                        Task { await store.delete(id: item.id) }
                    }
                    deleteCandidate = nil
                }
                Button("Abbrechen", role: .cancel) { deleteCandidate = nil }
            }
            .navigationTitle("Anfragen")
            .navigationDestination(for: String.self) { id in
                AnfrageDetailView(inquiryId: id, onMutate: { Task { await store.load() } })
            }
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button { Task { await store.load() } } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                }
            }
            .overlay {
                if store.loading && store.items.isEmpty { ProgressView() }
            }
            .refreshable { await store.load() }
            .task { await store.load() }
        }
    }
}

private struct AnfrageRow: View {
    let item: OfferInquirySummary

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(spacing: 8) {
                Text(item.sender_name ?? item.sender_email)
                    .font(.subheadline.weight(.semibold))
                    .lineLimit(1)
                Spacer(minLength: 8)
                statusBadge
            }
            if !metaLine.isEmpty {
                Text(metaLine)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
        }
        .padding(.vertical, 3)
    }

    /// Once an offer is sent, "Gesendet" is true of every row — so we show the
    /// lead state (Offen / Angenommen …) as a traffic-light dot instead. Only a
    /// not-yet-sent or failed inquiry falls back to the processing status, which
    /// is the thing that then needs attention.
    @ViewBuilder private var statusBadge: some View {
        if item.status == "SENT" {
            HStack(spacing: 6) {
                Circle()
                    .fill(OfferLead.color(item.lead_status))
                    .frame(width: 8, height: 8)
                Text(offerLeadLabel(item.lead_status))
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(OfferLead.color(item.lead_status))
            }
        } else {
            Text(OfferStatus.label(item.status))
                .font(.caption2.weight(.bold))
                .padding(.horizontal, 8)
                .padding(.vertical, 3)
                .background(OfferStatus.color(item.status).opacity(0.18))
                .foregroundStyle(OfferStatus.color(item.status))
                .clipShape(Capsule())
        }
    }

    /// One tidy secondary line: "WEG · 71254 Ditzingen · 3 WE · besichtigt 22.08.2026".
    private var metaLine: String {
        var parts: [String] = []
        if let art = item.art, !art.isEmpty { parts.append(art) }
        if let obj = item.object_address, !obj.isEmpty { parts.append(obj) }
        if let u = item.units { parts.append("\(u) WE") }
        if item.isVisited { parts.append("besichtigt \(offerDateDE(item.visited_at))") }
        return parts.joined(separator: " · ")
    }
}

// MARK: - Detail

struct AnfrageDetailView: View {
    let inquiryId: String
    var onMutate: () -> Void = {}

    private let api = APIClient()

    @State private var detail: OfferInquiryDetail?
    @State private var loading = true
    @State private var loadError: String?

    // editors (seeded from the loaded detail)
    @State private var leadStatus = "OPEN"
    @State private var note = ""
    @State private var editArt = ""  // "", "WEG", "MV"
    @State private var editAddress = ""
    @State private var editUnits = ""
    @State private var hasStart = false
    @State private var editStart = Date()

    @State private var busy = false
    @State private var actionError: String?
    @State private var sendSheet = false
    @State private var preview: OfferPreviewItem?
    @State private var showReminderConfirm = false

    var body: some View {
        Form {
            if let detail {
                content(detail)
            } else if loading {
                ProgressView()
            } else {
                Text(loadError ?? "Nicht gefunden.").foregroundStyle(.red)
            }
        }
        .navigationTitle("Anfrage")
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
        .sheet(isPresented: $sendSheet) {
            if let detail {
                AnfrageSendSheet(detail: detail) {
                    Task { await load() }
                    onMutate()
                }
            }
        }
        .sheet(item: $preview) { item in
            FilePreview(url: item.url).ignoresSafeArea()
        }
        .confirmationDialog(
            "Eine freundliche Erinnerung per E-Mail an den Absender senden?",
            isPresented: $showReminderConfirm, titleVisibility: .visible
        ) {
            Button("Erinnerung senden") { Task { await sendReminder() } }
            Button("Abbrechen", role: .cancel) {}
        }
    }

    @ViewBuilder
    private func content(_ d: OfferInquiryDetail) -> some View {
        Section {
            LabeledContent("Absender", value: d.sender_name ?? d.sender_email)
            if d.sender_name != nil {
                LabeledContent("E-Mail", value: d.sender_email)
            }
            if !d.subject.isEmpty { LabeledContent("Betreff", value: d.subject) }
            HStack {
                Text("Bearbeitung")
                Spacer()
                Text(OfferStatus.label(d.status))
                    .font(.caption.weight(.bold))
                    .padding(.horizontal, 8).padding(.vertical, 3)
                    .background(OfferStatus.color(d.status).opacity(0.18))
                    .foregroundStyle(OfferStatus.color(d.status))
                    .clipShape(Capsule())
            }
            Picker("Status", selection: $leadStatus) {
                ForEach(offerLeadStatuses, id: \.self) { Text(offerLeadLabel($0)).tag($0) }
            }
            .onChange(of: leadStatus) { _, new in Task { await saveLeadStatus(new) } }
            if let conf = d.confidence {
                LabeledContent("Sicherheit", value: "\(Int((conf * 100).rounded()))%")
            }
            if let n = d.visit_count, n > 0 {
                LabeledContent(
                    "Besichtigt",
                    value: n > 1
                        ? "\(n)× · zuletzt \(offerDateDE(d.visited_at))"
                        : offerDateDE(d.visited_at)
                )
            }
            if let err = d.error, d.status == "FAILED" {
                Text(err).font(.caption).foregroundStyle(.red)
            }
        }

        Section("E-Mail-Text") {
            Text(d.body.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                ? "Kein Text vorhanden." : d.body)
                .font(.callout)
                .textSelection(.enabled)
        }

        Section("Angaben bearbeiten") {
            Picker("Art", selection: $editArt) {
                Text("Unbekannt").tag("")
                Text("WEG").tag("WEG")
                Text("Mietverwaltung").tag("MV")
                Text("SEV").tag("SEV")
            }
            TextField("Objekt (Straße + Nr., PLZ + Ort)", text: $editAddress, axis: .vertical)
            TextField("Einheiten", text: $editUnits)
                .keyboardType(.numberPad)
            Toggle("Vertragsbeginn festlegen", isOn: $hasStart)
            if hasStart {
                DatePicker("Vertragsbeginn", selection: $editStart, displayedComponents: .date)
            }
            Button("Angaben speichern") { Task { await saveFields() } }
                .disabled(busy)
        }

        Section("Notizen (für alle sichtbar)") {
            TextField("Interne Notiz …", text: $note, axis: .vertical)
                .lineLimit(2...6)
            Button("Notiz speichern") { Task { await saveNote() } }
                .disabled(busy || note == (detail?.review_note ?? ""))
        }

        Section("Aktionen") {
            if d.status != "SENT" && d.status != "IGNORED" {
                Button {
                    sendSheet = true
                } label: {
                    Label("Angebot senden", systemImage: "paperplane.fill")
                }
            }
            if d.generated_offer_filename != nil {
                Button {
                    Task { await downloadOffer(d) }
                } label: {
                    Label("Angebot herunterladen", systemImage: "arrow.down.doc")
                }
                .disabled(busy)
            }
            if d.status == "SENT" {
                Button {
                    showReminderConfirm = true
                } label: {
                    Label("Erinnerung senden", systemImage: "bell.badge")
                }
                .disabled(busy)
                if d.reminder_count > 0 {
                    Text("Erinnerung \(d.reminder_count)× gesendet, zuletzt am \(offerDateDE(d.last_reminder_at))")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
            if let actionError {
                Text(actionError).font(.caption).foregroundStyle(.red)
            }
        }
    }

    // MARK: actions

    private func seed(_ d: OfferInquiryDetail) {
        leadStatus = d.lead_status
        note = d.review_note ?? ""
        editArt = d.art ?? ""
        editAddress = d.object_address ?? ""
        editUnits = d.units != nil ? String(d.units!) : ""
        if let start = offerDate(from: d.desired_start) {
            hasStart = true
            editStart = start
        } else {
            hasStart = false
        }
    }

    private func load() async {
        loading = true
        loadError = nil
        do {
            let d = try await api.getOfferInquiry(id: inquiryId)
            detail = d
            seed(d)
        } catch {
            loadError = "Anfrage konnte nicht geladen werden."
        }
        loading = false
    }

    private func saveLeadStatus(_ new: String) async {
        guard new != detail?.lead_status else { return }
        do {
            _ = try await api.setOfferLeadStatus(id: inquiryId, status: new)
            onMutate()
        } catch {
            actionError = "Status konnte nicht gespeichert werden."
        }
    }

    private func saveNote() async {
        busy = true
        actionError = nil
        do {
            let trimmed = note.trimmingCharacters(in: .whitespacesAndNewlines)
            detail = try await api.setOfferNote(id: inquiryId, note: trimmed.isEmpty ? nil : trimmed)
            if let detail { seed(detail) }
        } catch {
            actionError = "Notiz konnte nicht gespeichert werden."
        }
        busy = false
    }

    private func saveFields() async {
        busy = true
        actionError = nil
        do {
            let body = OfferFieldsBody(
                art: editArt.isEmpty ? nil : editArt,
                object_address: editAddress.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                    ? nil : editAddress.trimmingCharacters(in: .whitespacesAndNewlines),
                units: Int(editUnits.trimmingCharacters(in: .whitespacesAndNewlines)),
                desired_start: hasStart ? offerISO(from: editStart) : nil
            )
            detail = try await api.setOfferFields(id: inquiryId, body: body)
            if let detail { seed(detail) }
            onMutate()
        } catch {
            actionError = "Angaben konnten nicht gespeichert werden."
        }
        busy = false
    }

    private func sendReminder() async {
        busy = true
        actionError = nil
        do {
            detail = try await api.sendOfferReminder(id: inquiryId)
            if let detail { seed(detail) }
            onMutate()
        } catch {
            actionError = "Erinnerung konnte nicht gesendet werden."
        }
        busy = false
    }

    private func downloadOffer(_ d: OfferInquiryDetail) async {
        busy = true
        actionError = nil
        do {
            let url = try await api.downloadOffer(
                id: inquiryId, filename: d.generated_offer_filename ?? "Angebot.pdf"
            )
            preview = OfferPreviewItem(url: url)
        } catch {
            actionError = "Angebot konnte nicht geladen werden."
        }
        busy = false
    }
}

// MARK: - Send sheet

struct AnfrageSendSheet: View {
    let detail: OfferInquiryDetail
    var onSent: () -> Void = {}

    @Environment(\.dismiss) private var dismiss
    private let api = APIClient()

    @State private var art = "WEG"
    @State private var variant = "verbraucher"
    @State private var units = ""
    @State private var startDate = Date()
    @State private var endDate = Date()
    @State private var endTouched = false
    @State private var monthlyFee = ""
    @State private var priceTouched = false
    @State private var objectStreet = ""
    @State private var objectPlzCity = ""
    @State private var recipientName = ""
    @State private var recipientStreet = ""
    @State private var recipientPlzCity = ""
    @State private var object1 = ""
    @State private var busy = false
    @State private var error: String?

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Picker("Art", selection: $art) {
                        Text("WEG").tag("WEG")
                        Text("Mietverwaltung").tag("MV")
                        Text("SEV").tag("SEV")
                    }
                    .pickerStyle(.segmented)
                    if art != "WEG" {
                        // VDIV-2026: Verbraucher (mit Widerrufsbelehrung) vs. Unternehmer.
                        Picker("Vertragsvariante", selection: $variant) {
                            Text("Verbraucher").tag("verbraucher")
                            Text("Unternehmer").tag("unternehmer")
                        }
                        .pickerStyle(.segmented)
                    }
                    TextField("Einheiten", text: $units).keyboardType(.numberPad)
                    DatePicker("Vertragsbeginn", selection: $startDate, displayedComponents: .date)
                    DatePicker("Vertragsende", selection: $endDate, displayedComponents: .date)
                        .onChange(of: endDate) { _, _ in endTouched = true }
                    TextField("Preis / Monat (netto)", text: $monthlyFee)
                        .keyboardType(.decimalPad)
                        .onChange(of: monthlyFee) { _, _ in priceTouched = true }
                    if let net = Double(monthlyFee.replacingOccurrences(of: ",", with: ".")) {
                        Text("≈ \(String(format: "%.2f", net * 1.19)) € brutto inkl. 19% USt")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }

                if art == "WEG" {
                    Section("Objekt") {
                        TextField("Straße + Nr.", text: $objectStreet)
                        TextField("PLZ + Ort", text: $objectPlzCity)
                    }
                } else {
                    Section("Auftraggeber") {
                        TextField("Auftraggeber", text: $recipientName)
                        TextField("Straße + Nr.", text: $recipientStreet)
                        TextField("PLZ + Ort", text: $recipientPlzCity)
                        TextField("Objekt", text: $object1)
                    }
                }

                if let error {
                    Section { Text(error).foregroundStyle(.red).font(.callout) }
                }
            }
            .navigationTitle("Angebot senden")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Abbrechen") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Senden") { Task { await submit() } }
                        .disabled(busy)
                }
            }
            .onAppear(perform: seed)
            .onChange(of: units) { _, _ in recomputePrice() }
            .onChange(of: art) { _, _ in recomputePrice() }
            .onChange(of: startDate) { _, _ in recomputeEnd() }
        }
    }

    private func seed() {
        art = ["MV", "SEV"].contains(detail.art ?? "") ? detail.art! : "WEG"
        units = detail.units != nil ? String(detail.units!) : ""
        startDate = offerDate(from: detail.desired_start) ?? offerDate(from: offerDefaultStartISO()) ?? Date()
        let (street, plz) = offerSplitAddress(detail.object_address)
        objectStreet = street
        objectPlzCity = plz
        recipientName = detail.sender_name ?? ""
        object1 = detail.object_address ?? ""
        recomputeEnd()
        recomputePrice()
        endTouched = false
        priceTouched = false
    }

    private func recomputePrice() {
        guard !priceTouched, let u = Int(units.trimmingCharacters(in: .whitespaces)) else { return }
        if let net = offerComputedMonthlyNet(art: art, units: u) {
            monthlyFee = String(format: "%.0f", net)
        }
    }

    private func recomputeEnd() {
        guard !endTouched, let end = offerDate(from: offerComputedEndISO(start: offerISO(from: startDate)))
        else { return }
        endDate = end
    }

    private func submit() async {
        guard let u = Int(units.trimmingCharacters(in: .whitespaces)) else {
            error = "Bitte Einheiten angeben."
            return
        }
        busy = true
        error = nil
        let fee = Double(monthlyFee.replacingOccurrences(of: ",", with: "."))
        let isWeg = art == "WEG"
        let body = OfferGenerateBody(
            art: art,
            variant: isWeg ? nil : variant,
            units: u,
            start_date: offerISO(from: startDate),
            end_date: offerISO(from: endDate),
            monthly_fee_net_override: fee,
            object_street: isWeg ? objectStreet : nil,
            object_plz_city: isWeg ? objectPlzCity : nil,
            recipient_name: isWeg ? nil : recipientName,
            recipient_street: isWeg ? nil : recipientStreet,
            recipient_plz_city: isWeg ? nil : recipientPlzCity,
            salutation: nil,
            objects: isWeg ? nil : [object1].filter { !$0.isEmpty }
        )
        do {
            _ = try await api.sendOffer(id: detail.id, body: body)
            onSent()
            dismiss()
        } catch {
            self.error = "Angebot konnte nicht gesendet werden."
        }
        busy = false
    }
}
