from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


def load_module():
    path = Path(__file__).with_name("workbench-smoke-compose.py")
    spec = importlib.util.spec_from_file_location("workbench_smoke_compose", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WorkbenchSmokeComposeTests(unittest.TestCase):
    def test_task_state_groups_terminal_and_active_statuses(self) -> None:
        module = load_module()

        self.assertEqual(module.task_state("completed"), "success")
        self.assertEqual(module.task_state("SUCCEEDED"), "success")
        self.assertEqual(module.task_state("failed"), "failure")
        self.assertEqual(module.task_state("canceled"), "failure")
        self.assertEqual(module.task_state("running"), "active")
        self.assertEqual(module.task_state("pending"), "active")

    def test_assert_workbench_route_rejects_error_shell(self) -> None:
        module = load_module()

        with self.assertRaises(module.SmokeFailure):
            module.assert_workbench_route("Application error: a client-side exception has occurred")

    def test_assert_workbench_route_accepts_project_screen(self) -> None:
        module = load_module()

        module.assert_workbench_route("LensRhyme My Projects New Project Workbench")

    def test_parser_defaults_to_strict_terminal_failures(self) -> None:
        module = load_module()

        args = module.build_parser().parse_args([])

        self.assertFalse(args.allow_terminal_failure)

    def test_parser_can_allow_terminal_failures_for_no_stuck_checks(self) -> None:
        module = load_module()

        args = module.build_parser().parse_args(["--allow-terminal-failure"])

        self.assertTrue(args.allow_terminal_failure)


if __name__ == "__main__":
    unittest.main()
