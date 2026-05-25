// Lock screen overlay. Shown by WHVApp when
// BiometricLockStore.isLocked == true. Blocks every interaction
// with the underlying UI and re-prompts on every tap.

import SwiftUI

struct BiometricLockView: View {
    @EnvironmentObject var store: BiometricLockStore

    var body: some View {
        ZStack {
            // Solid backdrop so the locked content doesn't leak
            // through. Using a Color rather than blur because
            // SwiftUI's .blur(radius:) on the underlying tab shell
            // is expensive on iPad and a flat surface reads as
            // "locked, deliberate" more clearly anyway.
            Color(.systemBackground)
                .ignoresSafeArea()

            VStack(spacing: 20) {
                Image(systemName: iconName)
                    .font(.system(size: 64, weight: .semibold))
                    .foregroundStyle(.tint)
                VStack(spacing: 8) {
                    Text("WHV gesperrt")
                        .font(.title2.bold())
                    Text(unlockHint)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                }
                Button {
                    Task { await store.authenticate() }
                } label: {
                    Label("Entsperren", systemImage: iconName)
                        .font(.headline)
                        .padding(.horizontal, 24)
                        .padding(.vertical, 12)
                }
                .buttonStyle(.borderedProminent)

                if let err = store.lastError {
                    Text(err)
                        .font(.caption)
                        .foregroundStyle(.red)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 32)
                }
            }
            .padding(.horizontal, 32)
        }
        .task {
            // Auto-trigger the prompt on first appearance so the
            // user doesn't have to tap a button before iOS shows
            // the Face ID sheet. If they cancel, the button stays
            // and they can re-attempt.
            await store.authenticate()
        }
    }

    private var iconName: String {
        switch store.biometryLabel {
        case "Face ID": return "faceid"
        case "Touch ID": return "touchid"
        default: return "lock.fill"
        }
    }

    private var unlockHint: String {
        let method = store.biometryLabel.isEmpty ? "Biometrie" : store.biometryLabel
        return "Bitte mit \(method) entsperren."
    }
}
