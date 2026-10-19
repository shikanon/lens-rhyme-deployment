#!/usr/bin/env python3
"""Plan, explicitly apply, or CAS-roll back the reviewed host analytics guard.

Default execution is read-only. This does not deploy or restart application
containers, change GA4 settings, or revoke trackers already loaded in open tabs.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import uuid


API_PATH = "/api/v1/public/analytics-config"
VHOSTS = (
    frozenset(("lensrhyme.com", "www.lensrhyme.com")),
    frozenset(("lens-rhyme.tensorbytes.com",)),
    frozenset(("admin.lensrhyme.com",)),
    frozenset(("admin.lens-rhyme.tensorbytes.com",)),
)
SOURCE_SNIPPET = Path(__file__).resolve().parents[1] / "nginx/snippets/analytics-collection-paused.conf"


class PauseFailure(RuntimeError):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_config(text: str) -> dict:
    """Locate directives without treating comments or quoted braces as blocks."""
    tokens = []
    i = 0
    while i < len(text):
        start = i
        if text[i].isspace():
            i += 1
        elif text[i] == "#":
            end = text.find("\n", i)
            i = len(text) if end < 0 else end + 1
        elif text[i] in "{};":
            tokens.append((text[i], i, True))
            i += 1
        elif text[i] in "\"'":
            quote = text[i]
            i += 1
            value = ""
            while i < len(text) and text[i] != quote:
                if text[i] == "\\":
                    i += 1
                    if i >= len(text):
                        raise PauseFailure("Unterminated quoted directive")
                value += text[i]
                i += 1
            if i >= len(text):
                raise PauseFailure("Unterminated quoted directive")
            tokens.append((value, start, False))
            i += 1
        else:
            while i < len(text) and not text[i].isspace() and text[i] not in "{};#\"'":
                i += 1
            tokens.append((text[start:i], start, False))

    root = {"header": [], "children": [], "statements": []}
    stack = [root]
    pending = []
    for value, offset, punctuation in tokens:
        if punctuation and value == "{":
            if not pending:
                raise PauseFailure("Block without a directive")
            node = {"header": [x[0] for x in pending], "start": pending[0][1], "children": [], "statements": []}
            stack[-1]["children"].append(node)
            stack.append(node)
            pending = []
        elif punctuation and value == ";":
            stack[-1]["statements"].append([x[0] for x in pending])
            pending = []
        elif punctuation and value == "}":
            if len(stack) == 1 or pending:
                raise PauseFailure("Unexpected closing brace or missing semicolon")
            stack.pop()
        else:
            pending.append((value, offset))
    if len(stack) != 1 or pending:
        raise PauseFailure("Unterminated configuration")
    return root


def walk(node: dict):
    yield node
    for child in node["children"]:
        yield from walk(child)


def assert_reviewed_headers(config_dump: str) -> None:
    # Nginx 1.24 drops inherited add_header values when a location adds one.
    # The reviewed host only has immutable asset headers. Stop on any new set,
    # including unrelated vhosts, so an operator can preserve it deliberately.
    for node in walk(parse_config(config_dump)):
        for directive in node["statements"]:
            if not directive or directive[0] != "add_header":
                continue
            in_asset = node["header"] in (
                ["location", "^~", "/content-assets/"],
                ["location", "^~", "/editorial/"],
            )
            if not (in_asset and directive[1:] in (
                ["Cache-Control", "public, immutable"],
                ["Cache-Control", "public, immutable", "always"],
            )):
                raise PauseFailure("Unreviewed add_header set; preserve effective security headers before applying")


def candidate_site(text: str, snippet_target: Path) -> str:
    if not re.fullmatch(r"/[A-Za-z0-9_./-]+", str(snippet_target)):
        raise PauseFailure("Snippet target must be an absolute Nginx-safe path")
    root = parse_config(text)
    for node in walk(root):
        if node["header"][:1] == ["location"] and API_PATH in node["header"]:
            raise PauseFailure("An analytics-config location already exists")
        if ["include", str(snippet_target)] in node["statements"]:
            raise PauseFailure("Guard include already exists")
    found = set()
    positions = []
    for server in root["children"]:
        if server["header"] != ["server"]:
            continue
        names = [x[1:] for x in server["statements"] if x[:1] == ["server_name"]]
        if len(names) != 1:
            raise PauseFailure("Expected exactly one server_name per server")
        hosts = frozenset(names[0])
        if not any(hosts & expected for expected in VHOSTS):
            continue
        if hosts not in VHOSTS or hosts in found:
            raise PauseFailure("HTTPS vhost hostname set changed or duplicated")
        listeners = [x for x in server["statements"] if x[:1] == ["listen"]]
        if not listeners or any(x[1] not in ("443", "[::]:443") or "ssl" not in x for x in listeners):
            raise PauseFailure("Expected reviewed HTTPS listeners")
        apis = [x for x in server["children"] if x["header"] == ["location", "/api/"]]
        if len(apis) != 1 or apis[0]["statements"].count(["proxy_pass", "http://BACKEND_UPSTREAM"]) != 1:
            raise PauseFailure("Expected one direct /api/ anchor with BACKEND_UPSTREAM")
        start = apis[0]["start"]
        line_start = text.rfind("\n", 0, start) + 1
        indent = text[line_start:start]
        if indent.strip():
            raise PauseFailure("API anchor must start on its own line")
        positions.append((line_start, indent))
        found.add(hosts)
    if found != set(VHOSTS):
        raise PauseFailure("Expected all four reviewed HTTPS vhosts")
    for position, indent in sorted(positions, reverse=True):
        text = text[:position] + f"{indent}include {snippet_target};\n\n" + text[position:]
    return text


def command(args: list[str]) -> None:
    result = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
    if result.returncode:
        raise PauseFailure(f"Command failed: {args[0]} {' '.join(args[1:])}")


def config_dump(site: Path) -> str:
    result = subprocess.run(["nginx", "-T"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
    if result.returncode:
        raise PauseFailure("Current nginx -T failed; no changes made")
    markers = (f"# configuration file {site}:", f"# configuration file {site.resolve()}:")
    if not any(x in result.stdout for x in markers):
        raise PauseFailure("Requested site is not in the default Nginx configuration")
    assert_reviewed_headers(result.stdout)
    return result.stdout


def compare_site(site: Path, expected_realpath: Path, expected_hash: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        raise PauseFailure("Expected SHA256 must be 64 lowercase hex characters")
    if not expected_realpath.is_absolute() or site.resolve(strict=True) != expected_realpath:
        raise PauseFailure("Site realpath changed")
    if not expected_realpath.is_file() or sha256(expected_realpath.read_bytes()) != expected_hash:
        raise PauseFailure("Site checksum changed")
    return expected_realpath


def atomic_write(path: Path, data: bytes, metadata: Path | None = None) -> None:
    fd, temporary = tempfile.mkstemp(prefix=".analytics-pause-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if metadata:
            original = metadata.stat()
            os.chown(temporary, original.st_uid, original.st_gid)
            shutil.copystat(metadata, temporary)
        else:
            os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_receipt(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n")
    path.chmod(0o600)


def pause(args: argparse.Namespace) -> dict:
    realpath = compare_site(args.site, args.expected_realpath, args.expected_sha256)
    if os.path.lexists(args.snippet_target):
        raise PauseFailure("Snippet target exists; refusing to overwrite it")
    dump = config_dump(args.site)
    before = realpath.read_bytes()
    source = SOURCE_SNIPPET.read_bytes()
    candidate = candidate_site(before.decode(), args.snippet_target).encode()
    summary = {"status": "plan", "site": str(args.site), "realpath": str(realpath), "before_sha256": sha256(before), "after_sha256": sha256(candidate), "snippet": str(args.snippet_target), "snippet_sha256": sha256(source), "vhosts": [sorted(x) for x in VHOSTS], "nginx_dump_sha256": sha256(dump.encode()), "fresh_page_verification_required": True, "existing_tabs_revoked": False}
    if not args.apply:
        return summary
    if not args.snippet_target.parent.is_dir():
        raise PauseFailure("Snippet target directory must already exist")
    args.backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if args.backup_dir.is_symlink() or stat.S_IMODE(args.backup_dir.stat().st_mode) & 0o077:
        raise PauseFailure("Backup directory must be private and not a symlink")
    operation = args.backup_dir / (datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8])
    operation.mkdir(mode=0o700)
    backup = operation / "site.before"
    shutil.copy2(realpath, backup)
    original = realpath.stat()
    os.chown(backup, original.st_uid, original.st_gid)
    if sha256(backup.read_bytes()) != summary["before_sha256"]:
        raise PauseFailure("Site changed while backing up")
    receipt_path = operation / "receipt.json"
    receipt = {**summary, "status": "prepared", "backup": str(backup), "site_mode": stat.S_IMODE(original.st_mode), "site_uid": original.st_uid, "site_gid": original.st_gid, "snippet_was_absent": True}
    write_receipt(receipt_path, receipt)
    compare_site(args.site, args.expected_realpath, summary["before_sha256"])
    if os.path.lexists(args.snippet_target):
        raise PauseFailure("Snippet appeared concurrently")
    atomic_write(args.snippet_target, source)
    try:
        # Recheck the symlink and original bytes immediately before replacement.
        compare_site(args.site, args.expected_realpath, summary["before_sha256"])
        atomic_write(realpath, candidate, backup)
        command(["nginx", "-t"])
    except Exception:
        if args.site.resolve() != realpath:
            raise PauseFailure("Site symlink changed; automatic restore refused")
        current_hash = sha256(realpath.read_bytes())
        if current_hash == summary["after_sha256"]:
            atomic_write(realpath, before, backup)
        elif current_hash != summary["before_sha256"]:
            raise PauseFailure("Site changed concurrently; automatic restore refused")
        if sha256(args.snippet_target.read_bytes()) != summary["snippet_sha256"]:
            raise PauseFailure("Snippet changed concurrently; automatic cleanup refused")
        args.snippet_target.unlink()
        command(["nginx", "-t"])
        receipt["status"] = "restored_before_reload"
        write_receipt(receipt_path, receipt)
        raise PauseFailure(f"Candidate failed; original bytes restored without reload. Receipt: {receipt_path}")
    try:
        compare_site(args.site, realpath, summary["after_sha256"])
        if sha256(args.snippet_target.read_bytes()) != summary["snippet_sha256"]:
            raise PauseFailure("Snippet changed before reload")
        command(["systemctl", "reload", "nginx"])
    except Exception:
        receipt["status"] = "reload_failed_guard_retained"
        write_receipt(receipt_path, receipt)
        raise PauseFailure(f"Valid guard retained; reload result needs inspection. Receipt: {receipt_path}")
    receipt["status"] = "applied_verification_pending"
    write_receipt(receipt_path, receipt)
    return {**receipt, "receipt": str(receipt_path)}


def rollback(args: argparse.Namespace) -> dict:
    receipt = json.loads(args.rollback.read_text())
    site, realpath = Path(receipt["site"]), Path(receipt["realpath"])
    snippet, backup = Path(receipt["snippet"]), Path(receipt["backup"])
    compare_site(site, realpath, receipt["after_sha256"])
    if not snippet.is_file() or snippet.is_symlink() or sha256(snippet.read_bytes()) != receipt["snippet_sha256"]:
        raise PauseFailure("Snippet changed; rollback refused")
    if not backup.is_file() or sha256(backup.read_bytes()) != receipt["before_sha256"]:
        raise PauseFailure("Backup changed; rollback refused")
    summary = {"status": "rollback_plan", "site": str(site), "realpath": str(realpath), "receipt": str(args.rollback), "collection_may_resume": True}
    if not args.apply:
        return summary
    if not args.rollback_safety_confirmed:
        raise PauseFailure("Rollback can resume collection; require an accepted replacement pause or completed collection gate")
    # Keep the snippet until the restored configuration has passed validation.
    installed = realpath.read_bytes()
    compare_site(site, realpath, receipt["after_sha256"])
    atomic_write(realpath, backup.read_bytes(), backup)
    try:
        command(["nginx", "-t"])
    except Exception:
        compare_site(site, realpath, receipt["before_sha256"])
        atomic_write(realpath, installed, backup)
        command(["nginx", "-t"])
        raise PauseFailure("Rollback validation failed; paused site bytes restored without reload")
    command(["systemctl", "reload", "nginx"])
    if sha256(snippet.read_bytes()) != receipt["snippet_sha256"]:
        raise PauseFailure("Rollback reloaded; snippet changed and was left intact")
    snippet.unlink()
    receipt["status"] = "rolled_back_verification_pending"
    write_receipt(args.rollback, receipt)
    return {**summary, "status": receipt["status"]}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", type=Path, default=Path("/etc/nginx/sites-enabled/lensrhyme.conf"))
    parser.add_argument("--expected-realpath", type=Path)
    parser.add_argument("--expected-sha256", default="")
    parser.add_argument("--snippet-target", type=Path, default=Path("/etc/nginx/snippets/lensrhyme-analytics-collection-paused.conf"))
    parser.add_argument("--backup-dir", type=Path, default=Path("/var/backups/lensrhyme-analytics-pause"))
    parser.add_argument("--apply", action="store_true", help="Actually install/restore files, validate and gracefully reload host Nginx")
    parser.add_argument("--rollback", type=Path, metavar="RECEIPT", help="Plan restoration from this operation's receipt")
    parser.add_argument("--rollback-safety-confirmed", action="store_true", help="Operator confirms replacement pause is accepted or the collection gate is complete")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if not args.rollback and args.expected_realpath is None:
            raise PauseFailure("--expected-realpath and --expected-sha256 are required")
        result = rollback(args) if args.rollback else pause(args)
        print(json.dumps(result, indent=2))
        return 0
    except (PauseFailure, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "stopped", "error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
