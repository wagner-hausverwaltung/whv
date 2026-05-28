// Einstellungen tab.
//
// Six sections (top to bottom):
//   1. Konto            — email + role chip + Abmelden button
//   2. Liegenschaft     — active row, tap to switch (clears selection)
//   3. Erscheinungsbild — Light / Dark / System (drives the whole app)
//   4. Sprache          — DE / EN / System
//   5. Datenschutz      — DSGVO data export (ShareLink) + Konto löschen
//                         (alert-confirmed, signs out on success)
//   6. Rechtliches      — links to the marketing-site legal pages
//   7. App-Info         — version + build pulled from the bundle, plus
//                         a Verwaltung-Hotline row that mirrors the
//                         floating button for users who'd rather find
//                         it via the settings menu.

import SwiftUI

struct EinstellungenView: View {
    @EnvironmentObject var authStore: AuthStore
    @EnvironmentObject var liegenschaftStore: LiegenschaftStore
    @EnvironmentObject var settings: SettingsStore
    @EnvironmentObject var biometricLock: BiometricLockStore

    @StateObject private var dsgvo = DsgvoActionsStore()
    @StateObject private var prefs = NotificationPrefsStore()
    @State private var exportURL: URL?
    @State private var deletePrompt = false

    var body: some View {
        NavigationStack {
            List {
                liegenschaftSection
                appearanceSection
                languageSection
                sicherheitSection
                benachrichtigungenSection
                // Konto + Datenschutz cluster together at the
                // bottom — both are account-action pairs (sign out
                // up top, export + delete just below).
                kontoSection
                datenschutzSection
                rechtlichesSection
                infoSection
            }
            .navigationTitle("Einstellungen")
            .alert(
                "Konto löschen?",
                isPresented: $deletePrompt
            ) {
                Button("Abbrechen", role: .cancel) {}
                Button("Löschen", role: .destructive) {
                    Task {
                        await dsgvo.deleteAccount()
                        if dsgvo.lastError == nil {
                            authStore.signOut()
                        }
                    }
                }
            } message: {
                Text("Ihr Konto wird sofort deaktiviert und alle aktiven Sitzungen beendet. Die DSGVO-konforme endgültige Löschung erfolgt nach 30 Tagen.")
            }
            .sheet(
                item: Binding(
                    get: { dsgvo.exportURL.map(IdentifiableURL.init) },
                    set: { new in dsgvo.exportURL = new?.url }
                )
            ) { wrapped in
                ShareSheet(url: wrapped.url)
            }
            .task { await prefs.load() }
        }
    }

    // MARK: - Konto

    @ViewBuilder
    private var kontoSection: some View {
        if let user = authStore.user {
            Section("Konto") {
                VStack(alignment: .leading, spacing: 6) {
                    Text(user.email)
                        .font(.subheadline.weight(.semibold))
                    HStack(spacing: 8) {
                        Text(rolleLabel(user.role))
                            .font(.caption2.weight(.semibold))
                            .padding(.horizontal, 8)
                            .padding(.vertical, 3)
                            .background(roleBackground(user.role))
                            .foregroundStyle(roleForeground(user.role))
                            .clipShape(Capsule())
                    }
                }
                .padding(.vertical, 4)

                Button(role: .destructive) {
                    authStore.signOut()
                } label: {
                    Label("Abmelden", systemImage: "rectangle.portrait.and.arrow.right")
                }
            }
        }
    }

    private func rolleLabel(_ role: String) -> String {
        switch role.lowercased() {
        case "verwalter": return "Verwalter"
        case "eigentuemer": return "Eigentümer"
        case "mieter": return "Mieter"
        case "beirat": return "Beirat"
        case "dienstleister": return "Dienstleister"
        default: return role.capitalized
        }
    }

    private func roleBackground(_ role: String) -> Color {
        switch role.lowercased() {
        case "verwalter": return .accentColor
        case "beirat": return .green.opacity(0.18)
        default: return Color(.tertiarySystemFill)
        }
    }

    private func roleForeground(_ role: String) -> Color {
        switch role.lowercased() {
        case "verwalter": return .white
        case "beirat": return .green
        default: return .secondary
        }
    }

    // MARK: - Sections

