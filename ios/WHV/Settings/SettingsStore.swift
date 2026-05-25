// Appearance + language preferences. Both default to "System" —
// the iOS-canonical behaviour where the app mirrors device-level
// Settings → Display & Brightness / Settings → General → Language.
//
// Persisted in UserDefaults so a user who explicitly overrides
// keeps that override across launches. SwiftUI consumes
// `colorScheme` directly (via .preferredColorScheme); the locale
// is applied via .environment(\.locale, ...) at the root level.

import SwiftUI

enum AppearancePreference: String, CaseIterable, Identifiable, Codable {
    case system
    case light
    case dark

    var id: String { rawValue }
    var label: String {
        switch self {
        case .system: return "System"
        case .light: return "Hell"
        case .dark: return "Dunkel"
        }
    }

    /// Map to SwiftUI's `ColorScheme?` — nil means "follow the
    /// system / parent setting", which is what we want for `.system`.
    var colorScheme: ColorScheme? {
        switch self {
        case .system: return nil
        case .light: return .light
        case .dark: return .dark
        }
    }
}

/// English localisation isn't shipped on iOS yet — every visible
/// string in the codebase is hardcoded German. Keeping the cases
/// reduced to `system` + `de` so the Settings picker doesn't lie
/// to the user about an English mode that wouldn't change
/// anything. The full i18n pipeline (Localizable.xcstrings + run
/// every string through a key) is a separate workstream.
enum LanguagePreference: String, CaseIterable, Identifiable, Codable {
    case system
    case de

    var id: String { rawValue }
    var label: String {
        switch self {
        case .system: return "System"
        case .de: return "Deutsch"
        }
    }

    /// Map to a SwiftUI `Locale`. `.system` returns nil so we don't
    /// override — SwiftUI then uses Locale.current via the
    /// environment.
    var locale: Locale? {
        switch self {
        case .system: return nil
        case .de: return Locale(identifier: "de")
        }
    }
}

@MainActor
final class SettingsStore: ObservableObject {
    @Published var appearance: AppearancePreference {
        didSet { defaults.set(appearance.rawValue, forKey: appearanceKey) }
    }

    @Published var language: LanguagePreference {
        didSet { defaults.set(language.rawValue, forKey: languageKey) }
    }

    private let defaults: UserDefaults
    private let appearanceKey = "WHV.appearance"
    private let languageKey = "WHV.language"

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        self.appearance =
            AppearancePreference(rawValue: defaults.string(forKey: appearanceKey) ?? "")
            ?? .system
        self.language =
            LanguagePreference(rawValue: defaults.string(forKey: languageKey) ?? "")
            ?? .system
    }
}
