// Thin UIImagePickerController wrapper for capturing a meter photo with
// the camera. PhotosPicker covers the library path (no permission needed);
// this covers "take a fresh photo", which is the primary meter-reading
// flow. Requires NSCameraUsageDescription in WHV-Info.plist — it must live in
// the physical plist, NOT as an INFOPLIST_KEY build setting (those are ignored
// when GENERATE_INFOPLIST_FILE = NO, which is how this app crashed on first
// camera use). On the simulator the camera source is unavailable, so call
// sites gate on `CameraPicker.isAvailable`.

import SwiftUI
import UIKit

struct CameraPicker: UIViewControllerRepresentable {
    /// Hands back a JPEG-encoded capture. Empty/cancel → not called.
    let onImage: (Data) -> Void
    @Environment(\.dismiss) private var dismiss

    static var isAvailable: Bool {
        UIImagePickerController.isSourceTypeAvailable(.camera)
    }

    func makeUIViewController(context: Context) -> UIImagePickerController {
        let picker = UIImagePickerController()
        picker.sourceType = .camera
        picker.delegate = context.coordinator
        return picker
    }

    func updateUIViewController(_ controller: UIImagePickerController, context: Context) {}

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    final class Coordinator: NSObject, UIImagePickerControllerDelegate,
        UINavigationControllerDelegate
    {
        let parent: CameraPicker
        init(_ parent: CameraPicker) { self.parent = parent }

        func imagePickerController(
            _ picker: UIImagePickerController,
            didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey: Any]
        ) {
            if let image = info[.originalImage] as? UIImage,
                let data = image.jpegData(compressionQuality: 0.7)
            {
                parent.onImage(data)
            }
            parent.dismiss()
        }

        func imagePickerControllerDidCancel(_ picker: UIImagePickerController) {
            parent.dismiss()
        }
    }
}
