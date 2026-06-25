// Liegenschafts-Kalender (ADR-0018) — read-only month view for members.
// Presented as a sheet from PropertyDetailView. Shows the property's ETV
// dates + Winterdienst/Kehrwoche assignments; the owner's own duties are
// highlighted, and an ETV entry links to the assembly.

import SwiftUI
import UIKit

private let _isoDay: DateFormatter = {
    let f = DateFormatter()
    f.locale = Locale(identifier: "en_US_POSIX")
    f.dateFormat = "yyyy-MM-dd"
    return f
}()

// "Juni 2026" / "June 2026" — follows the device language.
private func monthTitle(_ year: Int, _ month: Int) -> String {
    let cal = Calendar(identifier: .gregorian)
    guard let date = cal.date(from: DateComponents(year: year, month: month, day: 1)) else {
        return "\(month)/\(year)"
    }
    let f = DateFormatter()
    f.locale = Locale.current
    f.setLocalizedDateFormatFromTemplate("LLLLyyyy")
    return f.string(from: date)
}

// Localized weekday abbreviations, Monday-first (Mo/Di… or Mon/Tue…).
private func weekdaySymbols() -> [String] {
    var cal = Calendar(identifier: .gregorian)
    cal.locale = Locale.current
    let syms = cal.shortStandaloneWeekdaySymbols  // index 0 = Sunday
    return Array(syms.dropFirst()) + [syms[0]]
}

private func kindColor(_ kind: String) -> Color {
    switch kind {
    case "ETV": return Color(red: 0.094, green: 0.388, blue: 0.863)
    case "WINTERDIENST": return Color(red: 0.054, green: 0.455, blue: 0.565)
    case "KEHRWOCHE": return Color(red: 0.082, green: 0.502, blue: 0.239)
    default: return Color(.systemGray)
    }
}

private func kindLabel(_ kind: String) -> String {
    switch kind {
    case "ETV": return "Eigentümerversammlung"
    case "WINTERDIENST": return "Winterdienst"
    case "KEHRWOCHE": return "Kehrwoche"
    default: return "Termin"
    }
}

private func spanLabel(_ e: CalendarEntry) -> String {
    func short(_ iso: String) -> String {
        guard let d = _isoDay.date(from: iso) else { return iso }
        let f = DateFormatter()
        f.locale = Locale(identifier: "de_DE")
        f.dateFormat = "dd.MM."
        return f.string(from: d)
    }
    if let end = e.ends_on, end != e.starts_on { return "\(short(e.starts_on))–\(short(end))" }
    return short(e.starts_on)
}

struct CalendarView: View {
    let propertyId: String

    @EnvironmentObject var authStore: AuthStore
    @State private var year = Calendar.current.component(.year, from: Date())
    @State private var month = Calendar.current.component(.month, from: Date())
    @State private var entries: [CalendarEntry] = []
    @State private var isLoading = true
    @State private var error: String?
    @State private var shareItem: ShareItem?

