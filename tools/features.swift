import Foundation
import AVFoundation
import Vision
import CoreGraphics

// 逐帧采样：亮度、动态（与上一采样帧的差）、人脸数量与最大人脸面积占比
let args = CommandLine.arguments
guard args.count >= 4 else { print("usage: features <video> <out.jsonl> <interval>"); exit(1) }
let videoPath = args[1], outPath = args[2], interval = Double(args[3]) ?? 0.5

let asset = AVURLAsset(url: URL(fileURLWithPath: videoPath))
let duration = CMTimeGetSeconds(asset.duration)
let gen = AVAssetImageGenerator(asset: asset)
gen.appliesPreferredTrackTransform = true
gen.maximumSize = CGSize(width: 640, height: 640)
gen.requestedTimeToleranceBefore = CMTime(seconds: 0.05, preferredTimescale: 600)
gen.requestedTimeToleranceAfter = CMTime(seconds: 0.05, preferredTimescale: 600)

let W = 64, H = 36
let rgbCS = CGColorSpaceCreateDeviceRGB()
guard let rgbCtx = CGContext(data: nil, width: W, height: H, bitsPerComponent: 8, bytesPerRow: W*4,
                             space: rgbCS, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { exit(1) }
let cs = CGColorSpaceCreateDeviceGray()
guard let ctx = CGContext(data: nil, width: W, height: H, bitsPerComponent: 8, bytesPerRow: W,
                          space: cs, bitmapInfo: CGImageAlphaInfo.none.rawValue) else { exit(1) }

func rgbStats(_ cg: CGImage) -> (sat: Double, edge: Double) {
    rgbCtx.draw(cg, in: CGRect(x: 0, y: 0, width: W, height: H))
    guard let d = rgbCtx.data else { return (0, 0) }
    let p = d.bindMemory(to: UInt8.self, capacity: W*H*4)
    var satSum = 0.0, edgeSum = 0.0
    var prevL = 0.0
    for y in 0..<H {
        prevL = 0
        for x in 0..<W {
            let i = (y*W + x)*4
            let r = Double(p[i]), g = Double(p[i+1]), b = Double(p[i+2])
            let mx = max(r, max(g, b)), mn = min(r, min(g, b))
            satSum += (mx > 1 ? (mx - mn) / mx * 255.0 : 0)
            let l = 0.299*r + 0.587*g + 0.114*b
            if x > 0 { edgeSum += abs(l - prevL) }
            prevL = l
        }
    }
    return (satSum / Double(W*H), edgeSum / Double(W*H))
}

func luma(_ cg: CGImage) -> [UInt8]? {
    ctx.draw(cg, in: CGRect(x: 0, y: 0, width: W, height: H))
    guard let data = ctx.data else { return nil }
    let p = data.bindMemory(to: UInt8.self, capacity: W * H)
    return Array(UnsafeBufferPointer(start: p, count: W * H))
}

let faceReq = VNDetectFaceRectanglesRequest()
let humanReq = VNDetectHumanRectanglesRequest()

var lines: [String] = []
var prev: [UInt8]? = nil
var t = 0.0
while t < duration {
    do {
        let cg = try gen.copyCGImage(at: CMTime(seconds: t, preferredTimescale: 600), actualTime: nil)
        guard let px = luma(cg) else { t += interval; continue }
        let mean = Double(px.reduce(0) { $0 + Int($1) }) / Double(px.count)
        var diff = 0.0
        if let p = prev { var s = 0; for i in 0..<px.count { s += abs(Int(px[i]) - Int(p[i])) }; diff = Double(s) / Double(px.count) }
        prev = px

        let handler = VNImageRequestHandler(cgImage: cg, options: [:])
        try? handler.perform([faceReq, humanReq])
        var humans = 0; var humanArea = 0.0
        for obs in (humanReq.results ?? []) {
            humans += 1
            let b = obs.boundingBox
            let a = Double(b.width * b.height)
            if a > humanArea { humanArea = a }
        }
        var count = 0; var maxArea = 0.0; var cx = 0.0
        for obs in (faceReq.results ?? []) {
            count += 1
            let b = obs.boundingBox
            let a = Double(b.width * b.height)
            if a > maxArea { maxArea = a; cx = Double(b.midX) }
        }
        let st = rgbStats(cg)
        let json = String(format: "{\"t\":%.2f,\"luma\":%.1f,\"motion\":%.2f,\"faces\":%d,\"face_area\":%.4f,\"face_x\":%.3f,\"sat\":%.1f,\"edge\":%.2f,\"humans\":%d,\"human_area\":%.4f}",
                          t, mean, diff, count, maxArea, cx, st.sat, st.edge, humans, humanArea)
        lines.append(json)
    } catch { }
    t += interval
}
try? lines.joined(separator: "\n").write(toFile: outPath, atomically: true, encoding: .utf8)
print("sampled \(lines.count) frames over \(Int(duration))s")
