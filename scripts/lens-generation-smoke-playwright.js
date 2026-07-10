#!/usr/bin/env node
/* eslint-disable no-console */

const fs = require("fs");
const path = require("path");

const QUICK_SCENARIOS = [
  "preflight.routes",
  "studio.audio.text_to_speech",
  "studio.image.text_to_image",
  "studio.speech.upload_mp4",
  "agents.prompt_reverse.generate_prompt",
  "agents.prompt_reverse.jump_to_studio_video",
  "agents.film.url_error",
  "chat.lightweight",
];

const FULL_ONLY_SCENARIOS = [
  "studio.video.text_to_video",
  "agents.preroll.generate",
  "agents.viral_fission.generate",
  "agents.film.upload_analysis",
  "studio.speech.browser_recording_support",
];

const SCENARIO_FLAGS = [
  ["--check-studio-audio", "studio.audio.text_to_speech"],
  ["--check-studio-image", "studio.image.text_to_image"],
  ["--check-studio-video", "studio.video.text_to_video"],
  ["--check-studio-speech-upload", "studio.speech.upload_mp4"],
  ["--check-studio-browser-recording", "studio.speech.browser_recording_support"],
  ["--check-agent-prompt-reverse", "agents.prompt_reverse.generate_prompt"],
  ["--check-agent-prompt-reverse-jump", "agents.prompt_reverse.jump_to_studio_video"],
  ["--check-agent-film-url", "agents.film.url_error"],
  ["--check-agent-film-upload", "agents.film.upload_analysis"],
  ["--check-agent-preroll", "agents.preroll.generate"],
  ["--check-agent-video-replication", "agents.viral_fission.generate"],
  ["--check-chat", "chat.lightweight"],
];

const CHINESE_SLUGS = [
  ["生视频", "video"],
  ["生音频", "audio"],
  ["生图", "image"],
  ["录音识别", "speech-recognition"],
  ["视频提示词反推", "prompt-reverse"],
  ["广告前贴", "preroll"],
  ["视频复刻", "viral-fission"],
  ["AI拉片", "film-analysis"],
  ["拉片", "film-analysis"],
];

function parseArgs(argv) {
  const args = {
    baseUrl: process.env.LENS_SMOKE_BASE_URL || process.env.SMOKE_TEST_BASE_URL || "http://127.0.0.1:5410",
    username: process.env.SMOKE_TEST_USER_USERNAME || process.env.TEST_USER_USERNAME || "test_user",
    password: process.env.SMOKE_TEST_USER_PASSWORD || process.env.TEST_USER_PASSWORD || "",
    chromePath: process.env.LENS_SMOKE_CHROME_PATH || "",
    videoPath: process.env.LENS_SMOKE_VIDEO_PATH || "",
    audioPath: process.env.LENS_SMOKE_AUDIO_PATH || "",
    outputDir: process.env.LENS_GENERATION_OUTPUT_DIR || "",
    headless: process.env.LENS_SMOKE_HEADLESS === "1",
    mode: "quick",
    scenarios: [],
    pollIntervalMs: Number(process.env.LENS_SMOKE_POLL_INTERVAL_MS || 10000),
    quickTimeoutMs: Number(process.env.LENS_SMOKE_QUICK_TIMEOUT_MS || 90000),
    longTimeoutMs: Number(process.env.LENS_SMOKE_LONG_TIMEOUT_MS || 1200000),
    help: false,
  };

  const explicitScenarios = [];
  for (let index = 0; index < argv.length; index += 1) {
    const key = argv[index];
    const value = argv[index + 1];
    const scenarioFlag = SCENARIO_FLAGS.find(([flag]) => flag === key);
    if (scenarioFlag) {
      explicitScenarios.push(scenarioFlag[1]);
      continue;
    }
    if (key === "--base-url") args.baseUrl = value, index += 1;
    else if (key === "--username") args.username = value, index += 1;
    else if (key === "--password") args.password = value, index += 1;
    else if (key === "--chrome-path") args.chromePath = value, index += 1;
    else if (key === "--video-path") args.videoPath = value, index += 1;
    else if (key === "--audio-path") args.audioPath = value, index += 1;
    else if (key === "--output-dir") args.outputDir = value, index += 1;
    else if (key === "--poll-interval-ms") args.pollIntervalMs = Number(value), index += 1;
    else if (key === "--quick-timeout-ms") args.quickTimeoutMs = Number(value), index += 1;
    else if (key === "--long-timeout-ms") args.longTimeoutMs = Number(value), index += 1;
    else if (key === "--headless") args.headless = true;
    else if (key === "--quick") args.mode = "quick";
    else if (key === "--full") args.mode = "full";
    else if (key === "--help") args.help = true;
  }
  if (explicitScenarios.length > 0) args.scenarios = explicitScenarios;
  return args;
}

