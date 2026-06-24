// Finger-drawn signature pad (no dependency). Strokes are point arrays in
// the canvas's coordinate space; `renderSignaturePNG` rasterises them to a
// transparent PNG the backend composites onto the Vollmacht PDF (ADR-0017).

import SwiftUI
import UIKit

struct SignatureCanvas: View {
    @Binding var strokes: [[CGPoint]]
    @Binding var canvasSize: CGSize
    @State private var inStroke = false

    var body: some View {
        Canvas { ctx, _ in
            for stroke in strokes where stroke.count > 1 {
                var path = Path()
                path.move(to: stroke[0])
                for p in stroke.dropFirst() { path.addLine(to: p) }
                ctx.stroke(
                    path,
                    with: .color(Color(white: 0.07)),
                    style: StrokeStyle(lineWidth: 2.5, lineCap: .round, lineJoin: .round)
                )
            }
        }
        .frame(height: 160)
        .background(
            GeometryReader { geo in
                Color(.secondarySystemBackground)
                    .onAppear { canvasSize = geo.size }
                    .onChange(of: geo.size) { _, newValue in canvasSize = newValue }
            }
        )
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color(.separator)))
        .contentShape(Rectangle())
        .gesture(
            DragGesture(minimumDistance: 0)
                .onChanged { value in
                    if !inStroke {
                        strokes.append([value.location])
                        inStroke = true
                    } else {
                        strokes[strokes.count - 1].append(value.location)
                    }
                }
                .onEnded { _ in inStroke = false }
        )
    }
}

/// Rasterise drawn strokes to a transparent PNG at the canvas size. Returns
/// nil when nothing meaningful was drawn (caller submits without a signature
/// → the PDF shows a blank line, still a valid Textform Vollmacht).
func renderSignaturePNG(strokes: [[CGPoint]], size: CGSize) -> Data? {
    guard size.width > 1, size.height > 1,
        strokes.contains(where: { $0.count > 1 })
    else { return nil }
    let renderer = UIGraphicsImageRenderer(size: size)  // non-opaque → transparent bg
    let image = renderer.image { _ in
        let path = UIBezierPath()
        path.lineWidth = 2.5
        path.lineCapStyle = .round
        path.lineJoinStyle = .round
        for stroke in strokes where stroke.count > 1 {
            path.move(to: stroke[0])
            for p in stroke.dropFirst() { path.addLine(to: p) }
        }
        UIColor(white: 0.07, alpha: 1).setStroke()
        path.stroke()
    }
    return image.pngData()
}
