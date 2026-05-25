// Invite-code redemption — mirrors the portal's InviteRedeemPage
// (web/src/pages/InviteRedeemPage.tsx). The user lands here from
// LoginView's "Einladungscode einlösen?" link. They paste the code
// from the email + enter their email + pick a password, and the same
// /auth/invite/redeem endpoint hands back a TokenResponse — at which
// point WHVApp's gate sees `authStore.signedIn` flip true and pushes
// them to the Liegenschaft picker.
//
// We deliberately mirror the portal's validation (≥8 chars + match)
// + error verbatim, so the same invitation can be redeemed on
// either client with the same UX.

import SwiftUI

struct RegistrationView: View {
    @EnvironmentObject var auth: AuthStore
    @Environment(\.dismiss) private var dismiss

    @State private var code = ""
    @State private var email = ""
    @State private var password = ""
    @State private var confirm = ""
    @State private var localError: String?

    @FocusState private var focused: Field?

    enum Field { case code, email, password, confirm }

    var body: some View {
        NavigationStack {
            ZStack {
                // Same subtle WHV-blue accent the login screen uses
                // so the two flows feel like one experience.
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
                            Text(
                                "Legen Sie Ihr Passwort fest, um sich künftig "
                                    + "in der App und im Portal anzumelden."
                            )
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                            .multilineTextAlignment(.center)
                        }
                        .padding(.top, 16)

                        if let err = displayedError {
                            errorBanner(err)
                        }

                        VStack(spacing: 14) {
                            field(
                                label: "Einladungscode",
                                placeholder: "z. B. ABC123-XYZ",
                                text: $code,
                                content: .none,
                                keyboard: .default,
                                capitalization: .characters,
                                submit: .next,
                                focus: .code,
                                next: .email
                            )
                            .font(.body.monospaced())

                            field(
                                label: "E-Mail-Adresse",
                                placeholder: "name@example.com",
                                text: $email,
                                content: .username,
                                keyboard: .emailAddress,
                                capitalization: .never,
                                submit: .next,
                                focus: .email,
                                next: .password
                            )

                            field(
                                label: "Neues Passwort",
                                placeholder: "min. 8 Zeichen",
                                text: $password,
                                content: .newPassword,
                                keyboard: .default,
                                capitalization: .never,
                                submit: .next,
                                focus: .password,
                                next: .confirm,
                                secure: true
                            )

                            field(
                                label: "Passwort bestätigen",
                                placeholder: "Passwort wiederholen",
                                text: $confirm,
                                content: .newPassword,
                                keyboard: .default,
                                capitalization: .never,
                                submit: .go,
                                focus: .confirm,
                                next: nil,
                                secure: true,
                                onSubmit: submit
                            )

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

                            Text(
                                "Die E-Mail-Adresse muss mit jener aus "
                                    + "der Einladung übereinstimmen."
                            )
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .multilineTextAlignment(.center)
                            .padding(.top, 4)
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
        }
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

    @ViewBuilder
    private func field(
        label: String,
        placeholder: String,
        text: Binding<String>,
        content: UITextContentType?,
        keyboard: UIKeyboardType,
        capitalization: TextInputAutocapitalization,
        submit: SubmitLabel,
        focus: Field,
        next: Field?,
        secure: Bool = false,
        onSubmit: (() -> Void)? = nil
    ) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(label)
                .font(.caption)
                .foregroundStyle(.secondary)
            Group {
                if secure {
                    SecureField(placeholder, text: text)
                } else {
                    TextField(placeholder, text: text)
                }
            }
            .textContentType(content)
            .keyboardType(keyboard)
            .textInputAutocapitalization(capitalization)
            .autocorrectionDisabled()
            .focused($focused, equals: focus)
            .submitLabel(submit)
            .onSubmit {
                if let onSubmit { onSubmit() }
                else if let next { focused = next }
            }
            .padding(12)
            .background(.background, in: RoundedRectangle(cornerRadius: 10))
            .overlay(
                RoundedRectangle(cornerRadius: 10)
                    .stroke(.separator, lineWidth: 0.5)
            )
        }
    }

    // MARK: - Validation + submit

    private var canSubmit: Bool {
        !code.trimmingCharacters(in: .whitespaces).isEmpty
            && !email.trimmingCharacters(in: .whitespaces).isEmpty
            && password.count >= 8
            && confirm.count >= 8
            && !auth.isAuthenticating
    }

    private func submit() {
        // Same client-side gates the portal applies, mirrored
        // verbatim so the error copy matches across both clients.
        localError = nil
        if password != confirm {
            localError = "Passwörter stimmen nicht überein."
            return
        }
        if password.count < 8 {
            localError = "Passwort muss mindestens 8 Zeichen lang sein."
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
            // If signedIn flipped, the parent's gate will swap us to
            // the picker — no explicit dismiss needed. If it failed,
            // auth.lastError now holds the backend's detail string.
        }
    }
}

#Preview {
    RegistrationView()
        .environmentObject(AuthStore())
}
