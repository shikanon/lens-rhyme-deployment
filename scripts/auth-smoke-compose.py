#!/usr/bin/env python3
"""Basic auth and permission smoke tests for a deployed LensRhyme stack."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any


class SmokeFailure(RuntimeError):
    """A user-facing smoke-test failure."""


class HttpError(SmokeFailure):
    def __init__(self, method: str, url: str, status: int | None, body: str) -> None:
        self.method = method
        self.url = url
        self.status = status
        self.body = body
        status_text = str(status) if status is not None else "network"
        super().__init__(f"{method} {url} failed with {status_text}: {body[:600]}")


def join_url(base: str, path: str) -> str:
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


def shorten(value: Any, limit: int = 200) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True) if not isinstance(value, str) else value
    return text if len(text) <= limit else f"{text[:limit]}..."


class HttpClient:
    def __init__(self, base_url: str, api_prefix: str, timeout: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_prefix = "/" + api_prefix.strip("/")
        self.timeout = timeout
        self.opener = urllib.request.build_opener()

    def raw(self, method: str, path: str, **kwargs: Any) -> Any:
        return self._request(method, join_url(self.base_url, path), **kwargs)

    def api(self, method: str, path: str, **kwargs: Any) -> Any:
        return self._request(method, join_url(self.base_url, f"{self.api_prefix}/{path.lstrip('/')}"), **kwargs)

    def _request(
        self,
        method: str,
        url: str,
        *,
        token: str | None = None,
        json_body: Any | None = None,
        headers: dict[str, str] | None = None,
        expect_status: int | None = 200,
    ) -> Any:
        request_headers = {
            "Accept": "application/json, text/plain;q=0.9, */*;q=0.8",
            "User-Agent": "lens-rhyme-auth-smoke/1.0",
        }
        if headers:
            request_headers.update(headers)
        data = None
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        if token:
            request_headers["Authorization"] = f"Bearer {token}"

        req = urllib.request.Request(url, data=data, headers=request_headers, method=method.upper())
        try:
            with self.opener.open(req, timeout=self.timeout) as response:
                raw = response.read()
                if expect_status is not None and response.status != expect_status:
                    raise HttpError(method.upper(), url, response.status, raw.decode("utf-8", errors="replace"))
                return self._decode_response(raw, response.headers.get("Content-Type", ""))
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            body_text = raw.decode("utf-8", errors="replace") if raw else exc.reason
            if expect_status is not None and exc.code == expect_status:
                return self._decode_response(raw, exc.headers.get("Content-Type", ""))
            raise HttpError(method.upper(), url, exc.code, body_text) from exc
        except urllib.error.URLError as exc:
            raise HttpError(method.upper(), url, None, str(exc.reason)) from exc

    @staticmethod
    def _decode_response(raw: bytes, content_type: str) -> Any:
        if not raw:
            return None
        text = raw.decode("utf-8", errors="replace")
        if "json" in content_type.lower() or text[:1] in ("{", "["):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text
        return text


class AuthSmokeRunner:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.client = HttpClient(args.base_url, args.api_prefix, args.http_timeout)
        self.admin_token = ""
        self.user_token = ""

    def run(self) -> None:
        steps: list[tuple[str, Any]] = [
            ("public frontend route", self.check_frontend),
            ("public docs route", self.check_docs),
            ("Super Admin login", self.admin_login),
            ("ensure main-site test user exists", self.ensure_test_user),
            ("main-site user login", self.user_login),
            ("wrong password is rejected", self.wrong_password_rejected),
            ("anonymous balance request is rejected", self.anonymous_balance_rejected),
            ("main-site user balance is readable", self.user_balance_readable),
            ("main-site user cannot list admin users", self.user_cannot_list_admin_users),
            ("Super Admin can list users", self.admin_can_list_users),
        ]
        for name, func in steps:
            self.run_step(name, func)
        print("\nAuth smoke test completed successfully.")

    def run_step(self, name: str, func: Any) -> None:
        print(f"==> {name}")
        started = time.monotonic()
        detail = func()
        elapsed = time.monotonic() - started
        suffix = f": {detail}" if detail else ""
        print(f"OK {name} ({elapsed:.1f}s){suffix}")

    def check_frontend(self) -> str:
        self.client.raw("GET", "/")
        return "GET / responded"

    def check_docs(self) -> str:
        self.client.raw("GET", "/docs/")
        return "GET /docs/ responded"

    def admin_login(self) -> str:
        data = self.client.api(
            "POST",
            "/admin/login",
            json_body={"username": self.args.admin_username, "password": self.args.admin_password},
        )
        self.admin_token = require_field(data, "access_token", "admin login response")
        return f"admin={self.args.admin_username}"

    def ensure_test_user(self) -> str:
        try:
            self.client.api(
                "POST",
                "/auth/login",
                json_body={"username": self.args.user_username, "password": self.args.user_password},
            )
            return f"user={self.args.user_username} already exists"
        except HttpError as exc:
            if exc.status != 400:
                raise

        payload = {
            "username": self.args.user_username,
            "password": self.args.user_password,
            "email": self.args.user_email,
            "enterprise_name": self.args.enterprise_name,
            "role": "Administrator",
            "is_sub_account": False,
        }
        data = self.client.api("POST", "/admin/users", token=self.admin_token, json_body=payload)
        user_id = require_field(data, "id", "admin create user response")
        return f"created user={self.args.user_username}, id={user_id}"

    def user_login(self) -> str:
        data = self.client.api(
            "POST",
            "/auth/login",
            json_body={"username": self.args.user_username, "password": self.args.user_password},
        )
        self.user_token = require_field(data, "access_token", "user login response")
        return f"user={self.args.user_username}"

    def wrong_password_rejected(self) -> str:
        self.client.api(
            "POST",
            "/auth/login",
            json_body={"username": self.args.user_username, "password": self.args.user_password + "-wrong"},
            expect_status=400,
        )
        return "HTTP 400"

    def anonymous_balance_rejected(self) -> str:
        self.client.api("GET", "/billing/balance", expect_status=401)
        return "HTTP 401"

    def user_balance_readable(self) -> str:
        data = self.client.api("GET", "/billing/balance", token=self.user_token)
        if not isinstance(data, dict):
            raise SmokeFailure(f"balance response is not an object: {shorten(data)}")
        return f"balance={data.get('balance', 'unknown')}"

    def user_cannot_list_admin_users(self) -> str:
        self.client.api("GET", "/admin/users", token=self.user_token, expect_status=403)
        return "HTTP 403"

    def admin_can_list_users(self) -> str:
        data = self.client.api("GET", "/admin/users", token=self.admin_token)
        if not isinstance(data, list):
            raise SmokeFailure(f"admin users response is not a list: {shorten(data)}")
        return f"users={len(data)}"


def require_field(data: Any, field: str, context: str) -> Any:
    if isinstance(data, dict) and data.get(field) not in (None, ""):
        return data[field]
    raise SmokeFailure(f"{context} missing '{field}': {shorten(data)}")


def validate_credentials(args: argparse.Namespace) -> None:
    missing = []
    if not args.admin_password:
        missing.append("SMOKE_TEST_ADMIN_PASSWORD or --admin-password")
    if not args.user_password:
        missing.append("SMOKE_TEST_USER_PASSWORD or --user-password")
    if missing:
        raise SmokeFailure(f"missing required credentials: set {', '.join(missing)}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate basic LensRhyme routes, login, and auth boundaries without model API keys."
    )
    parser.add_argument("--base-url", default=os.getenv("SMOKE_TEST_BASE_URL", "http://127.0.0.1:5410"))
    parser.add_argument("--api-prefix", default=os.getenv("SMOKE_TEST_API_PREFIX", "/api/v1"))
    parser.add_argument("--admin-username", default=os.getenv("SMOKE_TEST_ADMIN_USERNAME", "admin"))
    parser.add_argument("--admin-password", default=os.getenv("SMOKE_TEST_ADMIN_PASSWORD", ""))
    parser.add_argument("--user-username", default=os.getenv("SMOKE_TEST_USER_USERNAME", "test_user"))
    parser.add_argument("--user-password", default=os.getenv("SMOKE_TEST_USER_PASSWORD", ""))
    parser.add_argument("--user-email", default=os.getenv("SMOKE_TEST_USER_EMAIL", "test_user@local.lens-rhyme.test"))
    parser.add_argument("--enterprise-name", default=os.getenv("SMOKE_TEST_ENTERPRISE_NAME", "Local Test Enterprise"))
    parser.add_argument("--http-timeout", type=int, default=int(os.getenv("SMOKE_TEST_HTTP_TIMEOUT", "30")))
    return parser


def main() -> int:
    try:
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except AttributeError:
        pass
    args = build_parser().parse_args()
    args.base_url = args.base_url.rstrip("/")
    try:
        validate_credentials(args)
        AuthSmokeRunner(args).run()
    except KeyboardInterrupt:
        print("Auth smoke test interrupted.", file=sys.stderr)
        return 130
    except SmokeFailure as exc:
        print(f"\nAuth smoke test failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