    @ViewBuilder
    private var liegenschaftSection: some View {
        if let l = liegenschaftStore.selected {
            // Bare row in its own section so the library backdrop
            // stays clean — tap pushes the §8.3 detail screen
            // (address card + Verwaltung-Kontakt + units + quick
            // actions). "Liegenschaft wechseln" lives on the detail
            // page now rather than the tap action — discoverable
            // but not destructive on accidental taps.
            Section {
                NavigationLink {
                    PropertyDetailView(property: l)
                } label: {
                    HStack(spacing: 12) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(l.name)
                                .font(.headline)
                                .foregroundStyle(.primary)
                            Text(l.address)
                                .font(.subheadline)
                                .foregroundStyle(.secondary)
                        }
                        Spacer(minLength: 0)
                    }
                    .padding(.vertical, 2)
                }
                .listRowBackground(PropertyBackground())
            }
        }
    }

    private var appearanceSection: some View {
        Section("Erscheinungsbild") {
            Picker("Modus", selection: $settings.appearance) {
                ForEach(AppearancePreference.allCases) { p in
                    Text(p.label).tag(p)
                }
            }
            .pickerStyle(.segmented)
        }
    }

    private var languageSection: some View {
        Section {
            Picker("Sprache", selection: $settings.language) {
                ForEach(LanguagePreference.allCases) { p in
                    Text(p.label).tag(p)
                }
            }
            .pickerStyle(.segmented)
        } header: {
            Text("Sprache")
        } footer: {
            // iOS caches Bundle.main's localizations at process
            // startup, so a language switch only takes effect on a
            // true cold launch — not just background → foreground.
            // Surfaced inline rather than as a popup so the picker
            // doesn't feel broken when the labels don't change
            // immediately.
            Text("Die Sprachänderung wird erst nach einem vollständigen Neustart der App wirksam (App über den App-Switcher schließen und neu öffnen).")
        }
    }

    @ViewBuilder
    private var sicherheitSection: some View {
        if biometricLock.isAvailable {
            Section {
                Toggle(isOn: $biometricLock.enabled) {
                    Label(
                        biometricLock.biometryLabel.isEmpty
                            ? "App-Sperre"
                            : "App-Sperre mit \(biometricLock.biometryLabel)",
                        systemImage: biometryIcon
                    )
                }
            } header: {
                Text("Sicherheit")
            } footer: {
                Text("Die App wird gesperrt, wenn sie länger als eine Minute im Hintergrund war. Kurze Tab-Wechsel lösen keine Abfrage aus.")
            }
        }
    }

    private var biometryIcon: String {
        switch biometricLock.biometryLabel {
        case "Face ID": return "faceid"
        case "Touch ID": return "touchid"
        default: return "lock.fill"
        }
    }

    // MARK: - Benachrichtigungen
    //
    // Per-event Push / E-Mail matrix, backed by /me/notification-settings
    // (the same endpoint the web portal uses, so a change here follows
    // the user to the browser). Two labels-hidden toggles per row keep it
    // compact; a caption header aligns "Push" / "E-Mail" above them.

    @ViewBuilder
    private var benachrichtigungenSection: some View {
        Section {
            if !prefs.isLoaded && prefs.items.isEmpty {
                HStack {
                    ProgressView()
                    Text("Wird geladen…").foregroundStyle(.secondary)
                }
            } else {
                HStack(spacing: 0) {
                    Spacer()
                    Text("Push")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .frame(width: 56)
                    Text("E-Mail")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .frame(width: 56)
                }
                ForEach(NotificationPrefsStore.order, id: \.self) { cat in
                    if let idx = prefs.items.firstIndex(where: { $0.category == cat }) {
                        HStack(spacing: 0) {
                            Text(NotificationPrefsStore.label(for: cat))
                                .frame(maxWidth: .infinity, alignment: .leading)
                            Toggle(
                                "",
                                isOn: Binding(
                                    get: { prefs.items[idx].push },
                                    set: { v in
                                        Task { await prefs.set(category: cat, channel: .push, value: v) }
                                    }
                                )
                            )
                            .labelsHidden()
                            .frame(width: 56)
                            Toggle(
                                "",
                                isOn: Binding(
                                    get: { prefs.items[idx].email },
                                    set: { v in
                                        Task { await prefs.set(category: cat, channel: .email, value: v) }
                                    }
                                )
                            )
                            .labelsHidden()
                            .frame(width: 56)
                        }
                    }
                }
            }
        } header: {
            Text("Benachrichtigungen")
        } footer: {
            Text("Wählen Sie je Ereignis, ob Sie per Push (App) und/oder E-Mail benachrichtigt werden möchten.")
        }
    }

    @ViewBuilder
    private var datenschutzSection: some View {
        Section {
            Button {
                Task { await dsgvo.exportData() }
            } label: {
                HStack {
                    Label(
                        "Meine Daten exportieren",
                        systemImage: "arrow.down.doc"
                    )
                    Spacer()
                    if dsgvo.isExporting {
                        ProgressView()
                    }
                }
            }
            .disabled(dsgvo.isExporting)

            Button(role: .destructive) {
                deletePrompt = true
            } label: {
                HStack {
                    Label("Konto löschen", systemImage: "trash")
                    Spacer()
                    if dsgvo.isDeleting {
                        ProgressView()
                    }
                }
            }
            .disabled(dsgvo.isDeleting)

            if let err = dsgvo.lastError {
                Text(err)
                    .font(.caption)
                    .foregroundStyle(.red)
            }
        } header: {
            Text("Datenschutz")
        } footer: {
            Text("Export erfolgt nach DSGVO Art. 20 als JSON-Datei. Konto löschen deaktiviert Ihr Konto sofort; die endgültige Löschung erfolgt nach 30 Tagen.")
        }
    }

    private var rechtlichesSection: some View {
        Section("Rechtliches") {
            legalLink(
                "Impressum",
                url: "https://wagner-hausverwaltung.com/impressum"
            )
            legalLink(
                "Datenschutzerklärung",
                url: "https://wagner-hausverwaltung.com/datenschutz"
            )
            legalLink(
                "Cookie-Richtlinie (EU)",
                url: "https://wagner-hausverwaltung.com/cookie"
            )
        }
    }

    private var infoSection: some View {
        Section("App") {
            HStack {
                Text("Version")
                Spacer()
                Text(appVersionString)
                    .foregroundStyle(.secondary)
            }
        }
    }

    private var appVersionString: String {
        let info = Bundle.main.infoDictionary
        let version = info?["CFBundleShortVersionString"] as? String ?? "—"
        let build = info?["CFBundleVersion"] as? String ?? "—"
        return "\(version) (\(build))"
    }

    private func legalLink(_ label: String, url: String) -> some View {
        Link(destination: URL(string: url)!) {
            HStack {
                Text(label)
                    .foregroundStyle(.primary)
                Spacer()
                Image(systemName: "arrow.up.right.square")
                    .font(.caption)
                    .foregroundStyle(.tertiary)
            }
        }
    }
}

