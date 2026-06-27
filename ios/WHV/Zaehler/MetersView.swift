// Zähler — member-facing meter list + reading capture (ADR-0016).
//
// Presented as a sheet from PropertyDetailView's Schnellzugriff. Lists the
// property's active meters; tapping one opens its history + a "Stand
// melden" flow that photographs the meter (camera or library), OCRs the
// value server-side to pre-fill it, and submits after the user confirms.

import PhotosUI
import SwiftUI

private let isoDayFormatter: DateFormatter = {
    let f = DateFormatter()
    f.locale = Locale(identifier: "en_US_POSIX")
    f.dateFormat = "yyyy-MM-dd"
    return f
}()

private func germanDay(_ iso: String?) -> String {
    guard let iso, let date = isoDayFormatter.date(from: iso) else { return iso ?? "—" }
    let out = DateFormatter()
    out.locale = Locale(identifier: "de_DE")
    out.dateStyle = .medium
    return out.string(from: date)
}

private let germanDueFormatter: DateFormatter = {
    let f = DateFormatter()
    f.locale = Locale(identifier: "de_DE")
    f.dateFormat = "dd.MM.yyyy"
    return f
}()

/// "Fällig bis 30.06.2026" — the German short-date deadline label for a
/// due-soon meter. Falls back to the raw ISO string if parsing fails.
func germanDueShort(_ date: Date?) -> String {
    guard let date else { return "—" }
    return germanDueFormatter.string(from: date)
}

private func numberString(_ value: Double) -> String {
    let f = NumberFormatter()
    f.locale = Locale(identifier: "de_DE")
    f.maximumFractionDigits = 3
    return f.string(from: NSNumber(value: value)) ?? String(value)
}

// MARK: - List

struct MetersView: View {
    let propertyId: String

    @State private var meters: [MeterSummary] = []
    @State private var isLoading = true
    @State private var error: String?

    private let api = APIClient()

    var body: some View {
        NavigationStack {
            Group {
                if isLoading {
                    ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
                } else if let error {
                    ContentUnavailableView(
                        "Zähler nicht geladen", systemImage: "gauge.badge.xmark", description: Text(error))
                } else if meters.isEmpty {
                    ContentUnavailableView(
                        "Keine Zähler",
                        systemImage: "gauge.medium",
                        description: Text("Für diese Liegenschaft sind noch keine Zähler hinterlegt.")
                    )
                } else {
                    List(meters) { meter in
                        NavigationLink(destination: MeterDetailView(meter: meter)) {
                            MeterRow(meter: meter)
                        }
                        // Due-soon meters get the red frame + orange fill
                        // drawn behind the whole row; clear the default list
                        // row background so the accent shows through.
                        .listRowBackground(
                            Group {
                                if meter.isReadingDueSoon {
                                    RoundedRectangle(cornerRadius: 10)
                                        .fill(Color.orange.opacity(0.15))
                                        .overlay(
                                            RoundedRectangle(cornerRadius: 10)
                                                .stroke(Color.red, lineWidth: 1.5)
                                        )
                                        .padding(.vertical, 2)
                                }
                            }
                        )
                    }
                }
            }
            .navigationTitle("Zähler")
            .navigationBarTitleDisplayMode(.inline)
            .task { await load() }
            .refreshable { await load() }
        }
    }

    private func load() async {
        if meters.isEmpty { isLoading = true }
        do {
            meters = try await api.listMeters(propertyId: propertyId)
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
        isLoading = false
    }
}

private struct MeterRow: View {
    let meter: MeterSummary

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: meter.type.systemImage)
                .font(.title3)
                .foregroundStyle(.white)
                .frame(width: 36, height: 36)
                .background(Color.accentColor)
                .clipShape(RoundedRectangle(cornerRadius: 8))
            VStack(alignment: .leading, spacing: 2) {
                Text(meter.meter_number).font(.subheadline.weight(.semibold))
                Text(
                    [meter.type.label, meter.description].compactMap { $0 }.joined(separator: " · ")
                )
                .font(.caption)
                .foregroundStyle(.secondary)
                if let v = meter.latest_reading_value {
                    Text(
                        "Letzter Stand: \(numberString(v)) \(meter.unit_label ?? "") · \(germanDay(meter.latest_reading_on))"
                    )
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
                }
                if meter.isReadingDueSoon {
                    Text("Fällig bis \(germanDueShort(meter.readingDueDate))")
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(Color.red)
                }
            }
        }
        .padding(.vertical, 2)
    }
}

// MARK: - Detail + history

struct MeterDetailView: View {
    let meter: MeterSummary

    @State private var readings: [MeterReadingItem] = []
    @State private var isLoading = true
    @State private var showReport = false

    private let api = APIClient()

