// Sheet that opens a new ticket — subject + body + category +
// optional Liegenschaft. Server defaults share_scope to PRIVATE
// which matches the iOS UX (no advanced scope toggle in v1).
//
// Category picker is sectioned to mirror the admin SPA's grouped
// Select dropdown so the casavi taxonomy reads the same on both
// surfaces.

import SwiftUI

@MainActor
final class NewTicketStore: ObservableObject {
    @Published private(set) var isSubmitting = false
    @Published var lastError: String?

    private let api: APIClient

    init(api: APIClient = APIClient()) {
        self.api = api
    }

    func create(
        subject: String,
        body: String,
        category: TicketCategory,
        propertyId: String?
    ) async -> TicketDetail? {
        lastError = nil
        let s = subject.trimmingCharacters(in: .whitespacesAndNewlines)
        let b = body.trimmingCharacters(in: .whitespacesAndNewlines)
        guard s.count >= 3 else {
            lastError = "Bitte einen Betreff eingeben (mind. 3 Zeichen)."
            return nil
        }
        guard b.count >= 3 else {
            lastError = "Bitte das Ticket kurz beschreiben (mind. 3 Zeichen)."
            return nil
        }
        isSubmitting = true
        defer { isSubmitting = false }
        do {
            return try await api.createMyTicket(
                subject: s,
                body: b,
                category: category,
                propertyId: propertyId
            )
        } catch let err as APIError {
            lastError = err.errorDescription
            return nil
        } catch {
            lastError = error.localizedDescription
            return nil
        }
    }
}

struct NewTicketSheet: View {
    var onCreated: (TicketDetail) -> Void

    @EnvironmentObject var liegenschaftStore: LiegenschaftStore
    @StateObject private var store = NewTicketStore()
    @Environment(\.dismiss) private var dismiss

    @State private var subject = ""
    @State private var ticketBody = ""
    @State private var category: TicketCategory = .allgemeinFrage
    @State private var propertyId: String? = nil

    var body: some View {
        NavigationStack {
            Form {
                Section("Betreff") {
                    TextField("Worum geht es?", text: $subject)
                }
                Section("Kategorie") {
                    Picker("Kategorie", selection: $category) {
                        ForEach(TicketCategory.grouped(), id: \.group) { group in
                            // Section header uses the localized
                            // groupLabel — the .group string itself
                            // is the German identity key.
                            Section(header: Text(group.items.first?.groupLabel ?? "Sonstiges")) {
                                ForEach(group.items, id: \.self) { cat in
                                    Text(cat.label).tag(cat)
                                }
                            }
                        }
                    }
                    .pickerStyle(.navigationLink)
                }
                Section("Liegenschaft") {
                    Picker("Liegenschaft", selection: $propertyId) {
                        Text("Keine Zuordnung").tag(String?.none)
                        ForEach(liegenschaftStore.available) { l in
                            Text(l.name).tag(String?.some(l.id))
                        }
                    }
                    .pickerStyle(.navigationLink)
                }
                Section("Beschreibung") {
                    TextField(
                        "Bitte beschreiben …",
                        text: $ticketBody,
                        axis: .vertical
                    )
                    .lineLimit(4...10)
                }
                if let err = store.lastError {
                    Section {
                        Text(err)
                            .font(.caption)
                            .foregroundStyle(.red)
                    }
                }
            }
            .navigationTitle("Neues Ticket")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Abbrechen") { dismiss() }
                        .disabled(store.isSubmitting)
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        Task {
                            if let created = await store.create(
                                subject: subject,
                                body: ticketBody,
                                category: category,
                                propertyId: propertyId
                            ) {
                                onCreated(created)
                                dismiss()
                            }
                        }
                    } label: {
                        if store.isSubmitting {
                            ProgressView()
                        } else {
                            Text("Senden")
                        }
                    }
                    .disabled(store.isSubmitting)
                }
            }
            .onAppear {
                // Default property to the active Liegenschaft if the
                // user has one selected — matches the mental model of
                // "I'm reporting something about my Liegenschaft."
                if propertyId == nil, let l = liegenschaftStore.selected {
                    propertyId = l.id
                }
            }
        }
    }
}

#Preview {
    NewTicketSheet { _ in }
        .environmentObject(LiegenschaftStore())
}
