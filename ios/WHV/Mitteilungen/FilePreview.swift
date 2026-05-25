// QuickLook wrapper for any file URL — PDFs, images, Office docs.
//
// Used by AssemblyDetailView (signed protocol) and
// AnnouncementDetailView (Mitteilungen attachments). Both download
// the file to a temp URL via an authed APIClient call, then
// present this sheet. QLPreviewController is the same component
// Safari + Files use, so the user gets system-grade rendering,
// share, and print without us shipping a viewer.

import QuickLook
import SwiftUI
import UIKit

struct FilePreview: UIViewControllerRepresentable {
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
