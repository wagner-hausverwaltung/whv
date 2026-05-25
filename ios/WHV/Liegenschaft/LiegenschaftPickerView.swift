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
            List {
                Section {
                    ForEach(store.available) { l in
                        Button {
                            store.select(l)
                        } label: {
                            row(for: l)
                        }
                        .foregroundStyle(.primary)
                        // Library backdrop behind every Liegenschaft
                        // row. Same image for now; per-property
                        // image_url lands in Phase 2.
                        .listRowBackground(PropertyBackground())
                    }
                } header: {
                    Text("Ihre Liegenschaften")
                } footer: {
                    Text(
                        "Demo-Daten. In Phase 2 verbindet diese Liste sich "
                            + "automatisch mit Ihrem Konto."
                    )
                }
            }
            .navigationTitle("Liegenschaft wählen")
            .navigationBarTitleDisplayMode(.large)
        }
    }

    private func row(for l: Liegenschaft) -> some View {
        HStack(alignment: .center, spacing: 12) {
            Image(systemName: l.type?.contains("WEG") == true ? "building.2" : "house")
                .font(.system(size: 22))
                .foregroundStyle(.tint)
                .frame(width: 32)
            VStack(alignment: .leading, spacing: 2) {
                Text(l.name)
                    .font(.headline)
                Text(l.address)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                if let type = l.type {
                    Text(type)
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
