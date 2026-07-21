import Foundation

enum MomentStoreError: LocalizedError, Equatable {
    case corruptedData
    case unsupportedSchema(Int)

    var errorDescription: String? {
        switch self {
        case .corruptedData:
            return NSLocalizedString("storage.corrupted", comment: "")
        case .unsupportedSchema(let version):
            return String(format: NSLocalizedString("storage.unsupported", comment: ""), version)
        }
    }
}

protocol MomentStoring: AnyObject {
    func load() throws -> [CoolMoment]
    func save(_ moments: [CoolMoment]) throws
    func reset() throws
}

enum AppPaths {
    static var momentsURL: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
        return base.appendingPathComponent("SuperCool", isDirectory: true)
            .appendingPathComponent("moments-v1.json")
    }
}

private struct MomentArchive: Codable {
    static let currentSchema = 1

    let schemaVersion: Int
    let moments: [CoolMoment]
}

final class FileMomentStore: MomentStoring {
    private let fileURL: URL
    private let fileManager: FileManager
    private let encoder: JSONEncoder
    private let decoder: JSONDecoder

    init(fileURL: URL, fileManager: FileManager = .default) {
        self.fileURL = fileURL
        self.fileManager = fileManager
        encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        encoder.outputFormatting = [.sortedKeys]
        decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
    }

    func load() throws -> [CoolMoment] {
        guard fileManager.fileExists(atPath: fileURL.path) else {
            return []
        }

        do {
            let archive = try decoder.decode(MomentArchive.self, from: Data(contentsOf: fileURL))
            switch archive.schemaVersion {
            case MomentArchive.currentSchema:
                break
            case 0:
                // Schema 0 used the same fields but had no durable version contract.
                // Rewriting it once makes the migration explicit and idempotent.
                try save(archive.moments)
            default:
                throw MomentStoreError.unsupportedSchema(archive.schemaVersion)
            }
            return archive.moments.sorted { $0.createdAt > $1.createdAt }
        } catch let error as MomentStoreError {
            throw error
        } catch {
            throw MomentStoreError.corruptedData
        }
    }

    func save(_ moments: [CoolMoment]) throws {
        try fileManager.createDirectory(
            at: fileURL.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        let archive = MomentArchive(schemaVersion: MomentArchive.currentSchema, moments: moments)
        try encoder.encode(archive).write(to: fileURL, options: [.atomic, .completeFileProtection])
    }

    func reset() throws {
        guard fileManager.fileExists(atPath: fileURL.path) else {
            return
        }
        try fileManager.removeItem(at: fileURL)
    }
}
