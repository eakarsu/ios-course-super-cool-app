import Foundation
import Network

enum ConnectivityStatus: Equatable {
    case online
    case offline
}

protocol NetworkStatusProviding: AnyObject {
    var status: ConnectivityStatus { get }
    var statusDidChange: ((ConnectivityStatus) -> Void)? { get set }
    func start()
    func stop()
}

final class NetworkStatusMonitor: NetworkStatusProviding {
    private let monitor: NWPathMonitor?
    private let queue = DispatchQueue(label: "com.example.SuperCool.connectivity")
    private(set) var status: ConnectivityStatus
    var statusDidChange: ((ConnectivityStatus) -> Void)?

    init(forceOffline: Bool = false, forceOnline: Bool = false) {
        if forceOffline || forceOnline {
            monitor = nil
            status = forceOffline ? .offline : .online
        } else {
            monitor = NWPathMonitor()
            status = .online
        }
    }

    func start() {
        guard let monitor else {
            statusDidChange?(status)
            return
        }
        monitor.pathUpdateHandler = { [weak self] path in
            let next: ConnectivityStatus = path.status == .satisfied ? .online : .offline
            DispatchQueue.main.async {
                self?.status = next
                self?.statusDidChange?(next)
            }
        }
        monitor.start(queue: queue)
    }

    func stop() {
        monitor?.cancel()
    }
}
