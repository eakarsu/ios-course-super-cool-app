from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import closing
from pathlib import Path

from companion.runtime import (
    CANONICAL_OPENROUTER_BASE,
    Config,
    ProviderError,
    RuntimeService,
    create_servers,
)


def config_for(directory: str) -> Config:
    return Config(
        api_port=31006,
        ui_port=31007,
        database_path=Path(directory) / "runtime.sqlite",
        admin_email="runtime-admin@example.com",
        admin_password="RuntimeAcceptance123!",
        session_ttl_hours=12,
        openrouter_api_key="test-key",
        openrouter_model="test/model",
        openrouter_base_url=CANONICAL_OPENROUTER_BASE,
        openrouter_timeout_seconds=10,
    )


def fake_provider(_config: Config, prompt: str) -> dict[str, str]:
    return {
        "receipt": "test-provider-receipt-123",
        "model": "test/model",
        "content": (
            "Evidence-backed privacy, accessibility, rollback, and human-approval review for: " + prompt
        ),
    }


class RuntimeTests(unittest.TestCase):
    def test_environment_requires_distinct_ports_absolute_database_and_canonical_provider(self) -> None:
        environment = {
            "API_PORT": "31006",
            "UI_PORT": "31006",
            "DATABASE_PATH": "/tmp/test.sqlite",
            "ADMIN_EMAIL": "runtime-admin@example.com",
            "ADMIN_PASSWORD": "RuntimeAcceptance123!",
            "SESSION_TTL_HOURS": "12",
            "OPENROUTER_API_KEY": "key",
            "OPENROUTER_MODEL": "model",
            "OPENROUTER_BASE_URL": CANONICAL_OPENROUTER_BASE,
            "OPENROUTER_TIMEOUT_SECONDS": "10",
        }
        with self.assertRaisesRegex(ValueError, "distinct"):
            Config.from_env(environment)
        environment["UI_PORT"] = "31007"
        environment["DATABASE_PATH"] = "relative.sqlite"
        with self.assertRaisesRegex(ValueError, "absolute"):
            Config.from_env(environment)
        environment["DATABASE_PATH"] = "/tmp/test.sqlite"
        environment["OPENROUTER_BASE_URL"] = "https://example.com/v1"
        with self.assertRaisesRegex(ValueError, "must equal"):
            Config.from_env(environment)

    def test_sessions_provider_receipts_restart_and_append_only_rules_are_durable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = config_for(directory)
            service = RuntimeService(config, fake_provider)
            self.assertIsNone(service.store.login(config.admin_email, "wrong-password-value"))
            login = service.store.login(config.admin_email, config.admin_password)
            self.assertIsNotNone(login)
            token, _ = login or ("", {})
            authenticated = service.bearer_identity(f"Bearer {token}")
            self.assertIsNotNone(authenticated)
            result = service.ask(
                authenticated[1], "Review moment-advisory privacy, evidence, and rollback controls"
            )  # type: ignore[index]
            restarted = RuntimeService(config, fake_provider)
            persisted_identity = restarted.bearer_identity(f"Bearer {token}")
            self.assertIsNotNone(persisted_identity)
            row = restarted.store.interaction(
                str(result["interactionId"]), str(persisted_identity[1]["id"])
            )  # type: ignore[index]
            self.assertEqual(row["status"], "SUCCEEDED")  # type: ignore[index]
            self.assertEqual(row["provider_receipt"], "test-provider-receipt-123")  # type: ignore[index]
            application_connection = restarted.store.connect()
            try:
                self.assertEqual(application_connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
                self.assertEqual(application_connection.execute("PRAGMA synchronous").fetchone()[0], 2)
                self.assertEqual(application_connection.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            finally:
                application_connection.close()
            with closing(sqlite3.connect(config.database_path)) as database, database:
                with self.assertRaises(sqlite3.IntegrityError):
                    database.execute(
                        "UPDATE ai_interactions SET output_text='tampered' WHERE id=?",
                        (result["interactionId"],),
                    )
                with self.assertRaises(sqlite3.IntegrityError):
                    database.execute(
                        "DELETE FROM ai_interactions WHERE id=?", (result["interactionId"],)
                    )
                digest = database.execute("SELECT token_digest FROM sessions LIMIT 1").fetchone()[0]
                self.assertEqual(len(digest), 64)
                self.assertNotIn(token, digest)
            self.assertTrue(restarted.store.revoke(token))
            self.assertIsNone(restarted.bearer_identity(f"Bearer {token}"))

    def test_unexpected_provider_failures_are_terminal_and_controlled(self) -> None:
        def unexpected(_config: Config, _prompt: str) -> dict[str, str]:
            raise RuntimeError("unexpected parser failure")

        with tempfile.TemporaryDirectory() as directory:
            config = config_for(directory)
            service = RuntimeService(config, unexpected)
            token, identity = service.store.login(config.admin_email, config.admin_password) or ("", {})
            self.assertTrue(token)
            with self.assertRaisesRegex(ProviderError, "failed safely"):
                service.ask(identity, "Review the unexpected provider failure path safely")
            with closing(sqlite3.connect(config.database_path)) as database:
                row = database.execute(
                    "SELECT status,error_code,completed_at FROM ai_interactions"
                ).fetchone()
            self.assertEqual(row[0], "FAILED")
            self.assertEqual(row[1], "OPENROUTER_UNEXPECTED_FAILURE")
            self.assertIsNotNone(row[2])

    def test_http_login_identity_ai_logout_ui_cors_and_query_safe_logs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = config_for(directory)
            logs: list[dict[str, object]] = []
            service = RuntimeService(config, fake_provider)
            api, ui = create_servers(
                config, service, api_port=0, ui_port=0, logger=logs.append
            )
            threads = [
                threading.Thread(target=api.serve_forever),
                threading.Thread(target=ui.serve_forever),
            ]
            for thread in threads:
                thread.start()
            api_base = f"http://127.0.0.1:{api.server_address[1]}"
            ui_base = f"http://127.0.0.1:{ui.server_address[1]}"

            def request(
                path: str,
                method: str = "GET",
                body: dict | None = None,
                token: str | None = None,
                origin: str | None = None,
            ) -> tuple[int, dict | None, dict[str, str]]:
                headers = {"Accept": "application/json"}
                data = None
                if body is not None:
                    headers["Content-Type"] = "application/json"
                    data = json.dumps(body).encode()
                if token:
                    headers["Authorization"] = f"Bearer {token}"
                if origin:
                    headers["Origin"] = origin
                try:
                    with urllib.request.urlopen(
                        urllib.request.Request(
                            api_base + path, data=data, method=method, headers=headers
                        ),
                        timeout=5,
                    ) as response:
                        encoded = response.read()
                        return (
                            response.status,
                            json.loads(encoded) if encoded else None,
                            dict(response.headers),
                        )
                except urllib.error.HTTPError as error:
                    try:
                        encoded = error.read()
                        return error.code, json.loads(encoded) if encoded else None, dict(error.headers)
                    finally:
                        error.close()

            try:
                denied, _, _ = request(
                    "/api/ai/moment-governance-review",
                    "POST",
                    {"prompt": "anonymous request must fail safely"},
                )
                self.assertEqual(denied, 401)
                wrong, _, _ = request(
                    "/api/auth/login",
                    "POST",
                    {"email": config.admin_email, "password": config.admin_password + "-wrong"},
                )
                self.assertEqual(wrong, 401)
                rejected_origin, _, _ = request(
                    "/api/auth/login",
                    "POST",
                    {"email": config.admin_email, "password": config.admin_password},
                    origin="https://untrusted.example",
                )
                self.assertEqual(rejected_origin, 403)
                status, login, headers = request(
                    "/api/auth/login",
                    "POST",
                    {"email": config.admin_email, "password": config.admin_password},
                    origin=ui_base,
                )
                self.assertEqual(status, 200)
                self.assertEqual(headers["Access-Control-Allow-Origin"], ui_base)
                token = str(login["accessToken"])  # type: ignore[index]
                status, identity, _ = request("/api/auth/me", token=token)
                self.assertEqual(status, 200)
                self.assertEqual(identity["user"]["authType"], "SESSION")  # type: ignore[index]
                status, result, _ = request(
                    "/api/ai/moment-governance-review",
                    "POST",
                    {"prompt": "Review local-first moments privacy, rollback, and approval evidence"},
                    token,
                )
                self.assertEqual(status, 200)
                self.assertEqual(
                    result["providerReceipt"]["requestId"], "test-provider-receipt-123"
                )  # type: ignore[index]
                status, durable, _ = request(
                    f"/api/ai/interactions/{result['interactionId']}", token=token  # type: ignore[index]
                )
                self.assertEqual(status, 200)
                self.assertEqual(durable["interaction"]["status"], "SUCCEEDED")  # type: ignore[index]
                status, _, _ = request("/health/live?access_token=do-not-log-this", origin=ui_base)
                self.assertEqual(status, 200)
                self.assertNotIn("do-not-log-this", json.dumps(logs))
                status, _, _ = request("/api/auth/logout", "POST", {}, token)
                self.assertEqual(status, 204)
                status, _, _ = request("/api/auth/me", token=token)
                self.assertEqual(status, 401)
                with urllib.request.urlopen(ui_base, timeout=5) as response:
                    document = response.read()
                    self.assertEqual(response.status, 200)
                    self.assertIn(b'id="login-form"', document)
                    self.assertIn(b'id="advisory-form"', document)
                    self.assertIn(api_base.encode(), document)
                    self.assertIn(b"does not replace, inspect, or emulate", document)
                with urllib.request.urlopen(ui_base + "/health", timeout=5) as response:
                    health = json.loads(response.read())
                    self.assertEqual(health["apiOrigin"], api_base)
            finally:
                api.shutdown()
                ui.shutdown()
                api.server_close()
                ui.server_close()
                for thread in threads:
                    thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
