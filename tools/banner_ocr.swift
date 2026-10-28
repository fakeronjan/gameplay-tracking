// Reads the trophy name off PlayStation trophy-capture banners with macOS Vision.
// usage: swift banner_ocr.swift <file listing image paths> > out.json
import Foundation
import Vision
import AppKit

let paths = try! String(contentsOfFile: CommandLine.arguments[1], encoding: .utf8).split(separator: "\n").map(String.init)
var out: [String: String] = [:]
for p in paths {
    guard let img = NSImage(contentsOfFile: p), let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else { continue }
    // Banner text sits right of the trophy icon: x 20-80%, y 84-97% from the top
    let w = CGFloat(cg.width), h = CGFloat(cg.height)
    guard let crop = cg.cropping(to: CGRect(x: w * 0.2, y: h * 0.84, width: w * 0.6, height: h * 0.13)) else { continue }
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate
    try? VNImageRequestHandler(cgImage: crop).perform([req])
    let text = (req.results ?? []).compactMap { $0.topCandidates(1).first?.string }.joined(separator: " ")
    out[p] = text
}
let data = try! JSONSerialization.data(withJSONObject: out, options: [.prettyPrinted, .sortedKeys])
FileHandle.standardOutput.write(data)
