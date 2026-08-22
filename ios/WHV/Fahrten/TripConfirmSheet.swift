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
    let trip: TripResponse
    var onSaved: () -> Void

    @Environment(\.dismiss) private var dismiss
    private let api = APIClient()

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
                        Text(trip.started_at.formatted(date: .abbreviated, time: .shortened))
                        Spacer()
                        Text(TripFormat.km(trip.distance_m)).foregroundStyle(.secondary)
                    }
                    if trip.source == "AUTO" {
                        Text("Automatisch erkannt").font(.caption).foregroundStyle(.secondary)
                    }
                    if trip.inquiry_id != nil {
                        Label("Anfrage: \(trip.inquiry_address ?? "ohne Adresse")", systemImage: "binoculars")
                            .font(.caption).foregroundStyle(.secondary)
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
        purpose = trip.purpose.flatMap(TripPurpose.init(rawValue:))
        propertyId = trip.property_id
        note = trip.note ?? ""
        do {
            properties = try await api.getMyProperties()
        } catch {
            return
        }
        guard let end = trip.endCoordinate else { return }
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
        var body = TripUpdateBody(purpose: purpose.rawValue, note: note.isEmpty ? nil : note)
        if purpose.wantsProperty, let pid = propertyId {
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
        busy = false
    }
}
