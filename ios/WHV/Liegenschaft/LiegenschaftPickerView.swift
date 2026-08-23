// Startup screen — the user picks one Liegenschaft, the rest of
// the app then operates in its context.
//
// Shown only when LiegenschaftStore.selected is nil. After Save the
// store flips selected to a value, WHVApp re-evaluates and swaps the
// root from this view to RootTabView. The picker is a NavigationStack
// at root so the "wechseln" path back here (from Einstellungen)
// renders identically.

import SwiftUI

struct LiegenschaftPickerView: View {
    @EnvironmentObject var store: LiegenschaftStore

    var body: some View {
        NavigationStack {
            content
                .navigationTitle("Liegenschaft wählen")
                .navigationBarTitleDisplayMode(.large)
                .toolbar {
                    ToolbarItem(placement: .topBarTrailing) {
                        Button {
                            Task { await store.load() }
                        } label: {
                            Image(systemName: "arrow.clockwise")
                        }
                        .disabled(store.isLoading)
                    }
                }
                .task {
                    if store.available.isEmpty {
                        await store.load()
                    }
                }
        }
    }

    @ViewBuilder
    private var content: some View {
        if store.isLoading && store.available.isEmpty {
            VStack(spacing: 12) {
                ProgressView()
                Text("Liegenschaften werden geladen …")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if let err = store.lastError, store.available.isEmpty {
            VStack(spacing: 12) {
                Image(systemName: "exclamationmark.triangle")
                    .font(.system(size: 48))
                    .foregroundStyle(.tertiary)
                Text("Liegenschaften konnten nicht geladen werden.")
                    .font(.headline)
                Text(err)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                Button("Erneut versuchen") {
                    Task { await store.load() }
                }
                .buttonStyle(.borderedProminent)
            }
            .padding()
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if store.available.isEmpty {
            ContentUnavailableView(
                "Keine Liegenschaften",
                systemImage: "building.2",
                description: Text("Ihr Konto ist noch nicht mit einer Liegenschaft verknüpft. Bitte wenden Sie sich an die Verwaltung.")
            )
        } else {
            List {
                Section {
                    ForEach(store.available) { l in
                        Button {
                            store.select(l)
                        } label: {
                            row(for: l)
                        }
                        .foregroundStyle(.primary)
                        .listRowBackground(PropertyBackground())
                    }
                } header: {
                    Text("Ihre Liegenschaften")
                }
            }
        }
    }

    private func row(for l: Liegenschaft) -> some View {
        HStack(alignment: .center, spacing: 12) {
            Image(systemName: l.hasOwnershipShares ? "building.2" : "house")
                .font(.system(size: 22))
                .foregroundStyle(.tint)
                .frame(width: 32)
            VStack(alignment: .leading, spacing: 2) {
                Text(l.name)
                    .font(.headline)
                Text(l.address)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                if l.type != nil {
                    Text(l.typeLongLabel)
                        .font(.caption)
                        .foregroundStyle(.tertiary)
                        .padding(.top, 2)
                }
            }
            Spacer(minLength: 0)
            Image(systemName: "chevron.right")
                .font(.caption.bold())
                .foregroundStyle(.tertiary)
        }
        .padding(.vertical, 4)
    }
}

#Preview {
    LiegenschaftPickerView()
        .environmentObject(LiegenschaftStore())
}