function buildScenarioPlan(args) {
  if (args.scenarios.length > 0) return Array.from(new Set(args.scenarios));
  if (args.mode === "full") return [...QUICK_SCENARIOS, ...FULL_ONLY_SCENARIOS];
  return QUICK_SCENARIOS;
}

function printHelp() {
  console.log(`Usage: node scripts/lens-generation-smoke-playwright.js [options]

Modes:
  --quick                         Run short generation checks. Default.
  --full                          Include long video/Agent generation checks.

Common options:
  --base-url URL                  LensRhyme main-site URL.
  --username NAME                 Test username. Defaults to SMOKE_TEST_USER_USERNAME.
  --password VALUE                Test password. Prefer SMOKE_TEST_USER_PASSWORD.
  --chrome-path PATH              Local Chrome/Edge executable.
  --video-path PATH               Public/non-sensitive sample mp4.
  --audio-path PATH               Public/non-sensitive sample audio.
  --output-dir PATH               Report directory.
  --headless                      Run without a visible browser.

Single-scenario flags:
  --check-studio-audio
  --check-studio-image
  --check-studio-video
  --check-studio-speech-upload
  --check-studio-browser-recording
  --check-agent-prompt-reverse
  --check-agent-prompt-reverse-jump
  --check-agent-film-url
  --check-agent-film-upload
  --check-agent-preroll
  --check-agent-video-replication
  --check-chat
`);
}

function slugify(value) {
  let text = String(value || "").trim().toLowerCase();
  for (const [source, target] of CHINESE_SLUGS) text = text.replaceAll(source.toLowerCase(), target);
  text = text
    .replace(/studio/g, "studio")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return text || "screenshot";
}

function screenshotName(featureName, sequence, status) {
  return `${slugify(featureName)}-${String(sequence).padStart(2, "0")}-${slugify(status)}.png`;
}

function validateImageAsset(image, options = {}) {
  const minBytes = options.minBytes || 10000;
  if (image.error) return { ok: false, reason: `image error: ${image.error}` };
  if (Number(image.naturalWidth || 0) <= 0 || Number(image.naturalHeight || 0) <= 0) {
    return { ok: false, reason: "image natural size is empty" };
  }
  if (image.byteSize != null && Number(image.byteSize) < minBytes) {
    return { ok: false, reason: `image byte size ${image.byteSize} is below ${minBytes}` };
  }
  return { ok: true, reason: "image loaded" };
}

function validateTimedMedia(media, options = {}) {
  if (media.error) return { ok: false, reason: `media error: ${JSON.stringify(media.error)}` };
  if (Number(media.duration || 0) <= 0) return { ok: false, reason: "media duration is empty" };
  if (Number(media.readyState || 0) < 2) return { ok: false, reason: "media readyState is below HAVE_CURRENT_DATA" };
  if (options.expectedAspectRatio && media.videoWidth && media.videoHeight) {
    const actual = Number(media.videoWidth) / Number(media.videoHeight);
    const delta = Math.abs(actual - options.expectedAspectRatio) / options.expectedAspectRatio;
    if (delta > (options.aspectTolerance || 0.1)) {
      return { ok: false, reason: `media aspect ratio ${actual.toFixed(3)} differs from expected ${options.expectedAspectRatio.toFixed(3)}` };
    }
  }
  return { ok: true, reason: "media loaded" };
}

function findNewUsableMedia(beforeMedia, afterMedia, validator, options = {}) {
  const existingSources = new Set((beforeMedia || []).map((media) => String(media.src || "")).filter(Boolean));
  return (afterMedia || []).find((media) => {
    const source = String(media.src || "");
    return source && !existingSources.has(source) && validator(media, options).ok;
  }) || null;
}

function validateTextResult(text, options = {}) {
  const minLength = options.minLength || 50;
  const normalized = String(text || "").trim();
  if (normalized.length < minLength) return { ok: false, reason: `text length ${normalized.length} is below ${minLength}` };
  if (/error|failed|失败|报错|timeout/i.test(normalized)) return { ok: false, reason: "text contains an error marker" };
  return { ok: true, reason: "text is meaningful" };
}

function classifyTaskState(status) {
  const value = String(status || "").trim().toLowerCase();
  if (["completed", "complete", "success", "succeeded", "done"].includes(value)) return "pass";
  if (["failed", "failure", "error", "canceled", "cancelled", "aborted"].includes(value)) return "fail";
  if (["timeout", "timed_out", "timed-out"].includes(value)) return "timeout";
  return "running";
}

function containsExplicitError(text) {
  return /Tool Error|insufficient_quota|Error code\s*:|Bad Gateway|Workflow:\s*failed|Generation Failed|生成失败|任务失败|Timeout while/i.test(String(text || ""));
}

function hasNewExplicitError(currentText, previousText) {
  const current = String(currentText || "");
  if (!containsExplicitError(current)) return false;
  const previous = String(previousText || "");
  if (!previous) return true;
  if (current.startsWith(previous)) return containsExplicitError(current.slice(previous.length));
  if (current.includes(previous)) return containsExplicitError(current.replace(previous, ""));
  return false;
}

