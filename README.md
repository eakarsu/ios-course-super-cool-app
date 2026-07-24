# SuperCool

SuperCool is a small, local-first iOS app for recording “cool moments.” It now demonstrates one complete workflow instead of the original static course screen: users can add, validate, persist, reload, and delete moments; recover from malformed local data; and keep using the app offline.

## Requirements

- Xcode 16 or newer
- iOS 15 or newer
- No third-party dependencies, backend, account, or secrets

## Build and test

```sh
xcodebuild \
  -project SuperCool.xcodeproj \
  -scheme SuperCool \
  -destination 'generic/platform=iOS Simulator' \
  CODE_SIGNING_ALLOWED=NO \
  clean build

xcodebuild \
  -project SuperCool.xcodeproj \
  -scheme SuperCool \
  -destination 'platform=iOS Simulator,OS=latest,name=iPhone 16 Pro' \
  CODE_SIGNING_ALLOWED=NO \
  test

# Portable model/persistence suite; does not require CoreSimulator
swift test --parallel
```

The shared scheme runs model, persistence, corruption-recovery, connectivity, localization, launch, rotation, offline, malformed-archive, and persistence-across-launch tests. CI runs the same build and suites. The archive migrates the legacy schema-0 envelope to schema 1 exactly once and fails visibly on unknown future versions.

## Configuration and architecture

- `CoolMoment` owns validation and Codable boundaries.
- `FileMomentStore` owns a versioned, atomically written archive protected while the device is locked.
- `NetworkStatusMonitor` owns reachability; it is deliberately informational because the current workflow is local-first.
- `ViewController` renders loading, empty, content, and recoverable error states with Dynamic Type and stable accessibility identifiers.
- `Config/App.xcconfig` contains safe, non-secret defaults. Supply bundle/signing overrides locally or in protected CI settings.

See `docs/RELEASE.md` for privacy, telemetry, signing, asset, and release-owner gates.

## Isolated runtime-verification companion

The campaign-required root `start.sh` launches a separate loopback-only verification
companion; it does not launch, replace, or inspect the native UIKit app. The companion
provides a real local login UI, SQLite-backed sessions, and a protected OpenRouter
governance advisory whose provider receipt and output are stored append-only. See
`docs/RUNTIME_COMPANION.md` for its exact boundary and verification commands.
