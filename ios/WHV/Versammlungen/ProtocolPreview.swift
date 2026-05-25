// QuickLook wrapper for the signed-protocol PDF.
//
// The detail screen downloads the PDF to a temp path (authed), then
// presents this sheet. QLPreviewController is the same component
// Safari + Files use, so the user gets system-grade rendering,
// share, and print without us shipping a PDF viewer.

import QuickLook
import SwiftUI
import UIKit

struct ProtocolPreview: UIViewControllerRepresentable {
    let url: URL

    func makeCoordinator() -> Coordinator { Coordinator(url: url) }

    func makeUIViewController(context: Context) -> UINavigationController {
        let preview = QLPreviewController()
        preview.dataSource = context.coordinator
        return UINavigationController(rootViewController: preview)
    }

    func updateUIViewController(_ controller: UINavigationController, context: Context) {
        context.coordinator.url = url
        if let preview = controller.viewControllers.first as? QLPreviewController {
            preview.reloadData()
        }
    }

    final class Coordinator: NSObject, QLPreviewControllerDataSource {
        var url: URL
        init(url: URL) { self.url = url }

        func numberOfPreviewItems(in controller: QLPreviewController) -> Int { 1 }
        func previewController(
            _ controller: QLPreviewController,
            previewItemAt index: Int
        ) -> QLPreviewItem {
            url as QLPreviewItem
        }
    }
}