function hasNewMeaningfulTextResult(currentText, previousText, options = {}) {
  const current = String(currentText || "").trim();
  const previous = String(previousText || "").trim();
  if (!current || current === previous || containsExplicitError(current) || containsActiveTaskMarker(current)) return false;
  const delta = current.includes(previous) ? current.replace(previous, "").trim() : current;
  return validateTextResult(delta, options).ok;
}

function containsActiveTaskMarker(text) {
  return /Task is running|Waiting for rendering|Waiting for generated result|Workflow:\s*generating|Thinking\.\.\.|Reversing|Prompting|Creating|Submitting|Uploading(?: audio)?|上传中|识别中|提交中|生成中|运行中/i.test(String(text || ""));
}

function hasSpeechRecognitionResult(text) {
  const normalized = String(text || "").trim();
  if (!normalized || containsExplicitError(normalized) || containsActiveTaskMarker(normalized)) return false;
  return /(?:recognition\s+result|transcript(?:ion)?|识别结果|识别文本|转写结果)\s*[:：-]?\s*[\s\S]{12,}/i.test(normalized);
}

function redactSensitiveText(text) {
  return String(text || "")
    .replace(/\b([A-Z0-9_-]*(?:password|token|secret|api[_-]?key|credential|signature))(\s*[:=]\s*)([^\s&,'"]+)/gi, "$1$2<redacted>")
    .replace(/\b(bearer)(\s+)([A-Za-z0-9._~+/=-]{8,})/gi, "$1 <redacted>");
}

function redactValue(value) {
  if (Array.isArray(value)) return value.map(redactValue);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => {
      if (/password|token|secret|api[_-]?key|credential|signature|authorization/i.test(key)) return [key, "<redacted>"];
      return [key, redactValue(item)];
    }));
  }
  if (typeof value === "string") return redactSensitiveText(value);
  return value;
}

function statusLabel(status) {
  return {
    pass: "通过",
    warn: "警告",
    fail: "失败",
    timeout: "超时",
    skip: "跳过",
    running: "运行中",
  }[status] || status;
}

function renderMarkdownReport(results, options = {}) {
  const title = options.title || "LensRhyme 生成能力自动化测试报告";
  const safeResults = results.map(redactValue);
  const counts = safeResults.reduce((memo, result) => {
    memo[result.status] = (memo[result.status] || 0) + 1;
    return memo;
  }, {});
  const lines = [
    `# ${title}`,
    "",
    "## 总览",
    "",
    `- 通过：${counts.pass || 0}`,
    `- 警告：${counts.warn || 0}`,
    `- 失败：${counts.fail || 0}`,
    `- 超时：${counts.timeout || 0}`,
    `- 跳过：${counts.skip || 0}`,
    "",
    "## 明细",
    "",
  ];
  for (const result of safeResults) {
    lines.push(`### ${result.name || result.id}`);
    lines.push("");
    lines.push(`- 状态：${statusLabel(result.status)}`);
    lines.push(`- 耗时：${Number(result.duration_s || 0).toFixed(1)}s`);
    if (result.detail) lines.push(`- 说明：${redactSensitiveText(result.detail)}`);
    if (result.evidence) lines.push(`- 证据：\`${JSON.stringify(redactValue(result.evidence), null, 0)}\``);
    if (result.screenshots && result.screenshots.length) {
      lines.push("");
      lines.push("截图：");
      for (const screenshot of result.screenshots) {
        const name = path.basename(screenshot);
        lines.push(`![${name}](${screenshot.replaceAll("\\", "/")})`);
      }
    }
    lines.push("");
  }
  return `${lines.join("\n").trim()}\n`;
}

function joinUrl(baseUrl, route) {
  return `${baseUrl.replace(/\/$/, "")}/${route.replace(/^\//, "")}`;
}

function isLoginUrl(url) {
  return new URL(String(url)).pathname === "/login";
}

function ensureOutputDirs(outputDir) {
  fs.mkdirSync(outputDir, { recursive: true });
  const screenshotsDir = path.join(outputDir, "screenshots");
  fs.mkdirSync(screenshotsDir, { recursive: true });
  return { screenshotsDir };
}

function makeResult(id, name, started, status, detail, extra = {}) {
  return {
    id,
    name,
    status,
    duration_s: (Date.now() - started) / 1000,
    detail,
    screenshots: extra.screenshots || [],
    evidence: extra.evidence || {},
  };
}