// MARK: - DSGVO actions store

@MainActor
final class DsgvoActionsStore: ObservableObject {
    @Published var exportURL: URL?
    @Published var lastError: String?
    @Published private(set) var isExporting = false
    @Published private(set) var isDeleting = false

    private let api: APIClient

    init(api: APIClient = APIClient()) {
        self.api = api
    }

    func exportData() async {
        lastError = nil
        isExporting = true
        defer { isExporting = false }
        do {
            self.exportURL = try await api.exportMyData()
        } catch let err as APIError {
            lastError = err.errorDescription
        } catch {
            lastError = error.localizedDescription
        }
    }

    func deleteAccount() async {
        lastError = nil
        isDeleting = true
        defer { isDeleting = false }
        do {
            try await api.deleteMyAccount()
        } catch let err as APIError {
            lastError = err.errorDescription
        } catch {
            lastError = error.localizedDescription
        }
    }
}

// MARK: - Notification preferences store

@MainActor
final class NotificationPrefsStore: ObservableObject {
    enum Channel { case push, email }

    @Published var items: [NotificationSetting] = []
    @Published private(set) var isLoaded = false
    @Published var lastError: String?

    private let api: APIClient

    init(api: APIClient = APIClient()) {
        self.api = api
    }

    func load() async {
        do {
            items = try await api.getNotificationSettings()
            isLoaded = true
        } catch let err as APIError {
            lastError = err.errorDescription
        } catch {
            lastError = error.localizedDescription
        }
    }

    /// Optimistically flip one channel for one category, then PUT the
    /// whole set. Reverts on failure so the toggle never lies.
    func set(category: String, channel: Channel, value: Bool) async {
        guard let idx = items.firstIndex(where: { $0.category == category }) else { return }
        let snapshot = items
        switch channel {
        case .push: items[idx].push = value
        case .email: items[idx].email = value
        }
        lastError = nil
        do {
            items = try await api.updateNotificationSettings(items)
        } catch let err as APIError {
            items = snapshot
            lastError = err.errorDescription
        } catch {
            items = snapshot
            lastError = error.localizedDescription
        }
    }

    /// Render order — mirrors the backend category enum.
    static let order = ["ANNOUNCEMENT", "TICKET", "ETV_COMMENT", "ETV_INVITATION", "DOCUMENT"]

    static func label(for category: String) -> String {
        switch category {
        case "ANNOUNCEMENT": return "Mitteilungen / News"
        case "TICKET": return "Anliegen / Tickets"
        case "ETV_COMMENT": return "ETV-Kommentare"
        case "ETV_INVITATION": return "ETV-Einladungen"
        case "DOCUMENT": return "Neue Dokumente"
        default: return category
        }
    }
}

// MARK: - URL wrapper + share sheet

/// SwiftUI's .sheet(item:) needs Identifiable. Plain URL isn't.
private struct IdentifiableURL: Identifiable {
    let url: URL
    var id: String { url.absoluteString }
}

private struct ShareSheet: UIViewControllerRepresentable {
    let url: URL

    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: [url], applicationActivities: nil)
    }

    func updateUIViewController(_ controller: UIActivityViewController, context: Context) {}
}
