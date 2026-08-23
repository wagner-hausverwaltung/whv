//
//  WatchHomeView.swift
//  WHVWatch
//

import SwiftUI

struct WatchHomeView: View {
    @EnvironmentObject private var bridge: WatchBridge
    @State private var ticketText = ""
    @State private var showTicket = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 10) {
                    statusCard
                    if bridge.state.isRunning {
                        Button { Task { await bridge.send("arrive") } } label: {
                            Label("Angekommen", systemImage: "flag.checkered")
                        }
                        .buttonStyle(.borderedProminent).tint(.green)
                        Button { Task { await bridge.send("stop") } } label: {
                            Label("Fahrt beenden", systemImage: "stop.circle.fill")
                        }
                        .buttonStyle(.bordered).tint(.red)
                    } else {
                        Button { Task { await bridge.send("start") } } label: {
                            Label("Fahrt starten", systemImage: "car.fill")
                        }
                        .buttonStyle(.borderedProminent)
                    }
                    Button { showTicket = true } label: {
                        Label("Ticket diktieren", systemImage: "mic.fill")
                    }
                    .buttonStyle(.bordered)
                    if let m = bridge.lastMessage {
                        Text(m).font(.footnote).foregroundStyle(.secondary).multilineTextAlignment(.center)
                    }
                }
                .padding(.horizontal, 4)
            }
            .navigationTitle("WHV")
            .overlay { if bridge.busy { ProgressView() } }
            .task { await bridge.refresh() }
            .sheet(isPresented: $showTicket) {
                TicketDictationView { text in
                    Task { await bridge.send("ticket", ["text": text]) }
                }
            }
        }
    }

    private var statusCard: some View {
        VStack(spacing: 4) {
            if !bridge.state.signedIn {
                Label("Auf dem iPhone anmelden", systemImage: "iphone")
                    .font(.footnote).foregroundStyle(.secondary)
            } else if bridge.state.isRunning {
                Text("Fahrt läuft").font(.headline)
                Text(km(bridge.state.distanceM)).font(.title2.monospacedDigit())
                if let d = bridge.state.destinationName {
                    Text(d).font(.footnote).foregroundStyle(.secondary).lineLimit(2)
                }
                if let s = bridge.state.startedAt {
                    Text("seit \(s.formatted(date: .omitted, time: .shortened))")
                        .font(.footnote).foregroundStyle(.secondary)
                }
            } else {
                Text("Keine Fahrt aktiv").font(.headline)
                if bridge.state.pendingUploads > 0 {
                    Text("\(bridge.state.pendingUploads) Fahrt(en) warten auf Upload")
                        .font(.footnote).foregroundStyle(.orange)
                }
            }
        }
        .frame(maxWidth: .infinity)
        .padding(8)
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 12))
    }

    private func km(_ m: Int) -> String {
        String(format: "%.1f km", Double(m) / 1000).replacingOccurrences(of: ".", with: ",")
    }
}

/// Dictation sheet: TextField on watchOS opens the system input (dictation
/// first on the wrist); "Senden" relays to the phone which creates the ticket
/// at the current object.
struct TicketDictationView: View {
    @Environment(\.dismiss) private var dismiss
    @State private var text = ""
    var onSend: (String) -> Void

    var body: some View {
        VStack(spacing: 10) {
            TextField("Was ist los?", text: $text, axis: .vertical)
                .lineLimit(3...5)
            Button("Ticket anlegen") {
                onSend(text)
                dismiss()
            }
            .buttonStyle(.borderedProminent)
            .disabled(text.trimmingCharacters(in: .whitespaces).count < 3)
        }
        .padding()
        .navigationTitle("WHV Ticket")
    }
}