async function safeSnapshot(page) {
  return page.evaluate(() => ({
    url: location.href,
    title: document.title,
    text: (document.body?.innerText || "").slice(0, 8000),
    images: Array.from(document.querySelectorAll("img")).map((img) => ({
      src: img.currentSrc || img.src || "",
      naturalWidth: img.naturalWidth,
      naturalHeight: img.naturalHeight,
      complete: img.complete,
    })),
    audios: Array.from(document.querySelectorAll("audio")).map((audio) => ({
      src: audio.currentSrc || audio.src || "",
      readyState: audio.readyState,
      duration: Number.isFinite(audio.duration) ? audio.duration : 0,
      error: audio.error ? { code: audio.error.code, message: audio.error.message } : null,
    })),
    videos: Array.from(document.querySelectorAll("video")).map((video) => ({
      src: video.currentSrc || video.src || "",
      poster: video.poster || "",
      readyState: video.readyState,
      duration: Number.isFinite(video.duration) ? video.duration : 0,
      videoWidth: video.videoWidth || 0,
      videoHeight: video.videoHeight || 0,
      error: video.error ? { code: video.error.code, message: video.error.message } : null,
    })),
    textareas: Array.from(document.querySelectorAll("textarea")).map((textarea) => ({
      value: textarea.value || "",
      placeholder: textarea.getAttribute("placeholder") || "",
    })),
    fileInputs: Array.from(document.querySelectorAll("input[type=file]")).map((input) => ({
      accept: input.getAttribute("accept") || "",
    })),
  }));
}

async function screenshot(page, ctx, featureName, status) {
  ctx.screenshotIndex += 1;
  const filename = screenshotName(featureName, ctx.screenshotIndex, status);
  const absolute = path.join(ctx.screenshotsDir, filename);
  await page.screenshot({ path: absolute, fullPage: true });
  return path.relative(ctx.outputDir, absolute);
}

async function clickButtonByNames(page, names, options = {}) {
  for (const name of names) {
    const locator = page.getByRole("button", { name, exact: true });
    if (await locator.count() === 1) {
      try {
        if (await locator.isVisible()) {
          await locator.click({ timeout: options.timeout || 10000 });
          return true;
        }
      } catch (error) {
        // Try the next locator strategy.
      }
    }
  }
  for (const name of names) {
    const locator = page.getByText(name, { exact: false });
    const count = await locator.count();
    if (count > 0) {
      const matches = await locator.all();
      for (const match of matches.slice(0, 5)) {
        try {
          if (await match.isVisible()) {
            await match.click({ timeout: options.timeout || 10000 });
            return true;
          }
        } catch (error) {
          // Keep looking for a visible clickable match.
        }
      }
    }
  }
  return false;
}

async function fillFirstTextArea(page, value) {
  const textareas = page.locator("textarea");
  if (await textareas.count() === 0) return false;
  await textareas.first().fill(value);
  return true;
}

async function waitForOutcome(page, options) {
  const timeoutMs = options.timeoutMs;
  const pollIntervalMs = options.pollIntervalMs || 10000;
  const started = Date.now();
  let lastSnapshot = await safeSnapshot(page);
  const baselineText = options.baselineText == null ? lastSnapshot.text : options.baselineText;
  while (Date.now() - started < timeoutMs) {
    lastSnapshot = await safeSnapshot(page);
    const text = lastSnapshot.text;
    if (hasNewExplicitError(text, baselineText)) {
      return { state: "fail", snapshot: lastSnapshot, reason: "page contains an explicit error marker" };
    }
    const custom = options.check ? options.check(lastSnapshot) : null;
    if (custom?.state) return { ...custom, snapshot: lastSnapshot };
    await page.waitForTimeout(pollIntervalMs);
  }
  return { state: "timeout", snapshot: lastSnapshot, reason: `no terminal state within ${timeoutMs}ms` };
}

