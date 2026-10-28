// Reads the trophy name off PlayStation trophy captures with macOS Vision.
// usage: banner_ocr <file listing image paths> [x y w h] > out.json
// The optional crop is fractions of the image measured from the top left; the default is the
// bottom banner's text. The top-left flyover's text is at 0.12 0.13 0.22 0.12.
import Foundation
import Vision
import AppKit

let paths = try! String(contentsOfFile: CommandLine.arguments[1], encoding: .utf8).split(separator: "\n").map(String.init)
// Bottom banner text sits right of the trophy icon: x 20-80%, y 84-97% from the top
let box: [CGFloat] = CommandLine.arguments.count >= 6
    ? CommandLine.arguments[2...5].map { CGFloat(Double($0)!) } : [0.2, 0.84, 0.6, 0.13]
var out: [String: String] = [:]
for p in paths {
    guard let img = NSImage(contentsOfFile: p), let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else { continue }
    let w = CGFloat(cg.width), h = CGFloat(cg.height)
    guard let crop = cg.cropping(to: CGRect(x: w * box[0], y: h * box[1], width: w * box[2], height: h * box[3])) else { continue }
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate
    try? VNImageRequestHandler(cgImage: crop).perform([req])
    let text = (req.results ?? []).compactMap { $0.topCandidates(1).first?.string }.joined(separator: " ")
    out[p] = text
}
let data = try! JSONSerialization.data(withJSONObject: out, options: [.prettyPrinted, .sortedKeys])
FileHandle.standardOutput.write(data)
