// Owner-facing Vollmacht (ETV proxy, ADR-0017) section on the assembly
// detail. An Eigentümer delegates their vote to a proxy and signs in-app;
// the signed WHV-design PDF is viewable, and the Vollmacht is revocable
// before the meeting. Rendered only for owners (AssemblyDetailView gates).

import SwiftUI

private func germanDate(_ iso: String) -> String {
    let withFractional = ISO8601DateFormatter()
    withFractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    let plain = ISO8601DateFormatter()
    plain.formatOptions = [.withInternetDateTime]
    let date = withFractional.date(from: iso) ?? plain.date(from: iso)
    guard let date else { return iso }
    let out = DateFormatter()
    out.locale = Locale(identifier: "de_DE")
    out.dateStyle = .medium
    return out.string(from: date)
}

struct VollmachtSectionView: View {
    let assemblyId: String

    /// ONE sheet driver for both destinations. Two `.sheet` modifiers on the
    /// same view silently conflict in SwiftUI — the first one wins, so the PDF
    /// preview never opened while "Vollmacht erteilen" worked (owner feedback
    /// 07/2026: repeated taps, server returned the PDF every time).
    private enum ActiveSheet: Identifiable {
        case grant
        case preview(URL)

        var id: String {
            switch self {
            case .grant: "grant"
            case .preview(let url): url.absoluteString
            }
        }
    }

    @State private var vollmacht: VollmachtResponse?
    @State private var loaded = false
    @State private var activeSheet: ActiveSheet?
    @State private var busy = false
    @State private var error: String?

    private let api = APIClient()

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Vollmacht").font(.title3.bold())
            if let v = vollmacht, v.status == "SIGNED" {
                grantedCard(v)
            } else {
                grantCTA
            }
            if let error {
                Text(error).font(.caption).foregroundStyle(.red)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .task { await load() }
        .sheet(item: $activeSheet) { which in
            switch which {
            case .grant:
                GrantVollmachtSheet(assemblyId: assemblyId) { granted in
                    vollmacht = granted
                }
            case .preview(let url):
                FilePreview(url: url).ignoresSafeArea()
            }
        }
    }

    private var grantCTA: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Können Sie nicht teilnehmen?")
                .font(.subheadline.weight(.semibold))
            Text("Bevollmächtigen Sie eine Vertretung für Ihre Stimme — digital unterschrieben.")
                .font(.caption)
                .foregroundStyle(.secondary)
            Button {
                activeSheet = .grant
            } label: {
                Label("Vollmacht erteilen", systemImage: "signature")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12).fill(Color(.secondarySystemBackground)))
    }

    private func grantedCard(_ v: VollmachtResponse) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Label {
                Text("Vollmacht erteilt an \(v.proxy_name)").font(.subheadline.weight(.semibold))
            } icon: {
                Image(systemName: "checkmark.seal.fill").foregroundStyle(.green)
            }
            Text("Unterschrieben am \(germanDate(v.signed_at))")
                .font(.caption)
                .foregroundStyle(.secondary)
            if let scope = v.scope_note, !scope.isEmpty {
                Text("Weisung: \(scope)").font(.caption).foregroundStyle(.secondary)
            }
            HStack(spacing: 12) {
                Button {
                    Task { await download(v) }
                } label: {
                    Label("PDF ansehen", systemImage: "doc.text")
                }
                Button(role: .destructive) {
                    Task { await revoke(v) }
                } label: {
                    Label("Widerrufen", systemImage: "xmark.circle")
                }
                .disabled(busy)
            }
            .font(.subheadline)
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12).fill(Color(.secondarySystemBackground)))
    }

    private func load() async {
        do {
            vollmacht = try await api.getMyVollmacht(assemblyId: assemblyId)
        } catch {
            // Non-fatal — show the grant CTA.
            vollmacht = nil
        }
        loaded = true
    }

    private func download(_ v: VollmachtResponse) async {
        do {
            activeSheet = .preview(try await api.downloadVollmacht(id: v.id))
        } catch {
            self.error = "PDF konnte nicht geladen werden."
        }
    }

    private func revoke(_ v: VollmachtResponse) async {
        busy = true
        defer { busy = false }
        do {
            _ = try await api.revokeVollmacht(id: v.id)
            vollmacht = nil
        } catch {
            self.error = "Widerruf fehlgeschlagen."
        }
    }
}

private struct GrantVollmachtSheet: View {
    let assemblyId: String
    let onGranted: (VollmachtResponse) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var proxyName = ""
    @State private var scopeNote = ""
    @State private var strokes: [[CGPoint]] = []
    @State private var canvasSize: CGSize = .zero
    @State private var busy = false
    @State private var error: String?

    private let api = APIClient()

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("Bevollmächtigte Person", text: $proxyName)
                    TextField("Weisung / Einschränkung (optional)", text: $scopeNote, axis: .vertical)
                        .lineLimit(1...3)
                } header: {
                    Text("Wen bevollmächtigen Sie?")
                } footer: {
                    Text("z. B. Beirat, Herr Müller oder die Hausverwaltung.")
                }

                Section("Ihre Unterschrift") {
                    SignatureCanvas(strokes: $strokes, canvasSize: $canvasSize)
                    Button("Löschen") { strokes = [] }
                        .font(.caption)
                }

                if let error {
                    Section { Text(error).foregroundStyle(.red) }
                }
            }
            .navigationTitle("Vollmacht erteilen")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Abbrechen") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Erteilen") { Task { await submit() } }
                        .disabled(busy)
                }
            }
        }
    }

    private func submit() async {
        guard !proxyName.trimmingCharacters(in: .whitespaces).isEmpty else {
            error = "Bitte geben Sie an, wen Sie bevollmächtigen."
            return
        }
        busy = true
        error = nil
        do {
            let png = renderSignaturePNG(strokes: strokes, size: canvasSize)
            let v = try await api.createVollmacht(
                assemblyId: assemblyId,
                proxyName: proxyName.trimmingCharacters(in: .whitespaces),
                scopeNote: scopeNote.trimmingCharacters(in: .whitespaces),
                signaturePNG: png
            )
            onGranted(v)
            dismiss()
        } catch {
            self.error = error.localizedDescription
        }
        busy = false
    }
}
