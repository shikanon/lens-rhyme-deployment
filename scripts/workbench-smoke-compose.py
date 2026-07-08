#!/usr/bin/env python3
"""Workbench smoke test for a LensRhyme Compose stack.

This script keeps the CI-friendly pass/fail logic in HTTP APIs. Use
--open-browser locally when you also want a visible companion browser view.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser
from pathlib import Path
from typing import Any


DEFAULT_DOCX_URL = "http://cdn.ai.tensorbytes.com/test/workbench/test.docx"
SUCCESS_STATUSES = {"completed", "success", "succeeded"}
FAILURE_STATUSES = {"failed", "error", "aborted", "cancelled", "canceled"}
ACTIVE_STATUSES = {"pending", "running", "queued", "processing", "in_progress"}


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
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


def shorten(value: Any, limit: int = 220) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True) if not isinstance(value, str) else value
    return text if len(text) <= limit else f"{text[:limit]}..."


def require_field(data: Any, field: str, context: str) -> Any:
    if isinstance(data, dict) and data.get(field) not in (None, ""):
        return data[field]
    raise SmokeFailure(f"{context} missing '{field}': {shorten(data)}")


def task_state(status: str | None) -> str:
    normalized = (status or "").strip().lower()
    if normalized in SUCCESS_STATUSES:
        return "success"
    if normalized in FAILURE_STATUSES:
        return "failure"
    if normalized in ACTIVE_STATUSES or not normalized:
        return "active"
    return "unknown"


def assert_workbench_route(body: str) -> None:
    lowered = body.lower()
    if not body.strip():
        raise SmokeFailure("workbench route returned an empty response")
    if "application error" in lowered or "client-side exception" in lowered:
        raise SmokeFailure("workbench route returned a frontend error shell")
    if "lensrhyme" not in lowered:
        raise SmokeFailure("workbench route did not look like the LensRhyme app shell")


def validate_credentials(args: argparse.Namespace) -> None:
    if not args.user_password:
        raise SmokeFailure("missing required credentials: set SMOKE_TEST_USER_PASSWORD or --user-password")


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
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> Any:
        request_headers = {
            "Accept": "application/json, text/plain;q=0.9, */*;q=0.8",
            "User-Agent": "lens-rhyme-workbench-smoke/1.0",
        }
        if headers:
            request_headers.update(headers)
        data = body
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        if token:
            request_headers["Authorization"] = f"Bearer {token}"

        req = urllib.request.Request(url, data=data, headers=request_headers, method=method.upper())
        try:
            with self.opener.open(req, timeout=timeout or self.timeout) as response:
                raw = response.read()
                return self._decode_response(raw, response.headers.get("Content-Type", ""))
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            body_text = raw.decode("utf-8", errors="replace") if raw else exc.reason
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

    def upload_file(
        self,
        path: str,
        *,
        token: str,
        fields: dict[str, Any],
        field_name: str,
        filename: str,
        content: bytes,
    ) -> Any:
        boundary = f"----LensRhymeWorkbenchSmoke{uuid.uuid4().hex}"
        body = bytearray()

        def add(text: str) -> None:
            body.extend(text.encode("utf-8"))

        for name, value in fields.items():
            if value is None:
                continue
            add(f"--{boundary}\r\n")
            add(f'Content-Disposition: form-data; name="{name}"\r\n\r\n')
            add("true" if isinstance(value, bool) and value else "false" if isinstance(value, bool) else str(value))
            add("\r\n")

        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        add(f"--{boundary}\r\n")
        add(f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n')
        add(f"Content-Type: {content_type}\r\n\r\n")
        body.extend(content)
        add("\r\n")
        add(f"--{boundary}--\r\n")

        return self.api(
            "POST",
            path,
            token=token,
            body=bytes(body),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )


class WorkbenchSmokeRunner:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.client = HttpClient(args.base_url, args.api_prefix, args.http_timeout)
        self.user_token = ""

    def run(self) -> None:
        if self.args.open_browser:
            self.open_browser("/login", "visible login page")

        steps: list[tuple[str, Any]] = [
            ("Workbench route responds", self.check_workbench_route),
            ("main-site user login", self.user_login),
            ("Workbench project can be created", self.create_project),
            ("Workbench script import task completes", self.import_script_and_poll),
        ]
        for name, func in steps:
            self.run_step(name, func)

        if self.args.open_browser:
            self.open_browser("/workbench", "visible Workbench page")
        print("\nWorkbench smoke test completed successfully.")

    def run_step(self, name: str, func: Any) -> None:
        print(f"==> {name}")
        started = time.monotonic()
        detail = func()
        elapsed = time.monotonic() - started
        suffix = f": {detail}" if detail else ""
        print(f"OK {name} ({elapsed:.1f}s){suffix}")

    def open_browser(self, path: str, label: str) -> None:
        url = join_url(self.args.base_url, path)
        print(f"==> opening {label}: {url}")
        webbrowser.open(url)

    def check_workbench_route(self) -> str:
        body = self.client.raw("GET", "/workbench")
        if not isinstance(body, str):
            raise SmokeFailure(f"workbench route returned non-text response: {shorten(body)}")
        assert_workbench_route(body)
        return "GET /workbench returned LensRhyme app shell"

    def user_login(self) -> str:
        data = self.client.api(
            "POST",
            "/auth/login",
            json_body={"username": self.args.user_username, "password": self.args.user_password},
        )
        self.user_token = require_field(data, "access_token", "user login response")
        return f"user={self.args.user_username}"

    def create_project(self) -> str:
        payload = {
            "name": f"Workbench Smoke {time.strftime('%Y%m%d%H%M%S')}",
            "description": "Created by the Workbench smoke test.",
            "template_type": "blank",
            "project_type": "short_film",
            "resolution": "480p",
            "aspect_ratio": "16:9",
            "frame_rate": "24fps",
            "acknowledge_template_conflict": True,
        }
        data = self.client.api("POST", "/workbench/projects", token=self.user_token, json_body=payload)
        self.project_id = require_field(data, "id", "workbench create project response")
        return f"project={self.project_id}"

    def import_script_and_poll(self) -> str:
        filename, content = self.download_test_docx()
        response = self.client.upload_file(
            f"/workbench/projects/{self.project_id}/script/import",
            token=self.user_token,
            fields={
                "import_profile": "short_film",
                "merge_strategy": "append",
                "auto_create_episodes": False,
            },
            field_name="file",
            filename=filename,
            content=content,
        )
        task_id = require_field(response, "task_id", "script import response")
        task = self.poll_task(str(task_id))
        output = task.get("output") if isinstance(task, dict) else None
        if output is None:
            return f"project={self.project_id}, task={task_id}"
        return f"project={self.project_id}, task={task_id}, output={shorten(output)}"

    def download_test_docx(self) -> tuple[str, bytes]:
        url = self.args.docx_url
        req = urllib.request.Request(url, headers={"User-Agent": "lens-rhyme-workbench-smoke/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=self.args.http_timeout) as response:
                content = response.read()
        except urllib.error.URLError as exc:
            raise SmokeFailure(f"failed to download workbench test document {url}: {exc}") from exc
        if not content:
            raise SmokeFailure(f"workbench test document is empty: {url}")
        filename = Path(urllib.parse.urlparse(url).path).name or "test.docx"
        if not filename.lower().endswith(".docx"):
            filename = f"{filename}.docx"
        return filename, content

    def poll_task(self, task_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.args.poll_timeout
        last_task: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            task = self.client.api("GET", f"/tasks/{task_id}", token=self.user_token)
            if not isinstance(task, dict):
                raise SmokeFailure(f"script_import task detail is not an object: {shorten(task)}")
            last_task = task
            status = str(task.get("status") or "")
            state = task_state(status)
            print(f"    task {task_id} status={status or 'unknown'}")
            if state == "success":
                return task
            if state == "failure":
                if self.args.allow_terminal_failure:
                    print(
                        "    terminal failure accepted for no-stuck check; "
                        "use strict mode when model/API keys are available"
                    )
                    return task
                raise SmokeFailure(
                    f"script_import task {task_id} ended with status={status}, "
                    f"error={task.get('error_message') or task.get('error_code') or shorten(task)}"
                )
            time.sleep(self.args.poll_interval)
        raise SmokeFailure(f"script_import task {task_id} timed out; last state={shorten(last_task)}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate LensRhyme Workbench page availability and script import completion."
    )
    parser.add_argument("--base-url", default=os.getenv("SMOKE_TEST_BASE_URL", "http://127.0.0.1:5410"))
    parser.add_argument("--api-prefix", default=os.getenv("SMOKE_TEST_API_PREFIX", "/api/v1"))
    parser.add_argument("--user-username", default=os.getenv("SMOKE_TEST_USER_USERNAME", "test_user"))
    parser.add_argument("--user-password", default=os.getenv("SMOKE_TEST_USER_PASSWORD", ""))
    parser.add_argument("--docx-url", default=os.getenv("SMOKE_TEST_DOCX_URL", DEFAULT_DOCX_URL))
    parser.add_argument("--http-timeout", type=int, default=int(os.getenv("SMOKE_TEST_HTTP_TIMEOUT", "30")))
    parser.add_argument("--poll-timeout", type=int, default=int(os.getenv("SMOKE_TEST_POLL_TIMEOUT", "180")))
    parser.add_argument("--poll-interval", type=int, default=int(os.getenv("SMOKE_TEST_POLL_INTERVAL", "5")))
    parser.add_argument(
        "--open-browser",
        action="store_true",
        help="Open visible login/workbench pages as a local companion view; API checks still decide pass/fail.",
    )
    parser.add_argument(
        "--allow-terminal-failure",
        action="store_true",
        help=(
            "Pass when the Workbench task reaches any terminal state. "
            "Use this local no-stuck mode when external model/API keys are not configured."
        ),
    )
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
        WorkbenchSmokeRunner(args).run()
    except KeyboardInterrupt:
        print("Workbench smoke test interrupted.", file=sys.stderr)
        return 130
    except SmokeFailure as exc:
        print(f"\nWorkbench smoke test failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
