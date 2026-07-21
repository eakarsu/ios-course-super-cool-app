# Release and operations

## Release gate

1. Run `xcodebuild -project SuperCool.xcodeproj -scheme SuperCool -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO clean build`.
2. Run the unit and UI suites on the current supported iOS simulator.
3. Validate `SuperCool/PrivacyInfo.xcprivacy` with `plutil -lint` and review it whenever data collection or a required-reason API is introduced.
4. Set a real bundle identifier and signing team in a private/local override; do not commit certificates, profiles, or account identifiers.
5. Archive in Release mode, perform an organizer validation, and require a human release approval.

## Privacy, analytics, and crashes

The app stores user-authored moments only in its Application Support directory with complete file protection. It has no account, remote API, advertising, analytics, tracking, or crash-reporting SDK. The privacy manifest therefore declares no collected data and no tracking. Do not add telemetry silently: first define retention, consent, deletion, access controls, a data-processing owner, and update the manifest and user-facing privacy notice.

For a production release, the owner must choose an approved crash-reporting service or document an intentional reliance on Apple diagnostics, including retention and incident-response ownership. Upload dSYMs only to that approved service.

## Assets and store metadata

The checked-in app-icon catalog contains opaque iPhone, iPad, and 1024-pixel marketing artwork generated for SuperCool. A release owner must still approve that artwork and supply screenshots, support/privacy URLs, age rating, export-compliance answers, and localized store copy before distribution.
