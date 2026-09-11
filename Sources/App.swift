import AppKit
import SwiftUI

@main
struct StreamingCommunityApp: App {
    @NSApplicationDelegateAdaptor private var delegate: AppDelegate
    @State private var downloads = Downloads()
    @State private var watch = DomainWatch()

    init() {
        UserDefaults.standard.register(defaults: [
            "maxDownloads": 3, "maxSegments": 16, "notifications": true, "transcode": false, "maxTranscodes": 1,
            "domainAutoCheck": true, "domainAutoApply": false, "domainCheckMinutes": 360,
        ])
    }

    var body: some Scene {
        Window("StreamingCommunity Downloader", id: "main") {
            ContentView().environment(downloads).environment(watch)
        }
        .defaultSize(width: 1280, height: 860)
        .windowResizability(.contentMinSize)
        Settings { SettingsView().frame(width: 520, height: 760).environment(downloads).environment(watch) }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        // `swift run` starts a bare executable, which macOS treats as a background tool until told otherwise.
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
        MainActor.assumeIsolated { Notifier.shared.start() }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}
