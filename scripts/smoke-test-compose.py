#!/usr/bin/env python3
"""Post-deploy smoke tests for a LensRhyme Compose stack."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import secrets
import shlex
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_DOCX_URL = "http://cdn.ai.tensorbytes.com/test/workbench/test.docx"
DEFAULT_MODEL3D_REFERENCE_IMAGE_URL = (
    "https://upload.wikimedia.org/wikipedia/commons/3/3a/Cat03.jpg"
)

SUCCESS_STATUSES = {"completed", "success", "succeeded"}
FAILURE_STATUSES = {"failed", "error", "aborted", "cancelled", "canceled"}


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


def parse_dotenv_value(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return ""
    try:
        parts = shlex.split(raw, posix=True)
        if parts:
            return parts[0]
    except ValueError:
        pass
    return raw.strip("\"'")


def load_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key:
            values[key] = parse_dotenv_value(value)
    return values


def env_value(env: dict[str, str], name: str, default: str = "") -> str:
    return os.getenv(name) or env.get(name) or default


def getenv_int(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    return int(value)


def getenv_float(name: str, default: float) -> float:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    return float(value)


def getenv_bool(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def join_url(base: str, path: str) -> str:
    if path.startswith("http://") or path.startswith("https://"):
        return path
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
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> Any:
        request_headers = {
            "Accept": "application/json, text/plain;q=0.9, */*;q=0.8",
            "User-Agent": "lens-rhyme-smoke-test/1.0",
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
                content_type = response.headers.get("Content-Type", "")
                return self._decode_response(raw, content_type)
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
        boundary = f"----LensRhymeSmoke{uuid.uuid4().hex}"
        body = bytearray()

        def add(text: str) -> None:
            body.extend(text.encode("utf-8"))

        for name, value in fields.items():
            if value is None:
                continue
            add(f"--{boundary}\r\n")
            add(f'Content-Disposition: form-data; name="{name}"\r\n\r\n')
            if isinstance(value, bool):
                add("true" if value else "false")
            else:
                add(str(value))
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


@dataclass
class SmokeState:
    admin_token: str = ""
    user_token: str = ""
    test_user_id: int | None = None
    test_username: str = ""
    test_password: str = ""


class SmokeRunner:
    def __init__(self, args: argparse.Namespace, dotenv: dict[str, str]) -> None:
        self.args = args
        self.dotenv = dotenv
        self.client = HttpClient(args.base_url, args.api_prefix, args.http_timeout)
        self.state = SmokeState()
        self.warnings: list[str] = []

    def run(self) -> None:
        steps: list[tuple[str, Any]] = [
            ("public frontend and docs routes", self.check_public_routes),
            ("Super Admin login", self.admin_login),
            ("create temporary test user", self.create_test_user),
            ("recharge temporary test user", self.recharge_test_user),
            ("temporary test user login", self.user_login),
            ("temporary test user balance", self.check_user_balance),
        ]
        if not self.args.skip_studio:
            steps.extend(
                [
                    ("Studio audio generation", self.test_studio_audio),
                    ("Studio image generation", self.test_studio_image),
                    ("Studio video generation", self.test_studio_video),
                    ("Studio 3D generation", self.test_studio_model3d),
                ]
            )
        if not self.args.skip_workbench:
            steps.append(("Workbench script document import", self.test_workbench_import))

        failed = False
        try:
            for name, func in steps:
                self.run_step(name, func)
        except Exception:
            failed = True
            raise
        finally:
            self.cleanup_test_user()
            if self.warnings:
                print("\nWarnings:")
                for warning in self.warnings:
                    print(f"- {warning}")
            if not failed:
                print("\nSmoke test completed successfully.")

    def run_step(self, name: str, func: Any) -> None:
        print(f"==> {name}")
        started = time.monotonic()
        try:
            detail = func()
        except Exception as exc:
            print(f"FAIL {name}: {exc}", file=sys.stderr)
            raise
        elapsed = time.monotonic() - started
        suffix = f": {detail}" if detail else ""
        print(f"OK {name} ({elapsed:.1f}s){suffix}")

    def check_public_routes(self) -> str:
        self.client.raw("GET", "/")
        self.client.raw("GET", "/docs/")
        return "GET / and /docs/ responded"

    def admin_login(self) -> str:
        username = self.args.admin_username or env_value(self.dotenv, "ADMIN_DEFAULT_USERNAME", "admin")
        password = self.args.admin_password or env_value(self.dotenv, "ADMIN_DEFAULT_PASSWORD", "admin123")
        if not password:
            password = "admin123"
        data = self.client.api("POST", "/admin/login", json_body={"username": username, "password": password})
        token = require_field(data, "access_token", "admin login response")
        self.state.admin_token = token
        return f"admin={username}"

    def create_test_user(self) -> str:
        username = self.args.test_username or f"lr_smoke_{time.strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(3)}"
        password = self.args.test_password or secrets.token_urlsafe(18)
        email = f"{username}@smoke.lens-rhyme.local"
        payload = {
            "username": username,
            "password": password,
            "email": email,
            "enterprise_name": f"Smoke Test {username}",
            "role": "Administrator",
            "is_sub_account": False,
        }
        data = self.client.api("POST", "/admin/users", token=self.state.admin_token, json_body=payload)
        user_id = require_field(data, "id", "admin create user response")
        self.state.test_user_id = int(user_id)
        self.state.test_username = username
        self.state.test_password = password
        return f"user={username}, id={user_id}"

    def recharge_test_user(self) -> str:
        if self.state.test_user_id is None:
            raise SmokeFailure("test user has not been created")
        amount = self.args.credit_amount
        payload = {
            "user_id": self.state.test_user_id,
            "amount": amount,
            "remark": "Automated post-deploy smoke test recharge",
        }
        data = self.client.api("POST", "/billing/recharge", token=self.state.admin_token, json_body=payload)
        return shorten(data)

    def user_login(self) -> str:
        data = self.client.api(
            "POST",
            "/auth/login",
            json_body={"username": self.state.test_username, "password": self.state.test_password},
        )
        self.state.user_token = require_field(data, "access_token", "user login response")
        return f"user={self.state.test_username}"

    def check_user_balance(self) -> str:
        data = self.client.api("GET", "/billing/balance", token=self.state.user_token)
        balance = find_numeric_value(data, ("available_balance", "balance", "credit", "credits"))
        if balance is None:
            return shorten(data)
        if balance < float(self.args.credit_amount):
            raise SmokeFailure(f"expected balance >= {self.args.credit_amount}, got {balance}")
        return f"balance={balance:g}"

    def test_studio_audio(self) -> str:
        payload = {
            "text": "LensRhyme deployment smoke test audio.",
            "model": self.args.audio_model,
            "speed": 1.0,
        }
        if self.args.audio_voice_id:
            payload["voice_id"] = self.args.audio_voice_id
        task = self.submit_task("audio_generation", "Smoke Studio Audio Generation", payload)
        return self.describe_task_result(task)

    def test_studio_image(self) -> str:
        payload = {
            "mode": "text_to_image",
            "prompt": "A clean product-style photo of a small glass prism on a white desk, soft studio lighting.",
            "model": self.args.image_model,
            "size": self.args.image_size,
        }
        task = self.submit_task("image_generation", "Smoke Studio Image Generation", payload)
        return self.describe_task_result(task)

    def test_studio_video(self) -> str:
        payload = {
            "mode": "text_to_video",
            "prompt": "A calm four second shot of sunlight moving across a modern creative desk.",
            "model": self.args.video_model,
            "resolution": self.args.video_resolution,
            "duration": self.args.video_duration,
            "async_mode": True,
        }
        task = self.submit_task("video_generation", "Smoke Studio Video Generation", payload)
        return self.describe_task_result(task)

    def test_studio_model3d(self) -> str:
        payload = {
            "mode": "image_to_3d",
            "image_url": self.args.model3d_reference_image_url,
            "model": self.args.model3d_model,
            "file_format": self.args.model3d_file_format,
            "subdivision_level": self.args.model3d_subdivision_level,
        }
        task = self.submit_task("model3d_generation", "Smoke Studio 3D Generation", payload)
        return self.describe_task_result(task)

    def test_workbench_import(self) -> str:
        project_payload = {
            "name": f"Smoke Workbench Import {time.strftime('%Y%m%d%H%M%S')}",
            "description": "Created by the post-deploy smoke test.",
            "template_type": "blank",
            "project_type": "short_film",
            "resolution": "480p",
            "aspect_ratio": "16:9",
            "frame_rate": "24fps",
            "acknowledge_template_conflict": True,
        }
        project = self.client.api(
            "POST",
            "/workbench/projects",
            token=self.state.user_token,
            json_body=project_payload,
        )
        project_id = require_field(project, "id", "workbench create project response")
        filename, content = self.download_test_docx()
        response = self.client.upload_file(
            f"/workbench/projects/{project_id}/script/import",
            token=self.state.user_token,
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
        task = self.poll_task(str(task_id), label="script_import", require_result=False)
        output = task.get("output")
        if output is None:
            return f"project={project_id}, task={task_id}"
        return f"project={project_id}, task={task_id}, output={shorten(output)}"

    def download_test_docx(self) -> tuple[str, bytes]:
        url = self.args.docx_url
        req = urllib.request.Request(url, headers={"User-Agent": "lens-rhyme-smoke-test/1.0"})
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

    def submit_task(self, task_type: str, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = self.client.api(
            "POST",
            "/tasks/",
            token=self.state.user_token,
            json_body={
                "task_type": task_type,
                "name": name,
                "payload": payload,
                "timeout_seconds": self.args.task_timeout_seconds,
            },
        )
        task_id = data.get("id") or data.get("task_id") if isinstance(data, dict) else None
        if not task_id:
            raise SmokeFailure(f"task creation response did not include an id: {shorten(data)}")
        if isinstance(data, dict) and str(data.get("status", "")).lower() in SUCCESS_STATUSES:
            self.assert_task_result(data)
            return data
        return self.poll_task(str(task_id), label=task_type, require_result=True)

    def poll_task(self, task_id: str, *, label: str, require_result: bool) -> dict[str, Any]:
        deadline = time.monotonic() + self.args.poll_timeout
        last_task: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            task = self.client.api("GET", f"/tasks/{task_id}", token=self.state.user_token)
            if not isinstance(task, dict):
                raise SmokeFailure(f"{label} task detail is not an object: {shorten(task)}")
            last_task = task
            status = str(task.get("status") or "").lower()
            if status in SUCCESS_STATUSES:
                if require_result:
                    self.assert_task_result(task)
                return task
            if status in FAILURE_STATUSES:
                raise SmokeFailure(
                    f"{label} task {task_id} ended with status={status}, "
                    f"error={task.get('error_message') or task.get('error_code') or shorten(task)}"
                )
            time.sleep(self.args.poll_interval)
        raise SmokeFailure(f"{label} task {task_id} timed out; last state={shorten(last_task)}")

    def assert_task_result(self, task: dict[str, Any]) -> None:
        if extract_task_result_url(task):
            return
        raise SmokeFailure(f"task {task.get('id')} completed without a result URL: {shorten(task)}")

    def describe_task_result(self, task: dict[str, Any]) -> str:
        return f"task={task.get('id')}, result={extract_task_result_url(task)}"

    def cleanup_test_user(self) -> None:
        if self.args.keep_test_user or not self.state.test_user_id or not self.state.admin_token:
            if self.args.keep_test_user and self.state.test_username:
                print(f"Kept temporary test user: {self.state.test_username}")
            return
        try:
            self.client.api("DELETE", f"/admin/users/{self.state.test_user_id}", token=self.state.admin_token)
            print(f"Cleaned up temporary test user: {self.state.test_username}")
        except Exception as exc:
            self.warnings.append(f"failed to delete temporary user {self.state.test_username}: {exc}")


def require_field(data: Any, field: str, context: str) -> Any:
    if isinstance(data, dict) and data.get(field) not in (None, ""):
        return data[field]
    raise SmokeFailure(f"{context} missing '{field}': {shorten(data)}")


def find_numeric_value(data: Any, keys: tuple[str, ...]) -> float | None:
    if isinstance(data, dict):
        for key in keys:
            value = data.get(key)
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                try:
                    return float(value)
                except ValueError:
                    pass
        for value in data.values():
            found = find_numeric_value(value, keys)
            if found is not None:
                return found
    elif isinstance(data, list):
        for item in data:
            found = find_numeric_value(item, keys)
            if found is not None:
                return found
    return None


def extract_task_result_url(task: dict[str, Any]) -> str:
    direct = task.get("result_url")
    if isinstance(direct, str) and direct:
        return direct
    output = task.get("output")
    if isinstance(output, dict):
        for key in ("url", "image_url", "video_url", "audio_url", "model_url", "transcript_url"):
            value = output.get(key)
            if isinstance(value, str) and value:
                return value
    if isinstance(output, str) and output:
        return output
    return ""


def build_parser(dotenv: dict[str, str]) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a deployed LensRhyme Compose stack through admin, Studio, and Workbench flows."
    )
    parser.add_argument("--base-url", default=os.getenv("SMOKE_TEST_BASE_URL", "http://127.0.0.1"))
    parser.add_argument("--api-prefix", default=os.getenv("SMOKE_TEST_API_PREFIX", "/api/v1"))
    parser.add_argument("--env-file", default=os.getenv("SMOKE_TEST_ENV_FILE", ".env"))
    parser.add_argument("--admin-username", default=os.getenv("SMOKE_TEST_ADMIN_USERNAME"))
    parser.add_argument("--admin-password", default=os.getenv("SMOKE_TEST_ADMIN_PASSWORD"))
    parser.add_argument("--test-username", default=os.getenv("SMOKE_TEST_USERNAME"))
    parser.add_argument("--test-password", default=os.getenv("SMOKE_TEST_PASSWORD"))
    parser.add_argument(
        "--credit-amount",
        type=float,
        default=getenv_float("SMOKE_TEST_CREDIT_AMOUNT", 1000.0),
    )
    parser.add_argument("--http-timeout", type=int, default=getenv_int("SMOKE_TEST_HTTP_TIMEOUT", 60))
    parser.add_argument("--poll-timeout", type=int, default=getenv_int("SMOKE_TEST_POLL_TIMEOUT", 1800))
    parser.add_argument("--poll-interval", type=int, default=getenv_int("SMOKE_TEST_POLL_INTERVAL", 10))
    parser.add_argument(
        "--task-timeout-seconds",
        type=int,
        default=getenv_int("SMOKE_TEST_TASK_TIMEOUT_SECONDS", 1800),
    )
    parser.add_argument("--docx-url", default=os.getenv("SMOKE_TEST_DOCX_URL", DEFAULT_DOCX_URL))
    parser.add_argument(
        "--model3d-reference-image-url",
        default=os.getenv("SMOKE_TEST_MODEL3D_REFERENCE_IMAGE_URL", DEFAULT_MODEL3D_REFERENCE_IMAGE_URL),
    )
    parser.add_argument("--audio-model", default=os.getenv("SMOKE_TEST_AUDIO_MODEL", "doubao-tts-2-0"))
    parser.add_argument("--audio-voice-id", default=os.getenv("SMOKE_TEST_AUDIO_VOICE_ID", ""))
    parser.add_argument("--image-model", default=os.getenv("SMOKE_TEST_IMAGE_MODEL", "doubao-seedream-4-5-251128"))
    parser.add_argument("--image-size", default=os.getenv("SMOKE_TEST_IMAGE_SIZE", "2K"))
    parser.add_argument("--video-model", default=os.getenv("SMOKE_TEST_VIDEO_MODEL", "doubao-seedance-2-0-fast-260128"))
    parser.add_argument("--video-resolution", default=os.getenv("SMOKE_TEST_VIDEO_RESOLUTION", "480p"))
    parser.add_argument("--video-duration", type=int, default=getenv_int("SMOKE_TEST_VIDEO_DURATION", 4))
    parser.add_argument("--model3d-model", default=os.getenv("SMOKE_TEST_MODEL3D_MODEL", "doubao-seed3d-2-0-260328"))
    parser.add_argument("--model3d-file-format", default=os.getenv("SMOKE_TEST_MODEL3D_FILE_FORMAT", "glb"))
    parser.add_argument(
        "--model3d-subdivision-level",
        default=os.getenv("SMOKE_TEST_MODEL3D_SUBDIVISION_LEVEL", "medium"),
    )
    parser.add_argument("--skip-studio", action="store_true", default=getenv_bool("SMOKE_TEST_SKIP_STUDIO"))
    parser.add_argument(
        "--skip-workbench",
        action="store_true",
        default=getenv_bool("SMOKE_TEST_SKIP_WORKBENCH"),
    )
    parser.add_argument("--keep-test-user", action="store_true", default=getenv_bool("SMOKE_TEST_KEEP_USER"))
    parser.set_defaults(_dotenv=dotenv)
    return parser


def main() -> int:
    preliminary = argparse.ArgumentParser(add_help=False)
    preliminary.add_argument("--env-file", default=os.getenv("SMOKE_TEST_ENV_FILE", ".env"))
    known, _ = preliminary.parse_known_args()
    dotenv = load_dotenv(Path(known.env_file))
    parser = build_parser(dotenv)
    args = parser.parse_args()
    args.base_url = args.base_url.rstrip("/")
    args.api_prefix = args.api_prefix or "/api/v1"
    try:
        SmokeRunner(args, dotenv).run()
    except KeyboardInterrupt:
        print("Smoke test interrupted.", file=sys.stderr)
        return 130
    except SmokeFailure as exc:
        print(f"\nSmoke test failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
