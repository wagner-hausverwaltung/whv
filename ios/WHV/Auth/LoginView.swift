// Login screen — mirrors the portal's LoginPage shape (email +
// password + submit + error alert + "Passwort vergessen" link)
// so the visual + behaviour parity feels deliberate to a user
// who has touched both.
//
// Same backend (/auth/login on staging.api.wagner-hausverwaltung.com),
// same credentials — sign in on the portal, sign in on iOS, both
// work for the same account.

import SwiftUI

struct LoginView: View {
    @EnvironmentObject var auth: AuthStore

    @State private var email = ""
    @State private var password = ""
    @FocusState private var focused: Field?

    enum Field { case email, password }

    var body: some View {
        ZStack {
            // Subtle WHV-blue accent on the background so the
            // login screen feels like part of the brand even
            // before the icon shows.
            LinearGradient(
                colors: [Color(.systemBackground), Color.accentColor.opacity(0.08)],
                startPoint: .top, endPoint: .bottom
            )
            .ignoresSafeArea()

            ScrollView {
                VStack(spacing: 24) {
                    VStack(spacing: 8) {
                        Image(systemName: "lock.shield")
                            .font(.system(size: 44))
                            .foregroundStyle(.tint)
                        Text("Wagner Hausverwaltung")
                            .font(.title2.bold())
                        Text("Bitte mit Ihrem Portal-Konto anmelden.")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                            .multilineTextAlignment(.center)
                    }
                    .padding(.top, 40)

                    if let err = auth.lastError {
                        HStack(alignment: .top, spacing: 8) {
                            Image(systemName: "exclamationmark.triangle.fill")
                                .foregroundStyle(.orange)
                            Text(err)
                                .font(.subheadline)
                            Spacer(minLength: 0)
                        }
                        .padding(12)
                        .background(
                            RoundedRectangle(cornerRadius: 10)
                                .fill(.orange.opacity(0.12))
                        )
                    }

                    VStack(spacing: 16) {
                        TextField("E-Mail", text: $email)
                            .textContentType(.username)
                            .keyboardType(.emailAddress)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .focused($focused, equals: .email)
                            .submitLabel(.next)
                            .onSubmit { focused = .password }
                            .padding(12)
                            .background(.background, in: RoundedRectangle(cornerRadius: 10))
                            .overlay(
                                RoundedRectangle(cornerRadius: 10)
                                    .stroke(.separator, lineWidth: 0.5)
                            )

                        SecureField("Passwort", text: $password)
                            .textContentType(.password)
                            .focused($focused, equals: .password)
                            .submitLabel(.go)
                            .onSubmit(submit)
                            .padding(12)
                            .background(.background, in: RoundedRectangle(cornerRadius: 10))
                            .overlay(
                                RoundedRectangle(cornerRadius: 10)
                                    .stroke(.separator, lineWidth: 0.5)
                            )

                        Button(action: submit) {
                            HStack {
                                if auth.isAuthenticating {
                                    ProgressView()
                                        .tint(.white)
                                        .controlSize(.small)
                                }
                                Text(auth.isAuthenticating ? "Anmelden…" : "Anmelden")
                                    .font(.headline)
                            }
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 14)
                        }
                        .buttonStyle(.borderedProminent)
                        .controlSize(.large)
                        .disabled(!canSubmit)

                        // Forgot-password points at the portal —
                        // the iOS app intentionally doesn't ship
                        // its own reset flow until Phase 2 (email
                        // deep-links don't bounce back into the iOS
                        // app cleanly without a Universal Link
                        // setup we haven't done yet).
                        Link(
                            "Passwort vergessen?",
                            destination: URL(string: "https://staging.portal.wagner-hausverwaltung.com/forgot-password")!
                        )
                        .font(.subheadline)
                    }

                    Spacer(minLength: 40)
                }
                .padding(.horizontal, 24)
                .frame(maxWidth: 480)
                .frame(maxWidth: .infinity)
            }
        }
        .onAppear { focused = .email }
    }

    private var canSubmit: Bool {
        !email.trimmingCharacters(in: .whitespaces).isEmpty
            && !password.isEmpty
            && !auth.isAuthenticating
    }

    private func submit() {
        guard canSubmit else { return }
        focused = nil
        Task { await auth.login(email: email, password: password) }
    }
}

#Preview {
    LoginView()
        .environmentObject(AuthStore())
}
