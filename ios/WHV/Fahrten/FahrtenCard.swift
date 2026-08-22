//
//  FahrtenCard.swift
//  WHV
//
//  Start-tab card for Verwalter: Start/Stop a Dienstfahrt, see the live
//  distance, jump to open confirmations and the month's list. Sits above the
//  property content because it is the one thing the driver touches on the
//  way out the door.
//

import SwiftUI

struct FahrtenCard: View {
    @ObservedObject private var tracker = TripTracker.shared
    @State private var showList = false
    @State private var confirming: TripResponse?

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Label("Fahrtenbuch", systemImage: "car.fill")
                    .font(.headline)
                Spacer()
                Button("Meine Fahrten") { showList = true }
                    .font(.subheadline)
            }

            if !tracker.isAvailable {
                Text("Im Demo-Modus nicht verfügbar.")
                    .font(.footnote).foregroundStyle(.secondary)
            } else if tracker.isRunning {
                runningRow
            } else {
                idleRow
            }

            if !tracker.openTrips.isEmpty {
                Button {
                    confirming = tracker.openTrips.first
                } label: {
                    HStack {
                        Image(systemName: "questionmark.circle.fill")
                        Text(tracker.openTrips.count == 1
                             ? "1 Fahrt bestätigen"
                             : "\(tracker.openTrips.count) Fahrten bestätigen")
                        Spacer()
                        Image(systemName: "chevron.right").font(.caption)
                    }
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(.orange)
                }
                .buttonStyle(.plain)
            }

            if tracker.pendingUploads > 0 {
                Text("\(tracker.pendingUploads) Fahrt(en) warten auf Upload.")
                    .font(.caption2).foregroundStyle(.secondary)
            }
            if let err = tracker.lastError {
                Text(err).font(.caption2).foregroundStyle(.secondary)
            }
        }
        .padding(16)
        .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 16))
        .sheet(isPresented: $showList) {
            NavigationStack { FahrtenListView() }
        }
        .sheet(item: $confirming) { trip in
            TripConfirmSheet(trip: trip) {
                Task { await tracker.refreshOpen() }
            }
        }
        .task { await tracker.refreshOpen() }
    }

    private var runningRow: some View {
        HStack(spacing: 14) {
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Circle().fill(.green).frame(width: 8, height: 8)
                    Text("Fahrt läuft").font(.subheadline.weight(.semibold))
                    if tracker.source == "AUTO" {
                        Text("· automatisch").font(.caption).foregroundStyle(.secondary)
                    }
                }
                Text("\(TripFormat.km(tracker.liveDistanceM)) · seit \(tracker.startedAt.map { $0.formatted(date: .omitted, time: .shortened) } ?? "—")")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            Button(role: .destructive) {
                tracker.stopManually()
            } label: {
                Label("Beenden", systemImage: "stop.fill")
            }
            .buttonStyle(.borderedProminent)
            .tint(.red)
        }
    }

    private var idleRow: some View {
        HStack(spacing: 14) {
            VStack(alignment: .leading, spacing: 2) {
                Text(tracker.autoDetectEnabled ? "Fahrten werden automatisch erkannt" : "Keine Fahrt aktiv")
                    .font(.subheadline)
                if tracker.needsAlwaysForAutoDetect {
                    Text("Für die Erkennung im Hintergrund Standort auf „Immer“ stellen.")
                        .font(.caption2).foregroundStyle(.orange)
                }
            }
            Spacer()
            Button {
                tracker.startManually()
            } label: {
                Label("Fahrt starten", systemImage: "play.fill")
            }
            .buttonStyle(.borderedProminent)
        }
    }
}
