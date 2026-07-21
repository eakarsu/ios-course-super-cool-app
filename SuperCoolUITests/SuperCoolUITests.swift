import XCTest

final class SuperCoolUITests: XCTestCase {
    override func setUp() {
        super.setUp()
        continueAfterFailure = false
    }

    func testLoadingStateIsVisibleBeforeContent() {
        let app = launch(arguments: ["-reset-store", "-delay-load"])

        XCTAssertTrue(app.activityIndicators["moments.loading"].waitForExistence(timeout: 2))
        XCTAssertTrue(app.staticTexts["moments.empty"].waitForExistence(timeout: 3))
    }

    func testEmptyAddRotateAndPersistAcrossLaunches() {
        let app = launch(arguments: ["-reset-store"])
        XCTAssertTrue(app.staticTexts["moments.empty"].waitForExistence(timeout: 5))

        XCUIDevice.shared.orientation = .landscapeLeft
        XCTAssertTrue(app.otherElements["moments.root"].waitForExistence(timeout: 2))
        XCUIDevice.shared.orientation = .portrait

        app.buttons["moments.add"].tap()
        let input = app.textFields["moments.input"]
        XCTAssertTrue(input.waitForExistence(timeout: 2))
        input.typeText("First cool moment")
        app.alerts.buttons["Save"].tap()
        XCTAssertTrue(app.staticTexts["First cool moment"].waitForExistence(timeout: 3))

        app.terminate()
        let restored = launch()
        XCTAssertTrue(restored.staticTexts["First cool moment"].waitForExistence(timeout: 5))
    }

    func testOfflineStateRemainsUsable() {
        let app = launch(arguments: ["-reset-store", "-force-offline"])

        let offline = app.staticTexts["moments.connectivity"]
        XCTAssertTrue(offline.waitForExistence(timeout: 5))
        XCTAssertEqual(offline.label, "Offline — changes remain on this device")
        XCTAssertTrue(app.buttons["moments.add"].isEnabled)

        app.buttons["moments.add"].tap()
        app.textFields["moments.input"].typeText("Created offline")
        app.alerts.buttons["Save"].tap()
        XCTAssertTrue(app.staticTexts["Created offline"].waitForExistence(timeout: 3))

        app.terminate()
        let recovered = launch(arguments: ["-force-online"])
        XCTAssertTrue(recovered.staticTexts["Created offline"].waitForExistence(timeout: 5))
        XCTAssertEqual(recovered.staticTexts["moments.connectivity"].label, "Online")
    }

    func testMalformedArchiveShowsRecoveryAction() {
        let app = launch(arguments: ["-reset-store", "-seed-malformed-store"])

        XCTAssertTrue(app.staticTexts["moments.error"].waitForExistence(timeout: 5))
        let reset = app.buttons["moments.reset"]
        XCTAssertTrue(reset.exists)
        reset.tap()
        XCTAssertTrue(app.staticTexts["moments.empty"].waitForExistence(timeout: 3))
    }

    func testSpanishLocalization() {
        let app = launch(
            arguments: ["-reset-store", "-AppleLanguages", "(es)", "-AppleLocale", "es_ES"]
        )

        XCTAssertTrue(app.navigationBars["Momentos geniales"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Aún no hay momentos. Añade el primero."].exists)
    }

    @discardableResult
    private func launch(arguments: [String] = []) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = arguments
        app.launchEnvironment["SUPERCOOL_UI_TESTING"] = "1"
        app.launch()
        return app
    }
}
