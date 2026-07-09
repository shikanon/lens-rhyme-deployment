#!/usr/bin/env python3
"""LensRhyme feature regression report helper.

This script turns manual observations into a small, shareable report:
duration statistics, success rates, reproduction probability, impact scope,
URL/DOM jump checks, and video element health checks. It intentionally reads
credentials and environment-specific values from the environment or arguments
instead of storing secrets in the repository.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


SENSITIVE_PATTERNS = [
    re.compile(
        r"(?i)\b([A-Z0-9_-]*(?:password|passwd|pwd|access[_-]?token|refresh[_-]?token|api[_-]?key|secret|token|credential|signature))"
        r"(\s*[:=]\s*)([^\s&,'\"]+)"
    ),
    re.compile(r"(?i)\b(authorization\s*:\s*bearer)(\s+)([^\s,'\"]+)"),
    re.compile(r"(?i)\b(bearer)(\s+)([A-Za-z0-9._~+/=-]{8,})"),
]


@dataclass
class ScenarioResult:
    feature: str
    status: str
    duration_s: float
    detail: str = ""
    impact_scope: str = "待评估"
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "status": self.status,
            "duration_s": round(self.duration_s, 3),
            "detail": redact_sensitive_values(self.detail),
            "impact_scope": self.impact_scope,
            "evidence": redact_json(self.evidence),
        }


def redact_sensitive_values(text: str) -> str:
    redacted = text
    for pattern in SENSITIVE_PATTERNS:
        redacted = pattern.sub(lambda match: f"{match.group(1)}{match.group(2)}<redacted>", redacted)
    return redacted


def redact_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: redact_json("<redacted>" if is_sensitive_key(str(key)) else item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_json(item) for item in value]
    if isinstance(value, str):
        return redact_sensitive_values(value)
    return value


def is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in ("password", "token", "secret", "api_key", "apikey", "authorization"))


def summarize_results(results: list[ScenarioResult]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[ScenarioResult]] = defaultdict(list)
    for result in results:
        grouped[result.feature].append(result)

    summaries: dict[str, dict[str, Any]] = {}
    for feature, items in grouped.items():
        durations = [item.duration_s for item in items]
        passed = sum(1 for item in items if item.status == "pass")
        failed = sum(1 for item in items if item.status == "fail")
        warned = sum(1 for item in items if item.status == "warn")
        runs = len(items)
        issue_rate = (failed + warned) / runs if runs else 0.0
        summaries[feature] = {
            "runs": runs,
            "passed": passed,
            "failed": failed,
            "warned": warned,
            "skipped": sum(1 for item in items if item.status == "skip"),
            "success_rate": passed / runs if runs else 0.0,
            "avg_duration_s": sum(durations) / runs if runs else 0.0,
            "max_duration_s": max(durations) if durations else 0.0,
            "reproduction_probability": f"{issue_rate * 100:.1f}%",
        }
    return summaries


def validate_jump_target(
    *,
    actual_url: str,
    expected_path: str,
    dom_text: str,
    required_markers: list[str],
) -> dict[str, Any]:
    parsed = urllib.parse.urlparse(actual_url)
    url_matches = parsed.path.rstrip("/") == expected_path.rstrip("/")
    lowered_dom = dom_text.lower()
    missing_markers = [marker for marker in required_markers if marker.lower() not in lowered_dom]
    dom_matches = not missing_markers
    return {
        "status": "pass" if url_matches and dom_matches else "fail",
        "url_matches": url_matches,
        "dom_matches": dom_matches,
        "actual_path": parsed.path,
        "expected_path": expected_path,
        "missing_markers": missing_markers,
    }


def summarize_video_elements(videos: list[dict[str, Any]]) -> dict[str, int]:
    summary = {
        "video_count": len(videos),
        "missing_source_or_poster": 0,
        "unplayable": 0,
        "playable": 0,
    }
    for video in videos:
        has_visual_identity = bool(video.get("src")) or bool(video.get("poster"))
        if not has_visual_identity:
            summary["missing_source_or_poster"] += 1
        error = video.get("error")
        ready_state = int(video.get("readyState") or 0)
        if error or ready_state < 2:
            summary["unplayable"] += 1
        else:
            summary["playable"] += 1
    return summary


def render_markdown_report(results: list[ScenarioResult]) -> str:
    summaries = summarize_results(results)
    lines = [
        "# LensRhyme 功能回归测试报告",
        "",
        "## 汇总",
        "",
        "| 功能 | 轮次 | 通过 | 警告 | 失败 | 平均耗时 | 最大耗时 | 问题复现概率 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for feature in sorted(summaries):
        item = summaries[feature]
        lines.append(
            "| {feature} | {runs} | {passed} | {warned} | {failed} | {avg:.1f}s | {max:.1f}s | {prob} |".format(
                feature=feature,
                runs=item["runs"],
                passed=item["passed"],
                warned=item["warned"],
                failed=item["failed"],
                avg=item["avg_duration_s"],
                max=item["max_duration_s"],
                prob=item["reproduction_probability"],
            )
        )

    lines.extend(["", "## 明细", ""])
    for result in results:
        lines.extend(
            [
                f"### {result.feature}",
                "",
                f"- 状态：{result.status}",
                f"- 耗时：{result.duration_s:.1f}s",
                f"- 问题复现概率：{summaries[result.feature]['reproduction_probability']}",
                f"- 影响范围：{result.impact_scope}",
                f"- 说明：{redact_sensitive_values(result.detail) if result.detail else '无'}",
                "",
            ]
        )
        if result.evidence:
            evidence = json.dumps(redact_json(result.evidence), ensure_ascii=False, sort_keys=True)
            lines.extend([f"- 证据：`{evidence}`", ""])
    return "\n".join(lines).rstrip() + "\n"


def join_url(base: str, path: str) -> str:
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


def route_looks_like_app_shell(body: str) -> bool:
    lowered = body.lower()
    return "<html" in lowered and ("lensrhyme" in lowered or "_next/static" in lowered)


def check_route(base_url: str, route: str, timeout: int) -> ScenarioResult:
    started = time.monotonic()
    url = join_url(base_url, route)
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "lens-rhyme-feature-report/1.0"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            status = response.status
        ok = 200 <= status < 400 and route_looks_like_app_shell(body)
        return ScenarioResult(
            feature=f"route{route}",
            status="pass" if ok else "fail",
            duration_s=time.monotonic() - started,
            detail=f"GET {route} returned {status}",
            impact_scope="基础页面访问",
            evidence={"status": status, "body_chars": len(body)},
        )
    except (urllib.error.URLError, TimeoutError) as exc:
        return ScenarioResult(
            feature=f"route{route}",
            status="fail",
            duration_s=time.monotonic() - started,
            detail=f"GET {route} failed: {exc}",
            impact_scope="基础页面访问",
        )


def load_browser_findings(path: str) -> list[ScenarioResult]:
    if not path:
        return []
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    results = []
    for item in raw:
        results.append(
            ScenarioResult(
                feature=str(item["feature"]),
                status=str(item["status"]),
                duration_s=float(item.get("duration_s") or 0),
                detail=str(item.get("detail") or ""),
                impact_scope=str(item.get("impact_scope") or "待评估"),
                evidence=dict(item.get("evidence") or {}),
            )
        )
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a LensRhyme feature regression report.")
    parser.add_argument("--base-url", default=os.getenv("LENS_SMOKE_BASE_URL", os.getenv("SMOKE_TEST_BASE_URL", "http://127.0.0.1:5410")))
    parser.add_argument("--routes", default="/chat,/studio,/workbench")
    parser.add_argument("--runs", type=int, default=int(os.getenv("LENS_SMOKE_RUNS", "1")))
    parser.add_argument("--http-timeout", type=int, default=int(os.getenv("LENS_SMOKE_HTTP_TIMEOUT", "30")))
    parser.add_argument("--browser-findings-json", default="")
    parser.add_argument("--report-path", default="")
    parser.add_argument("--json-path", default="")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    routes = [route.strip() for route in args.routes.split(",") if route.strip()]
    results: list[ScenarioResult] = []
    for _ in range(max(args.runs, 1)):
        for route in routes:
            results.append(check_route(args.base_url, route, args.http_timeout))
    results.extend(load_browser_findings(args.browser_findings_json))

    report = render_markdown_report(results)
    if args.report_path:
        Path(args.report_path).write_text(report, encoding="utf-8")
    else:
        print(report)
    if args.json_path:
        Path(args.json_path).write_text(
            json.dumps([result.to_dict() for result in results], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return 1 if any(result.status == "fail" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
