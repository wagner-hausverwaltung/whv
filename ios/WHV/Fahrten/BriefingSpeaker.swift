//
//  BriefingSpeaker.swift
//  WHV
//
//  Reads the Objekt-Briefing aloud (AVSpeechSynthesizer, de-DE). In the car
//  the audio goes through the vehicle speakers and ducks whatever is
//  playing; on the phone through the speaker. Speech only — no media, so
//  this stays within what a Driving-Task app may do (disclosed in the
//  App Store review notes).
//
//  Voice quality: iOS ships a "compact" German voice by default, which is
//  the robotic one. Enhanced/premium voices sound far better but are an
//  opt-in download (Einstellungen → Bedienungshilfen → Gesprochene Inhalte →
//  Stimmen). We therefore pick the best INSTALLED German voice instead of
//  taking whatever `AVSpeechSynthesisVoice(language:)` hands us, and the
//  Fahrtenbuch settings section offers a shortcut to that download.
//

import AVFoundation
import Combine
import Foundation

struct BriefingSection: Codable, Hashable {
    let title: String
    let lines: [String]
}

struct BriefingResponse: Codable {
    let property_id: String
    let property_name: String
    let spoken: String
    let sections: [BriefingSection]
    let generated_at: Date
}

@MainActor
final class BriefingSpeaker: NSObject, ObservableObject, AVSpeechSynthesizerDelegate {
    static let shared = BriefingSpeaker()

    @Published private(set) var isSpeaking = false
    @Published private(set) var loadingFor: String?
    @Published private(set) var lastError: String?

    private let synth = AVSpeechSynthesizer()
    private let api = APIClient()

    private override init() {
        super.init()
        synth.delegate = self
    }

    /// Fetch + speak the briefing for a property; a second call while
    /// speaking stops it (toggle semantics for a single CarPlay row).
    func toggle(propertyId: String) async {
        if isSpeaking {
            stop()
            return
        }
        loadingFor = propertyId
        lastError = nil
        defer { loadingFor = nil }
        do {
            let b: BriefingResponse = try await api.getBriefing(propertyId: propertyId)
            speak(b.spoken)
        } catch {
            lastError = "Briefing konnte nicht geladen werden."
        }
    }

    func speak(_ text: String) {
        let session = AVAudioSession.sharedInstance()
        // Spoken audio: pause/duck music, route to the car when connected.
        try? session.setCategory(.playback, mode: .spokenAudio, options: [.duckOthers, .interruptSpokenAudioAndMixWithOthers])
        try? session.setActive(true)

        let voice = Self.preferredGermanVoice()
        let sentences = Self.spokenSentences(from: text)
        guard !sentences.isEmpty else { return }
        isSpeaking = true
        // One utterance per sentence: the synthesiser then breathes between
        // facts instead of racing through "Termine: A; B; C." in one breath.
        for (index, sentence) in sentences.enumerated() {
            let utterance = AVSpeechUtterance(string: sentence)
            utterance.voice = voice
            // A touch under the default (0.5): the briefing is dense —
            // dates, counts, names — and is heard once, while driving.
            utterance.rate = AVSpeechUtteranceDefaultSpeechRate * 0.94
            utterance.pitchMultiplier = 1.0
            utterance.postUtteranceDelay = index == sentences.count - 1 ? 0 : 0.28
            utterance.prefersAssistiveTechnologySettings = false
            synth.speak(utterance)
        }
    }

    func stop() {
        synth.stopSpeaking(at: .immediate)
        isSpeaking = false
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    // MARK: - Voice + text shaping

    /// Best German voice installed on this device: premium beats enhanced
    /// beats the built-in compact one. Siri's voices are off-limits to
    /// third-party apps, so they're filtered out rather than silently
    /// falling back. Nil ⇒ let the system choose (no German voice at all).
    static func preferredGermanVoice() -> AVSpeechSynthesisVoice? {
        if let cached = cachedVoice { return cached }
        let rank: (AVSpeechSynthesisVoice) -> Int = { voice in
            switch voice.quality {
            case .premium: return 3
            case .enhanced: return 2
            default: return 1
            }
        }
        let german = AVSpeechSynthesisVoice.speechVoices().filter {
            $0.language.hasPrefix("de") && !$0.identifier.localizedCaseInsensitiveContains("siri")
        }
        // Prefer de-DE over de-AT/de-CH, then quality, then a stable order so
        // the same device always speaks with the same voice.
        let best = german.max { a, b in
            let keyA = (a.language == "de-DE" ? 1 : 0, rank(a), a.identifier)
            let keyB = (b.language == "de-DE" ? 1 : 0, rank(b), b.identifier)
            return keyA < keyB
        }
        cachedVoice = best ?? AVSpeechSynthesisVoice(language: "de-DE")
        return cachedVoice
    }

    /// True when only the built-in compact voice is installed — the settings
    /// screen then points at the (free) download for a natural one.
    static var hasOnlyCompactGermanVoice: Bool {
        let german = AVSpeechSynthesisVoice.speechVoices().filter {
            $0.language.hasPrefix("de") && !$0.identifier.localizedCaseInsensitiveContains("siri")
        }
        return !german.isEmpty && german.allSatisfy { $0.quality == .default }
    }

    private nonisolated(unsafe) static var cachedVoice: AVSpeechSynthesisVoice?

    /// Split the briefing into utterance-sized pieces and smooth the bits
    /// that read badly aloud. The server sends compact prose
    /// ("Termine: A; B."); semicolons and colons get almost no pause from
    /// AVSpeech, so they become sentence boundaries here.
    static func spokenSentences(from text: String) -> [String] {
        var normalised = text
        for (needle, replacement) in [
            (": ", ", "),   // "Termine: A" → a comma actually pauses
            ("; ", ". "),   // list items become their own sentences
            (" · ", ", "),
            ("–", "bis"),
            ("—", ","),
        ] {
            normalised = normalised.replacingOccurrences(of: needle, with: replacement)
        }
        return normalised
            .split(whereSeparator: { $0 == "." || $0 == "!" || $0 == "?" || $0 == "\n" })
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
            // Put the full stop back so the synthesiser lands the cadence.
            .map { $0.hasSuffix(",") ? String($0.dropLast()) + "." : $0 + "." }
    }

    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        Task { @MainActor in
            // Several utterances per briefing — only settle once the queue
            // has actually run dry, otherwise the first sentence "ends" it.
            guard !self.synth.isSpeaking else { return }
            self.isSpeaking = false
            try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        }
    }

    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) {
        Task { @MainActor in self.isSpeaking = false }
    }
}
