// Zähler — member-facing meter list + reading capture (ADR-0016).
//
// Presented as a sheet from PropertyDetailView's Schnellzugriff. Lists the
// property's active meters; tapping one opens its history + a "Stand
// melden" flow that photographs the meter (camera or library), OCRs the
// value server-side to pre-fill it, and submits after the user confirms.

import Charts
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

// MARK: - Verbrauch (consumption)

/// One consumption interval: the difference between two consecutive
/// cumulative meter readings, attributed to the interval's END date.
private struct ConsumptionPoint: Identifiable {
    let id: String  // the closing reading's id — stable & unique
    let date: Date  // the interval's end date (later reading's read_on)
    let value: Double  // reading[n].value − reading[n-1].value (always > 0)

    /// Calendar year of the interval's end date — used to group/colour
    /// bars year-over-year. String so it reads as a discrete category.
    var year: String { String(Calendar.current.component(.year, from: date)) }
}

/// Build the consumption series from raw readings.
///
/// - Sort readings ascending by `read_on`.
/// - For each consecutive pair, the consumption is the cumulative-value
///   delta `value[n] − value[n-1]`, dated to the later reading.
/// - Non-positive deltas are skipped: a decrease means a meter reset /
///   Zählerwechsel / rollover, not real consumption.
/// - With fewer than two readings there are no pairs, so the result is
///   empty and the caller hides the chart.
private func consumptionPoints(from readings: [MeterReadingItem]) -> [ConsumptionPoint] {
    let sorted =
        readings
        .compactMap { r -> (date: Date, item: MeterReadingItem)? in
            guard let d = isoDayFormatter.date(from: r.read_on) else { return nil }
            return (d, r)
        }
        .sorted { $0.date < $1.date }

    guard sorted.count >= 2 else { return [] }

    var points: [ConsumptionPoint] = []
    for i in 1..<sorted.count {
        let delta = sorted[i].item.value - sorted[i - 1].item.value
        guard delta > 0 else { continue }
        points.append(
            ConsumptionPoint(id: sorted[i].item.id, date: sorted[i].date, value: delta))
    }
    return points
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
                                            // strokeBorder draws the line INSIDE the
                                            // shape's bounds so the frame isn't clipped
                                            // at the row edges (plain stroke centers on
                                            // the edge → outer half gets cropped).
                                            RoundedRectangle(cornerRadius: 10)
                                                .strokeBorder(Color.red, lineWidth: 1.5)
                                        )
                                        .padding(.vertical, 2)
                                        .padding(.horizontal, 2)
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

    /// Consumption deltas between consecutive cumulative readings.
    private var consumption: [ConsumptionPoint] { consumptionPoints(from: readings) }

    var body: some View {
        List {
            Section {
                Button {
                    showReport = true
                } label: {
                    Label("Stand melden", systemImage: "gauge.with.dots.needle.bottom.50percent")
                }
            }

            Section("Verbrauch") {
                if isLoading {
                    ProgressView()
                } else if consumption.isEmpty {
                    Text("Noch keine Verbrauchsdaten")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                } else {
                    ConsumptionChart(
                        points: consumption,
                        unit: meter.unit_label ?? ""
                    )
                    .listRowInsets(EdgeInsets(top: 8, leading: 8, bottom: 8, trailing: 12))
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

// MARK: - Consumption chart

/// Bar chart of per-interval consumption. Bars are grouped/coloured by
/// calendar year so multiple years read as distinct year-over-year series;
/// a single year stays clean (one colour, legend still labels the year).
private struct ConsumptionChart: View {
    let points: [ConsumptionPoint]
    let unit: String

    /// Distinct years present, ascending — drives the legend and whether
    /// a legend is worth showing at all.
    private var years: [String] {
        Array(Set(points.map(\.year))).sorted()
    }

    /// "1.234 kWh" — German-formatted value with the meter's unit appended.
    private func valueLabel(_ value: Double) -> String {
        let n = numberString(value)
        return unit.isEmpty ? n : "\(n) \(unit)"
    }

    var body: some View {
        Chart(points) { point in
            BarMark(
                x: .value("Zeitraum", point.date, unit: .month),
                y: .value("Verbrauch", point.value)
            )
            .foregroundStyle(by: .value("Jahr", point.year))
        }
        .chartForegroundStyleScale(domain: years)
        .chartLegend(years.count > 1 ? .visible : .hidden)
        .chartYAxis {
            AxisMarks { value in
                AxisGridLine()
                AxisValueLabel {
                    if let v = value.as(Double.self) {
                        Text(valueLabel(v)).font(.caption2)
                    }
                }
            }
        }
        .chartXAxis {
            AxisMarks(values: .stride(by: .month, count: 3)) { _ in
                AxisGridLine()
                AxisTick()
                AxisValueLabel(format: .dateTime.month(.abbreviated), centered: false)
            }
        }
        .frame(height: 200)
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
    /// Backend plausibility warning (HTTP 409). When set, the
    /// "Ungewöhnlicher Wert" alert is shown with a "Trotzdem speichern"
    /// action that resubmits the same entry with `force: true`. Cleared
    /// on dismiss so the user can correct the value and try again.
    @State private var plausibilityWarning: String?

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
            // Plausibility soft-block (HTTP 409): the backend flagged the
            // value as unusual. Offer to save anyway (force) or go back and
            // fix it. "Abbrechen" keeps the entry so the user can correct it.
            .alert(
                "Ungewöhnlicher Wert",
                isPresented: Binding(
                    get: { plausibilityWarning != nil },
                    set: { if !$0 { plausibilityWarning = nil } }
                ),
                presenting: plausibilityWarning
            ) { _ in
                Button("Trotzdem speichern") {
                    plausibilityWarning = nil
                    Task { await submit(force: true) }
                }
                Button("Abbrechen", role: .cancel) {
                    plausibilityWarning = nil
                }
            } message: { message in
                Text(message)
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

    /// Submit the entered reading. `force` overrides the backend's
    /// plausibility soft-block: the first attempt is `force: false`; an
    /// `APIError.implausibleReading` (HTTP 409) raises the "Ungewöhnlicher
    /// Wert" alert, whose "Trotzdem speichern" action re-calls this with
    /// `force: true`. On the forced retry any further (non-409) error
    /// surfaces normally. A 201 dismisses the sheet either way.
    private func submit(force: Bool = false) async {
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
                imageData: imageData,
                force: force
            )
            onSaved()
            dismiss()
        } catch let APIError.implausibleReading(message, _, _, _) {
            // Soft-block: keep the entry, ask the user to confirm or fix.
            plausibilityWarning = message
        } catch {
            self.error = error.localizedDescription
        }
        busy = false
    }
}