async function login(page, args) {
  if (!args.password) throw new Error("missing password: set SMOKE_TEST_USER_PASSWORD or pass --password");
  await page.goto(joinUrl(args.baseUrl, "/login"), { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.getByPlaceholder("Username", { exact: true }).fill(args.username);
  await page.getByPlaceholder("Password", { exact: true }).fill(args.password);
  await Promise.all([
    page.waitForURL((url) => !isLoginUrl(url), { timeout: 30000 }).catch(() => {}),
    page.getByRole("button", { name: "Log In", exact: true }).click({ timeout: 10000 }),
  ]);
  await page.waitForTimeout(3000);
  if (isLoginUrl(page.url())) {
    throw new Error("login did not complete; verify the main-site test account configuration");
  }
}

async function runPreflight(page, args, ctx) {
  const started = Date.now();
  const screenshots = [];
  const failures = [];
  for (const route of ["/chat", "/agents", "/studio", "/workbench"]) {
    await page.goto(joinUrl(args.baseUrl, route), { waitUntil: "domcontentloaded", timeout: 60000 });
    await page.waitForTimeout(1000);
    const snap = await safeSnapshot(page);
    if (!snap.text.includes("LensRhyme")) failures.push(route);
  }
  screenshots.push(await screenshot(page, ctx, "preflight-routes", failures.length ? "fail" : "success"));
  return makeResult(
    "preflight.routes",
    "基础页面访问检查",
    started,
    failures.length ? "fail" : "pass",
    failures.length ? `routes failed: ${failures.join(", ")}` : "Chat, Agents, Studio, Workbench routes rendered",
    { screenshots, evidence: { failures } },
  );
}

async function openStudioTab(page, args, tabName) {
  await page.goto(joinUrl(args.baseUrl, "/studio"), { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForTimeout(2000);
  await clickButtonByNames(page, [tabName]);
  await page.waitForTimeout(1500);
}

async function runStudioAudio(page, args, ctx) {
  const started = Date.now();
  const screenshots = [];
  await openStudioTab(page, args, "Audio");
  await clickButtonByNames(page, ["Text to Speech"]);
  await fillFirstTextArea(page, "LensRhyme 自动化测试：请生成一段很短的中文语音。");
  screenshots.push(await screenshot(page, ctx, "studio-audio", "input"));
  const before = await safeSnapshot(page);
  await clickButtonByNames(page, ["Generate Audio", "生成音频", "Start Generation"]);
  screenshots.push(await screenshot(page, ctx, "studio-audio", "submitted"));
  const outcome = await waitForOutcome(page, {
    timeoutMs: args.quickTimeoutMs,
    pollIntervalMs: args.pollIntervalMs,
    baselineText: before.text,
    check: (snap) => {
      const usable = findNewUsableMedia(before.audios, snap.audios, validateTimedMedia);
      if (usable) return { state: "pass", reason: "audio element is playable", media: usable };
      return null;
    },
  });
  screenshots.push(await screenshot(page, ctx, "studio-audio", outcome.state));
  return makeResult(
    "studio.audio.text_to_speech",
    "Studio 文本生音频",
    started,
    outcome.state === "pass" ? "pass" : outcome.state,
    outcome.reason,
    { screenshots, evidence: { audio_count: outcome.snapshot.audios.length } },
  );
}

async function runStudioImage(page, args, ctx) {
  const started = Date.now();
  const screenshots = [];
  await openStudioTab(page, args, "Image");
  await fillFirstTextArea(page, "A clean product photo of a small white cup on a bright desk, high quality");
  screenshots.push(await screenshot(page, ctx, "studio-image", "input"));
  const before = await safeSnapshot(page);
  await clickButtonByNames(page, ["Generate Image", "生成图片", "Start Generation", "Generate"]);
  screenshots.push(await screenshot(page, ctx, "studio-image", "submitted"));
  const outcome = await waitForOutcome(page, {
    timeoutMs: args.quickTimeoutMs,
    pollIntervalMs: args.pollIntervalMs,
    baselineText: before.text,
    check: (snap) => {
      const usable = findNewUsableMedia(before.images, snap.images, validateImageAsset, { minBytes: 0 });
      if (usable) return { state: "pass", reason: "image loaded with natural size", image: usable };
      return null;
    },
  });
  screenshots.push(await screenshot(page, ctx, "studio-image", outcome.state));
  return makeResult(
    "studio.image.text_to_image",
    "Studio 文本生图",
    started,
    outcome.state === "pass" ? "pass" : outcome.state,
    outcome.reason,
    { screenshots, evidence: { image_count: outcome.snapshot.images.length } },
  );
}

async function runStudioVideo(page, args, ctx) {
  const started = Date.now();
  const screenshots = [];
  await openStudioTab(page, args, "Video");
  await fillFirstTextArea(page, "A calm 3 second cinematic shot of a white cup on a desk, soft daylight");
  screenshots.push(await screenshot(page, ctx, "studio-video", "input"));
  const before = await safeSnapshot(page);
  await clickButtonByNames(page, ["Generate Video", "生成视频", "Start Generation"]);
  screenshots.push(await screenshot(page, ctx, "studio-video", "submitted"));
  const outcome = await waitForOutcome(page, {
    timeoutMs: args.longTimeoutMs,
    pollIntervalMs: args.pollIntervalMs,
    baselineText: before.text,
    check: (snap) => {
      const usable = findNewUsableMedia(before.videos, snap.videos, validateTimedMedia);
      if (usable) return { state: "pass", reason: "video element is playable", video: usable };
      return null;
    },
  });
  screenshots.push(await screenshot(page, ctx, "studio-video", outcome.state));
  return makeResult("studio.video.text_to_video", "Studio 文本生视频", started, outcome.state === "pass" ? "pass" : outcome.state, outcome.reason, {
    screenshots,
    evidence: { video_count: outcome.snapshot.videos.length },
  });
}

async function runSpeechUpload(page, args, ctx) {
  const started = Date.now();
  const screenshots = [];
  if (!args.videoPath && !args.audioPath) {
    return makeResult("studio.speech.upload_mp4", "Studio 录音识别上传测试", started, "skip", "missing --video-path or --audio-path");
  }
  await openStudioTab(page, args, "Audio");
  await clickButtonByNames(page, ["Speech Recognition"]);
  const uploadPath = args.audioPath || args.videoPath;
  const input = page.locator("input[type=file]");
  if ((await input.count()) === 0) {
    screenshots.push(await screenshot(page, ctx, "studio-speech-upload", "missing-input"));
    return makeResult("studio.speech.upload_mp4", "Studio 录音识别上传测试", started, "fail", "file input not found", { screenshots });
  }
  await input.first().setInputFiles(uploadPath);
  screenshots.push(await screenshot(page, ctx, "studio-speech-upload", "uploaded"));
  const before = await safeSnapshot(page);
  await clickButtonByNames(page, ["Start Recognition", "Recognize", "Generate", "开始识别", "录音识别"]);
  const outcome = await waitForOutcome(page, {
    timeoutMs: args.quickTimeoutMs,
    pollIntervalMs: args.pollIntervalMs,
    baselineText: before.text,
    check: (snap) => {
      if (hasSpeechRecognitionResult(snap.text)) return { state: "pass", reason: "recognition transcript appears" };
      return null;
    },
  });
  screenshots.push(await screenshot(page, ctx, "studio-speech-upload", outcome.state));
  return makeResult("studio.speech.upload_mp4", "Studio 录音识别上传测试", started, outcome.state === "pass" ? "pass" : outcome.state, outcome.reason, {
    screenshots,
    evidence: { upload_file: path.basename(uploadPath) },
  });
}

async function runPromptReverse(page, args, ctx) {
  const started = Date.now();
  const screenshots = [];
  if (!args.videoPath) return makeResult("agents.prompt_reverse.generate_prompt", "视频提示词反推", started, "skip", "missing --video-path");
  await page.goto(joinUrl(args.baseUrl, "/agents/video-prompt-reverse"), { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForTimeout(2000);
  const input = page.locator("input[type=file]");
  if ((await input.count()) > 0) await input.first().setInputFiles(args.videoPath);
  screenshots.push(await screenshot(page, ctx, "prompt-reverse", "uploaded"));
  const before = await safeSnapshot(page);
  await clickButtonByNames(page, ["Reverse prompt", "反推提示词"]);
  const outcome = await waitForOutcome(page, {
    timeoutMs: args.quickTimeoutMs,
    pollIntervalMs: args.pollIntervalMs,
    baselineText: before.text,
    check: (snap) => {
      if (/Use for video generation|用于视频生成|Structured breakdown|Observed summary/i.test(snap.text)) {
        if (hasNewMeaningfulTextResult(snap.text, before.text, { minLength: 120 })) {
          return { state: "pass", reason: "new reverse prompt text appears" };
        }
      }
      return null;
    },
  });
  screenshots.push(await screenshot(page, ctx, "prompt-reverse", outcome.state));
  return makeResult("agents.prompt_reverse.generate_prompt", "视频提示词反推", started, outcome.state === "pass" ? "pass" : outcome.state, outcome.reason, {
    screenshots,
    evidence: { video_file: path.basename(args.videoPath) },
  });
}

async function runPromptReverseJump(page, args, ctx) {
  const started = Date.now();
  const screenshots = [];
  await page.goto(joinUrl(args.baseUrl, "/agents/video-prompt-reverse"), { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForTimeout(2000);
  screenshots.push(await screenshot(page, ctx, "prompt-reverse-jump", "before"));
  let clicked = await clickButtonByNames(page, ["Use for video generation", "用于视频生成"]);
  if (!clicked && args.videoPath) {
    const input = page.locator("input[type=file]");
    if ((await input.count()) > 0) await input.first().setInputFiles(args.videoPath);
    await clickButtonByNames(page, ["Reverse prompt", "反推提示词"]);
    await waitForOutcome(page, {
      timeoutMs: args.quickTimeoutMs,
      pollIntervalMs: args.pollIntervalMs,
      check: (snap) => {
        if (/Use for video generation|用于视频生成|Structured breakdown|Observed summary/i.test(snap.text)) {
          if (containsActiveTaskMarker(snap.text)) return null;
          const valid = validateTextResult(snap.text, { minLength: 120 });
          if (valid.ok) return { state: "pass", reason: "reverse prompt text appears before jump" };
        }
        return null;
      },
    });
    screenshots.push(await screenshot(page, ctx, "prompt-reverse-jump", "generated"));
    clicked = await clickButtonByNames(page, ["Use for video generation", "用于视频生成"]);
  }
  if (clicked) await page.waitForTimeout(4000);
  const snap = await safeSnapshot(page);
  const isVideoStudio = snap.url.includes("/studio") && snap.text.includes("Generate Video") && snap.text.includes("doubao-seedance");
  const hasPrompt = snap.textareas.some((textarea) => textarea.value.trim().length >= 50);
  const parsedUrl = new URL(snap.url);
  screenshots.push(await screenshot(page, ctx, "prompt-reverse-jump", isVideoStudio && hasPrompt ? "success" : "warn"));
  return makeResult(
    "agents.prompt_reverse.jump_to_studio_video",
    "反推提示词跳转到视频生成",
    started,
    isVideoStudio && hasPrompt ? "pass" : "warn",
    clicked ? "checked Studio Video tab and prompt autofill after jump" : "Use for video generation button not found; run prompt generation first",
    { screenshots, evidence: { clicked, is_video_studio: isVideoStudio, prompt_autofilled: hasPrompt, path: parsedUrl.pathname, has_agent_video_prompt_query: parsedUrl.searchParams.has("agent_video_prompt") } },
  );
}

async function runFilmUrl(page, args, ctx) {
  const started = Date.now();
  const screenshots = [];
  await page.goto(joinUrl(args.baseUrl, "/agent/film/new"), { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForTimeout(2000);
  const testUrl = "https://samplelib.com/lib/preview/mp4/sample-5s.mp4";
  const textInput = page.locator("input:not([type=file]), textarea");
  if ((await textInput.count()) > 0) await textInput.first().fill(testUrl);
  screenshots.push(await screenshot(page, ctx, "film-url", "input"));
  const before = await safeSnapshot(page);
  await clickButtonByNames(page, ["开始拉片", "Start", "Analyze"]);
  const outcome = await waitForOutcome(page, {
    timeoutMs: Math.min(args.quickTimeoutMs, 60000),
    pollIntervalMs: args.pollIntervalMs,
    baselineText: before.text,
    check: (snap) => {
      if (/进行中\s*1|Running/i.test(snap.text)) return { state: "warn", reason: "film URL task appears accepted but not completed in quick check" };
      return null;
    },
  });
  screenshots.push(await screenshot(page, ctx, "film-url", outcome.state));
  return makeResult("agents.film.url_error", "AI 拉片 URL 方式", started, outcome.state, outcome.reason, { screenshots, evidence: { test_url: testUrl } });
}

async function runChat(page, args, ctx) {
  const started = Date.now();
  const screenshots = [];
  await page.goto(joinUrl(args.baseUrl, "/chat"), { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForTimeout(2000);
  await fillFirstTextArea(page, "hello");
  screenshots.push(await screenshot(page, ctx, "chat-lightweight", "input"));
  const textarea = page.locator("textarea");
  const before = await safeSnapshot(page);
  if ((await textarea.count()) > 0) await textarea.first().press("Enter");
  const outcome = await waitForOutcome(page, {
    timeoutMs: Math.min(args.quickTimeoutMs, 30000),
    pollIntervalMs: 5000,
    baselineText: before.text,
    check: (snap) => {
      const grew = snap.text.length > before.text.length + 30;
      const thinking = containsActiveTaskMarker(snap.text);
      if (snap.text.includes("hello") && grew && !thinking && !containsExplicitError(snap.text)) {
        return { state: "pass", reason: "chat returned non-error text after the submitted prompt" };
      }
      return null;
    },
  });
  screenshots.push(await screenshot(page, ctx, "chat-lightweight", outcome.state));
  return makeResult("chat.lightweight", "Chat 轻量回归", started, outcome.state, outcome.reason, { screenshots });
}

async function runGenericLongAgent(page, args, ctx, id, name, route, buttonNames, timeoutMs) {
  const started = Date.now();
  const screenshots = [];
  if (!args.videoPath) return makeResult(id, name, started, "skip", "missing --video-path");
  await page.goto(joinUrl(args.baseUrl, route), { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForTimeout(2000);
  const input = page.locator("input[type=file]");
  if ((await input.count()) > 0) await input.first().setInputFiles(args.videoPath);
  await page.waitForTimeout(2000);
  await fillFirstTextArea(page, "LensRhyme generation smoke test with a short public sample video.");
  screenshots.push(await screenshot(page, ctx, id, "input"));
  const before = await safeSnapshot(page);
  await clickButtonByNames(page, buttonNames);
  screenshots.push(await screenshot(page, ctx, id, "submitted"));
  const outcome = await waitForOutcome(page, {
    timeoutMs,
    pollIntervalMs: args.pollIntervalMs,
    baselineText: before.text,
    check: (snap) => {
      if (containsActiveTaskMarker(snap.text)) return null;
      const video = findNewUsableMedia(before.videos, snap.videos, validateTimedMedia);
      if (video) return { state: "pass", reason: "generated or result video is playable" };
      if (id === "agents.film.upload_analysis" && hasNewMeaningfulTextResult(snap.text, before.text, { minLength: 100 })) {
        return { state: "pass", reason: "new text analysis result appears" };
      }
      return null;
    },
  });
  screenshots.push(await screenshot(page, ctx, id, outcome.state));
  return makeResult(id, name, started, outcome.state, outcome.reason, { screenshots, evidence: { route } });
}

async function runScenario(page, args, ctx, scenario) {
  if (scenario === "preflight.routes") return runPreflight(page, args, ctx);
  if (scenario === "studio.audio.text_to_speech") return runStudioAudio(page, args, ctx);
  if (scenario === "studio.image.text_to_image") return runStudioImage(page, args, ctx);
  if (scenario === "studio.video.text_to_video") return runStudioVideo(page, args, ctx);
  if (scenario === "studio.speech.upload_mp4") return runSpeechUpload(page, args, ctx);
  if (scenario === "studio.speech.browser_recording_support") {
    const started = Date.now();
    return makeResult(scenario, "Studio 浏览器录音支持性检查", started, "skip", "manual permission check; avoid automatically granting microphone permission");
  }
  if (scenario === "agents.prompt_reverse.generate_prompt") return runPromptReverse(page, args, ctx);
  if (scenario === "agents.prompt_reverse.jump_to_studio_video") return runPromptReverseJump(page, args, ctx);
  if (scenario === "agents.film.url_error") return runFilmUrl(page, args, ctx);
  if (scenario === "agents.film.upload_analysis") return runGenericLongAgent(page, args, ctx, scenario, "AI 拉片上传分析", "/agent/film/new", ["开始拉片", "Start", "Analyze"], args.longTimeoutMs);
  if (scenario === "agents.preroll.generate") return runGenericLongAgent(page, args, ctx, scenario, "广告前贴生成", "/agents/preroll-ad", ["Start Generation", "生成", "Generate"], args.longTimeoutMs);
  if (scenario === "agents.viral_fission.generate") return runGenericLongAgent(page, args, ctx, scenario, "视频复刻生成", "/agents/viral-video-fission", ["Start replication", "开始复刻", "Generate"], args.longTimeoutMs);
  if (scenario === "chat.lightweight") return runChat(page, args, ctx);
  return makeResult(scenario, scenario, Date.now(), "skip", "unknown scenario");
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    printHelp();
    return 0;
  }
  const outputDir = path.resolve(args.outputDir || path.join(process.cwd(), "reports", `lens-generation-smoke-${new Date().toISOString().replace(/[:.]/g, "-")}`));
  const { screenshotsDir } = ensureOutputDirs(outputDir);
  const ctx = { outputDir, screenshotsDir, screenshotIndex: 0 };
  const scenarioPlan = buildScenarioPlan(args);

  let chromium;
  try {
    ({ chromium } = require("playwright-core"));
  } catch (error) {
    console.error("Missing dependency: install playwright-core outside this repo or in your CI image.");
    return 1;
  }

  const launchOptions = { headless: args.headless };
  if (args.chromePath) launchOptions.executablePath = args.chromePath;
  const browser = await chromium.launch(launchOptions);
  const page = await browser.newPage({ viewport: { width: 1365, height: 768 } });
  const results = [];
  try {
    await login(page, args);
    for (const scenario of scenarioPlan) {
      console.log(`==> ${scenario}`);
      let result;
      try {
        result = await runScenario(page, args, ctx, scenario);
      } catch (error) {
        let screenshots = [];
        try {
          screenshots = [await screenshot(page, ctx, scenario, "exception")];
        } catch (screenshotError) {
          screenshots = [];
        }
        result = makeResult(
          scenario,
          scenario,
          Date.now(),
          "fail",
          `scenario crashed: ${String(error.message || error).slice(0, 500)}`,
          { screenshots },
        );
      }
      results.push(redactValue(result));
      fs.writeFileSync(path.join(outputDir, "report.json"), JSON.stringify(results, null, 2), "utf8");
      fs.writeFileSync(path.join(outputDir, "report.md"), renderMarkdownReport(results), "utf8");
      await page.goto(joinUrl(args.baseUrl, "/studio"), { waitUntil: "domcontentloaded", timeout: 60000 }).catch(() => {});
      await page.waitForTimeout(1000).catch(() => {});
    }
  } finally {
    await browser.close();
  }

  console.log(`Report: ${path.join(outputDir, "report.md")}`);
  console.log(JSON.stringify(results.map(({ id, status, duration_s }) => ({ id, status, duration_s })), null, 2));
  return results.some((result) => ["fail", "timeout"].includes(result.status)) ? 1 : 0;
}

if (require.main === module) {
  main().then((code) => process.exit(code)).catch((error) => {
    console.error(error);
    process.exit(1);
  });
}

module.exports = {
  parseArgs,
  buildScenarioPlan,
  isLoginUrl,
  screenshotName,
  validateImageAsset,
  validateTimedMedia,
  findNewUsableMedia,
  validateTextResult,
  classifyTaskState,
  containsExplicitError,
  hasNewExplicitError,
  hasNewMeaningfulTextResult,
  containsActiveTaskMarker,
  hasSpeechRecognitionResult,
  renderMarkdownReport,
  redactSensitiveText,
  redactValue,
};
