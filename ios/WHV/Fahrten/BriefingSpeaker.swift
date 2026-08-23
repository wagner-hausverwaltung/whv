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
        let utterance = AVSpeechUtterance(string: text)
        utterance.voice = AVSpeechSynthesisVoice(language: "de-DE")
        utterance.rate = AVSpeechUtteranceDefaultSpeechRate
        utterance.prefersAssistiveTechnologySettings = false
        isSpeaking = true
        synth.speak(utterance)
    }

    func stop() {
        synth.stopSpeaking(at: .immediate)
        isSpeaking = false
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        Task { @MainActor in
            self.isSpeaking = false
            try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        }
    }

    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) {
        Task { @MainActor in self.isSpeaking = false }
    }
}
