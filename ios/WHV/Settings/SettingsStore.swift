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

enum LanguagePreference: String, CaseIterable, Identifiable, Codable {
    case system
    case de
    case en

    var id: String { rawValue }
    var label: String {
        switch self {
        case .system: return "System"
        case .de: return "Deutsch"
        case .en: return "English"
        }
    }

    /// Map to a SwiftUI `Locale`. `.system` returns nil so the
    /// environment uses Locale.current; the manual cases force the
    /// bundle's localised strings from Localizable.xcstrings.
    var locale: Locale? {
        switch self {
        case .system: return nil
        case .de: return Locale(identifier: "de")
        case .en: return Locale(identifier: "en")
        }
    }
}

@MainActor
final class SettingsStore: ObservableObject {
    @Published var appearance: AppearancePreference {
        didSet { defaults.set(appearance.rawValue, forKey: appearanceKey) }
    }

    @Published var language: LanguagePreference {
        didSet {
            defaults.set(language.rawValue, forKey: languageKey)
            applyAppleLanguagesOverride()
        }
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
        // Pre-flight: persist whatever the stored preference resolves
        // to on every launch. We do this even on a fresh install
        // because if the user changes language inside the app, then
        // force-quits + reopens, the didSet above only fires when
        // they tap the picker — not on the next cold launch. Writing
        // here makes the override survive across launches.
        applyAppleLanguagesOverride()
    }

    /// Bridge the in-app language picker to iOS's actual localization
    /// pipeline. SwiftUI's `.environment(\.locale, …)` we set at the
    /// root only steers date / number / collation behaviour — it does
    /// NOT switch which `Localizable.xcstrings` translation `Text`
    /// resolves to. That decision is locked at process startup based
    /// on `Bundle.main.preferredLocalizations`, which iOS computes
    /// from `UserDefaults["AppleLanguages"]`.
    ///
    /// So: writing the user's pick into `AppleLanguages` is what
    /// actually changes the displayed strings — but the change only
    /// takes effect on the NEXT cold launch (a true force-quit, not
    /// just background→foreground; the bundle stays cached during
    /// suspension). EinstellungenView surfaces a "Neustart
    /// erforderlich" hint right under the language picker.
    ///
    /// `.system` clears the override so iOS falls back to the
    /// device-level Settings → General → Language order. The bundle
    /// is loaded against `Bundle.main.preferredLocalizations.first`,
    /// which on a German device is `de` automatically.
    private func applyAppleLanguagesOverride() {
        switch language {
        case .system:
            defaults.removeObject(forKey: "AppleLanguages")
        case .de:
            defaults.set(["de"], forKey: "AppleLanguages")
        case .en:
            defaults.set(["en"], forKey: "AppleLanguages")
        }
    }
}
