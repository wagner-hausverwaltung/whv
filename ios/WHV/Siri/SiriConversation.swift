//
//  SiriConversation.swift
//  WHV
//
//  Short-lived memory for "Frag WHV": Siri runs every intent standalone, so
//  "Telefonnummer von Weinberger im Eibenweg" → "und die Adresse?" would
//  otherwise lose both the vendor and the object. We keep the last few
//  turns (+ the object they were about) for a few minutes in UserDefaults
//  and replay them as `history` / reuse the object — the same multi-turn
//  contract the web assistant uses (conversation_id groups the turns in the
//  Verwalter's assistant log).
//

import Foundation

struct SiriConversation: Codable {
    struct Turn: Codable {
        let role: String  // "user" | "assistant"
        let content: String
    }

    var conversationId: String
    var propertyId: String?
    var turns: [Turn]
    var updatedAt: Date

    static let ttl: TimeInterval = 10 * 60
    static let maxTurns = 6
    private static let key = "WHV.siriAssistantConversation"

    /// The live conversation, or nil when the last exchange is older than
    /// `ttl` (a new topic gets a fresh id).
    static func current(now: Date = Date()) -> SiriConversation? {
        guard let data = UserDefaults.standard.data(forKey: key),
              let c = try? JSONDecoder().decode(SiriConversation.self, from: data),
              now.timeIntervalSince(c.updatedAt) <= ttl
        else { return nil }
        return c
    }

    static func record(
        conversationId: String,
        question: String,
        answer: String,
        propertyId: String?,
        now: Date = Date()
    ) {
        var c = current(now: now) ?? SiriConversation(
            conversationId: conversationId, propertyId: nil, turns: [], updatedAt: now
        )
        c.turns.append(Turn(role: "user", content: question))
        c.turns.append(Turn(role: "assistant", content: answer))
        c.turns = Array(c.turns.suffix(maxTurns))
        if let propertyId { c.propertyId = propertyId }
        c.updatedAt = now
        if let data = try? JSONEncoder().encode(c) {
            UserDefaults.standard.set(data, forKey: key)
        }
    }

    static func clear() {
        UserDefaults.standard.removeObject(forKey: key)
    }
}
