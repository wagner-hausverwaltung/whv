// Invite-code redemption — mirrors the portal's InviteRedeemPage
// (web/src/pages/InviteRedeemPage.tsx). The user lands here from
// LoginView's "Einladungscode einlösen?" link.
//
// Flow:
//   1. User types/pastes the code.
//   2. When focus leaves the code field, we hit GET /auth/invite/{code}
//      and pre-fill the email as read-only — typing it manually is the
//      #1 cause of "Einladung ungültig" failures (typo vs. the address
//      the Verwalter sent the invite to).
//   3. User sets a password (min 10 chars; backend enforces).
//   4. POST /auth/invite/redeem returns tokens; AuthStore.persist drops
//      them into Keychain and the WHVApp gate flips to the picker.
//
// Server-side: the email is still required + validated on /redeem,
// so the second-factor stays intact — we just pre-fill it for the
// legitimate path.

import SwiftUI

struct RegistrationView: View {
    @EnvironmentObject var auth: AuthStore
    @Environment(\.dismiss) private var dismiss

    @State private var code = ""
    @State private var email = ""
    @State private var password = ""
    @State private var confirm = ""

    @State private var inviteInfo: InviteInfoResponse?
    @State private var inviteLookupState: LookupState = .idle
    @State private var emailEditable = false

    @State private var localError: String?

    @FocusState private var focused: Field?

    enum Field { case code, email, password, confirm }
    enum LookupState { case idle, loading, success, failed }

