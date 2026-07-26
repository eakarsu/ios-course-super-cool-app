from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
import re
import secrets
import signal
import socket
import sqlite3
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

CANONICAL_OPENROUTER_BASE = "https://openrouter.ai/api/v1"
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
BEARER_PATTERN = re.compile(r"^Bearer\s+(scv_[A-Za-z0-9_-]{40,160})$", re.IGNORECASE)
MAX_BODY_BYTES = 64 * 1024
MAX_PROVIDER_BYTES = 2 * 1024 * 1024


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class Config:
    api_port: int
    ui_port: int
    database_path: Path
    admin_email: str
    admin_password: str
    session_ttl_hours: int
    openrouter_api_key: str
    openrouter_model: str
    openrouter_base_url: str
    openrouter_timeout_seconds: int

    @classmethod
    def from_env(cls, environment: dict[str, str] | os._Environ[str] = os.environ) -> Config:
        def integer(name: str, minimum: int, maximum: int) -> int:
            raw = str(environment.get(name, ""))
            if not raw.isdigit():
                raise ValueError(f"{name} must be an integer")
            value = int(raw)
            if not minimum <= value <= maximum:
                raise ValueError(f"{name} must be between {minimum} and {maximum}")
            return value

        api_port = integer("API_PORT", 1024, 65535)
        ui_port = integer("UI_PORT", 1024, 65535)
        if api_port == ui_port:
            raise ValueError("API_PORT and UI_PORT must be distinct")
        database_path = Path(str(environment.get("DATABASE_PATH", "")))
        if not database_path.is_absolute():
            raise ValueError("DATABASE_PATH must be absolute")
        email = str(environment.get("ADMIN_EMAIL", "")).strip().lower()
        if not EMAIL_PATTERN.fullmatch(email):
            raise ValueError("ADMIN_EMAIL must be valid")
        password = str(environment.get("ADMIN_PASSWORD", ""))
        if len(password) < 12:
            raise ValueError("ADMIN_PASSWORD must contain at least 12 characters")
        api_key = str(environment.get("OPENROUTER_API_KEY", "")).strip()
        model = str(environment.get("OPENROUTER_MODEL", "")).strip()
        base_url = str(environment.get("OPENROUTER_BASE_URL", "")).rstrip("/")
        if not api_key or not model:
            raise ValueError("OPENROUTER_API_KEY and OPENROUTER_MODEL are required")
        if base_url != CANONICAL_OPENROUTER_BASE:
            raise ValueError(f"OPENROUTER_BASE_URL must equal {CANONICAL_OPENROUTER_BASE}")
        return cls(
            api_port=api_port,
            ui_port=ui_port,
            database_path=database_path,
            admin_email=email,
            admin_password=password,
            session_ttl_hours=integer("SESSION_TTL_HOURS", 1, 168),
            openrouter_api_key=api_key,
            openrouter_model=model,
            openrouter_base_url=base_url,
            openrouter_timeout_seconds=integer("OPENROUTER_TIMEOUT_SECONDS", 1, 120),
        )


def password_record(password: str, salt: bytes | None = None) -> tuple[str, str]:
    resolved_salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=resolved_salt, n=16_384, r=8, p=1, dklen=64)
    return resolved_salt.hex(), digest.hex()


