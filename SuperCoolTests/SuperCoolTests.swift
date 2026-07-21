import XCTest
@testable import SuperCool

final class SuperCoolTests: XCTestCase {
    private var temporaryDirectory: URL!

    override func setUpWithError() throws {
        temporaryDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent("SuperCoolTests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(
            at: temporaryDirectory,
            withIntermediateDirectories: true
        )
    }

    override func tearDownWithError() throws {
        if let temporaryDirectory {
            try? FileManager.default.removeItem(at: temporaryDirectory)
        }
    }

    func testMomentNormalizesWhitespaceAndRetainsIdentity() throws {
        let id = UUID()
        let createdAt = Date(timeIntervalSince1970: 1_700_000_000)
        let moment = try CoolMoment(
            id: id,
            title: "  A   very\n cool moment  ",
            createdAt: createdAt
        )

        XCTAssertEqual(moment.id, id)
        XCTAssertEqual(moment.title, "A very cool moment")
        XCTAssertEqual(moment.createdAt, createdAt)
    }

    func testMomentRejectsEmptyAndOversizedTitles() {
        XCTAssertThrowsError(try CoolMoment(title: " \n ")) { error in
            XCTAssertEqual(error as? CoolMomentValidationError, .emptyTitle)
        }

        let oversized = String(repeating: "x", count: CoolMoment.maximumTitleLength + 1)
        XCTAssertThrowsError(try CoolMoment(title: oversized)) { error in
            XCTAssertEqual(
                error as? CoolMomentValidationError,
                .titleTooLong(maximum: CoolMoment.maximumTitleLength)
            )
        }
    }

    func testStoreRoundTripIsDurableAndSortedNewestFirst() throws {
        let url = temporaryDirectory.appendingPathComponent("moments.json")
        let store = FileMomentStore(fileURL: url)
        let older = try CoolMoment(title: "Older", createdAt: Date(timeIntervalSince1970: 100))
        let newer = try CoolMoment(title: "Newer", createdAt: Date(timeIntervalSince1970: 200))

        try store.save([older, newer])

        XCTAssertTrue(FileManager.default.fileExists(atPath: url.path))
        XCTAssertEqual(try FileMomentStore(fileURL: url).load(), [newer, older])
    }

    func testStoreReportsMalformedDataAndCanRecoverWithReset() throws {
        let url = temporaryDirectory.appendingPathComponent("moments.json")
        try Data("{not-json".utf8).write(to: url)
        let store = FileMomentStore(fileURL: url)

        XCTAssertThrowsError(try store.load()) { error in
            XCTAssertEqual(error as? MomentStoreError, .corruptedData)
        }

        try store.reset()
        XCTAssertEqual(try store.load(), [])
    }

    func testStoreRejectsUnknownSchemaVersion() throws {
        let url = temporaryDirectory.appendingPathComponent("moments.json")
        try Data("{\"schemaVersion\":99,\"moments\":[]}".utf8).write(to: url)

        XCTAssertThrowsError(try FileMomentStore(fileURL: url).load()) { error in
            XCTAssertEqual(error as? MomentStoreError, .unsupportedSchema(99))
        }
    }

    func testStoreMigratesLegacySchemaAndRewritesCurrentVersion() throws {
        let url = temporaryDirectory.appendingPathComponent("moments.json")
        let id = UUID()
        let legacy = """
        {"schemaVersion":0,"moments":[{"id":"\(id.uuidString)","title":"Legacy moment","createdAt":"2024-01-01T00:00:00Z"}]}
        """
        try Data(legacy.utf8).write(to: url)

        let migrated = try FileMomentStore(fileURL: url).load()

        XCTAssertEqual(migrated.map(\.title), ["Legacy moment"])
        let rewritten = try String(contentsOf: url, encoding: .utf8)
        XCTAssertTrue(rewritten.contains("\"schemaVersion\":1"))
        XCTAssertFalse(rewritten.contains("\"schemaVersion\":0"))
    }

    func testForcedOfflineMonitorPublishesOfflineState() {
        let monitor = NetworkStatusMonitor(forceOffline: true)
        var received: ConnectivityStatus?
        monitor.statusDidChange = { received = $0 }

        monitor.start()

        XCTAssertEqual(monitor.status, .offline)
        XCTAssertEqual(received, .offline)
        monitor.stop()
    }

    func testForcedOnlineMonitorPublishesOnlineState() {
        let monitor = NetworkStatusMonitor(forceOnline: true)
        var received: ConnectivityStatus?
        monitor.statusDidChange = { received = $0 }

        monitor.start()

        XCTAssertEqual(monitor.status, .online)
        XCTAssertEqual(received, .online)
        monitor.stop()
    }

    func testEnglishAndSpanishResourcesContainCriticalMessages() throws {
        let resourceBundle = Bundle(for: AppDelegate.self)
        let englishPath = try XCTUnwrap(resourceBundle.path(forResource: "en", ofType: "lproj"))
        let spanishPath = try XCTUnwrap(resourceBundle.path(forResource: "es", ofType: "lproj"))
        let english = try XCTUnwrap(Bundle(path: englishPath))
        let spanish = try XCTUnwrap(Bundle(path: spanishPath))

        XCTAssertEqual(english.localizedString(forKey: "moments.title", value: nil, table: nil), "Cool Moments")
        XCTAssertEqual(spanish.localizedString(forKey: "moments.title", value: nil, table: nil), "Momentos geniales")
        XCTAssertNotEqual(
            spanish.localizedString(forKey: "connectivity.offline", value: nil, table: nil),
            "connectivity.offline"
        )
    }
}
