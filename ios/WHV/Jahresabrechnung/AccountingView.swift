// Jahresabrechnung progress tracker — the member-facing surface. A small
// progress bar on the Liegenschaft (Start) tab shows how far this property's
// annual accounting (last calendar year) has come; tapping opens the stage
// detail. Verwalter can tick stages there; owners see it read-only. v1 mirrors
// the paper Kanban (all-manual A–I); auto-signals/todos come later.

import SwiftUI

// MARK: - Models

struct AccountingStage: Codable, Identifiable, Hashable {
    let code: String
    let label: String
    let done: Bool
    let done_at: String?
    let note: String?
    var id: String { code }
}

struct AccountingProgress: Codable, Hashable {
    let property_id: String
    let year: Int
    let done_count: Int
    let total: Int
    let stages: [AccountingStage]

    var fraction: Double { total > 0 ? Double(done_count) / Double(total) : 0 }

    static func demo(year: Int) -> AccountingProgress {
        let labels = [
            "A": "Zählerstände gemeldet", "B": "Rechnungen Energieversorger vorhanden",
            "C": "Kostenaufstellung erstellt und versendet", "D": "Kostenaufstellung eingegangen",
            "E": "Abrechnung erstellt", "F": "Abrechnung geprüft", "G": "Abrechnung versendet",
            "H": "Eigentümerversammlung geplant", "I": "Eigentümerversammlung erledigt / Protokoll versendet",
        ]
        let doneCodes = Set(["A", "B", "C"])
        let stages = ["A", "B", "C", "D", "E", "F", "G", "H", "I"].map {
            AccountingStage(
                code: $0, label: labels[$0] ?? $0, done: doneCodes.contains($0),
                done_at: doneCodes.contains($0) ? "2026-02-14T00:00:00Z" : nil, note: nil
            )
        }
        return AccountingProgress(
            property_id: "demo", year: year, done_count: doneCodes.count, total: 9, stages: stages
        )
    }
}

struct AccountingStageBody: Encodable {
    let done: Bool
    let note: String?
}

/// The Wirtschaftsjahr currently being settled = last calendar year (the 2025
/// bar appears from 1 Jan 2026). Mirrors the backend default.
func activeAccountingYear() -> Int { Calendar.current.component(.year, from: Date()) - 1 }

/// "2026-02-14T…" or "2026-02-14" → "14.02.2026".
private func accDate(_ s: String?) -> String? {
    guard let s, s.count >= 10 else { return nil }
    let p = s.prefix(10).split(separator: "-")
    return p.count == 3 ? "\(p[2]).\(p[1]).\(p[0])" : nil
}

// MARK: - Start-tab card

struct AccountingProgressCard: View {
    let propertyId: String
    @State private var progress: AccountingProgress?
    private let api = APIClient()
    private var year: Int { activeAccountingYear() }

    var body: some View {
        NavigationLink {
            AccountingDetailView(propertyId: propertyId, year: year)
        } label: {
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Label("Jahresabrechnung \(String(year))", systemImage: "doc.text.magnifyingglass")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(.primary)
                    Spacer()
                    if let p = progress {
                        Text("\(p.done_count)/\(p.total)")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(.secondary)
                    }
                    Image(systemName: "chevron.right")
                        .font(.caption.weight(.bold))
                        .foregroundStyle(.tertiary)
                }
                ProgressView(value: progress?.fraction ?? 0)
                    .tint(.green)
            }
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: 10).fill(Color(.secondarySystemBackground))
            )
        }
        .buttonStyle(.plain)
        .task(id: propertyId) { await load() }
    }

    private func load() async {
        progress = try? await api.getAccountingProgress(propertyId: propertyId, year: year)
    }
}

// MARK: - Detail

struct AccountingDetailView: View {
    let propertyId: String
    let year: Int
    @EnvironmentObject var authStore: AuthStore
    private let api = APIClient()

    @State private var progress: AccountingProgress?
    @State private var loading = true
    @State private var busyCode: String?
    @State private var error: String?

    private var isVerwalter: Bool { authStore.user?.role.lowercased() == "verwalter" }

    var body: some View {
        List {
            if let p = progress {
                Section {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("\(p.done_count) von \(p.total) Schritten erledigt")
                            .font(.subheadline.weight(.semibold))
                        ProgressView(value: p.fraction).tint(.green)
                    }
                    .padding(.vertical, 4)
                }
                Section("Schritte") {
                    ForEach(p.stages) { stageRow($0) }
                }
                Section {
                    Text(isVerwalter
                        ? "Schritt antippen, um ihn als erledigt zu markieren."
                        : "Nur-Lese-Ansicht. Die Verwaltung pflegt den Fortschritt.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                if let error {
                    Section { Text(error).font(.caption).foregroundStyle(.red) }
                }
            } else if loading {
                ProgressView()
            } else {
                Text("Konnte nicht geladen werden.").foregroundStyle(.secondary)
            }
        }
        .navigationTitle("Jahresabrechnung \(String(year))")
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
    }

    @ViewBuilder
    private func stageRow(_ st: AccountingStage) -> some View {
        let row = HStack(alignment: .top, spacing: 12) {
            Image(systemName: st.done ? "checkmark.circle.fill" : "circle")
                .font(.title3)
                .foregroundStyle(st.done ? Color.green : Color.secondary)
            VStack(alignment: .leading, spacing: 2) {
                Text("\(st.code) · \(st.label)").font(.subheadline)
                if st.done, let d = accDate(st.done_at) {
                    Text("erledigt am \(d)").font(.caption2).foregroundStyle(.secondary)
                }
                if let note = st.note, !note.isEmpty {
                    Text("„\(note)\u{201C}").font(.caption2).foregroundStyle(.secondary).italic()
                }
            }
            Spacer(minLength: 0)
            if busyCode == st.code { ProgressView().controlSize(.small) }
        }
        .contentShape(Rectangle())

        if isVerwalter {
            Button { Task { await toggle(st) } } label: { row }
                .buttonStyle(.plain)
                .disabled(busyCode != nil)
        } else {
            row
        }
    }

    private func load() async {
        loading = true
        progress = try? await api.getAccountingProgress(propertyId: propertyId, year: year)
        loading = false
    }

    private func toggle(_ st: AccountingStage) async {
        busyCode = st.code
        error = nil
        do {
            progress = try await api.setAccountingStage(
                propertyId: propertyId, year: year, code: st.code, done: !st.done
            )
        } catch {
            self.error = "Schritt konnte nicht gespeichert werden."
        }
        busyCode = nil
    }
}
