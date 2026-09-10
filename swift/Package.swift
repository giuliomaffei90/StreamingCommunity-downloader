// swift-tools-version:5.10
import PackageDescription

// The native port of the Python app one directory up. `swift run` opens the window, and Xcode opens
// this file as a project.
let package = Package(
    name: "StreamingCommunityDownloader",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(name: "StreamingCommunityDownloader", path: "Sources"),
        .testTarget(name: "Tests", dependencies: ["StreamingCommunityDownloader"], path: "Tests"),
    ]
)
