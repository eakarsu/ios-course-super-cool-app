import UIKit

final class ViewController: UIViewController {
    private let store: MomentStoring
    private let connectivity: NetworkStatusProviding
    private let loadingDelay: TimeInterval
    private var moments: [CoolMoment] = []
    private var restoredOffset: CGFloat?

    private let tableView = UITableView(frame: .zero, style: .insetGrouped)
    private let activityIndicator = UIActivityIndicatorView(style: .large)
    private let emptyLabel = UILabel()
    private let errorLabel = UILabel()
    private let connectivityLabel = UILabel()
    private let retryButton = UIButton(type: .system)
    private let resetButton = UIButton(type: .system)

    init(
        store: MomentStoring,
        connectivity: NetworkStatusProviding,
        loadingDelay: TimeInterval = 0
    ) {
        self.store = store
        self.connectivity = connectivity
        self.loadingDelay = loadingDelay
        super.init(nibName: nil, bundle: nil)
        restorationIdentifier = "moments.list"
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) {
        fatalError("ViewController must be created with a moment store and connectivity provider")
    }

    override func viewDidLoad() {
        super.viewDidLoad()
        configureInterface()
        configureConnectivity()
        loadMoments()
    }

    deinit {
        connectivity.stop()
    }

    private func configureInterface() {
        title = text("moments.title")
        view.backgroundColor = .systemBackground
        view.accessibilityIdentifier = "moments.root"
        navigationItem.rightBarButtonItem = UIBarButtonItem(
            barButtonSystemItem: .add,
            target: self,
            action: #selector(addMoment)
        )
        navigationItem.rightBarButtonItem?.accessibilityIdentifier = "moments.add"

        connectivityLabel.translatesAutoresizingMaskIntoConstraints = false
        connectivityLabel.font = .preferredFont(forTextStyle: .footnote)
        connectivityLabel.adjustsFontForContentSizeCategory = true
        connectivityLabel.numberOfLines = 0
        connectivityLabel.textAlignment = .center
        connectivityLabel.accessibilityIdentifier = "moments.connectivity"

        tableView.translatesAutoresizingMaskIntoConstraints = false
        tableView.dataSource = self
        tableView.delegate = self
        tableView.register(UITableViewCell.self, forCellReuseIdentifier: "MomentCell")
        tableView.accessibilityIdentifier = "moments.list"
        tableView.refreshControl = UIRefreshControl()
        tableView.refreshControl?.addTarget(self, action: #selector(refreshMoments), for: .valueChanged)

        activityIndicator.translatesAutoresizingMaskIntoConstraints = false
        activityIndicator.accessibilityIdentifier = "moments.loading"

        emptyLabel.translatesAutoresizingMaskIntoConstraints = false
        emptyLabel.text = text("moments.empty")
        emptyLabel.font = .preferredFont(forTextStyle: .title3)
        emptyLabel.adjustsFontForContentSizeCategory = true
        emptyLabel.textAlignment = .center
        emptyLabel.numberOfLines = 0
        emptyLabel.accessibilityIdentifier = "moments.empty"

        errorLabel.translatesAutoresizingMaskIntoConstraints = false
        errorLabel.font = .preferredFont(forTextStyle: .body)
        errorLabel.adjustsFontForContentSizeCategory = true
        errorLabel.textColor = .systemRed
        errorLabel.textAlignment = .center
        errorLabel.numberOfLines = 0
        errorLabel.accessibilityIdentifier = "moments.error"

        retryButton.translatesAutoresizingMaskIntoConstraints = false
        retryButton.setTitle(text("actions.retry"), for: .normal)
        retryButton.titleLabel?.font = .preferredFont(forTextStyle: .headline)
        retryButton.addTarget(self, action: #selector(refreshMoments), for: .touchUpInside)
        retryButton.accessibilityIdentifier = "moments.retry"

        resetButton.translatesAutoresizingMaskIntoConstraints = false
        resetButton.setTitle(text("actions.reset"), for: .normal)
        resetButton.titleLabel?.font = .preferredFont(forTextStyle: .headline)
        resetButton.addTarget(self, action: #selector(resetLocalData), for: .touchUpInside)
        resetButton.accessibilityIdentifier = "moments.reset"

        view.addSubview(connectivityLabel)
        view.addSubview(tableView)
        view.addSubview(activityIndicator)
        view.addSubview(emptyLabel)
        view.addSubview(errorLabel)
        view.addSubview(retryButton)
        view.addSubview(resetButton)

        NSLayoutConstraint.activate([
            connectivityLabel.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor, constant: 8),
            connectivityLabel.leadingAnchor.constraint(equalTo: view.layoutMarginsGuide.leadingAnchor),
            connectivityLabel.trailingAnchor.constraint(equalTo: view.layoutMarginsGuide.trailingAnchor),

            tableView.topAnchor.constraint(equalTo: connectivityLabel.bottomAnchor, constant: 4),
            tableView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            tableView.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            tableView.bottomAnchor.constraint(equalTo: view.bottomAnchor),

            activityIndicator.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            activityIndicator.centerYAnchor.constraint(equalTo: view.centerYAnchor),

            emptyLabel.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            emptyLabel.centerYAnchor.constraint(equalTo: view.centerYAnchor),
            emptyLabel.leadingAnchor.constraint(greaterThanOrEqualTo: view.layoutMarginsGuide.leadingAnchor),
            emptyLabel.trailingAnchor.constraint(lessThanOrEqualTo: view.layoutMarginsGuide.trailingAnchor),

            errorLabel.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            errorLabel.centerYAnchor.constraint(equalTo: view.centerYAnchor, constant: -48),
            errorLabel.leadingAnchor.constraint(equalTo: view.layoutMarginsGuide.leadingAnchor),
            errorLabel.trailingAnchor.constraint(equalTo: view.layoutMarginsGuide.trailingAnchor),

            retryButton.topAnchor.constraint(equalTo: errorLabel.bottomAnchor, constant: 12),
            retryButton.centerXAnchor.constraint(equalTo: view.centerXAnchor),

            resetButton.topAnchor.constraint(equalTo: retryButton.bottomAnchor, constant: 8),
            resetButton.centerXAnchor.constraint(equalTo: view.centerXAnchor)
        ])
    }

    private func configureConnectivity() {
        connectivity.statusDidChange = { [weak self] status in
            self?.renderConnectivity(status)
        }
        renderConnectivity(connectivity.status)
        connectivity.start()
    }

    private func renderConnectivity(_ status: ConnectivityStatus) {
        switch status {
        case .online:
            connectivityLabel.text = text("connectivity.online")
            connectivityLabel.textColor = .secondaryLabel
        case .offline:
            connectivityLabel.text = text("connectivity.offline")
            connectivityLabel.textColor = .systemOrange
        }
    }

    private func loadMoments() {
        renderLoading()
        // Yield one run-loop turn so loading is a real rendered state instead of
        // being replaced by empty/content before UIKit can draw it.
        DispatchQueue.main.asyncAfter(deadline: .now() + loadingDelay) { [weak self] in
            self?.performLoad()
        }
    }

    private func performLoad() {
        do {
            moments = try store.load()
            renderContent()
        } catch {
            renderError(error)
        }
    }

    private func renderLoading() {
        activityIndicator.startAnimating()
        navigationItem.rightBarButtonItem?.isEnabled = false
        tableView.isHidden = true
        emptyLabel.isHidden = true
        errorLabel.isHidden = true
        retryButton.isHidden = true
        resetButton.isHidden = true
    }

    private func renderContent() {
        activityIndicator.stopAnimating()
        navigationItem.rightBarButtonItem?.isEnabled = true
        tableView.refreshControl?.endRefreshing()
        tableView.isHidden = moments.isEmpty
        emptyLabel.isHidden = !moments.isEmpty
        errorLabel.isHidden = true
        retryButton.isHidden = true
        resetButton.isHidden = true
        tableView.reloadData()

        if let restoredOffset {
            tableView.setContentOffset(CGPoint(x: 0, y: restoredOffset), animated: false)
            self.restoredOffset = nil
        }
    }

    private func renderError(_ error: Error) {
        activityIndicator.stopAnimating()
        navigationItem.rightBarButtonItem?.isEnabled = false
        tableView.refreshControl?.endRefreshing()
        tableView.isHidden = true
        emptyLabel.isHidden = true
        errorLabel.text = String(format: text("moments.error.format"), error.localizedDescription)
        errorLabel.isHidden = false
        retryButton.isHidden = false
        resetButton.isHidden = false
        UIAccessibility.post(notification: .announcement, argument: errorLabel.text)
    }

    @objc private func refreshMoments() {
        loadMoments()
    }

    @objc private func resetLocalData() {
        do {
            try store.reset()
            moments = []
            renderContent()
        } catch {
            renderError(error)
        }
    }

    @objc private func addMoment() {
        let alert = UIAlertController(
            title: text("add.title"),
            message: text("add.message"),
            preferredStyle: .alert
        )
        alert.addTextField { textField in
            textField.placeholder = self.text("add.placeholder")
            textField.accessibilityIdentifier = "moments.input"
            textField.autocapitalizationType = .sentences
            textField.clearButtonMode = .whileEditing
        }
        alert.addAction(UIAlertAction(title: text("actions.cancel"), style: .cancel))
        alert.addAction(UIAlertAction(title: text("actions.save"), style: .default) { [weak self, weak alert] _ in
            self?.saveMoment(title: alert?.textFields?.first?.text ?? "")
        })
        present(alert, animated: true)
    }

    private func saveMoment(title: String) {
        let previous = moments
        do {
            let moment = try CoolMoment(title: title)
            moments.insert(moment, at: 0)
            try store.save(moments)
            renderContent()
            UIAccessibility.post(notification: .announcement, argument: text("moments.saved"))
        } catch {
            moments = previous
            showValidationOrStorageError(error)
        }
    }

    private func deleteMoment(at indexPath: IndexPath) {
        let previous = moments
        moments.remove(at: indexPath.row)
        do {
            try store.save(moments)
            renderContent()
        } catch {
            moments = previous
            renderError(error)
        }
    }

    private func showValidationOrStorageError(_ error: Error) {
        let alert = UIAlertController(
            title: text("validation.title"),
            message: error.localizedDescription,
            preferredStyle: .alert
        )
        alert.addAction(UIAlertAction(title: text("actions.ok"), style: .default))
        present(alert, animated: true)
    }

    override func encodeRestorableState(with coder: NSCoder) {
        super.encodeRestorableState(with: coder)
        coder.encode(Double(tableView.contentOffset.y), forKey: "moments.contentOffset")
    }

    override func decodeRestorableState(with coder: NSCoder) {
        super.decodeRestorableState(with: coder)
        restoredOffset = CGFloat(coder.decodeDouble(forKey: "moments.contentOffset"))
    }

    private func text(_ key: String) -> String {
        NSLocalizedString(key, comment: "")
    }
}

extension ViewController: UITableViewDataSource, UITableViewDelegate {
    func tableView(_ tableView: UITableView, numberOfRowsInSection section: Int) -> Int {
        moments.count
    }

    func tableView(_ tableView: UITableView, cellForRowAt indexPath: IndexPath) -> UITableViewCell {
        let cell = tableView.dequeueReusableCell(withIdentifier: "MomentCell", for: indexPath)
        var configuration = cell.defaultContentConfiguration()
        let moment = moments[indexPath.row]
        configuration.text = moment.title
        configuration.textProperties.font = .preferredFont(forTextStyle: .body)
        configuration.secondaryText = Self.dateFormatter.string(from: moment.createdAt)
        configuration.secondaryTextProperties.font = .preferredFont(forTextStyle: .caption1)
        cell.contentConfiguration = configuration
        cell.accessibilityIdentifier = "moments.row.\(indexPath.row)"
        cell.accessibilityLabel = "\(moment.title), \(configuration.secondaryText ?? "")"
        return cell
    }

    func tableView(
        _ tableView: UITableView,
        trailingSwipeActionsConfigurationForRowAt indexPath: IndexPath
    ) -> UISwipeActionsConfiguration? {
        let delete = UIContextualAction(style: .destructive, title: text("actions.delete")) { [weak self] _, _, completion in
            self?.deleteMoment(at: indexPath)
            completion(true)
        }
        return UISwipeActionsConfiguration(actions: [delete])
    }

    private static let dateFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateStyle = .medium
        formatter.timeStyle = .short
        return formatter
    }()
}
