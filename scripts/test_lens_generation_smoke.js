const assert = require("assert");
const path = require("path");

const smoke = require("./lens-generation-smoke-playwright.js");

function testParseArgsDefaultsToQuickMode() {
  const args = smoke.parseArgs([]);
  const plan = smoke.buildScenarioPlan(args);

  assert.strictEqual(args.mode, "quick");
  assert.ok(plan.includes("studio.audio.text_to_speech"));
  assert.ok(plan.includes("studio.image.text_to_image"));
  assert.ok(plan.includes("studio.speech.upload_mp4"));
  assert.ok(plan.includes("agents.prompt_reverse.generate_prompt"));
  assert.ok(plan.includes("agents.prompt_reverse.jump_to_studio_video"));
  assert.ok(plan.includes("agents.film.url_error"));
  assert.ok(plan.includes("chat.lightweight"));
  assert.ok(!plan.includes("studio.video.text_to_video"));
}

function testFullModeIncludesLongGenerationScenarios() {
  const args = smoke.parseArgs(["--full"]);
  const plan = smoke.buildScenarioPlan(args);

  assert.strictEqual(args.mode, "full");
  assert.ok(plan.includes("studio.video.text_to_video"));
  assert.ok(plan.includes("agents.preroll.generate"));
  assert.ok(plan.includes("agents.viral_fission.generate"));
  assert.ok(plan.includes("agents.film.upload_analysis"));
}

function testSpecificScenarioFlagsOverrideMode() {
  const args = smoke.parseArgs(["--check-studio-video"]);
  const plan = smoke.buildScenarioPlan(args);

  assert.deepStrictEqual(plan, ["studio.video.text_to_video"]);
}

function testScreenshotNameIsStableAndSafe() {
  const name = smoke.screenshotName("Studio 生视频", 3, "result success");

  assert.strictEqual(name, "studio-video-03-result-success.png");
}

function testMediaValidationRejectsFakeSuccess() {
  const image = smoke.validateImageAsset({ naturalWidth: 0, naturalHeight: 0, byteSize: 9000, error: null });
  const audio = smoke.validateTimedMedia({ duration: 0, readyState: 4, error: null });
  const video = smoke.validateTimedMedia({ duration: 8, readyState: 4, error: null, videoWidth: 1920, videoHeight: 1080 }, { expectedAspectRatio: 16 / 9 });
  const squashed = smoke.validateTimedMedia({ duration: 8, readyState: 4, error: null, videoWidth: 1080, videoHeight: 1920 }, { expectedAspectRatio: 16 / 9 });

  assert.strictEqual(image.ok, false);
  assert.match(image.reason, /natural size/);
  assert.strictEqual(audio.ok, false);
  assert.match(audio.reason, /duration/);
  assert.strictEqual(video.ok, true);
  assert.strictEqual(squashed.ok, false);
  assert.match(squashed.reason, /aspect ratio/);
}

function testTextValidationNeedsMeaningfulContent() {
  assert.strictEqual(smoke.validateTextResult("短", { minLength: 50 }).ok, false);
  assert.strictEqual(smoke.validateTextResult("这是一个足够长的反推提示词内容，用来证明不是空字符串，也不是错误提示。".repeat(2), { minLength: 50 }).ok, true);
}

function testClassifyTaskStateSeparatesFailureTimeoutAndRunning() {
  assert.strictEqual(smoke.classifyTaskState("completed"), "pass");
  assert.strictEqual(smoke.classifyTaskState("failed"), "fail");
  assert.strictEqual(smoke.classifyTaskState("running"), "running");
  assert.strictEqual(smoke.classifyTaskState(""), "running");
  assert.strictEqual(smoke.classifyTaskState("timeout"), "timeout");
}

function testExplicitErrorDetectionIgnoresHistoryLegend() {
  assert.strictEqual(smoke.containsExplicitError("Recent Generations Running Completed Failed"), false);
  assert.strictEqual(smoke.containsExplicitError("Generation Failed Error code: 400"), true);
  assert.strictEqual(smoke.containsExplicitError("Tool Error: OpenAI Responses API failed (429)"), true);
}

function testActiveTaskDetectionCatchesRunningPlaceholders() {
  assert.strictEqual(smoke.containsActiveTaskMarker("Task is running. The reverse prompt will appear here when ready."), true);
  assert.strictEqual(smoke.containsActiveTaskMarker("Waiting for rendering..."), true);
  assert.strictEqual(smoke.containsActiveTaskMarker("Final completed result is ready"), false);
}

function testRenderReportIncludesScreenshotsAndSummary() {
  const result = {
    id: "studio.audio.text_to_speech",
    name: "Studio 文本生音频",
    status: "pass",
    duration_s: 12.4,
    detail: "audio generated",
    screenshots: [path.join("screenshots", "studio-audio-01-input.png")],
    evidence: { audio_ready: true },
  };
  const report = smoke.renderMarkdownReport([result], { title: "LensRhyme 生成能力测试报告" });

  assert.match(report, /LensRhyme 生成能力测试报告/);
  assert.match(report, /Studio 文本生音频/);
  assert.match(report, /12.4s/);
  assert.match(report, /!\[studio-audio-01-input.png\]/);
}

function run() {
  const tests = [
    testParseArgsDefaultsToQuickMode,
    testFullModeIncludesLongGenerationScenarios,
    testSpecificScenarioFlagsOverrideMode,
    testScreenshotNameIsStableAndSafe,
    testMediaValidationRejectsFakeSuccess,
    testTextValidationNeedsMeaningfulContent,
    testClassifyTaskStateSeparatesFailureTimeoutAndRunning,
    testExplicitErrorDetectionIgnoresHistoryLegend,
    testActiveTaskDetectionCatchesRunningPlaceholders,
    testRenderReportIncludesScreenshotsAndSummary,
  ];

  for (const test of tests) {
    test();
    console.log(`ok ${test.name}`);
  }
}

run();