def verify_password(password: str, salt_hex: str, expected_hex: str) -> bool:
    try:
        _, actual = password_record(password, bytes.fromhex(salt_hex))
        return hmac.compare_digest(actual, expected_hex)
    except (TypeError, ValueError):
        return False


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Store:
    def __init__(self, config: Config):
        self.config = config
        config.database_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._migrate()
        self._bootstrap_admin()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.config.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    def _migrate(self) -> None:
        with closing(self.connect()) as database, database:
            database.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                ) STRICT;
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY CHECK(length(id) = 36),
                    email TEXT NOT NULL COLLATE NOCASE UNIQUE
                        CHECK(email = lower(email) AND length(email) BETWEEN 3 AND 254),
                    password_salt TEXT NOT NULL CHECK(length(password_salt) = 32),
                    password_hash TEXT NOT NULL CHECK(length(password_hash) = 128),
                    role TEXT NOT NULL CHECK(role IN ('ADMIN')),
                    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_login_at TEXT
                ) STRICT;
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY CHECK(length(id) = 36),
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
                    token_digest TEXT NOT NULL UNIQUE CHECK(length(token_digest) = 64),
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    revoked_at TEXT
                ) STRICT;
                CREATE INDEX IF NOT EXISTS sessions_active_idx
                    ON sessions(token_digest, expires_at) WHERE revoked_at IS NULL;
                CREATE TABLE IF NOT EXISTS ai_interactions (
                    id TEXT PRIMARY KEY CHECK(length(id) = 36),
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE RESTRICT,
                    provider TEXT NOT NULL DEFAULT 'OPENROUTER' CHECK(provider = 'OPENROUTER'),
                    prompt TEXT NOT NULL CHECK(length(prompt) BETWEEN 10 AND 12000),
                    requested_model TEXT NOT NULL CHECK(length(requested_model) BETWEEN 2 AND 200),
                    provider_model TEXT CHECK(provider_model IS NULL OR length(provider_model) BETWEEN 2 AND 200),
                    provider_receipt TEXT UNIQUE
                        CHECK(provider_receipt IS NULL OR length(provider_receipt) BETWEEN 3 AND 240),
                    output_text TEXT CHECK(output_text IS NULL OR length(output_text) BETWEEN 1 AND 100000),
                    status TEXT NOT NULL CHECK(status IN ('PENDING', 'SUCCEEDED', 'FAILED')),
                    error_code TEXT CHECK(error_code IS NULL OR length(error_code) BETWEEN 2 AND 80),
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    latency_ms INTEGER CHECK(latency_ms IS NULL OR latency_ms >= 0),
                    CHECK(
                        (status = 'PENDING' AND provider_model IS NULL AND provider_receipt IS NULL
                            AND output_text IS NULL AND error_code IS NULL AND completed_at IS NULL)
                        OR (status = 'SUCCEEDED' AND provider_model IS NOT NULL AND provider_receipt IS NOT NULL
                            AND output_text IS NOT NULL AND error_code IS NULL AND completed_at IS NOT NULL)
                        OR (status = 'FAILED' AND provider_receipt IS NULL AND output_text IS NULL
                            AND error_code IS NOT NULL AND completed_at IS NOT NULL)
                    )
                ) STRICT;
                CREATE INDEX IF NOT EXISTS ai_interactions_owner_idx
                    ON ai_interactions(user_id, created_at DESC);
                CREATE TRIGGER IF NOT EXISTS ai_interactions_terminal_immutable
                    BEFORE UPDATE ON ai_interactions WHEN OLD.status <> 'PENDING'
                    BEGIN SELECT RAISE(ABORT, 'terminal AI interactions are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS ai_interactions_no_delete
                    BEFORE DELETE ON ai_interactions
                    BEGIN SELECT RAISE(ABORT, 'AI interactions are append-only'); END;
                INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (1, CURRENT_TIMESTAMP);
                """
            )
        os.chmod(self.config.database_path, 0o600)

    def _bootstrap_admin(self) -> None:
        now = iso()
        with closing(self.connect()) as database, database:
            existing = database.execute(
                "SELECT * FROM users WHERE email = ?", (self.config.admin_email,)
            ).fetchone()
            if existing is None:
                salt, digest = password_record(self.config.admin_password)
                database.execute(
                    "INSERT INTO users(id,email,password_salt,password_hash,role,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (str(uuid.uuid4()), self.config.admin_email, salt, digest, "ADMIN", now, now),
                )
            elif not verify_password(
                self.config.admin_password, existing["password_salt"], existing["password_hash"]
            ):
                salt, digest = password_record(self.config.admin_password)
                database.execute(
                    "UPDATE users SET password_salt=?,password_hash=?,updated_at=? WHERE id=?",
                    (salt, digest, now, existing["id"]),
                )
                database.execute(
                    "UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
                    (now, existing["id"]),
                )

    def readiness(self) -> dict[str, object]:
        with closing(self.connect()) as database:
            migrations = database.execute(
                "SELECT count(*) AS count FROM schema_migrations"
            ).fetchone()["count"]
            users = database.execute(
                "SELECT count(*) AS count FROM users WHERE active=1"
            ).fetchone()["count"]
        return {"ready": migrations == 1 and users >= 1, "migrations": migrations, "activeUsers": users}

    def login(self, email: str, password: str) -> tuple[str, dict[str, object]] | None:
        normalized = email.strip().lower()
        with closing(self.connect()) as database, database:
            user = database.execute(
                "SELECT * FROM users WHERE email=? AND active=1", (normalized,)
            ).fetchone()
            if user is None or not verify_password(password, user["password_salt"], user["password_hash"]):
                return None
            now = utc_now()
            token = f"scv_{secrets.token_urlsafe(48)}"
            session_id = str(uuid.uuid4())
            expires = now + timedelta(hours=self.config.session_ttl_hours)
            database.execute(
                "UPDATE users SET last_login_at=?,updated_at=? WHERE id=?", (iso(now), iso(now), user["id"])
            )
            database.execute(
                "INSERT INTO sessions(id,user_id,token_digest,created_at,expires_at,last_seen_at) "
                "VALUES(?,?,?,?,?,?)",
                (session_id, user["id"], token_digest(token), iso(now), iso(expires), iso(now)),
            )
            return token, {
                "id": user["id"],
                "email": user["email"],
                "role": user["role"],
                "sessionId": session_id,
                "expiresAt": iso(expires),
            }

    def identity(self, token: str) -> dict[str, object] | None:
        now = iso()
        with closing(self.connect()) as database, database:
            row = database.execute(
                """SELECT s.id AS session_id,s.expires_at,u.id AS user_id,u.email,u.role
                   FROM sessions s JOIN users u ON u.id=s.user_id
                   WHERE s.token_digest=? AND s.revoked_at IS NULL AND s.expires_at>? AND u.active=1""",
                (token_digest(token), now),
            ).fetchone()
            if row is None:
                return None
            database.execute(
                "UPDATE sessions SET last_seen_at=? WHERE id=?", (now, row["session_id"])
            )
            return {
                "id": row["user_id"],
                "email": row["email"],
                "role": row["role"],
                "sessionId": row["session_id"],
                "authType": "SESSION",
            }

    def revoke(self, token: str) -> bool:
        with closing(self.connect()) as database, database:
            result = database.execute(
                "UPDATE sessions SET revoked_at=? WHERE token_digest=? AND revoked_at IS NULL",
                (iso(), token_digest(token)),
            )
            return result.rowcount == 1

    def begin_ai(self, identity: dict[str, object], prompt: str) -> str:
        interaction_id = str(uuid.uuid4())
        with closing(self.connect()) as database, database:
            database.execute(
                """INSERT INTO ai_interactions
                   (id,user_id,session_id,prompt,requested_model,status,created_at)
                   VALUES(?,?,?,?,?,'PENDING',?)""",
                (
                    interaction_id,
                    identity["id"],
                    identity["sessionId"],
                    prompt,
                    self.config.openrouter_model,
                    iso(),
                ),
            )
        return interaction_id

    def complete_ai(self, interaction_id: str, result: dict[str, str], latency_ms: int) -> None:
        with closing(self.connect()) as database, database:
            update = database.execute(
                """UPDATE ai_interactions SET provider_model=?,provider_receipt=?,output_text=?,
                   status='SUCCEEDED',completed_at=?,latency_ms=? WHERE id=? AND status='PENDING'""",
                (
                    result["model"],
                    result["receipt"],
                    result["content"],
                    iso(),
                    latency_ms,
                    interaction_id,
                ),
            )
            if update.rowcount != 1:
                raise RuntimeError("AI interaction was not pending")

    def fail_ai(self, interaction_id: str, code: str, latency_ms: int) -> None:
        with closing(self.connect()) as database, database:
            update = database.execute(
                """UPDATE ai_interactions SET status='FAILED',error_code=?,completed_at=?,latency_ms=?
                   WHERE id=? AND status='PENDING'""",
                (code, iso(), latency_ms, interaction_id),
            )
            if update.rowcount != 1:
                raise RuntimeError("AI interaction was not pending")

    def interaction(self, interaction_id: str, user_id: str) -> dict[str, object] | None:
        with closing(self.connect()) as database:
            row = database.execute(
                """SELECT id,provider,requested_model,provider_model,provider_receipt,output_text,
                          status,error_code,created_at,completed_at,latency_ms
                   FROM ai_interactions WHERE id=? AND user_id=?""",
                (interaction_id, user_id),
            ).fetchone()
        return dict(row) if row else None


class ProviderError(Exception):
    def __init__(self, code: str, message: str, status: int = HTTPStatus.BAD_GATEWAY):
        super().__init__(message)
        self.code = code
        self.status = status


def invoke_openrouter(config: Config, prompt: str) -> dict[str, str]:
    payload = json.dumps(
        {
            "model": config.openrouter_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Provide concise governance advice for optional AI features adjacent to a local-first "
                        "iOS moments app. Cover privacy, accessibility, evidence, rollback, and accountable "
                        "human approval. Do not claim access to the native app or its local data."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 700,
        }
    ).encode()
    request = urllib.request.Request(
        f"{config.openrouter_base_url}/chat/completions",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {config.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/ios-course-super-cool-app",
            "X-Title": "SuperCool Runtime Verification Companion",
        },
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=config.openrouter_timeout_seconds,
            context=ssl.create_default_context(),
        ) as response:
            encoded = response.read(MAX_PROVIDER_BYTES + 1)
    except urllib.error.HTTPError as error:
        status = error.code
        error.close()
        raise ProviderError(f"OPENROUTER_HTTP_{status}", "The AI provider rejected the request") from error
    except (urllib.error.URLError, TimeoutError, socket.timeout) as error:
        raise ProviderError("OPENROUTER_UNAVAILABLE", "The AI provider is unavailable") from error
    if len(encoded) > MAX_PROVIDER_BYTES:
        raise ProviderError("OPENROUTER_RESPONSE_TOO_LARGE", "The AI provider response was too large")
    try:
        body = json.loads(encoded.decode("utf-8"))
        if not isinstance(body, dict):
            raise TypeError("provider body must be an object")
        receipt = body.get("id")
        model = body.get("model")
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise TypeError("provider choices are invalid")
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise TypeError("provider message is invalid")
        content_value = message.get("content")
        if isinstance(content_value, list):
            content = "\n".join(
                str(item.get("text", ""))
                for item in content_value
                if isinstance(item, dict) and item.get("type") in {None, "text"}
            ).strip()
        elif isinstance(content_value, str):
            content = content_value.strip()
        else:
            raise TypeError("provider content is invalid")
        if not isinstance(receipt, str) or not 3 <= len(receipt.strip()) <= 240:
            raise ValueError("provider receipt is invalid")
        if not isinstance(model, str) or not 2 <= len(model.strip()) <= 200:
            raise ValueError("provider model is invalid")
        if not 1 <= len(content) <= 100_000:
            raise ValueError("provider content is invalid")
    except (AttributeError, IndexError, KeyError, TypeError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
        raise ProviderError("OPENROUTER_RESPONSE_INVALID", "The AI provider response was invalid") from error
    return {"receipt": receipt.strip(), "model": model.strip(), "content": content}


class RuntimeService:
    def __init__(
        self,
        config: Config,
        provider: Callable[[Config, str], dict[str, str]] = invoke_openrouter,
    ):
        self.config = config
        self.store = Store(config)
        self.provider = provider

    def bearer_identity(self, authorization: str | None) -> tuple[str, dict[str, object]] | None:
        match = BEARER_PATTERN.fullmatch(authorization or "")
        if not match:
            return None
        token = match.group(1)
        identity = self.store.identity(token)
        return (token, identity) if identity else None

    def ask(self, identity: dict[str, object], prompt: str) -> dict[str, object]:
        interaction_id = self.store.begin_ai(identity, prompt)
        started = time.monotonic()
        try:
            provider_result = self.provider(self.config, prompt)
            self.store.complete_ai(
                interaction_id, provider_result, int((time.monotonic() - started) * 1000)
            )
        except ProviderError as error:
            self._record_failure(interaction_id, error.code, started)
            raise
        except Exception as error:
            self._record_failure(interaction_id, "OPENROUTER_UNEXPECTED_FAILURE", started)
            raise ProviderError(
                "OPENROUTER_UNEXPECTED_FAILURE", "The AI provider request failed safely"
            ) from error
        return {
            "interactionId": interaction_id,
            "content": provider_result["content"],
            "providerReceipt": {
                "requestId": provider_result["receipt"],
                "provider": "openrouter",
                "upstreamModel": provider_result["model"],
            },
            "model": self.config.openrouter_model,
        }

    def _record_failure(self, interaction_id: str, code: str, started: float) -> None:
        try:
            self.store.fail_ai(interaction_id, code, int((time.monotonic() - started) * 1000))
        except (RuntimeError, sqlite3.Error):
            # The handler still returns a controlled response without exposing internal details.
            # Storage failures are separately visible through readiness and operator diagnostics.
            return


LogFunction = Callable[[dict[str, object]], None]


def emit_log(record: dict[str, object]) -> None:
    print(json.dumps(record, separators=(",", ":")), flush=True)


class RequestError(Exception):
    def __init__(self, status: int, code: str):
        super().__init__(code)
        self.status = status
        self.code = code


def api_handler(
    service: RuntimeService, allowed_origin: str, logger: LogFunction = emit_log
) -> type[BaseHTTPRequestHandler]:
    class ApiHandler(BaseHTTPRequestHandler):
        server_version = "SuperCoolVerification/1"
        sys_version = ""

        def log_message(self, _format: str, *_args: object) -> None:
            return

        def route_path(self) -> str:
            return urlsplit(self.path).path

        def request_log(self, status: int, started: float) -> None:
            logger(
                {
                    "event": "http_request",
                    "method": self.command,
                    "path": self.route_path(),
                    "status": int(status),
                    "durationMs": int((time.monotonic() - started) * 1000),
                }
            )

        def add_security_headers(self) -> None:
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
            if self.headers.get("Origin") == allowed_origin:
                self.send_header("Access-Control-Allow-Origin", allowed_origin)
                self.send_header("Vary", "Origin")

        def send_json(self, status: int, body: dict[str, object], started: float) -> None:
            encoded = json.dumps(body, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.add_security_headers()
            self.end_headers()
            self.wfile.write(encoded)
            self.request_log(status, started)

        def send_empty(self, status: int, started: float) -> None:
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.add_security_headers()
            self.end_headers()
            self.request_log(status, started)

        def origin_allowed(self, started: float) -> bool:
            origin = self.headers.get("Origin")
            if origin and origin != allowed_origin:
                self.send_json(HTTPStatus.FORBIDDEN, {"error": "ORIGIN_REJECTED"}, started)
                return False
            return True

        def read_json(self) -> dict[str, object]:
            if self.headers.get_content_type() != "application/json":
                raise RequestError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "JSON_CONTENT_TYPE_REQUIRED")
            raw_length = self.headers.get("Content-Length", "")
            if not raw_length.isdigit() or not 0 < int(raw_length) <= MAX_BODY_BYTES:
                raise RequestError(HTTPStatus.BAD_REQUEST, "INVALID_JSON")
            try:
                body = json.loads(self.rfile.read(int(raw_length)))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise RequestError(HTTPStatus.BAD_REQUEST, "INVALID_JSON") from error
            if not isinstance(body, dict):
                raise RequestError(HTTPStatus.BAD_REQUEST, "INVALID_JSON")
            return body

        def require_identity(self, started: float) -> tuple[str, dict[str, object]] | None:
            authenticated = service.bearer_identity(self.headers.get("Authorization"))
            if authenticated is None:
                self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "AUTHENTICATION_REQUIRED"}, started)
            return authenticated

        def do_OPTIONS(self) -> None:
            started = time.monotonic()
            if not self.origin_allowed(started):
                return
            if self.headers.get("Origin") != allowed_origin:
                self.send_json(HTTPStatus.FORBIDDEN, {"error": "ORIGIN_REQUIRED"}, started)
                return
            self.send_response(HTTPStatus.NO_CONTENT)
            self.send_header("Access-Control-Allow-Origin", allowed_origin)
            self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Authorization,Content-Type")
            self.send_header("Content-Length", "0")
            self.add_security_headers()
            self.end_headers()
            self.request_log(HTTPStatus.NO_CONTENT, started)

        def do_GET(self) -> None:
            started = time.monotonic()
            try:
                if not self.origin_allowed(started):
                    return
                path = self.route_path()
                if path == "/health/live":
                    self.send_json(HTTPStatus.OK, {"status": "live"}, started)
                    return
                if path == "/health/ready":
                    readiness = service.store.readiness()
                    status = HTTPStatus.OK if readiness["ready"] else HTTPStatus.SERVICE_UNAVAILABLE
                    self.send_json(status, readiness, started)
                    return
                if path == "/api/auth/demo-credentials":
                    if os.environ.get("NODE_ENV") == "production":
                        self.send_json(HTTPStatus.NOT_FOUND, {"error": "NOT_FOUND"}, started)
                    else:
                        self.send_json(HTTPStatus.OK, {"email": service.config.admin_email, "password": service.config.admin_password}, started)
                    return
                if path == "/api/auth/me":
                    authenticated = self.require_identity(started)
                    if authenticated:
                        self.send_json(HTTPStatus.OK, {"user": authenticated[1]}, started)
                    return
                prefix = "/api/ai/interactions/"
                if path.startswith(prefix):
                    authenticated = self.require_identity(started)
                    if not authenticated:
                        return
                    interaction_id = path.removeprefix(prefix)
                    try:
                        uuid.UUID(interaction_id)
                    except ValueError:
                        self.send_json(HTTPStatus.NOT_FOUND, {"error": "NOT_FOUND"}, started)
                        return
                    row = service.store.interaction(interaction_id, str(authenticated[1]["id"]))
                    if row is None:
                        self.send_json(HTTPStatus.NOT_FOUND, {"error": "NOT_FOUND"}, started)
                        return
                    self.send_json(HTTPStatus.OK, {"interaction": row}, started)
                    return
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "NOT_FOUND"}, started)
            except Exception as error:
                logger(
                    {
                        "event": "request_failed",
                        "method": self.command,
                        "path": self.route_path(),
                        "errorType": type(error).__name__,
                    }
                )
                self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "REQUEST_FAILED"}, started)

        def do_POST(self) -> None:
            started = time.monotonic()
            try:
                if not self.origin_allowed(started):
                    return
                path = self.route_path()
                if path not in {
                    "/api/auth/login",
                    "/api/auth/logout",
                    "/api/ai/moment-governance-review",
                }:
                    self.send_json(HTTPStatus.NOT_FOUND, {"error": "NOT_FOUND"}, started)
                    return
                try:
                    body = self.read_json()
                except RequestError as error:
                    self.send_json(error.status, {"error": error.code}, started)
                    return
                if path == "/api/auth/login":
                    result = service.store.login(
                        str(body.get("email") or ""), str(body.get("password") or "")
                    )
                    if result is None:
                        self.send_json(
                            HTTPStatus.UNAUTHORIZED, {"error": "INVALID_CREDENTIALS"}, started
                        )
                        return
                    token, identity = result
                    self.send_json(
                        HTTPStatus.OK,
                        {"accessToken": token, "tokenType": "Bearer", "user": identity},
                        started,
                    )
                    return
                if path == "/api/auth/logout":
                    authenticated = self.require_identity(started)
                    if not authenticated:
                        return
                    service.store.revoke(authenticated[0])
                    self.send_empty(HTTPStatus.NO_CONTENT, started)
                    return
                authenticated = self.require_identity(started)
                if not authenticated:
                    return
                prompt = str(body.get("prompt") or "").strip()
                if not 10 <= len(prompt) <= 12_000:
                    self.send_json(HTTPStatus.BAD_REQUEST, {"error": "PROMPT_INVALID"}, started)
                    return
                try:
                    result = service.ask(authenticated[1], prompt)
                    self.send_json(HTTPStatus.OK, result, started)
                except ProviderError as error:
                    self.send_json(error.status, {"error": error.code}, started)
            except Exception as error:
                logger(
                    {
                        "event": "request_failed",
                        "method": self.command,
                        "path": self.route_path(),
                        "errorType": type(error).__name__,
                    }
                )
                self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "REQUEST_FAILED"}, started)

    return ApiHandler


def ui_document(api_origin: str) -> bytes:
    safe_origin = html.escape(api_origin, quote=True)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SuperCool verification companion</title>
<style>body{{font:16px system-ui;max-width:760px;margin:3rem auto;padding:0 1rem;color:#152238}}main{{border:1px solid #ccd5e0;border-radius:16px;padding:2rem;background:#f8fafc}}label,input,textarea,button{{display:block;width:100%;box-sizing:border-box;margin:.55rem 0}}input,textarea,button{{padding:.7rem}}textarea{{min-height:8rem}}pre{{white-space:pre-wrap;background:#e8eef5;padding:1rem;border-radius:8px}}</style></head>
<body><main><h1>SuperCool runtime-verification companion</h1><p>This local page verifies credentials and an optional governed AI advisory boundary. It does not replace, inspect, or emulate the native local-first UIKit app.</p>
<form id="login-form"><label>Email<input id="email" type="email" autocomplete="username" required></label><label>Password<input id="password" type="password" autocomplete="current-password" required></label><button type="submit">Sign in</button></form>
<form id="advisory-form" hidden><label>Governance question<textarea id="prompt" minlength="10" maxlength="12000" required>Review privacy, accessibility, evidence, rollback, and human approval controls for an optional AI feature adjacent to a local-first moments app.</textarea></label><button type="submit">Request advisory</button><button id="logout" type="button">Sign out</button></form>
<pre id="result" aria-live="polite">Not signed in.</pre></main>
<script>'use strict';const api='{safe_origin}';let token='';const loginForm=document.getElementById('login-form');const advisoryForm=document.getElementById('advisory-form');const result=document.getElementById('result');loginForm.addEventListener('submit',async(event)=>{{event.preventDefault();const response=await fetch(api+'/api/auth/login',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{email:email.value,password:password.value}})}});const body=await response.json();password.value='';if(!response.ok){{result.textContent='Sign in failed.';return}}token=body.accessToken;const me=await fetch(api+'/api/auth/me',{{headers:{{Authorization:'Bearer '+token}}}});const identity=await me.json();loginForm.hidden=true;advisoryForm.hidden=false;result.textContent='Signed in as '+identity.user.email+' ('+identity.user.role+').';}});advisoryForm.addEventListener('submit',async(event)=>{{event.preventDefault();const response=await fetch(api+'/api/ai/moment-governance-review',{{method:'POST',headers:{{Authorization:'Bearer '+token,'Content-Type':'application/json'}},body:JSON.stringify({{prompt:prompt.value}})}});const body=await response.json();result.textContent=response.ok?body.content:'Advisory request failed.';}});document.getElementById('logout').addEventListener('click',async()=>{{await fetch(api+'/api/auth/logout',{{method:'POST',headers:{{Authorization:'Bearer '+token,'Content-Type':'application/json'}},body:'{{}}'}});token='';advisoryForm.hidden=true;loginForm.hidden=false;result.textContent='Signed out.';}});</script></body></html>""".encode()


def ui_handler(
    api_origin: str, logger: LogFunction = emit_log
) -> type[BaseHTTPRequestHandler]:
    document = ui_document(api_origin)

    class UiHandler(BaseHTTPRequestHandler):
        server_version = "SuperCoolCompanionUI/1"
        sys_version = ""

        def log_message(self, _format: str, *_args: object) -> None:
            return

        def do_GET(self) -> None:
            started = time.monotonic()
            path = urlsplit(self.path).path
            if path == "/health":
                encoded = json.dumps({"status": "ok", "apiOrigin": api_origin}).encode()
                content_type = "application/json"
            elif path in {"/", "/index.html"}:
                encoded = document
                content_type = "text/html; charset=utf-8"
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                f"default-src 'self'; connect-src 'self' {api_origin}; script-src 'unsafe-inline'; "
                "style-src 'unsafe-inline'; object-src 'none'; frame-ancestors 'none'",
            )
            self.end_headers()
            self.wfile.write(encoded)
            logger(
                {
                    "event": "ui_request",
                    "method": self.command,
                    "path": path,
                    "status": 200,
                    "durationMs": int((time.monotonic() - started) * 1000),
                }
            )

    return UiHandler


