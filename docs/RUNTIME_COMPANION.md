# Runtime-verification companion

The supported product remains the local-first UIKit application in
`SuperCool.xcodeproj`. The root `start.sh` does not launch a simulator and does not
pretend that the native app is a web product. It launches isolated, standard-library
verification infrastructure for the campaign-required credential, persistence, and
OpenRouter acceptance checks.

The ignored `0600` root `.env` supplies the assigned loopback ports `31006` and `31007`,
an absolute SQLite path, one bootstrap administrator, and the approved OpenRouter
key/model/base. The committed `.env.example` contains no usable credentials. Bare
`./start.sh` installs nothing, kills nothing, refuses occupied or changed ports, and
fails closed on invalid runtime configuration.

The companion provides:

- SQLite-backed password login, digest-only bearer sessions, authenticated identity,
  logout/revocation, and restart persistence.
- A real browser login form on the separate UI port. Its session token stays only in
  page memory and is not written to browser storage.
- An authenticated `POST /api/ai/moment-governance-review` route that calls the
  canonical `https://openrouter.ai/api/v1` chat-completions endpoint.
- Append-only AI evidence containing the prompt, configured/returned models, provider
  receipt, output, status, and timing. Unexpected provider failures become terminal
  safe failures instead of traceback logs or abandoned `PENDING` rows.
- Structured request logs containing method, query-free path, status, and duration—no
  credentials, authorization headers, prompts, provider content, or query strings.

Run `scripts/verify-companion.sh` for companion tests, Python/static linting, the empty
third-party dependency audit, shell syntax, and diff validation. Run `swift test` for
the portable native domain suite. Simulator launch and signed distribution remain
subject to the CoreSimulator, platform, signing, account, asset, and human-approval
gates documented in `README.md` and `docs/RELEASE.md`.
