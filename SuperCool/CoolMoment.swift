import Foundation

enum CoolMomentValidationError: LocalizedError, Equatable {
    case emptyTitle
    case titleTooLong(maximum: Int)

    var errorDescription: String? {
        switch self {
        case .emptyTitle:
            return NSLocalizedString("validation.empty", comment: "")
        case .titleTooLong(let maximum):
            return String(format: NSLocalizedString("validation.tooLong", comment: ""), maximum)
        }
    }
}

struct CoolMoment: Codable, Equatable, Identifiable {
    static let maximumTitleLength = 120

    let id: UUID
    let title: String
    let createdAt: Date

    init(id: UUID = UUID(), title: String, createdAt: Date = Date()) throws {
        let normalized = title
            .components(separatedBy: .whitespacesAndNewlines)
            .filter { !$0.isEmpty }
            .joined(separator: " ")

        guard !normalized.isEmpty else {
            throw CoolMomentValidationError.emptyTitle
        }
        guard normalized.count <= Self.maximumTitleLength else {
            throw CoolMomentValidationError.titleTooLong(maximum: Self.maximumTitleLength)
        }

        self.id = id
        self.title = normalized
        self.createdAt = createdAt
    }

    private enum CodingKeys: String, CodingKey {
        case id
        case title
        case createdAt
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try self.init(
            id: container.decode(UUID.self, forKey: .id),
            title: container.decode(String.self, forKey: .title),
            createdAt: container.decode(Date.self, forKey: .createdAt)
        )
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(id, forKey: .id)
        try container.encode(title, forKey: .title)
        try container.encode(createdAt, forKey: .createdAt)
    }
}
