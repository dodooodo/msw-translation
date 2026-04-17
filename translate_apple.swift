// translate_apple.swift
// macOS 26 Translation framework helper for msw_translation overlay
// 使用 SwiftUI + .translationTask()，可自動觸發語言模型下載 UI
//
// 編譯方式 (Python 會自動執行):
//   swiftc translate_apple.swift -o translate_apple
//
// 使用方式:
//   echo '{"texts":["안녕하세요"],"source":"ko","target":"zh-Hant"}' | ./translate_apple

import AppKit
import Foundation
import SwiftUI
import Translation

struct Payload: Decodable {
    let texts: [String]
    let source: String  // e.g. "ko", "ja", "en"
    let target: String  // e.g. "zh-Hant", "zh-Hans", "en"
}

// MARK: - SwiftUI View

@available(macOS 26.0, *)
struct TranslatorView: View {
    let payload: Payload
    let config: TranslationSession.Configuration

    var body: some View {
        Color.clear
            .translationTask(config) { session in
                do {
                    let requests = payload.texts.enumerated().map { index, text in
                        TranslationSession.Request(sourceText: text, clientIdentifier: "\(index)")
                    }
                    let responses = try await session.translations(from: requests)

                    var resultMap = [Int: String]()
                    for r in responses {
                        if let idStr = r.clientIdentifier, let idx = Int(idStr) {
                            resultMap[idx] = r.targetText
                        }
                    }
                    let results = payload.texts.enumerated().map { idx, orig in
                        resultMap[idx] ?? orig
                    }

                    let outData = try JSONEncoder().encode(results)
                    print(String(data: outData, encoding: .utf8)!)
                } catch {
                    fputs("translate_apple: Translation error: \(error.localizedDescription)\n", stderr)
                    // 失敗回傳原文
                    let fallback = try! JSONEncoder().encode(payload.texts)
                    print(String(data: fallback, encoding: .utf8)!)
                }
                NSApp.terminate(nil)
            }
    }
}

// MARK: - Entry Point

let rawData = FileHandle.standardInput.readDataToEndOfFile()
guard let payload = try? JSONDecoder().decode(Payload.self, from: rawData) else {
    fputs("translate_apple: Invalid JSON input\n", stderr)
    exit(1)
}

guard #available(macOS 26.0, *) else {
    fputs("translate_apple: Requires macOS 26.0+\n", stderr)
    let fallback = try! JSONEncoder().encode(payload.texts)
    print(String(data: fallback, encoding: .utf8)!)
    exit(0)
}

let config = TranslationSession.Configuration(
    source: Locale.Language(identifier: payload.source),
    target: Locale.Language(identifier: payload.target)
)

let app = NSApplication.shared
// 允許視窗顯示（讓下載 UI 可以彈出），但不在 Dock 常駐
app.setActivationPolicy(.accessory)

// 建立一個最小化的隱形視窗，作為 SwiftUI hosting 容器
let window = NSWindow(
    contentRect: NSRect(x: 0, y: 0, width: 1, height: 1),
    styleMask: [.borderless],
    backing: .buffered,
    defer: false
)
window.isOpaque = false
window.backgroundColor = .clear
window.level = .floating
window.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]

let hostingView = NSHostingView(rootView: TranslatorView(payload: payload, config: config))
hostingView.frame = NSRect(x: 0, y: 0, width: 1, height: 1)
window.contentView = hostingView
window.makeKeyAndOrderFront(nil)

app.run()
