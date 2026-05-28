// UIKit AppDelegate — exists purely to catch the remote-notification
// device-token callbacks, which SwiftUI's App lifecycle doesn't
// surface. Wired into WHVApp via @UIApplicationDelegateAdaptor.
//
// All it does is forward the token (and registration failures) to
// PushManager.shared, which owns the actual register/POST logic.

import UIKit

final class AppDelegate: NSObject, UIApplicationDelegate {
    func application(
        _ application: UIApplication,
        didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data
    ) {
        Task { @MainActor in
            PushManager.shared.didReceive(token: deviceToken)
        }
    }

    func application(
        _ application: UIApplication,
        didFailToRegisterForRemoteNotificationsWithError error: Error
    ) {
        Task { @MainActor in
            PushManager.shared.didFailToRegister(error: error)
        }
    }
}
