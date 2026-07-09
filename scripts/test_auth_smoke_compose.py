from __future__ import annotations

import importlib.util
import os
import unittest
from unittest import mock
from pathlib import Path


def load_module():
    path = Path(__file__).with_name("auth-smoke-compose.py")
    spec = importlib.util.spec_from_file_location("auth_smoke_compose", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AuthSmokeComposeTests(unittest.TestCase):
    def test_join_url_normalizes_slashes(self) -> None:
        module = load_module()

        self.assertEqual(
            module.join_url("http://127.0.0.1:5410/", "/api/v1/auth/login"),
            "http://127.0.0.1:5410/api/v1/auth/login",
        )

    def test_http_error_message_includes_method_status_and_body(self) -> None:
        module = load_module()

        err = module.HttpError("GET", "http://127.0.0.1:5410/api/v1/admin/users", 403, "forbidden")

        self.assertIn("GET", str(err))
        self.assertIn("403", str(err))
        self.assertIn("forbidden", str(err))

    def test_passwords_default_to_empty_and_can_come_from_env(self) -> None:
        module = load_module()

        with mock.patch.dict(os.environ, {}, clear=True):
            args = module.build_parser().parse_args([])
            self.assertEqual(args.admin_password, "")
            self.assertEqual(args.user_password, "")

        with mock.patch.dict(
            os.environ,
            {
                "SMOKE_TEST_ADMIN_PASSWORD": "admin-from-env",
                "SMOKE_TEST_USER_PASSWORD": "user-from-env",
            },
            clear=True,
        ):
            args = module.build_parser().parse_args([])
            self.assertEqual(args.admin_password, "admin-from-env")
            self.assertEqual(args.user_password, "user-from-env")


if __name__ == "__main__":
    unittest.main()