    var body: some View {
        List {
            Section {
                Button {
                    showReport = true
                } label: {
                    Label("Stand melden", systemImage: "gauge.with.dots.needle.bottom.50percent")
                }
            }

            Section("Verlauf") {
                if isLoading {
                    ProgressView()
                } else if readings.isEmpty {
                    Text("Noch keine Ablesungen.").foregroundStyle(.secondary)
                } else {
                    ForEach(readings) { r in
                        HStack {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(germanDay(r.read_on)).font(.subheadline)
                                Text(r.source == "OCR" ? "Foto" : "Manuell")
                                    .font(.caption2)
                                    .foregroundStyle(.secondary)
                            }
                            Spacer()
                            Text("\(numberString(r.value)) \(meter.unit_label ?? "")")
                                .font(.subheadline.weight(.semibold))
                            if r.has_photo {
                                Image(systemName: "photo").foregroundStyle(.secondary)
                            }
                        }
                    }
                }
            }
        }
        .navigationTitle(meter.meter_number)
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
        .sheet(isPresented: $showReport) {
            ReportReadingSheet(meter: meter) {
                Task { await load() }
            }
        }
    }

    private func load() async {
        do {
            readings = try await api.listMeterReadings(meterId: meter.id)
        } catch {
            readings = []
        }
        isLoading = false
    }
}

// MARK: - Report a reading

struct ReportReadingSheet: View {
    let meter: MeterSummary
    let onSaved: () -> Void

    @Environment(\.dismiss) private var dismiss

    @State private var imageData: Data?
    @State private var photosItem: PhotosPickerItem?
    @State private var showCamera = false
    @State private var value = ""
    @State private var readOn = Date()
    @State private var note = ""
    @State private var ocrBusy = false
    @State private var ocrApplied = false
    @State private var ocrHint: String?
    @State private var busy = false
    @State private var error: String?

    private let api = APIClient()

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text(
                        [meter.type.label, meter.meter_number, meter.description]
                            .compactMap { $0 }.joined(separator: " · ")
                    )
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                }

                Section("Foto") {
                    if CameraPicker.isAvailable {
                        Button {
                            showCamera = true
                        } label: {
                            Label(
                                imageData == nil ? "Foto aufnehmen" : "Neues Foto aufnehmen",
                                systemImage: "camera.fill")
                        }
                    }
                    PhotosPicker(selection: $photosItem, matching: .images) {
                        Label("Aus Mediathek", systemImage: "photo.on.rectangle")
                    }
                    if ocrBusy {
                        HStack(spacing: 8) {
                            ProgressView()
                            Text("Wert wird erkannt…").foregroundStyle(.secondary)
                        }
                    } else if let ocrHint {
                        Text(ocrHint)
                            .font(.caption)
                            .foregroundStyle(ocrApplied ? Color.green : Color.secondary)
                    } else if imageData != nil {
                        Label("Foto ausgewählt", systemImage: "checkmark.circle.fill")
                            .font(.caption)
                            .foregroundStyle(.green)
                    }
                }

                Section("Zählerstand") {
                    HStack {
                        TextField("Wert", text: $value)
                            .keyboardType(.decimalPad)
                            .onChange(of: value) { _, _ in ocrApplied = false }
                        if let unit = meter.unit_label, !unit.isEmpty {
                            Text(unit).foregroundStyle(.secondary)
                        }
                    }
                    DatePicker("Ablesedatum", selection: $readOn, displayedComponents: .date)
                    TextField("Notiz (optional)", text: $note, axis: .vertical)
                        .lineLimit(1...3)
                }

                if let error {
                    Section { Text(error).foregroundStyle(.red) }
                }
            }
            .navigationTitle("Stand melden")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Abbrechen") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Melden") { Task { await submit() } }
                        .disabled(busy || ocrBusy)
                }
            }
            .sheet(isPresented: $showCamera) {
                CameraPicker { data in
                    imageData = data
                    Task { await runOCR(data) }
                }
                .ignoresSafeArea()
            }
            .onChange(of: photosItem) { _, item in
                guard let item else { return }
                Task {
                    if let data = try? await item.loadTransferable(type: Data.self) {
                        imageData = data
                        await runOCR(data)
                    }
                }
            }
        }
    }

    private func runOCR(_ data: Data) async {
        ocrBusy = true
        ocrHint = nil
        ocrApplied = false
        defer { ocrBusy = false }
        do {
            let result = try await api.ocrMeterPhoto(meterId: meter.id, imageData: data)
            if !result.provider_available {
                ocrHint = "Automatische Erkennung nicht verfügbar — bitte Wert eintragen."
            } else if let suggested = result.suggested_value {
                value = numberString(suggested)
                ocrApplied = true
                ocrHint = "Wert aus Foto erkannt — bitte prüfen."
            } else {
                ocrHint = "Wert nicht sicher lesbar — bitte manuell eintragen."
            }
        } catch {
            ocrHint = "Erkennung fehlgeschlagen — bitte Wert eintragen."
        }
    }

    private func submit() async {
        let normalized = value.replacingOccurrences(of: ",", with: ".")
            .trimmingCharacters(in: .whitespaces)
        guard let numeric = Double(normalized), numeric >= 0 else {
            error = "Bitte einen gültigen Zählerstand eintragen."
            return
        }
        busy = true
        error = nil
        do {
            _ = try await api.submitMeterReading(
                meterId: meter.id,
                value: normalized,
                readOn: isoDayFormatter.string(from: readOn),
                note: note.isEmpty ? nil : note,
                source: ocrApplied ? "OCR" : "MANUAL",
                imageData: imageData
            )
            onSaved()
            dismiss()
        } catch {
            self.error = error.localizedDescription
        }
        busy = false
    }
}
