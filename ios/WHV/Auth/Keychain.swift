// Tiny Keychain wrapper for JWT storage.
//
// We don't pull a third-party dep (KeychainAccess etc.) — the
// Security framework's surface is small and we only need three
// operations: read / write / delete a single string by key.
//
// Why Keychain vs. UserDefaults: tokens are bearer credentials.
// UserDefaults is a plist that any process with the app's sandbox
// can read; Keychain is encrypted-at-rest and survives app deletion
// only when we ask it to (we don't — see kSecAttrAccessible).
//
// Access policy is `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`:
//   - first-unlock: tokens are readable in the background after the
//     user unlocks once post-boot (lets push handlers refresh).
//   - this-device-only: never syncs via iCloud Keychain. Auth state
//     should re-establish on a new device, not transparently
//     teleport.

import Foundation
import Security

enum KeychainError: Error {
    case unexpectedStatus(OSStatus)
    case dataCorrupted
}

struct Keychain {
    let service: String

    init(service: String = "com.wagner-hausverwaltung.WHV.auth") {
        self.service = service
    }

    func write(_ value: String, for key: String) throws {
        guard let data = value.data(using: .utf8) else {
            throw KeychainError.dataCorrupted
        }
        // Upsert: SecItemAdd would fail with duplicate, so we
        // delete-then-add. The delete is forgiving (errSecItemNotFound
        // is fine on first write).
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key,
        ]
        SecItemDelete(query as CFDictionary)

        var addQuery = query
        addQuery[kSecValueData as String] = data
        addQuery[kSecAttrAccessible as String] =
            kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        let status = SecItemAdd(addQuery as CFDictionary, nil)
        guard status == errSecSuccess else {
            throw KeychainError.unexpectedStatus(status)
        }
    }

    func read(_ key: String) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        guard status == errSecSuccess,
              let data = item as? Data,
              let s = String(data: data, encoding: .utf8)
        else {
            return nil
        }
        return s
    }

    func delete(_ key: String) {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key,
        ]
        SecItemDelete(query as CFDictionary)
    }
}
