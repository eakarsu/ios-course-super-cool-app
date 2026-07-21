import UIKit

@main
final class AppDelegate: UIResponder, UIApplicationDelegate {
    var window: UIWindow?

    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
    ) -> Bool {
        let arguments = ProcessInfo.processInfo.arguments
        let environment = ProcessInfo.processInfo.environment
        let isUITesting = environment["SUPERCOOL_UI_TESTING"] == "1"
        let storeURL = AppPaths.momentsURL

        if isUITesting && arguments.contains("-reset-store") {
            try? FileManager.default.removeItem(at: storeURL)
        }

        if isUITesting && arguments.contains("-seed-malformed-store") {
            try? FileManager.default.createDirectory(
                at: storeURL.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            try? Data("{malformed".utf8).write(to: storeURL, options: .atomic)
        }

        let store = FileMomentStore(fileURL: storeURL)
        let forceOffline = isUITesting && arguments.contains("-force-offline")
        let forceOnline = isUITesting && arguments.contains("-force-online")
        let loadingDelay = isUITesting && arguments.contains("-delay-load") ? 1.0 : 0
        let connectivity = NetworkStatusMonitor(
            forceOffline: forceOffline,
            forceOnline: forceOnline
        )
        let rootViewController = ViewController(
            store: store,
            connectivity: connectivity,
            loadingDelay: loadingDelay
        )
        let navigationController = UINavigationController(rootViewController: rootViewController)
        navigationController.restorationIdentifier = "main.navigation"

        let window = UIWindow(frame: UIScreen.main.bounds)
        window.restorationIdentifier = "main.window"
        window.rootViewController = navigationController
        window.makeKeyAndVisible()
        self.window = window

        return true
    }

    func application(_ application: UIApplication, shouldSaveApplicationState coder: NSCoder) -> Bool {
        true
    }

    func application(_ application: UIApplication, shouldRestoreApplicationState coder: NSCoder) -> Bool {
        true
    }
}
