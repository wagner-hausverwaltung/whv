//
//  CallDirectoryHandler.swift
//  WHVCallDirectory
//
//  CallKit Call Directory Extension: labels incoming calls from owners,
//  tenants and vendors with name · object · role. The list comes from the
//  app (app-group file written by CallDirectorySync); CallKit calls
//  beginRequest when the app asks for a reload or at system discretion.
//  Entries MUST be added in ascending numeric order — the store sorts.
//

import CallKit
import Foundation

final class CallDirectoryHandler: CXCallDirectoryProvider {
    override func beginRequest(with context: CXCallDirectoryExtensionContext) {
        context.delegate = self
        // We always rebuild from the full snapshot (it is small); on an
        // incremental request that means clearing first.
        if context.isIncremental {
            context.removeAllIdentificationEntries()
        }
        let entries = CallDirectoryStore.load()?.entries ?? []
        var last: Int64 = -1
        for e in entries where e.number > last {
            context.addIdentificationEntry(
                withNextSequentialPhoneNumber: CXCallDirectoryPhoneNumber(e.number),
                label: e.label
            )
            last = e.number
        }
        context.completeRequest()
    }
}

extension CallDirectoryHandler: CXCallDirectoryExtensionContextDelegate {
    func requestFailed(for extensionContext: CXCallDirectoryExtensionContext, withError error: Error) {
        // Nothing to do here — the app shows the enabled/disabled status
        // and offers a retry in Einstellungen.
    }
}