class LoopbackThreadingServer(ThreadingHTTPServer):
    daemon_threads = True


def create_servers(
    config: Config,
    service: RuntimeService | None = None,
    api_port: int | None = None,
    ui_port: int | None = None,
    logger: LogFunction = emit_log,
) -> tuple[ThreadingHTTPServer, ThreadingHTTPServer]:
    resolved_service = service or RuntimeService(config)
    ui_server = LoopbackThreadingServer(
        ("127.0.0.1", config.ui_port if ui_port is None else ui_port), ui_handler("", logger)
    )
    ui_origin = f"http://127.0.0.1:{ui_server.server_address[1]}"
    try:
        api_server = LoopbackThreadingServer(
            ("127.0.0.1", config.api_port if api_port is None else api_port),
            api_handler(resolved_service, ui_origin, logger),
        )
    except OSError:
        ui_server.server_close()
        raise
    api_origin = f"http://127.0.0.1:{api_server.server_address[1]}"
    ui_server.RequestHandlerClass = ui_handler(api_origin, logger)
    return api_server, ui_server


def run() -> int:
    try:
        config = Config.from_env()
        service = RuntimeService(config)
        api_server, ui_server = create_servers(config, service)
    except (OSError, ValueError, sqlite3.Error) as error:
        print(
            json.dumps(
                {
                    "event": "startup_failed",
                    "errorType": type(error).__name__,
                    "message": str(error),
                },
                separators=(",", ":"),
            ),
            file=sys.stderr,
            flush=True,
        )
        return 1
    stop = threading.Event()

    def request_stop(signum: int, _frame: object) -> None:
        emit_log({"event": "server_stopping", "signal": signal.Signals(signum).name})
        stop.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    threads = [
        threading.Thread(target=api_server.serve_forever, name="api-server", daemon=True),
        threading.Thread(target=ui_server.serve_forever, name="ui-server", daemon=True),
    ]
    for thread in threads:
        thread.start()
    emit_log({"event": "servers_started", "apiPort": config.api_port, "uiPort": config.ui_port})
    try:
        while not stop.wait(0.25):
            if not all(thread.is_alive() for thread in threads):
                raise RuntimeError("a companion listener exited unexpectedly")
    finally:
        api_server.shutdown()
        ui_server.shutdown()
        api_server.server_close()
        ui_server.server_close()
        for thread in threads:
            thread.join(timeout=5)
    emit_log({"event": "servers_stopped"})
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
