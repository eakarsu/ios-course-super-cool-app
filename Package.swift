// swift-tools-version: 5.9

import PackageDescription

let package = Package(
    name: "SuperCoolCore",
    platforms: [.macOS(.v13)],
    products: [
        .library(name: "SuperCoolCore", targets: ["SuperCoolCore"])
    ],
    targets: [
        .target(
            name: "SuperCoolCore",
            path: "SuperCool",
            exclude: [
                "AppDelegate.swift",
                "Assets.xcassets",
                "Base.lproj",
                "Boom-App.png",
                "Info.plist",
                "PrivacyInfo.xcprivacy",
                "ViewController.swift",
                "en.lproj",
                "es.lproj"
            ],
            sources: [
                "CoolMoment.swift",
                "MomentStore.swift",
                "NetworkStatusMonitor.swift"
            ]
        ),
        .testTarget(
            name: "SuperCoolCoreTests",
            dependencies: ["SuperCoolCore"],
            path: "CoreTests"
        )
    ]
)