    var body: some View {
        NavigationStack {
            ZStack {
                LinearGradient(
                    colors: [
                        Color(.systemBackground),
                        Color.accentColor.opacity(0.08),
                    ],
                    startPoint: .top, endPoint: .bottom
                )
                .ignoresSafeArea()

                ScrollView {
                    VStack(spacing: 20) {
                        VStack(spacing: 12) {
                            Image("Logo")
                                .resizable()
                                .scaledToFit()
                                .frame(maxWidth: 240, maxHeight: 92)
                                .accessibilityLabel("Wagner Hausverwaltung")
                            Text("Einladung einlösen")
                                .font(.title3.bold())
                            Text(subtitleCopy)
                                .font(.subheadline)
                                .foregroundStyle(.secondary)
                                .multilineTextAlignment(.center)
                        }
                        .padding(.top, 16)

                        if let err = displayedError {
                            errorBanner(err)
                        }

                        VStack(spacing: 14) {
                            codeField
                            emailField
                            passwordField
                            confirmField

                            Button(action: submit) {
                                HStack {
                                    if auth.isAuthenticating {
                                        ProgressView()
                                            .tint(.white)
                                            .controlSize(.small)
                                    }
                                    Text(
                                        auth.isAuthenticating
                                            ? "Wird eingelöst…"
                                            : "Einladung einlösen + anmelden"
                                    )
                                    .font(.headline)
                                }
                                .frame(maxWidth: .infinity)
                                .padding(.vertical, 14)
                            }
                            .buttonStyle(.borderedProminent)
                            .controlSize(.large)
                            .disabled(!canSubmit)
                        }

                        Spacer(minLength: 40)
                    }
                    .padding(.horizontal, 24)
                    .frame(maxWidth: 480)
                    .frame(maxWidth: .infinity)
                }
            }
            .navigationTitle("Registrierung")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Abbrechen") { dismiss() }
                }
            }
            .onAppear { focused = .code }
            .onChange(of: focused) { _, newValue in
                // Trigger the invite lookup when focus moves *off* the
                // code field (after the user has typed/pasted it).
                // Skips repeat lookups for the same code.
                if newValue != .code && !code.trimmingCharacters(in: .whitespaces).isEmpty {
                    if inviteInfo?.email == nil || inviteLookupState == .failed {
                        Task { await lookupInvite() }
                    }
                }
            }
        }
    }

    // MARK: - Copy

    private var subtitleCopy: String {
        if let info = inviteInfo {
            return
                "Legen Sie Ihr Passwort fest. "
                + "Einladung von \(info.organization_name)."
        }
        return
            "Legen Sie Ihr Passwort fest, um sich künftig in der App "
            + "und im Portal anzumelden."
    }

    // MARK: - Pieces

    private var displayedError: String? { localError ?? auth.lastError }

    private func errorBanner(_ text: String) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundStyle(.orange)
            Text(text)
                .font(.subheadline)
            Spacer(minLength: 0)
        }
        .padding(12)
        .background(
            RoundedRectangle(cornerRadius: 10)
                .fill(.orange.opacity(0.12))
        )
    }

    private var codeField: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text("Einladungscode")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer()
                if inviteLookupState == .loading {
                    ProgressView()
                        .controlSize(.mini)
                } else if inviteLookupState == .success {
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundStyle(.green)
                        .font(.caption)
                }
            }
            TextField("z. B. ABC123-XYZ", text: $code)
                .textContentType(.oneTimeCode)
                .keyboardType(.default)
                .textInputAutocapitalization(.characters)
                .autocorrectionDisabled()
                .focused($focused, equals: .code)
                .submitLabel(.next)
                .onSubmit { focused = .email }
                .padding(12)
                .background(.background, in: RoundedRectangle(cornerRadius: 10))
                .overlay(
                    RoundedRectangle(cornerRadius: 10)
                        .stroke(.separator, lineWidth: 0.5)
                )
                .font(.body.monospaced())
        }
    }

    private var emailField: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text("E-Mail-Adresse")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer()
                if inviteLookupState == .success && !emailEditable {
                    Button("Andere E-Mail?") { emailEditable = true }
                        .font(.caption)
                }
            }
            TextField("name@example.com", text: $email)
                .textContentType(.username)
                .keyboardType(.emailAddress)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .focused($focused, equals: .email)
                .submitLabel(.next)
                .onSubmit { focused = .password }
                .disabled(inviteLookupState == .success && !emailEditable)
                .padding(12)
                .background(
                    (inviteLookupState == .success && !emailEditable
                        ? Color(.tertiarySystemFill)
                        : Color(.systemBackground)),
                    in: RoundedRectangle(cornerRadius: 10)
                )
                .overlay(
                    RoundedRectangle(cornerRadius: 10)
                        .stroke(.separator, lineWidth: 0.5)
                )
            if inviteLookupState == .success && !emailEditable {
                Text("Aus der Einladung übernommen.")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .padding(.leading, 2)
            }
        }
    }

    private var passwordField: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Neues Passwort")
                .font(.caption)
                .foregroundStyle(.secondary)
            SecureField("min. 10 Zeichen", text: $password)
                .textContentType(.newPassword)
                .focused($focused, equals: .password)
                .submitLabel(.next)
                .onSubmit { focused = .confirm }
                .padding(12)
                .background(.background, in: RoundedRectangle(cornerRadius: 10))
                .overlay(
                    RoundedRectangle(cornerRadius: 10)
                        .stroke(.separator, lineWidth: 0.5)
                )
        }
    }

    private var confirmField: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Passwort bestätigen")
                .font(.caption)
                .foregroundStyle(.secondary)
            SecureField("Passwort wiederholen", text: $confirm)
                .textContentType(.newPassword)
                .focused($focused, equals: .confirm)
                .submitLabel(.go)
                .onSubmit(submit)
                .padding(12)
                .background(.background, in: RoundedRectangle(cornerRadius: 10))
                .overlay(
                    RoundedRectangle(cornerRadius: 10)
                        .stroke(.separator, lineWidth: 0.5)
                )
        }
    }

    // MARK: - Lookup

    private func lookupInvite() async {
        let trimmed = code.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        inviteLookupState = .loading
        localError = nil
        do {
            let info = try await APIClient().fetchInviteInfo(code: trimmed)
            self.inviteInfo = info
            self.email = info.email
            self.emailEditable = false
            self.inviteLookupState = .success
        } catch {
            self.inviteInfo = nil
            self.emailEditable = true
            self.inviteLookupState = .failed
            self.localError =
                "Diese Einladung ist nicht (mehr) gültig. "
                + "Bitte wenden Sie sich an Ihre Hausverwaltung."
        }
    }

    // MARK: - Submit

    private var canSubmit: Bool {
        !code.trimmingCharacters(in: .whitespaces).isEmpty
            && !email.trimmingCharacters(in: .whitespaces).isEmpty
            && password.count >= 10
            && confirm.count >= 10
            && !auth.isAuthenticating
    }

    private func submit() {
        localError = nil
        if password != confirm {
            localError = "Passwörter stimmen nicht überein."
            return
        }
        if password.count < 10 {
            // Match the backend's min_length=10 rather than the
            // portal's 8 — backend rejects 8 with a useless 422.
            localError = "Passwort muss mindestens 10 Zeichen lang sein."
            return
        }
        guard canSubmit else { return }
        focused = nil
        Task {
            await auth.redeemInvite(
                code: code,
                email: email,
                password: password
            )
        }
    }
}

#Preview {
    RegistrationView()
        .environmentObject(AuthStore())
}
