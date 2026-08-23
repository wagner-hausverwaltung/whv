//
//  TripConfirmSheet.swift
//  WHV
//
//  After a trip: pick the purpose and confirm the property. The property is
//  pre-selected from the trip's end position (nearest managed property
//  within 300 m) so the common case is one tap on "Speichern".
//

import CoreLocation
import SwiftUI

struct TripConfirmSheet: View {
    /// What is being confirmed: a trip already on the server (PATCH) or one
    /// still waiting in the phone's upload queue (edited in place).
    enum Target {
        case server(TripResponse)
        case pending(TripCompleteBody)
    }

    let target: Target
    var onSaved: () -> Void

    init(trip: TripResponse, onSaved: @escaping () -> Void) {
        self.target = .server(trip)
        self.onSaved = onSaved
    }

    init(pending: TripCompleteBody, onSaved: @escaping () -> Void) {
        self.target = .pending(pending)
        self.onSaved = onSaved
    }

    @Environment(\.dismiss) private var dismiss
    private let api = APIClient()

    // Common view of both targets.
    private var startedAt: Date {
        switch target {
        case .server(let t): return t.started_at
        case .pending(let b): return b.started_at
        }
    }
    private var distanceM: Int? {
        switch target {
        case .server(let t): return t.distance_m
        case .pending(let b): return b.distance_m
        }
    }
    private var source: String {
        switch target {
        case .server(let t): return t.source
        case .pending(let b): return b.source
        }
    }
    private var endCoordinate: CLLocationCoordinate2D? {
        switch target {
        case .server(let t): return t.endCoordinate
        case .pending(let b): return b.endCoordinate
        }
    }
    private var initialPurpose: String? {
        switch target {
        case .server(let t): return t.purpose
        case .pending(let b): return b.purpose
        }
    }
    private var initialPropertyId: String? {
        switch target {
        case .server(let t): return t.property_id
        case .pending(let b): return b.property_id
        }
    }
    private var initialNote: String? {
        switch target {
        case .server(let t): return t.note
        case .pending(let b): return b.note
        }
    }
    private var inquiryAddress: String? {
        if case .server(let t) = target, t.inquiry_id != nil { return t.inquiry_address ?? "ohne Adresse" }
        return nil
    }
    private var isPending: Bool {
        if case .pending = target { return true }
        return false
    }

    @State private var purpose: TripPurpose?
    @State private var propertyId: String?
    @State private var note: String = ""
    @State private var properties: [PropertyResponse] = []
    @State private var suggestedId: String?
    @State private var busy = false
    @State private var error: String?

    private let suggestRadiusM = 300.0

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    HStack {
                        Text(startedAt.formatted(date: .abbreviated, time: .shortened))
                        Spacer()
                        Text(TripFormat.km(distanceM)).foregroundStyle(.secondary)
                    }
                    if source == "AUTO" {
                        Text("Automatisch erkannt").font(.caption).foregroundStyle(.secondary)
                    }
                    if let inquiryAddress {
                        Label("Anfrage: \(inquiryAddress)", systemImage: "binoculars")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                    if isPending {
                        Label("Wartet auf Upload — wird mit diesen Angaben hochgeladen.", systemImage: "icloud.and.arrow.up")
                            .font(.caption).foregroundStyle(.orange)
                    }
                } header: { Text("Fahrt") }

                Section("Zweck") {
                    ForEach(TripPurpose.allCases) { p in
                        Button {
                            purpose = p
                            if !p.wantsProperty { propertyId = nil }
                            else if propertyId == nil { propertyId = suggestedId }
                        } label: {
                            HStack {
                                Label(p.label, systemImage: p.systemImage)
                                    .foregroundStyle(.primary)
                                Spacer()
                                if purpose == p {
                                    Image(systemName: "checkmark").foregroundStyle(.tint)
                                }
                            }
                        }
                    }
                }

                if purpose?.wantsProperty ?? true {
                    Section {
                        Picker("Objekt", selection: $propertyId) {
                            Text("— kein Objekt —").tag(String?.none)
                            ForEach(sortedProperties, id: \.id) { p in
                                HStack {
                                    Text(p.name)
                                    if p.id == suggestedId { Text("· in der Nähe").foregroundStyle(.secondary) }
                                }
                                .tag(Optional(p.id))
                            }
                        }
                        .pickerStyle(.navigationLink)
                    } header: { Text("Objekt") } footer: {
                        if suggestedId != nil {
                            Text("Vorschlag aus der Endposition der Fahrt.")
                        }
                    }
                }

                Section("Notiz") {
                    TextField("optional", text: $note, axis: .vertical)
                        .lineLimit(1...3)
                }

                if let error {
                    Section { Text(error).foregroundStyle(.red).font(.callout) }
                }
            }
            .navigationTitle("Fahrt bestätigen")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Später") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Speichern") { Task { await save() } }
                        .disabled(purpose == nil || busy)
                }
            }
            .task { await load() }
        }
    }

    /// Suggested property first, then alphabetical.
    private var sortedProperties: [PropertyResponse] {
        properties.sorted { a, b in
            if a.id == suggestedId { return true }
            if b.id == suggestedId { return false }
            return a.name < b.name
        }
    }

    private func load() async {
        purpose = initialPurpose.flatMap(TripPurpose.init(rawValue:))
        propertyId = initialPropertyId
        note = initialNote ?? ""
        do {
            properties = try await api.getMyProperties()
        } catch {
            return
        }
        guard let end = endCoordinate else { return }
        // Nearest property within the radius becomes the suggestion.
        var best: (id: String, d: Double)?
        for p in properties {
            guard let lat = p.lat, let lng = p.lng else { continue }
            let d = haversineMeters(end, CLLocationCoordinate2D(latitude: lat, longitude: lng))
            if d <= suggestRadiusM, d < (best?.d ?? .infinity) { best = (p.id, d) }
        }
        suggestedId = best?.id
        if propertyId == nil { propertyId = suggestedId }
    }

    private func save() async {
        guard let purpose else { return }
        busy = true
        error = nil
        let pid = purpose.wantsProperty ? propertyId : nil
        switch target {
        case .pending(let b):
            TripTracker.shared.updatePending(
                startedAt: b.started_at, purpose: purpose.rawValue, propertyId: pid,
                note: note.isEmpty ? nil : note
            )
            onSaved()
            dismiss()
        case .server(let trip):
            var body = TripUpdateBody(purpose: purpose.rawValue, note: note.isEmpty ? nil : note)
            if let pid {
                body.property_id = pid
            } else {
                body.clearProperty = true
            }
            do {
                _ = try await api.updateTrip(id: trip.id, body: body)
                onSaved()
                dismiss()
            } catch {
                self.error = "Konnte nicht gespeichert werden."
            }
        }
        busy = false
    }
}
