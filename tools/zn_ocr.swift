// Reads Zelda Notes screenshots (medal pages, Photo Studio milestones) with macOS Vision and keeps
// each line's position, so build_zelda_notes.py can pair a label with the value on its row.
// usage: zn_ocr <file listing image paths> > out.json
// Output: {path: [{"t": text, "x": left, "y": top, "w": width, "h": height}, ...]}, fractions of the
// image measured from the top left.
import Foundation
import Vision
import AppKit

let paths = try! String(contentsOfFile: CommandLine.arguments[1], encoding: .utf8).split(separator: "\n").map(String.init)
var out: [String: [[String: Any]]] = [:]
for p in paths {
    guard let img = NSImage(contentsOfFile: p), let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else { continue }
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate
    req.usesLanguageCorrection = false
    try? VNImageRequestHandler(cgImage: cg).perform([req])
    out[p] = (req.results ?? []).compactMap { r in
        guard let s = r.topCandidates(1).first?.string else { return nil }
        let b = r.boundingBox  // normalized, bottom-left origin
        return ["t": s, "x": b.minX, "y": 1 - b.maxY, "w": b.width, "h": b.height]
    }
}
let data = try! JSONSerialization.data(withJSONObject: out, options: [.sortedKeys])
FileHandle.standardOutput.write(data)
