//
//  FahrtenListView.swift
//  WHV
//
//  The driver's own Fahrtenbuch, one month at a time, with km + Kilometergeld
//  totals. Tap a row to (re)confirm purpose/property, swipe to delete a
//  mis-detected trip.
//

import SwiftUI

struct FahrtenListView: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject private var tracker = TripTracker.shared
    private let api = APIClient()

    @State private var month: Date = Date()
    @State private var trips: [TripResponse] = []
    @State private var loading = false
    @State private var editing: TripResponse?
    @State private var editingPending: TripCompleteBody?
    @State private var error: String?

    var body: some View {
        List {
            Section {
                HStack {
                    Button { shift(-1) } label: { Image(systemName: "chevron.left") }
                    Spacer()
                    Text(month.formatted(.dateTime.month(.wide).year()))
                        .font(.headline)
                    Spacer()
                    Button { shift(1) } label: { Image(systemName: "chevron.right") }
                        .disabled(isCurrentMonth)
                }
                .buttonStyle(.plain)
                HStack {
                    stat("Fahrten", "\(trips.count)")
                    Divider()
                    stat("Strecke", TripFormat.km(trips.reduce(0) { $0 + ($1.distance_m ?? 0) }))
                    Divider()
                    stat("Kilometergeld", TripFormat.eur(trips.reduce(0) { $0 + $1.amount_cents }))
                }
                .frame(maxWidth: .infinity)
            }

            // Finished on the phone, not yet on the server: visible, deletable,
            // retryable — otherwise a queued test drive is invisible until it
            // suddenly uploads weeks later.
            if !tracker.pending.isEmpty {
                Section {
                    ForEach(tracker.pending, id: \.started_at) { b in
                        Button { editingPending = b } label: {
                            HStack(spacing: 12) {
                                Image(systemName: "icloud.and.arrow.up")
                                    .foregroundStyle(.orange)
                                    .frame(width: 24)
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(b.started_at.formatted(date: .abbreviated, time: .shortened))
                                    Text("\(TripPurpose.label(for: b.purpose)) · \(b.source) · wartet auf Upload")
                                        .font(.caption).foregroundStyle(.secondary)
                                }
                                Spacer()
                                Text(TripFormat.km(b.distance_m)).font(.body.monospacedDigit())
                            }
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .swipeActions {
                            Button(role: .destructive) {
                                tracker.discardPending(startedAt: b.started_at)
                            } label: { Label("Verwerfen", systemImage: "trash") }
                        }
                    }
                    Button {
                        Task { await tracker.retryPending(); await load() }
                    } label: {
                        Label("Jetzt hochladen", systemImage: "arrow.clockwise")
                    }
                } header: {
                    Text("Warten auf Upload (\(tracker.pending.count))")
                } footer: {
                    if let err = tracker.lastError { Text(err) }
                }
            }

            if trips.isEmpty, !loading, tracker.pending.isEmpty {
                ContentUnavailableView("Keine Fahrten", systemImage: "car",
                                       description: Text("In diesem Monat wurde nichts aufgezeichnet."))
            }

            ForEach(trips) { t in
                Button { editing = t } label: { row(t) }
                    .buttonStyle(.plain)
                    .swipeActions {
                        Button(role: .destructive) {
                            Task { await delete(t) }
                        } label: { Label("Löschen", systemImage: "trash") }
                    }
            }

            if let error {
                Section { Text(error).foregroundStyle(.red).font(.callout) }
            }
        }
        .navigationTitle("Meine Fahrten")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .confirmationAction) { Button("Fertig") { dismiss() } }
        }
        .task(id: month) { await load() }
        .refreshable { await load() }
        .sheet(item: $editing) { t in
            TripConfirmSheet(trip: t) { Task { await load() } }
        }
        .sheet(item: $editingPending) { b in
            TripConfirmSheet(pending: b) {}
        }
    }

    private func row(_ t: TripResponse) -> some View {
        HStack(spacing: 12) {
            Image(systemName: TripPurpose(rawValue: t.purpose ?? "")?.systemImage ?? "questionmark.circle")
                .foregroundStyle(t.isOpen ? .orange : .secondary)
                .frame(width: 24)
            VStack(alignment: .leading, spacing: 2) {
                Text(t.objectLabel ?? TripPurpose.label(for: t.purpose))
                    .font(.body)
                Text("\(t.started_at.formatted(date: .abbreviated, time: .shortened)) · \(TripPurpose.label(for: t.purpose))")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 2) {
                Text(TripFormat.km(t.distance_m)).font(.body.monospacedDigit())
                Text(TripFormat.eur(t.amount_cents)).font(.caption).foregroundStyle(.secondary)
            }
        }
        .contentShape(Rectangle())
    }

    private func stat(_ label: String, _ value: String) -> some View {
        VStack(spacing: 2) {
            Text(value).font(.subheadline.weight(.semibold).monospacedDigit())
            Text(label).font(.caption2).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
    }

    private var isCurrentMonth: Bool {
        Calendar.current.isDate(month, equalTo: Date(), toGranularity: .month)
    }

    private func shift(_ by: Int) {
        if let d = Calendar.current.date(byAdding: .month, value: by, to: month) { month = d }
    }

    private var monthKey: String {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM"
        return f.string(from: month)
    }

    private func load() async {
        loading = true
        error = nil
        do {
            trips = try await api.getMyTrips(month: monthKey)
        } catch {
            self.error = "Fahrten konnten nicht geladen werden."
        }
        loading = false
    }

    private func delete(_ t: TripResponse) async {
        do {
            try await api.deleteTrip(id: t.id)
            trips.removeAll { $0.id == t.id }
        } catch {
            self.error = "Löschen fehlgeschlagen."
        }
    }
}
