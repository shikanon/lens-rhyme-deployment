from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


def load_module():
    path = Path(__file__).with_name("lens-feature-report.py")
    spec = importlib.util.spec_from_file_location("lens_feature_report", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class LensFeatureReportTests(unittest.TestCase):
    def test_redact_sensitive_values_masks_tokens_passwords_and_keys(self) -> None:
        module = load_module()

        text = (
            "password=secret123&access_token=abc.def "
            "Authorization: Bearer live-token OPENAI_API_KEY=sk-real "
            "https://example.com/a.mp4?X-Tos-Credential=ak-value&X-Tos-Signature=sig-value"
        )

        redacted = module.redact_sensitive_values(text)

        self.assertNotIn("secret123", redacted)
        self.assertNotIn("abc.def", redacted)
        self.assertNotIn("live-token", redacted)
        self.assertNotIn("sk-real", redacted)
        self.assertNotIn("ak-value", redacted)
        self.assertNotIn("sig-value", redacted)
        self.assertIn("password=<redacted>", redacted)
        self.assertIn("access_token=<redacted>", redacted)
        self.assertIn("Bearer <redacted>", redacted)
        self.assertIn("OPENAI_API_KEY=<redacted>", redacted)
        self.assertIn("X-Tos-Credential=<redacted>", redacted)
        self.assertIn("X-Tos-Signature=<redacted>", redacted)

    def test_metric_summary_reports_average_max_and_success_rate(self) -> None:
        module = load_module()
        results = [
            module.ScenarioResult("agents.video_clone", "pass", 10.0),
            module.ScenarioResult("agents.video_clone", "fail", 20.0),
            module.ScenarioResult("agents.video_clone", "pass", 30.0),
        ]

        summary = module.summarize_results(results)["agents.video_clone"]

        self.assertEqual(summary["runs"], 3)
        self.assertEqual(summary["passed"], 2)
        self.assertEqual(summary["failed"], 1)
        self.assertAlmostEqual(summary["success_rate"], 2 / 3)
        self.assertAlmostEqual(summary["avg_duration_s"], 20.0)
        self.assertAlmostEqual(summary["max_duration_s"], 30.0)
        self.assertEqual(summary["reproduction_probability"], "33.3%")

    def test_metric_summary_treats_warnings_as_issue_probability(self) -> None:
        module = load_module()
        results = [
            module.ScenarioResult("agents.preroll", "warn", 15.0),
            module.ScenarioResult("agents.preroll", "pass", 10.0),
        ]

        summary = module.summarize_results(results)["agents.preroll"]

        self.assertEqual(summary["warned"], 1)
        self.assertEqual(summary["reproduction_probability"], "50.0%")

    def test_jump_target_validation_checks_url_and_dom_markers(self) -> None:
        module = load_module()

        ok = module.validate_jump_target(
            actual_url="http://site/video-generation?source=prompt",
            expected_path="/video-generation",
            dom_text="Video generation prompt storyboard",
            required_markers=["video generation", "prompt"],
        )
        wrong = module.validate_jump_target(
            actual_url="http://site/studio",
            expected_path="/video-generation",
            dom_text="Text to speech Audio studio",
            required_markers=["video generation"],
        )

        self.assertTrue(ok["url_matches"])
        self.assertTrue(ok["dom_matches"])
        self.assertEqual(ok["status"], "pass")
        self.assertFalse(wrong["url_matches"])
        self.assertFalse(wrong["dom_matches"])
        self.assertEqual(wrong["status"], "fail")

    def test_video_element_summary_detects_black_or_unplayable_video(self) -> None:
        module = load_module()
        videos = [
            {"src": "", "poster": "", "readyState": 0, "error": None},
            {"src": "https://cdn.example/video.mp4", "poster": "", "readyState": 0, "error": {"code": 4}},
            {"src": "https://cdn.example/ok.mp4", "poster": "https://cdn.example/ok.jpg", "readyState": 3, "error": None},
        ]

        summary = module.summarize_video_elements(videos)

        self.assertEqual(summary["video_count"], 3)
        self.assertEqual(summary["missing_source_or_poster"], 1)
        self.assertEqual(summary["unplayable"], 2)
        self.assertEqual(summary["playable"], 1)

    def test_markdown_report_includes_impact_and_probability_fields(self) -> None:
        module = load_module()
        result = module.ScenarioResult(
            "studio.speech_recognition",
            "fail",
            42.5,
            detail="upload accepted but generation failed",
            impact_scope="AI创作室-录音识别用户",
        )

        report = module.render_markdown_report([result])

        self.assertIn("问题复现概率", report)
        self.assertIn("警告", report)
        self.assertIn("影响范围", report)
        self.assertIn("AI创作室-录音识别用户", report)
        self.assertIn("42.5s", report)


if __name__ == "__main__":
    unittest.main()
