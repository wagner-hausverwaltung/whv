//
//  AwardSplashView.swift
//  WHV
//
//  Plus X Award "Top 100 Hausverwaltungen Deutschlands 2024" — shown once
//  per launch for a few seconds before the login screen, slowly pulsing.
//  The asset catalog swaps the white badge for the black one in dark mode.
//  A tap skips; Reduce Motion shows it static.
//

import SwiftUI

struct AwardSplashView: View {
    var onDone: () -> Void

    @State private var pulsing = false
    @State private var fadingOut = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        ZStack {
            Color(.systemBackground).ignoresSafeArea()
            Image("PlusXAward")
                .resizable()
                .scaledToFit()
                .frame(maxWidth: 190)
                .scaleEffect(pulsing && !reduceMotion ? 1.05 : 1.0)
                .animation(
                    reduceMotion ? nil : .easeInOut(duration: 1.4).repeatForever(autoreverses: true),
                    value: pulsing
                )
                .accessibilityLabel("Plus X Award — Top 100 Hausverwaltungen Deutschlands, ausgezeichnet 2024")
        }
        .opacity(fadingOut ? 0 : 1)
        .contentShape(Rectangle())
        .onTapGesture { finish() }
        .onAppear { pulsing = true }
        .task {
            try? await Task.sleep(for: .seconds(3))
            finish()
        }
    }

    private func finish() {
        guard !fadingOut else { return }
        withAnimation(.easeOut(duration: 0.45)) { fadingOut = true }
        Task {
            try? await Task.sleep(for: .milliseconds(450))
            onDone()
        }
    }
}
