from __future__ import annotations

import copy
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


def load_module():
    path = Path(__file__).with_name("host-backend-analytics-pause.py")
    name = "host_backend_analytics_pause_test_target"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class BackendAnalyticsPauseTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.image = "docker.io/shikanon096/lens-rhyme-backend@sha256:" + "1" * 64
        self.old_image = "docker.io/shikanon096/lens-rhyme-backend@sha256:" + "2" * 64
        self.revision = "d" * 40
        self.upstreams = b"""# Keep all unrelated bytes and upstreams.
upstream BACKEND_UPSTREAM {
    server 172.18.0.8:8000;
    keepalive 32;
}
upstream FRONTEND_UPSTREAM {
    server 172.18.0.9:3000;
}
"""
        self.before_config = {
            "name": "compose",
            "services": {
                "backend": {
                    "image": self.old_image,
                    "command": ["python3", "-m", "scripts.server", "start"],
                    "environment": {"DEBUG": "False", "RUN_MIGRATIONS": "0"},
                    "depends_on": {"postgres": {"condition": "service_healthy"}},
                    "volumes": [{"type": "bind", "source": "/data", "target": "/app/data"}],
                    "networks": {"default": {}},
                    "ports": [{"target": 8000, "published": "8000"}],
                },
                "seo-generation-worker": {"image": self.old_image},
                "seo-publication-worker": {"image": self.old_image},
                "frontend": {"image": "example.invalid/frontend:stable"},
                "admin-frontend": {"image": "example.invalid/admin:stable"},
                "content-frontend": {"image": "example.invalid/content:stable"},
                "docs-site": {"image": "example.invalid/docs:stable"},
                "codex-runner-manager": {"image": "example.invalid/runner:stable"},
            },
            "networks": {"default": {"name": "compose_default"}},
            "volumes": {"data": {}},
        }
        self.no_subprocess = mock.patch.object(self.module.subprocess, "run", side_effect=AssertionError("Real subprocess is forbidden in offline tests"))
        self.no_subprocess.start()
        self.addCleanup(self.no_subprocess.stop)

    def candidate_config(self):
        value = copy.deepcopy(self.before_config)
        value["services"]["backend"]["image"] = self.image
        return value

    def test_complete_compose_config_accepts_only_backend_image_change(self):
        before = copy.deepcopy(self.before_config)
        after = self.candidate_config()
        self.module.only_backend_image_changed(before, after, self.image)
        self.assertEqual(before, self.before_config)
        self.assertEqual(after, self.candidate_config())

    def test_complete_compose_config_rejects_shared_worker_or_other_service_change(self):
        for service in ("seo-generation-worker", "seo-publication-worker", "frontend", "codex-runner-manager"):
            after = self.candidate_config()
            after["services"][service]["image"] = self.image
            with self.subTest(service=service), self.assertRaises(self.module.PauseFailure):
                self.module.only_backend_image_changed(self.before_config, after, self.image)

    def test_complete_compose_config_rejects_backend_environment_command_or_topology_change(self):
        mutations = (
            lambda value: value["services"]["backend"]["environment"].update(RUN_MIGRATIONS="1"),
            lambda value: value["services"]["backend"].update(command=["unsafe-migration"]),
            lambda value: value["services"]["backend"].update(ports=[]),
            lambda value: value["networks"]["default"].update(name="changed"),
            lambda value: value["services"].pop("docs-site"),
        )
        for index, change in enumerate(mutations):
            after = self.candidate_config()
            change(after)
            with self.subTest(index=index), self.assertRaises(self.module.PauseFailure):
                self.module.only_backend_image_changed(self.before_config, after, self.image)

    def test_complete_compose_config_rejects_wrong_target_image(self):
        with self.assertRaises(self.module.PauseFailure):
            self.module.only_backend_image_changed(self.before_config, self.before_config, self.image)

    def test_override_contains_only_the_pinned_backend_image(self):
        self.assertEqual(self.module.override_text(self.image), "services:\n  backend:\n    image: " + self.image + "\n")
        for image in (self.image.replace("@sha256:", ":"), "another.invalid/backend@sha256:" + "1" * 64):
            with self.subTest(image=image), self.assertRaises(self.module.PauseFailure):
                self.module.override_text(image)

    def test_upstream_patch_changes_exactly_one_backend_server_line(self):
        result = self.module.patch_backend_upstream(self.upstreams, "172.18.0.27")
        self.assertEqual(result, self.upstreams.replace(b"server 172.18.0.8:8000;", b"server 172.18.0.27:8000;", 1))

    def test_upstream_patch_rejects_missing_duplicate_or_multiple_backend_servers(self):
        cases = (
            self.upstreams.replace(b"BACKEND_UPSTREAM", b"UNRELATED_UPSTREAM"),
            self.upstreams + b"upstream BACKEND_UPSTREAM { server 172.18.0.10:8000; }\n",
            self.upstreams.replace(b"    keepalive 32;", b"    server 172.18.0.10:8000;\n    keepalive 32;"),
        )
        for data in cases:
            with self.subTest(data=data), self.assertRaises(self.module.PauseFailure):
                self.module.patch_backend_upstream(data, "172.18.0.27")

    def test_upstream_patch_rejects_invalid_address(self):
        for address in ("172.18.0.999", "hostname.invalid", "172.18.0.27; server 127.0.0.1:8000", ""):
            with self.subTest(address=address), self.assertRaises((self.module.PauseFailure, ValueError)):
                self.module.patch_backend_upstream(self.upstreams, address)

    def test_fingerprint_tracks_bytes_realpath_and_mode(self):
        target = self.root / "real.conf"
        target.write_bytes(self.upstreams)
        target.chmod(0o640)
        link = self.root / "enabled.conf"
        link.symlink_to(target)
        value = self.module.fingerprint(link)
        self.assertEqual(value["sha256"], hashlib.sha256(self.upstreams).hexdigest())
        self.assertEqual(value["realpath"], str(target))
        self.assertEqual(value["mode"], 0o640)

    def test_atomic_install_is_private_and_never_overwrites_existing_file(self):
        target = self.root / "pause.json"
        self.module.atomic_install(target, b"reviewed")
        self.assertEqual(target.read_bytes(), b"reviewed")
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        with self.assertRaises((self.module.PauseFailure, FileExistsError)):
            self.module.atomic_install(target, b"replacement")
        self.assertEqual(target.read_bytes(), b"reviewed")

    def test_atomic_install_never_follows_or_replaces_concurrent_symlink(self):
        target = self.root / "pause.json"
        unrelated = self.root / "unrelated.json"
        unrelated.write_bytes(b"unrelated")
        original_link = self.module.os.link

        def create_before_publish(source, destination, *args, **kwargs):
            Path(destination).symlink_to(unrelated)
            return original_link(source, destination, *args, **kwargs)

        with mock.patch.object(self.module.os, "link", side_effect=create_before_publish):
            with self.assertRaises((self.module.PauseFailure, FileExistsError)):
                self.module.atomic_install(target, b"reviewed")
        self.assertTrue(target.is_symlink())
        self.assertEqual(unrelated.read_bytes(), b"unrelated")

    def test_atomic_replace_uses_expected_content_cas_and_private_mode(self):
        target = self.root / "upstreams.conf"
        target.write_bytes(b"before")
        expected = hashlib.sha256(b"before").hexdigest()
        self.module.atomic_replace(target, b"after", expected)
        self.assertEqual(target.read_bytes(), b"after")
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        with self.assertRaises(self.module.PauseFailure):
            self.module.atomic_replace(target, b"overwrite", expected)
        self.assertEqual(target.read_bytes(), b"after")

    def host_fixture(self):
        module = self.module
        (self.root / "compose").mkdir()
        site_real = self.root / "site-real.conf"
        site_real.write_bytes(b"server { include analytics-paused.conf; }\n")
        site = self.root / "site-enabled.conf"
        site.symlink_to(site_real)
        snippet = self.root / "analytics-paused.conf"
        snippet.write_bytes(b'return 200 \'{"measurement_id":""}\';\n')
        upstreams = self.root / "upstreams.conf"
        upstreams.write_bytes(self.upstreams)
        paths = module.Paths(root=self.root, site=site, snippet=snippet, upstreams=upstreams)
        for path in paths.inputs():
            if not path.exists():
                path.write_text("fixture-only configuration\n")
                path.chmod(0o600)
        for name, value in (("SITE_SHA", hashlib.sha256(site.read_bytes()).hexdigest()), ("SNIPPET_SHA", hashlib.sha256(snippet.read_bytes()).hexdigest())):
            patch = mock.patch.object(module, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        owner = self

        class FakeHost(module.Host):
            def __init__(self):
                super().__init__(paths)
                self.calls = []
                self.switches = []
                self.schema_value = module.SCHEMA
                self.main_pid = 2952584
                self.fail_switch = False
                self.fail_direct_pause = False
                self.concurrent_upstream_after_refresh = False
                self.runtime = {
                    service: {"id": "original-" + service, "image": owner.before_config["services"][service]["image"], "source": "e" * 40,
                              "started_at": "2026-10-19T00:00:00Z", "status": "running",
                              "config_hash": hashlib.sha256(json.dumps(owner.before_config["services"][service], sort_keys=True).encode()).hexdigest(),
                              "config_files": str(paths.root / "compose/docker-compose.yml") + "," + str(paths.root / "compose/docker-compose.override.yml")}
                    for service in module.SERVICES
                }
                self.metadata = {
                    owner.image: {"id": "sha256:" + "1" * 64, "digests": [owner.image], "source": owner.revision, "component": "backend", "os": "linux", "architecture": "amd64"},
                    owner.old_image: {"id": "sha256:" + "2" * 64, "digests": [owner.old_image], "source": "e" * 40, "component": "backend", "os": "linux", "architecture": "amd64"},
                }

            def command(self, args, input_text=None):
                self.calls.append(list(args))
                if args == ["systemctl", "show", "nginx", "--property=MainPID", "--value"]:
                    return str(self.main_pid)
                if args in (["nginx", "-t"], ["systemctl", "reload", "nginx"]):
                    return ""
                suffix = ["up", "-d", "--no-deps", "--no-build", "--pull", "never", "backend"]
                owner.assertEqual(args[:len(self.prefix())], self.prefix())
                owner.assertEqual(args[len(self.prefix()):len(self.prefix()) + 1], ["-f"])
                owner.assertEqual(args[len(self.prefix()) + 2:], suffix)
                override = Path(args[len(self.prefix()) + 1])
                self.switches.append(override)
                if self.fail_switch:
                    self.fail_switch = False
                    raise module.PauseFailure("synthetic command failure with private value")
                image = override.read_text().split("    image: ", 1)[1].strip()
                backend = self.runtime["backend"]
                backend.update(id="installed-" + str(len(self.switches)), image=image,
                               source=self.metadata[image]["source"], started_at="2026-10-20T01:00:00Z",
                               status="running",
                               config_hash=self.compose_hash(override.read_text()),
                               config_files=backend["config_files"].split("," + str(override))[0] + "," + str(override))
                return ""

            def containers(self):
                return copy.deepcopy(self.runtime)

            def schema(self):
                module.require(self.schema_value == module.SCHEMA, "Schema drift")
                return self.schema_value

            def image_info(self, image):
                return copy.deepcopy(self.metadata[image])

            def compose_config(self, override_text=None):
                value = copy.deepcopy(owner.before_config)
                if override_text is not None:
                    value["services"]["backend"]["image"] = override_text.split("    image: ", 1)[1].strip()
                return value

            def compose_hash(self, override_text=None):
                backend = self.compose_config(override_text)["services"]["backend"]
                return hashlib.sha256(json.dumps(backend, sort_keys=True).encode()).hexdigest()

            def backend_ip(self):
                return "172.18.0.27" if self.runtime["backend"]["image"] == owner.image else "172.18.0.8"

            def http_checks(self, expect_empty):
                if self.fail_direct_pause and expect_empty:
                    self.fail_direct_pause = False
                    raise module.PauseFailure("synthetic direct pause check failure")
                return {"fixture": "pause" if expect_empty else "rollback"}

            def refresh_upstream(self, expected_fingerprint, new_ip):
                value = super().refresh_upstream(expected_fingerprint, new_ip)
                if self.concurrent_upstream_after_refresh:
                    self.concurrent_upstream_after_refresh = False
                    self.paths.upstreams.write_bytes(self.paths.upstreams.read_bytes() + b"# concurrent operator edit\n")
                return value

        return FakeHost()

    def test_plan_is_readonly_and_binds_runtime_and_both_image_metadata(self):
        host = self.host_fixture()
        before = host.state()
        result = self.module.make_plan(host, self.image, self.revision)
        self.assertEqual(result["before"], before)
        self.assertEqual(result["candidate_metadata"], host.metadata[self.image])
        self.assertEqual(result["rollback_metadata"], host.metadata[self.old_image])
        self.assertEqual(host.state(), before)
        self.assertEqual(host.switches, [])
        self.assertFalse((self.root / "release").exists())

    def test_plan_rejects_guard_schema_source_or_runtime_drift(self):
        host = self.host_fixture()
        scenarios = (
            lambda: host.metadata[self.image].update(source="f" * 40),
            lambda: host.runtime["frontend"].update(status="exited"),
            lambda: host.runtime["backend"].update(config_files=host.runtime["backend"]["config_files"] + ",/unreviewed/runtime-override.yml"),
            lambda: setattr(host, "schema_value", "20261018_0131"),
            lambda: host.paths.snippet.write_bytes(b"concurrent guard change"),
        )
        for index, change in enumerate(scenarios):
            prior_runtime = copy.deepcopy(host.runtime)
            prior_metadata = copy.deepcopy(host.metadata)
            prior_snippet = host.paths.snippet.read_bytes()
            change()
            with self.subTest(index=index), self.assertRaises(self.module.PauseFailure):
                self.module.make_plan(host, self.image, self.revision)
            host.runtime = prior_runtime
            host.metadata = prior_metadata
            host.schema_value = self.module.SCHEMA
            host.paths.snippet.write_bytes(prior_snippet)
        self.assertEqual(host.switches, [])

    def test_plan_rejects_concurrent_change_during_compose_inspection(self):
        host = self.host_fixture()
        original = host.compose_config

        def change_during_compose(override_text=None):
            result = original(override_text)
            if override_text is not None:
                host.paths.root.joinpath(".release.env").write_bytes(b"concurrent environment\n")
            return result

        with mock.patch.object(host, "compose_config", side_effect=change_during_compose):
            with self.assertRaisesRegex(self.module.PauseFailure, "Runtime changed"):
                self.module.make_plan(host, self.image, self.revision)
        self.assertEqual(host.switches, [])

    def test_switch_command_targets_backend_only_and_never_builds_or_pulls(self):
        host = self.module.Host(self.module.Paths(root=self.root))
        override = self.root / "backend-only.override.yml"
        with mock.patch.object(host, "command", return_value="") as command:
            host.switch(override)
        command.assert_called_once_with([
            "docker", "compose", "--project-name", "compose", "--project-directory", str(self.root / "compose"),
            "--env-file", str(self.root / ".env"), "--env-file", str(self.root / ".release.env"),
            "-f", str(self.root / "compose/docker-compose.yml"), "-f", str(self.root / "compose/docker-compose.override.yml"),
            "-f", str(override), "up", "-d", "--no-deps", "--no-build", "--pull", "never", "backend",
        ])

    def test_schema_probe_is_readonly_without_application_import_or_dsn_output(self):
        host = self.module.Host()
        with mock.patch.object(host, "command", return_value=json.dumps([self.module.SCHEMA])) as command:
            self.assertEqual(host.schema(), self.module.SCHEMA)
        args, program = command.call_args.args
        self.assertEqual(args, ["docker", "exec", "-i", "compose-seo-publication-worker-1", "python", "-"])
        self.assertIn("default_transaction_read_only=on", program)
        self.assertIn("statement_timeout=5000", program)
        self.assertIn("c.rollback();c.close()", program)
        self.assertNotIn("settings", program)
        with mock.patch.object(host, "command", return_value=json.dumps(["20261018_0131"])):
            with self.assertRaises(self.module.PauseFailure):
                host.schema()

    def test_local_image_inspection_rejects_wrong_digest_component_or_source(self):
        host = self.module.Host()
        valid = {"id": "sha256:" + "1" * 64, "digests": [self.image.removeprefix("docker.io/")], "source": self.revision, "component": "backend", "os": "linux", "architecture": "amd64"}
        for field, value in (("digests", []), ("component", "frontend"), ("source", "not-a-revision"), ("architecture", "arm64"), ("os", "windows")):
            changed = {**valid, field: value}
            with self.subTest(field=field), mock.patch.object(host, "command", return_value=json.dumps(changed)) as command:
                with self.assertRaises(self.module.PauseFailure):
                    host.image_info(self.image)
                self.assertEqual(command.call_args.args[0][:3], ["docker", "image", "inspect"])
        with mock.patch.object(host, "command", return_value=json.dumps(valid)):
            self.assertEqual(host.image_info(self.image), valid)

    def test_apply_changes_only_backend_and_upstream_with_private_review_artifacts(self):
        host = self.host_fixture()
        plan = self.module.make_plan(host, self.image, self.revision)
        directory = self.root / "release"
        result = self.module.apply(host, plan, directory)
        self.assertEqual(result["status"], "applied")
        self.assertEqual(len(host.switches), 1)
        self.assertEqual(host.runtime["backend"]["image"], self.image)
        self.assertEqual(result["after"]["schema"], plan["before"]["schema"])
        for service in self.module.SERVICES[1:]:
            self.assertEqual(result["after"]["containers"][service], plan["before"]["containers"][service])
        self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
        for name in ("reviewed-plan.json", "upstreams.before", "backend-only.override.yml", "receipt.json"):
            self.assertEqual(stat.S_IMODE((directory / name).stat().st_mode), 0o600)
        self.assertEqual((directory / "upstreams.before").read_bytes(), self.upstreams)
        self.assertEqual(host.paths.upstreams.read_bytes(), self.upstreams.replace(b"172.18.0.8", b"172.18.0.27", 1))

    def test_apply_rechecks_prepared_state_before_any_service_mutation(self):
        host = self.host_fixture()
        plan = self.module.make_plan(host, self.image, self.revision)
        original_install = self.module.atomic_install

        def concurrent_after_prepare(path, data, *args, **kwargs):
            original_install(path, data, *args, **kwargs)
            if Path(path).name == "backend-only.override.yml":
                host.paths.root.joinpath(".env").write_bytes(b"concurrent operator environment\n")

        with mock.patch.object(self.module, "atomic_install", side_effect=concurrent_after_prepare):
            with self.assertRaises(self.module.PauseFailure):
                self.module.apply(host, plan, self.root / "release")
        self.assertEqual(host.switches, [])
        self.assertEqual(host.paths.root.joinpath(".env").read_bytes(), b"concurrent operator environment\n")

    def test_apply_failure_before_container_change_retains_original_and_private_error(self):
        host = self.host_fixture()
        plan = self.module.make_plan(host, self.image, self.revision)
        host.fail_switch = True
        directory = self.root / "release"
        with self.assertRaisesRegex(self.module.PauseFailure, "failed_original_runtime_retained"):
            self.module.apply(host, plan, directory)
        receipt_text = (directory / "receipt.json").read_text()
        self.assertEqual(json.loads(receipt_text)["status"], "failed_original_runtime_retained")
        self.assertNotIn("private value", receipt_text)
        self.assertEqual(host.runtime["backend"]["image"], self.old_image)
        self.assertEqual(len(host.switches), 1)

    def test_direct_pause_failure_rolls_back_owned_backend_only(self):
        host = self.host_fixture()
        plan = self.module.make_plan(host, self.image, self.revision)
        host.fail_direct_pause = True
        directory = self.root / "release"
        with self.assertRaisesRegex(self.module.PauseFailure, "failed_rolled_back"):
            self.module.apply(host, plan, directory)
        receipt = json.loads((directory / "receipt.json").read_text())
        self.assertEqual(receipt["status"], "failed_rolled_back")
        self.assertEqual(host.runtime["backend"]["image"], self.old_image)
        self.assertEqual(host.paths.upstreams.read_bytes(), self.upstreams)
        self.assertEqual(len(host.switches), 2)

    def test_explicit_rollback_rejects_runtime_or_override_ownership_drift(self):
        host = self.host_fixture()
        plan = self.module.make_plan(host, self.image, self.revision)
        directory = self.root / "release"
        receipt = self.module.apply(host, plan, directory)
        host.runtime["frontend"]["started_at"] = "concurrent restart"
        with self.assertRaises(self.module.PauseFailure):
            self.module.rollback(host, receipt, directory)
        self.assertEqual(len(host.switches), 1)
        host.runtime["frontend"] = copy.deepcopy(plan["before"]["containers"]["frontend"])
        (directory / "backend-only.override.yml").write_text("concurrent unrelated override\n")
        with self.assertRaises(self.module.PauseFailure):
            self.module.rollback(host, receipt, directory)
        self.assertEqual((directory / "backend-only.override.yml").read_text(), "concurrent unrelated override\n")
        self.assertEqual(len(host.switches), 1)

    def test_explicit_rollback_restores_backend_image_and_preserves_other_services(self):
        host = self.host_fixture()
        plan = self.module.make_plan(host, self.image, self.revision)
        directory = self.root / "release"
        receipt = self.module.apply(host, plan, directory)
        result = self.module.rollback(host, receipt, directory)
        self.assertEqual(result["status"], "rolled_back")
        self.assertEqual(host.runtime["backend"]["image"], self.old_image)
        self.assertEqual(host.paths.upstreams.read_bytes(), self.upstreams)
        self.assertEqual(len(host.switches), 2)
        for service in self.module.SERVICES[1:]:
            self.assertEqual(host.runtime[service], plan["before"]["containers"][service])

    def test_upstream_parser_does_not_accept_commented_configuration(self):
        for data in (b"# upstream BACKEND_UPSTREAM { server 172.18.0.8:8000; }\n", self.upstreams + b"# upstream BACKEND_UPSTREAM { server 172.18.0.99:8000; }\n"):
            with self.subTest(data=data):
                if data.startswith(b"# upstream"):
                    with self.assertRaises(self.module.PauseFailure):
                        self.module.patch_backend_upstream(data, "172.18.0.27")
                else:
                    self.assertEqual(self.module.patch_backend_upstream(data, "172.18.0.27"), data.replace(b"172.18.0.8", b"172.18.0.27", 1))

    def test_apply_stops_if_upstream_changes_after_refresh_without_overwriting_operator_edit(self):
        host = self.host_fixture()
        plan = self.module.make_plan(host, self.image, self.revision)
        host.concurrent_upstream_after_refresh = True
        directory = self.root / "release"
        with self.assertRaises(self.module.PauseFailure):
            self.module.apply(host, plan, directory)
        self.assertTrue(host.paths.upstreams.read_bytes().endswith(b"# concurrent operator edit\n"))
        self.assertEqual(len(host.switches), 1)

    def test_direct_backend_checks_require_empty_id_no_store_and_json_on_both_paths(self):
        host = self.module.Host()
        response = {
            "/healthz": {"status": 200, "body": {"status": "ok"}},
            "/readyz": {"status": 200, "body": {"checks": {"schema": "head"}}},
        }
        for path in ("/api/v1/public/analytics-config", "/api/v1/public/analytics-config?pause_check=1"):
            response[path] = {"status": 200, "body": {"measurement_id": ""}, "cache_control": "no-store", "content_type": "application/json; charset=utf-8"}
        with mock.patch.object(host, "command", return_value=json.dumps(response)):
            self.assertEqual(host.http_checks(True), response)
        for path, field, value in (
            ("/api/v1/public/analytics-config", "body", {"measurement_id": "G-NOT-PAUSED"}),
            ("/api/v1/public/analytics-config?pause_check=1", "cache_control", "public"),
            ("/api/v1/public/analytics-config?pause_check=1", "content_type", "text/html"),
        ):
            changed = copy.deepcopy(response)
            changed[path][field] = value
            with self.subTest(path=path, field=field), mock.patch.object(host, "command", return_value=json.dumps(changed)):
                with self.assertRaises(self.module.PauseFailure):
                    host.http_checks(True)

    def test_invalid_upstream_candidate_restores_original_without_reload(self):
        host = self.host_fixture()
        before = self.module.fingerprint(host.paths.upstreams)
        original_command = host.command

        def reject_nginx(args, input_text=None):
            if args == ["nginx", "-t"]:
                host.calls.append(list(args))
                raise self.module.PauseFailure("synthetic invalid upstream")
            return original_command(args, input_text)

        with mock.patch.object(host, "command", side_effect=reject_nginx):
            with self.assertRaises(self.module.PauseFailure):
                host.refresh_upstream(before, "172.18.0.27")
        self.assertEqual(host.paths.upstreams.read_bytes(), self.upstreams)
        self.assertEqual(self.module.fingerprint(host.paths.upstreams), before)
        self.assertNotIn(["systemctl", "reload", "nginx"], host.calls)

    def test_atomic_replace_rechecks_content_after_temporary_file_preparation(self):
        target = self.root / "upstreams.conf"
        target.write_bytes(b"before")
        expected = hashlib.sha256(b"before").hexdigest()
        original_mkstemp = self.module.tempfile.mkstemp

        def concurrent_during_prepare(*args, **kwargs):
            result = original_mkstemp(*args, **kwargs)
            target.write_bytes(b"concurrent operator bytes")
            return result

        with mock.patch.object(self.module.tempfile, "mkstemp", side_effect=concurrent_during_prepare):
            with self.assertRaises(self.module.PauseFailure):
                self.module.atomic_replace(target, b"candidate", expected)
        self.assertEqual(target.read_bytes(), b"concurrent operator bytes")
        self.assertEqual(list(self.root.glob(".upstreams.conf.*")), [])

    def test_command_failure_never_exposes_stdout_or_stderr(self):
        host = self.module.Host()
        result = SimpleNamespace(returncode=1, stdout="private stdout sentinel", stderr="private stderr sentinel")
        with mock.patch.object(self.module.subprocess, "run", return_value=result) as command:
            with self.assertRaises(self.module.PauseFailure) as raised:
                host.command(["docker", "image", "inspect", "fixture-only"])
        self.assertNotIn("sentinel", str(raised.exception))
        self.assertEqual(command.call_args.kwargs["timeout"], 90)
        self.assertTrue(command.call_args.kwargs["capture_output"])

    def test_crashed_candidate_can_use_independent_schema_probe_and_roll_back(self):
        host = self.host_fixture()
        plan = self.module.make_plan(host, self.image, self.revision)
        original_switch = host.switch
        original_schema = host.schema
        schema_backend_statuses = []

        def crash_candidate(override):
            original_switch(override)
            if host.runtime["backend"]["image"] == self.image:
                host.runtime["backend"]["status"] = "exited"

        def independent_schema():
            schema_backend_statuses.append(host.runtime["backend"]["status"])
            return original_schema()

        host.fail_direct_pause = True
        directory = self.root / "release"
        with mock.patch.object(host, "switch", side_effect=crash_candidate), mock.patch.object(host, "schema", side_effect=independent_schema):
            with self.assertRaisesRegex(self.module.PauseFailure, "failed_rolled_back"):
                self.module.apply(host, plan, directory)
        self.assertIn("exited", schema_backend_statuses)
        self.assertEqual(host.runtime["backend"]["image"], self.old_image)
        self.assertEqual(host.runtime["backend"]["status"], "running")
        self.assertEqual(host.paths.upstreams.read_bytes(), self.upstreams)
        self.assertEqual(len(host.switches), 2)
        for service in self.module.SERVICES[1:]:
            self.assertEqual(host.runtime[service], plan["before"]["containers"][service])

    def test_receipt_updates_bind_previous_hash_and_preserve_concurrent_edit(self):
        helper_directory = self.root / "receipt-helper"
        helper_directory.mkdir()
        first = {"status": "prepared"}
        first_hash = self.module.write_receipt(helper_directory, first)
        receipt_path = helper_directory / "receipt.json"
        self.assertEqual(first_hash, hashlib.sha256(receipt_path.read_bytes()).hexdigest())
        with self.assertRaises((self.module.PauseFailure, FileExistsError)):
            self.module.write_receipt(helper_directory, {"status": "unowned"})
        self.assertEqual(json.loads(receipt_path.read_text()), first)
        second_hash = self.module.write_receipt(helper_directory, {"status": "applied"}, first_hash)
        self.assertEqual(second_hash, hashlib.sha256(receipt_path.read_bytes()).hexdigest())

        host = self.host_fixture()
        plan = self.module.make_plan(host, self.image, self.revision)
        directory = self.root / "release"
        original_checks = host.http_checks
        concurrent = b'{"status":"operator-owned concurrent receipt"}\n'

        def edit_receipt_during_verification(expect_empty):
            result = original_checks(expect_empty)
            (directory / "receipt.json").write_bytes(concurrent)
            return result

        with mock.patch.object(host, "http_checks", side_effect=edit_receipt_during_verification):
            with self.assertRaises(self.module.PauseFailure):
                self.module.apply(host, plan, directory)
        self.assertEqual((directory / "receipt.json").read_bytes(), concurrent)
        self.assertEqual(len(host.switches), 1)

    def test_rollback_override_cas_binds_reviewed_bytes_before_concurrent_read_window(self):
        host = self.host_fixture()
        plan = self.module.make_plan(host, self.image, self.revision)
        directory = self.root / "release"
        receipt = self.module.apply(host, plan, directory)
        override = directory / "backend-only.override.yml"
        reviewed = self.module.override_text(self.image).encode()
        concurrent = b"operator-owned override arriving after ownership read\n"
        original_read = Path.read_bytes
        changed = False

        def change_after_ownership_read(path):
            nonlocal changed
            data = original_read(path)
            if path == override and data == reviewed and not changed:
                changed = True
                path.write_bytes(concurrent)
            return data

        with mock.patch.object(Path, "read_bytes", change_after_ownership_read):
            with self.assertRaises(self.module.PauseFailure):
                self.module.rollback(host, receipt, directory)
        self.assertTrue(changed)
        self.assertEqual(override.read_bytes(), concurrent)
        self.assertEqual(host.runtime["backend"]["image"], self.image)
        self.assertEqual(len(host.switches), 1)

    def test_upstream_reload_failure_restores_and_reloads_reviewed_original_bytes(self):
        host = self.host_fixture()
        before = self.module.fingerprint(host.paths.upstreams)
        original_command = host.command
        reload_failed = False
        tested_bytes = []

        def fail_first_reload(args, input_text=None):
            nonlocal reload_failed
            if args == ["nginx", "-t"]:
                tested_bytes.append(host.paths.upstreams.read_bytes())
            if args == ["systemctl", "reload", "nginx"] and not reload_failed:
                host.calls.append(list(args))
                reload_failed = True
                raise self.module.PauseFailure("synthetic candidate reload failure")
            return original_command(args, input_text)

        with mock.patch.object(host, "command", side_effect=fail_first_reload):
            with self.assertRaises(self.module.PauseFailure):
                host.refresh_upstream(before, "172.18.0.27")
        self.assertEqual(tested_bytes, [self.upstreams.replace(b"172.18.0.8", b"172.18.0.27", 1), self.upstreams])
        self.assertEqual(host.paths.upstreams.read_bytes(), self.upstreams)
        self.assertEqual(self.module.fingerprint(host.paths.upstreams), before)
        self.assertEqual(host.calls, [["nginx", "-t"], ["systemctl", "reload", "nginx"], ["nginx", "-t"], ["systemctl", "reload", "nginx"]])

    def test_apply_cli_requires_callers_exact_plan_hash_before_parsing_or_flow(self):
        plan_path = self.root / "reviewed-plan.json"
        plan_bytes = b'{ "schema_version": 1, "image": "fixture-reviewed-image" }\n'
        plan_path.write_bytes(plan_bytes)
        directory = self.root / "release"
        base_args = ["--apply", "--plan-file", str(plan_path), "--release-dir", str(directory)]
        with mock.patch.object(self.module, "apply", return_value={"status": "fixture-applied"}) as apply_flow, mock.patch.object(self.module, "rollback") as rollback_flow:
            for hash_args in ([], ["--expected-plan-sha256", "0" * 64]):
                output = io.StringIO()
                with self.subTest(hash_args=hash_args), contextlib.redirect_stdout(output), mock.patch.object(self.module.json, "loads", side_effect=AssertionError("Unapproved plan must not be parsed")):
                    self.assertEqual(self.module.main(base_args + hash_args), 1)
                self.assertEqual(json.loads(output.getvalue())["status"], "stopped")
                apply_flow.assert_not_called()
                rollback_flow.assert_not_called()
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = self.module.main(base_args + ["--expected-plan-sha256", hashlib.sha256(plan_bytes).hexdigest()])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue()), {"status": "fixture-applied"})
            apply_flow.assert_called_once_with(mock.ANY, json.loads(plan_bytes), directory)
            self.assertIsInstance(apply_flow.call_args.args[0], self.module.Host)
            rollback_flow.assert_not_called()

    def test_rollback_cli_requires_callers_exact_receipt_hash_before_parsing_or_flow(self):
        receipt_path = self.root / "reviewed-receipt.json"
        receipt_bytes = b'{ "status": "applied", "release_dir": "fixture-release" }\n'
        receipt_path.write_bytes(receipt_bytes)
        directory = self.root / "release"
        base_args = ["--rollback", "--receipt-file", str(receipt_path), "--release-dir", str(directory)]
        with mock.patch.object(self.module, "rollback", return_value={"status": "fixture-rolled-back"}) as rollback_flow, mock.patch.object(self.module, "apply") as apply_flow:
            for hash_args in ([], ["--expected-receipt-sha256", "0" * 64]):
                output = io.StringIO()
                with self.subTest(hash_args=hash_args), contextlib.redirect_stdout(output), mock.patch.object(self.module.json, "loads", side_effect=AssertionError("Unapproved receipt must not be parsed")):
                    self.assertEqual(self.module.main(base_args + hash_args), 1)
                self.assertEqual(json.loads(output.getvalue())["status"], "stopped")
                rollback_flow.assert_not_called()
                apply_flow.assert_not_called()
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = self.module.main(base_args + ["--expected-receipt-sha256", hashlib.sha256(receipt_bytes).hexdigest()])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue()), {"status": "fixture-rolled-back"})
            rollback_flow.assert_called_once_with(mock.ANY, json.loads(receipt_bytes), directory)
            self.assertIsInstance(rollback_flow.call_args.args[0], self.module.Host)
            apply_flow.assert_not_called()

    def test_native_compose_hash_uses_exact_backend_command_and_rejects_ambiguous_output(self):
        host = self.module.Host(self.module.Paths(root=self.root))
        expected = "a" * 64
        override = self.module.override_text(self.image)
        with mock.patch.object(host, "command", return_value="backend " + expected + "\n") as command:
            self.assertEqual(host.compose_hash(), expected)
            self.assertEqual(host.compose_hash(override), expected)
        self.assertEqual(command.call_args_list, [
            mock.call(host.prefix() + ["config", "--hash", "backend"], None),
            mock.call(host.prefix() + ["-f", "-", "config", "--hash", "backend"], override),
        ])
        for output in (expected, "frontend " + expected, "backend " + "A" * 64, "backend " + expected + "\nbackend " + "b" * 64, ""):
            with self.subTest(output=output), mock.patch.object(host, "command", return_value=output):
                with self.assertRaises(self.module.PauseFailure):
                    host.compose_hash()

    def test_plan_rejects_current_environment_model_drift_from_running_native_hash(self):
        host = self.host_fixture()
        running_hash = host.runtime["backend"]["config_hash"]
        self.before_config["services"]["backend"]["environment"]["DEFAULT_TEXT_MODEL"] = "new-model-on-disk"
        host.paths.root.joinpath(".env").write_text("DEFAULT_TEXT_MODEL=new-model-on-disk\n")
        self.assertNotEqual(host.compose_hash(), running_hash)
        with self.assertRaisesRegex(self.module.PauseFailure, "Base Compose differs from running backend config hash"):
            self.module.make_plan(host, self.image, self.revision)
        self.assertEqual(host.runtime["backend"]["config_hash"], running_hash)
        self.assertEqual(host.switches, [])
        self.assertFalse((self.root / "release").exists())

    def test_candidate_wrong_native_hash_cannot_succeed_and_owned_backend_rolls_back(self):
        host = self.host_fixture()
        plan = self.module.make_plan(host, self.image, self.revision)
        self.assertEqual(plan["compose_native_base_hash"], host.runtime["backend"]["config_hash"])
        self.assertEqual(plan["compose_native_candidate_hash"], host.compose_hash(self.module.override_text(self.image)))
        original_switch = host.switch

        def wrong_candidate_hash(override):
            original_switch(override)
            if host.runtime["backend"]["image"] == self.image:
                host.runtime["backend"]["config_hash"] = "f" * 64

        directory = self.root / "release"
        with mock.patch.object(host, "switch", side_effect=wrong_candidate_hash):
            with self.assertRaisesRegex(self.module.PauseFailure, "failed_rolled_back"):
                self.module.apply(host, plan, directory)
        self.assertEqual(json.loads((directory / "receipt.json").read_text())["status"], "failed_rolled_back")
        self.assertEqual(host.runtime["backend"]["image"], self.old_image)
        self.assertEqual(host.runtime["backend"]["config_hash"], plan["compose_native_base_hash"])
        self.assertEqual(len(host.switches), 2)
        for service in self.module.SERVICES[1:]:
            self.assertEqual(host.runtime[service], plan["before"]["containers"][service])

    def test_rollback_wrong_base_native_hash_cannot_record_success(self):
        host = self.host_fixture()
        plan = self.module.make_plan(host, self.image, self.revision)
        directory = self.root / "release"
        receipt = self.module.apply(host, plan, directory)
        stored_receipt = (directory / "receipt.json").read_bytes()
        original_switch = host.switch

        def wrong_rollback_hash(override):
            original_switch(override)
            if host.runtime["backend"]["image"] == self.old_image:
                host.runtime["backend"]["config_hash"] = "f" * 64

        with mock.patch.object(host, "switch", side_effect=wrong_rollback_hash):
            with self.assertRaisesRegex(self.module.PauseFailure, "Rollback container native config hash mismatch"):
                self.module.rollback(host, receipt, directory)
        self.assertEqual((directory / "receipt.json").read_bytes(), stored_receipt)
        self.assertEqual(host.runtime["backend"]["image"], self.old_image)
        self.assertNotEqual(host.runtime["backend"]["config_hash"], plan["compose_native_base_hash"])
        self.assertEqual(len(host.switches), 2)
        for service in self.module.SERVICES[1:]:
            self.assertEqual(host.runtime[service], plan["before"]["containers"][service])


if __name__ == "__main__":
    unittest.main()
