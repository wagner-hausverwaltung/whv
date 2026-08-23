//
//  CallDirectoryStore.swift
//  Shared between the WHV app (writer) and the WHVCallDirectory extension
//  (reader). The app fetches /me/call-directory and drops the list into the
//  app-group container; CallKit then loads the extension, which reads the
//  file and hands the numbers to the system. Kept deliberately tiny — the
//  extension runs under a hard memory limit.
//

import Foundation

public struct CallDirectoryEntry: Codable, Equatable {
    /// E.164 digits without "+", as CallKit wants it (CXCallDirectoryPhoneNumber).
    public let number: Int64
    public let label: String

    public init(number: Int64, label: String) {
        self.number = number
        self.label = label
    }
}

public struct CallDirectorySnapshot: Codable {
    public var generatedAt: Date
    /// Ascending by number, unique — the extension relies on that order.
    public var entries: [CallDirectoryEntry]

    public init(generatedAt: Date, entries: [CallDirectoryEntry]) {
        self.generatedAt = generatedAt
        self.entries = entries
    }
}

public enum CallDirectoryStore {
    public static let appGroup = "group.com.wagner-hausverwaltung.portal"
    public static let extensionIdentifier = "com.wagner-hausverwaltung.portal.calldirectory"
    static let fileName = "call-directory.json"

    static var fileURL: URL? {
        FileManager.default
            .containerURL(forSecurityApplicationGroupIdentifier: appGroup)?
            .appendingPathComponent(fileName)
    }

    public static func save(_ snapshot: CallDirectorySnapshot) throws {
        guard let url = fileURL else { throw CocoaError(.fileNoSuchFile) }
        var sorted = snapshot
        sorted.entries = snapshot.entries.sorted { $0.number < $1.number }
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        try encoder.encode(sorted).write(to: url, options: .atomic)
    }

    public static func load() -> CallDirectorySnapshot? {
        guard let url = fileURL, let data = try? Data(contentsOf: url) else { return nil }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return try? decoder.decode(CallDirectorySnapshot.self, from: data)
    }
}