    private let api = APIClient()
    private let cols = Array(repeating: GridItem(.flexible(), spacing: 1), count: 7)

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 16) {
                    monthNav
                    grid
                    if isLoading {
                        ProgressView()
                    } else if !entries.isEmpty {
                        entryList
                    } else if error == nil {
                        Text("Keine Termine in diesem Monat.")
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                    if let error {
                        Text(error).font(.caption).foregroundStyle(.red)
                    }
                }
                .padding(16)
            }
            .navigationTitle("Kalender")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        Task {
                            if let url = try? await api.downloadCalendarIcs(propertyId: propertyId) {
                                shareItem = ShareItem(url: url)
                            }
                        }
                    } label: {
                        Image(systemName: "square.and.arrow.up")
                    }
                    .accessibilityLabel("Kalender exportieren")
                }
            }
            .task(id: "\(year)-\(month)") { await load() }
            .sheet(item: $shareItem) { item in
                ActivityView(url: item.url)
            }
        }
    }

    private var monthNav: some View {
        HStack {
            Button { shift(-1) } label: { Image(systemName: "chevron.left") }
            Spacer()
            Text(monthTitle(year, month)).font(.headline)
            Spacer()
            Button { shift(1) } label: { Image(systemName: "chevron.right") }
        }
    }

    private var grid: some View {
        LazyVGrid(columns: cols, spacing: 1) {
            ForEach(weekdaySymbols(), id: \.self) { d in
                Text(d)
                    .font(.caption2.weight(.semibold))
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 4)
                    .background(Color.accentColor)
                    .foregroundStyle(.white)
            }
            ForEach(cells.indices, id: \.self) { idx in
                dayCell(cells[idx])
            }
        }
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color(.separator)))
    }

    private func dayCell(_ day: Int?) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            if let day {
                Text("\(day)").font(.caption2).foregroundStyle(.secondary)
                ForEach(entriesFor(day).prefix(2)) { e in
                    Text(e.title)
                        .font(.system(size: 8))
                        .lineLimit(1)
                        .padding(.horizontal, 2)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(kindColor(e.kind).opacity(0.18))
                        .overlay(Rectangle().frame(width: 2).foregroundStyle(kindColor(e.kind)), alignment: .leading)
                }
            }
            Spacer(minLength: 0)
        }
        .frame(height: 60, alignment: .topLeading)
        .frame(maxWidth: .infinity)
        .padding(2)
        .background(day == nil ? Color(.systemGray6) : Color(.systemBackground))
    }

    private var entryList: some View {
        VStack(spacing: 8) {
            ForEach(entries.sorted { $0.starts_on < $1.starts_on }) { e in
                entryRow(e)
            }
        }
    }

    @ViewBuilder
    private func entryRow(_ e: CalendarEntry) -> some View {
        let mine = e.assigned_user_id != nil && e.assigned_user_id == authStore.user?.id
        let row = HStack(spacing: 10) {
            Text(spanLabel(e))
                .font(.caption)
                .foregroundStyle(.secondary)
                .frame(width: 64, alignment: .leading)
            Circle().fill(kindColor(e.kind)).frame(width: 8, height: 8)
            VStack(alignment: .leading, spacing: 1) {
                Text(e.title).font(.subheadline)
                if let label = e.assigned_label, !label.isEmpty {
                    Text(label).font(.caption2).foregroundStyle(.secondary)
                }
            }
            Spacer()
            if mine {
                Text("Ihre Aufgabe")
                    .font(.caption2.weight(.semibold))
                    .padding(.horizontal, 6)
                    .padding(.vertical, 2)
                    .background(Capsule().fill(Color.accentColor.opacity(0.15)))
                    .foregroundStyle(Color.accentColor)
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity)
        .background(RoundedRectangle(cornerRadius: 10).fill(Color(.secondarySystemBackground)))

        if e.source == "etv", let aid = e.assembly_id {
            NavigationLink(destination: AssemblyDetailView(assemblyId: aid)) { row }
                .buttonStyle(.plain)
        } else {
            row
        }
    }

    // MARK: - Month math

    private var cells: [Int?] {
        var cal = Calendar(identifier: .gregorian)
        cal.firstWeekday = 2  // Monday
        guard let first = cal.date(from: DateComponents(year: year, month: month, day: 1)),
            let range = cal.range(of: .day, in: .month, for: first)
        else { return [] }
        let weekday = cal.component(.weekday, from: first)  // 1=Sun … 7=Sat
        let lead = (weekday + 5) % 7  // Monday-first leading blanks
        var out: [Int?] = Array(repeating: nil, count: lead)
        out.append(contentsOf: range.map { Optional($0) })
        while out.count % 7 != 0 { out.append(nil) }
        return out
    }

    private func entriesFor(_ day: Int) -> [CalendarEntry] {
        let iso = String(format: "%04d-%02d-%02d", year, month, day)
        return entries.filter { $0.starts_on <= iso && ($0.ends_on ?? $0.starts_on) >= iso }
    }

    private func shift(_ delta: Int) {
        var m = month + delta
        var y = year
        if m < 1 { m = 12; y -= 1 }
        if m > 12 { m = 1; y += 1 }
        month = m
        year = y
    }

    private func load() async {
        isLoading = true
        do {
            entries = try await api.getCalendar(propertyId: propertyId, year: year, month: month)
            error = nil
        } catch {
            self.error = "Kalender konnte nicht geladen werden."
        }
        isLoading = false
    }
}

private struct ShareItem: Identifiable {
    let id = UUID()
    let url: URL
}

/// Share sheet for the exported .ics — lets the user "Add to Calendar" or
/// send it to Outlook / Mail / Files.
private struct ActivityView: UIViewControllerRepresentable {
    let url: URL
    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: [url], applicationActivities: nil)
    }
    func updateUIViewController(_ controller: UIActivityViewController, context: Context) {}
}
