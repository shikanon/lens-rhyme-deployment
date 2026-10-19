from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


def load_module():
    path = Path(__file__).with_name("host-nginx-analytics-pause.py")
    spec = importlib.util.spec_from_file_location("host_nginx_analytics_pause", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HostNginxAnalyticsPauseTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.realpath = self.root / "site.conf"
        self.site = self.root / "enabled.conf"
        self.site.symlink_to(self.realpath)
        (self.root / "snippets").mkdir()
        self.before = "# Preserve this TLS/upstream configuration byte for byte.\nserver {\n    listen 80;\n    server_name _;\n    location / { return 301 https://$host$request_uri; }\n}\n"
        for hosts in self.module.VHOSTS:
            self.before += """server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name HOSTS;
    # location = /api/v1/public/analytics-config { is only a comment
    location /api/ {
        proxy_pass http://BACKEND_UPSTREAM;
        proxy_read_timeout 600;
    }
    location /outputs/ { proxy_pass http://BACKEND_UPSTREAM; }
    location ^~ /content-assets/ {
        add_header Cache-Control "public, immutable";
    }
}
""".replace("HOSTS", " ".join(sorted(hosts)))
        self.realpath.write_text(self.before)
        self.realpath.chmod(0o640)
        self.args = self.module.build_parser().parse_args([
            "--site", str(self.site),
            "--expected-realpath", str(self.realpath),
            "--expected-sha256", self.module.sha256(self.before.encode()),
            "--snippet-target", str(self.root / "snippets/analytics-paused.conf"),
            "--backup-dir", str(self.root / "backups"),
        ])
        self.calls = []
        self.test_failures = 0
        self.reload_failure = False
        self.patch = mock.patch.object(self.module.subprocess, "run", side_effect=self.run_command)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def run_command(self, args, **kwargs):
        self.calls.append(args)
        if args == ["nginx", "-T"]:
            return SimpleNamespace(returncode=0, stdout=f"# configuration file {self.site}:\n" + self.realpath.read_text(), stderr="")
        if args == ["nginx", "-t"] and self.test_failures:
            self.test_failures -= 1
            return SimpleNamespace(returncode=1, stdout="", stderr="synthetic invalid candidate")
        if args == ["systemctl", "reload", "nginx"] and self.reload_failure:
            return SimpleNamespace(returncode=1, stdout="", stderr="synthetic reload failure")
        self.assertIn(args, (["nginx", "-t"], ["systemctl", "reload", "nginx"]))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def apply(self):
        self.args.apply = True
        return self.module.pause(self.args)

    def rollback_args(self, result, apply=False, safety=False):
        return self.module.build_parser().parse_args([
            "--rollback", result["receipt"],
            *(["--apply"] if apply else []),
            *(["--rollback-safety-confirmed"] if safety else []),
        ])

    def test_default_plan_has_no_writes_or_reload(self):
        result = self.module.pause(self.args)
        self.assertEqual(result["status"], "plan")
        self.assertFalse(self.args.apply)
        self.assertEqual(self.realpath.read_text(), self.before)
        self.assertTrue(self.site.is_symlink())
        self.assertFalse(self.args.snippet_target.exists())
        self.assertFalse(self.args.backup_dir.exists())
        self.assertEqual(self.calls, [["nginx", "-T"]])

    def test_only_four_server_scope_includes_change(self):
        candidate = self.module.candidate_site(self.before, self.args.snippet_target)
        addition = f"    include {self.args.snippet_target};\n\n"
        self.assertEqual(candidate.count(addition), 4)
        self.assertEqual(candidate.replace(addition, ""), self.before)
        parsed = self.module.parse_config(candidate)
        affected = [x for x in parsed["children"] if ["include", str(self.args.snippet_target)] in x["statements"]]
        self.assertEqual(len(affected), 4)

    def test_comments_and_quoted_braces_are_not_configuration_blocks(self):
        text = self.before.replace("proxy_read_timeout 600;", "proxy_read_timeout 600;\n        set $synthetic '}#;';")
        self.assertIn("set $synthetic '}#;';", self.module.candidate_site(text, self.args.snippet_target))

    def test_exact_snippet_response_contract(self):
        snippet = self.module.parse_config(self.module.SOURCE_SNIPPET.read_text())["children"]
        self.assertEqual(len(snippet), 1)
        self.assertEqual(snippet[0]["header"], ["location", "=", self.module.API_PATH])
        self.assertEqual(snippet[0]["statements"], [
            ["default_type", "application/json"],
            ["add_header", "Cache-Control", "no-store", "always"],
            ["return", "200", '{"measurement_id":""}'],
        ])

    def test_checksum_mismatch_stops_before_nginx_or_writes(self):
        self.realpath.write_text(self.before + "# concurrent edit\n")
        with self.assertRaisesRegex(self.module.PauseFailure, "checksum"):
            self.module.pause(self.args)
        self.assertEqual(self.calls, [])
        self.assertFalse(self.args.snippet_target.exists())

    def test_symlink_target_mismatch_stops(self):
        other = self.root / "other.conf"
        other.write_text(self.before)
        self.site.unlink()
        self.site.symlink_to(other)
        with self.assertRaisesRegex(self.module.PauseFailure, "realpath"):
            self.module.pause(self.args)
        self.assertEqual(self.calls, [])

    def test_unexpected_hostname_or_missing_vhost_stops(self):
        for text in [self.before.replace("www.lensrhyme.com", "extra.invalid"), self.before.replace("admin.lensrhyme.com", "other.invalid")]:
            with self.subTest(text=text[-100:]), self.assertRaises(self.module.PauseFailure):
                self.module.candidate_site(text, self.args.snippet_target)

    def test_api_anchor_upstream_or_listener_changes_stop(self):
        for text in [self.before.replace("location /api/", "location /api-other/", 1), self.before.replace("http://BACKEND_UPSTREAM", "http://OTHER_UPSTREAM", 1), self.before.replace("listen 443 ssl http2", "listen 8443 ssl http2", 1)]:
            with self.subTest(text=text[:200]), self.assertRaises(self.module.PauseFailure):
                self.module.candidate_site(text, self.args.snippet_target)

    def test_duplicate_api_anchor_or_existing_guard_stops(self):
        duplicate = self.before.replace("location /outputs/", "location /api/", 1)
        exact = self.before + f"server {{ location = {self.module.API_PATH} {{ return 200 ''; }} }}\n"
        for text in [duplicate, exact, f"include {self.args.snippet_target};\n" + self.before]:
            with self.subTest(text=text[-100:]), self.assertRaises(self.module.PauseFailure):
                self.module.candidate_site(text, self.args.snippet_target)

    def test_unknown_parent_or_location_headers_stop(self):
        for text in ["http { add_header Strict-Transport-Security 'max-age=123'; }\n" + self.before, self.before.replace("server_name lensrhyme.com", "add_header X-Content-Type-Options nosniff;\n    server_name lensrhyme.com"), self.before.replace('add_header Cache-Control "public, immutable";', 'add_header Content-Security-Policy "default-src none";', 1)]:
            with self.subTest(text=text[:100]), self.assertRaisesRegex(self.module.PauseFailure, "add_header"):
                self.module.assert_reviewed_headers(text)

    def test_preexisting_snippet_is_never_overwritten(self):
        self.args.snippet_target.write_text("existing unrelated file")
        with self.assertRaisesRegex(self.module.PauseFailure, "exists"):
            self.apply()
        self.assertEqual(self.args.snippet_target.read_text(), "existing unrelated file")
        self.assertEqual(self.calls, [])

    def test_apply_preserves_symlink_permissions_and_private_backup(self):
        before_stat = self.realpath.stat()
        result = self.apply()
        self.assertEqual(result["status"], "applied_verification_pending")
        self.assertTrue(self.site.is_symlink())
        self.assertEqual(stat.S_IMODE(self.realpath.stat().st_mode), 0o640)
        self.assertEqual((self.realpath.stat().st_uid, self.realpath.stat().st_gid), (before_stat.st_uid, before_stat.st_gid))
        self.assertEqual(Path(result["backup"]).read_text(), self.before)
        self.assertEqual(stat.S_IMODE(Path(result["backup"]).parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(Path(result["receipt"]).stat().st_mode), 0o600)
        self.assertEqual(self.calls, [["nginx", "-T"], ["nginx", "-t"], ["systemctl", "reload", "nginx"]])

    def test_invalid_candidate_restores_original_and_never_reloads(self):
        self.test_failures = 1
        with self.assertRaisesRegex(self.module.PauseFailure, "original bytes restored"):
            self.apply()
        self.assertEqual(self.realpath.read_text(), self.before)
        self.assertTrue(self.site.is_symlink())
        self.assertEqual(stat.S_IMODE(self.realpath.stat().st_mode), 0o640)
        self.assertFalse(self.args.snippet_target.exists())
        self.assertEqual(self.calls, [["nginx", "-T"], ["nginx", "-t"], ["nginx", "-t"]])

    def test_reload_failure_retains_valid_guard_and_receipt(self):
        self.reload_failure = True
        with self.assertRaisesRegex(self.module.PauseFailure, "Valid guard retained"):
            self.apply()
        self.assertTrue(self.args.snippet_target.is_file())
        self.assertNotEqual(self.realpath.read_text(), self.before)
        receipts = list(self.args.backup_dir.glob("*/receipt.json"))
        self.assertEqual(json.loads(receipts[0].read_text())["status"], "reload_failed_guard_retained")

    def test_rollback_plan_is_readonly_and_apply_requires_safety_condition(self):
        result = self.apply()
        installed = self.realpath.read_bytes()
        self.calls.clear()
        self.assertEqual(self.module.rollback(self.rollback_args(result))["status"], "rollback_plan")
        with self.assertRaisesRegex(self.module.PauseFailure, "resume collection"):
            self.module.rollback(self.rollback_args(result, apply=True))
        self.assertEqual(self.realpath.read_bytes(), installed)
        self.assertEqual(self.calls, [])

    def test_rollback_with_changed_site_or_snippet_refuses_overwrite(self):
        result = self.apply()
        installed = self.realpath.read_bytes()
        self.realpath.write_bytes(installed + b"# concurrent\n")
        with self.assertRaisesRegex(self.module.PauseFailure, "checksum"):
            self.module.rollback(self.rollback_args(result, apply=True, safety=True))
        self.assertTrue(self.realpath.read_bytes().endswith(b"# concurrent\n"))
        self.realpath.write_bytes(installed)
        self.args.snippet_target.write_text("changed snippet")
        with self.assertRaisesRegex(self.module.PauseFailure, "Snippet changed"):
            self.module.rollback(self.rollback_args(result, apply=True, safety=True))
        self.assertEqual(self.realpath.read_bytes(), installed)

    def test_accepted_rollback_restores_backup_and_only_removes_owned_snippet(self):
        result = self.apply()
        unrelated = self.root / "snippets/unrelated.conf"
        unrelated.write_text("leave me")
        self.calls.clear()
        restored = self.module.rollback(self.rollback_args(result, apply=True, safety=True))
        self.assertEqual(restored["status"], "rolled_back_verification_pending")
        self.assertEqual(self.realpath.read_text(), self.before)
        self.assertEqual(stat.S_IMODE(self.realpath.stat().st_mode), 0o640)
        self.assertTrue(self.site.is_symlink())
        self.assertFalse(self.args.snippet_target.exists())
        self.assertEqual(unrelated.read_text(), "leave me")
        self.assertEqual(self.calls, [["nginx", "-t"], ["systemctl", "reload", "nginx"]])

    def test_failed_rollback_validation_restores_paused_bytes_without_reload(self):
        result = self.apply()
        installed = self.realpath.read_bytes()
        self.calls.clear()
        self.test_failures = 1
        with self.assertRaisesRegex(self.module.PauseFailure, "paused site bytes restored"):
            self.module.rollback(self.rollback_args(result, apply=True, safety=True))
        self.assertEqual(self.realpath.read_bytes(), installed)
        self.assertTrue(self.args.snippet_target.is_file())
        self.assertEqual(self.calls, [["nginx", "-t"], ["nginx", "-t"]])


if __name__ == "__main__":
    unittest.main()
