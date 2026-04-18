// translate_apple.swift
// macOS 26 Translation framework helper for msw_translation overlay
// Long-running daemon mode: reads JSON lines from stdin, writes JSON lines to stdout.
//
// 編譯方式 (Python 會自動執行):
//   swiftc translate_apple.swift -o translate_apple
//
// 使用方式:
//   ./translate_apple ko zh-Hant
//   Then send JSON lines on stdin, one per line:
//     {"texts":["안녕하세요","감사합니다"]}
//   Each line produces one JSON array line on stdout:
//     ["你好","謝謝"]

import AppKit
import Foundation
import SwiftUI
import Translation

// MARK: - Data Types

struct Payload: Decodable {
    let texts: [String]
}

// MARK: - Argument Parsing

guard CommandLine.arguments.count >= 3 else {
    fputs("Usage: translate_apple <source_lang> <target_lang>\n", stderr)
    fputs("  Then send JSON lines on stdin: {\"texts\":[\"...\"]}\n", stderr)
    exit(1)
}

let sourceLang = CommandLine.arguments[1]  // e.g. "ko"
let targetLang = CommandLine.arguments[2]  // e.g. "zh-Hant"

guard #available(macOS 26.0, *) else {
    fputs("translate_apple: Requires macOS 26.0+\n", stderr)
    // Legacy mode: echo back originals for each stdin line until EOF
    while let line = readLine() {
        guard let data = line.data(using: .utf8),
              let payload = try? JSONDecoder().decode(Payload.self, from: data) else {
            print("[]")
            fflush(stdout)
            continue
        }
        let fallback = try! JSONEncoder().encode(payload.texts)
        print(String(data: fallback, encoding: .utf8)!)
        fflush(stdout)
    }
    exit(0)
}

// MARK: - Session Actor
//
// Owns the TranslationSession.  All translate calls are serialised through
// this actor so we never have concurrent session access.

@available(macOS 26.0, *)
actor SessionActor {
    private var session: TranslationSession?

    func setSession(_ s: TranslationSession) {
        self.session = s
    }

    func translate(_ texts: [String]) async -> [String] {
        guard let session else { return texts }
        do {
            let requests = texts.enumerated().map { idx, text in
                TranslationSession.Request(sourceText: text, clientIdentifier: "\(idx)")
            }
            let responses = try await session.translations(from: requests)
            var resultMap = [Int: String]()
            for r in responses {
                if let idStr = r.clientIdentifier, let idx = Int(idStr) {
                    resultMap[idx] = r.targetText
                }
            }
            return texts.enumerated().map { idx, orig in resultMap[idx] ?? orig }
        } catch {
            fputs("translate_apple: Translation error: \(error.localizedDescription)\n", stderr)
            return texts
        }
    }
}

// MARK: - SwiftUI Daemon View

@available(macOS 26.0, *)
struct TranslatorDaemonView: View {
    let config: TranslationSession.Configuration
    let sessionActor: SessionActor

    var body: some View {
        Color.clear
            .translationTask(config) { session in
                // Hand the live session to the actor, then start the stdin loop
                await sessionActor.setSession(session)

                // Process stdin lines on a background task so we never block
                // the main run loop (which drives the session).
                await Task.detached(priority: .userInitiated) {
                    while let line = readLine() {
                        let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
                        guard !trimmed.isEmpty,
                              let data = trimmed.data(using: .utf8),
                              let payload = try? JSONDecoder().decode(Payload.self, from: data)
                        else {
                            print("[]")
                            fflush(stdout)
                            continue
                        }

                        let results = await sessionActor.translate(payload.texts)
                        let outData = (try? JSONEncoder().encode(results))
                            ?? (try! JSONEncoder().encode(payload.texts))
                        print(String(data: outData, encoding: .utf8)!)
                        fflush(stdout)
                    }
                    // stdin closed — exit cleanly
                    await MainActor.run { NSApp.terminate(nil) }
                }.value
            }
    }
}

// MARK: - Entry Point

let sessionActor = SessionActor()

let config = TranslationSession.Configuration(
    source: Locale.Language(identifier: sourceLang),
    target: Locale.Language(identifier: targetLang)
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

let hostingView = NSHostingView(
    rootView: TranslatorDaemonView(config: config, sessionActor: sessionActor)
)
hostingView.frame = NSRect(x: 0, y: 0, width: 1, height: 1)
window.contentView = hostingView
window.makeKeyAndOrderFront(nil)

app.run()
