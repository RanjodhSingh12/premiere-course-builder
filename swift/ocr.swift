// Read the text in images with macOS Vision (on-device, free).
//   ocr <image> [<image> ...]   ->  one JSON line per image:
//   {"file": "...", "lines": [{"text": "...", "x": 0.1, "y": 0.2, "w": 0.3, "h": 0.04, "conf": 0.98}]}
// x/y are from the TOP-left, as fractions of the image size.
import AppKit
import Foundation
import Vision

for path in CommandLine.arguments.dropFirst() {
    guard let img = NSImage(contentsOfFile: path),
          let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
        print("{\"file\":\"\(path)\",\"error\":\"cannot read image\"}")
        continue
    }
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate
    req.usesLanguageCorrection = true
    req.minimumTextHeight = 0.008
    try? VNImageRequestHandler(cgImage: cg, options: [:]).perform([req])
    var lines: [[String: Any]] = []
    for obs in req.results ?? [] {
        guard let cand = obs.topCandidates(1).first else { continue }
        let b = obs.boundingBox
        lines.append(["text": cand.string, "x": b.minX, "y": 1 - b.maxY, "w": b.width, "h": b.height,
                      "conf": cand.confidence])
    }
    let obj: [String: Any] = ["file": path, "lines": lines]
    let data = try! JSONSerialization.data(withJSONObject: obj)
    print(String(data: data, encoding: .utf8)!)
}
