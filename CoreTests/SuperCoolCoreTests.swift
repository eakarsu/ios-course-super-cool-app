import Foundation
import XCTest
@testable import SuperCoolCore

final class SuperCoolCoreTests: XCTestCase {
    private var temporaryDirectory: URL!

    override func setUpWithError() throws {
        temporaryDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent("SuperCoolCoreTests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: temporaryDirectory, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        if let temporaryDirectory {
            try? FileManager.default.removeItem(at: temporaryDirectory)
        }
    }

    func testValidationNormalizesInputAndRejectsInvalidValues() throws {
        XCTAssertEqual(try CoolMoment(title: "  Very\n cool  ").title, "Very cool")
        XCTAssertThrowsError(try CoolMoment(title: " \n "))
        XCTAssertThrowsError(
            try CoolMoment(title: String(repeating: "x", count: CoolMoment.maximumTitleLength + 1))
        )
    }

    func testArchiveRoundTripSurvivesAStoreRestart() throws {
        let url = temporaryDirectory.appendingPathComponent("moments.json")
        let old = try CoolMoment(title: "Old", createdAt: Date(timeIntervalSince1970: 1))
        let new = try CoolMoment(title: "New", createdAt: Date(timeIntervalSince1970: 2))

        try FileMomentStore(fileURL: url).save([old, new])

        XCTAssertEqual(try FileMomentStore(fileURL: url).load(), [new, old])
    }

    func testLegacyArchiveMigratesOnceAndRemainsReadable() throws {
        let url = temporaryDirectory.appendingPathComponent("moments.json")
        let id = UUID()
        let legacy = """
        {"schemaVersion":0,"moments":[{"id":"\(id.uuidString)","title":"Legacy","createdAt":"2024-01-01T00:00:00Z"}]}
        """
        try Data(legacy.utf8).write(to: url)

        let store = FileMomentStore(fileURL: url)
        XCTAssertEqual(try store.load().map(\.title), ["Legacy"])
        XCTAssertEqual(try store.load().map(\.title), ["Legacy"])
        XCTAssertTrue(try String(contentsOf: url).contains("\"schemaVersion\":1"))
    }

    func testMalformedAndFutureArchivesFailClosedAndResetRecovers() throws {
        let url = temporaryDirectory.appendingPathComponent("moments.json")
        let store = FileMomentStore(fileURL: url)

        try Data("{malformed".utf8).write(to: url)
        XCTAssertThrowsError(try store.load()) { error in
            XCTAssertEqual(error as? MomentStoreError, .corruptedData)
        }

        try Data("{\"schemaVersion\":99,\"moments\":[]}".utf8).write(to: url)
        XCTAssertThrowsError(try store.load()) { error in
            XCTAssertEqual(error as? MomentStoreError, .unsupportedSchema(99))
        }

        try store.reset()
        XCTAssertEqual(try store.load(), [])
    }

    func testForcedOfflineMonitorIsDeterministic() {
        let monitor = NetworkStatusMonitor(forceOffline: true)
        var states: [ConnectivityStatus] = []
        monitor.statusDidChange = { states.append($0) }

        monitor.start()

        XCTAssertEqual(monitor.status, .offline)
        XCTAssertEqual(states, [.offline])
        monitor.stop()
    }

    func testForcedOnlineMonitorIsDeterministic() {
        let monitor = NetworkStatusMonitor(forceOnline: true)
        var received: ConnectivityStatus?
        monitor.statusDidChange = { received = $0 }

        monitor.start()

        XCTAssertEqual(monitor.status, .online)
        XCTAssertEqual(received, .online)
        monitor.stop()
    }
}
