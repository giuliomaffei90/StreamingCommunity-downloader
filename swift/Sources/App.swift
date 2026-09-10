import AppKit
import SwiftUI

@main
struct StreamingCommunityApp: App {
    @NSApplicationDelegateAdaptor private var delegate: AppDelegate
    @State private var downloads = Downloads()

    init() {
        UserDefaults.standard.register(defaults: [
            "maxDownloads": 3, "maxSegments": 16, "notifications": true, "transcode": false, "maxTranscodes": 1,
        ])
    }

    var body: some Scene {
        Window("StreamingCommunity Downloader", id: "main") {
            ContentView().environment(downloads)
        }
        .defaultSize(width: 1280, height: 860)
        .windowResizability(.contentMinSize)
        Settings { SettingsView() }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        // `swift run` starts a bare executable, which macOS treats as a background tool until told otherwise.
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}
