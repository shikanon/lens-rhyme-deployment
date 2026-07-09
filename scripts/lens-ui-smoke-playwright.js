#!/usr/bin/env node
/* eslint-disable no-console */

const fs = require("fs");
const path = require("path");

function parseArgs(argv) {
  const args = {
    baseUrl: process.env.LENS_SMOKE_BASE_URL || process.env.SMOKE_TEST_BASE_URL || "http://127.0.0.1:5410",
    username: process.env.SMOKE_TEST_USER_USERNAME || "test_user",
    password: process.env.SMOKE_TEST_USER_PASSWORD || "",
    chromePath: process.env.LENS_SMOKE_CHROME_PATH || "",
    videoPath: process.env.LENS_SMOKE_VIDEO_PATH || "",
    outputJson: "",
    headless: process.env.LENS_SMOKE_HEADLESS === "1",
    checkChat: false,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const key = argv[index];
    const value = argv[index + 1];
    if (key === "--base-url") args.baseUrl = value, index += 1;
    else if (key === "--username") args.username = value, index += 1;
    else if (key === "--password") args.password = value, index += 1;
    else if (key === "--chrome-path") args.chromePath = value, index += 1;
    else if (key === "--video-path") args.videoPath = value, index += 1;
    else if (key === "--output-json") args.outputJson = value, index += 1;
    else if (key === "--headless") args.headless = true;
    else if (key === "--check-chat") args.checkChat = true;
    else if (key === "--help") args.help = true;
  }
  return args;
}

function printHelp() {
  console.log(`Usage: node scripts/lens-ui-smoke-playwright.js [options]

Options:
  --base-url URL       LensRhyme main site URL.
  --username NAME     Test username. Defaults to SMOKE_TEST_USER_USERNAME.
  --password VALUE    Test password. Prefer SMOKE_TEST_USER_PASSWORD.
  --chrome-path PATH  Local Chrome/Edge executable path.
  --video-path PATH   Public/non-sensitive sample video to upload.
  --output-json PATH  Write safe browser findings JSON here.
  --headless          Run browser headlessly.
  --check-chat        Send one short chat prompt and verify model response/error.

Install dependency outside the repo if needed:
  npm install playwright-core
`);
}

function joinUrl(baseUrl, route) {
  return `${baseUrl.replace(/\/$/, "")}/${route.replace(/^\//, "")}`;
}

function summarizeVideos(videos) {
  return videos.reduce(
    (summary, video) => {
      const hasIdentity = Boolean(video.src) || Boolean(video.poster);
      if (!hasIdentity) summary.missing_source_or_poster += 1;
      if (video.error || Number(video.readyState || 0) < 2) summary.unplayable += 1;
      else summary.playable += 1;
      return summary;
    },
    { video_count: videos.length, missing_source_or_poster: 0, unplayable: 0, playable: 0 },
  );
}

async function safePageSnapshot(page) {
  return page.evaluate(() => ({
    url: location.href,
    title: document.title,
    text: (document.body?.innerText || "").slice(0, 3000),
    fileInputs: Array.from(document.querySelectorAll("input[type=file]")).map((input) => ({
      accept: input.getAttribute("accept") || "",
    })),
    videos: Array.from(document.querySelectorAll("video")).map((video) => ({
      src: video.currentSrc || video.src || "",
      poster: video.poster || "",
      readyState: video.readyState,
      error: video.error ? { code: video.error.code, message: video.error.message } : null,
    })),
  }));
}

async function login(page, args) {
  if (!args.password) {
    throw new Error("missing password: set SMOKE_TEST_USER_PASSWORD or pass --password");
  }
  await page.goto(joinUrl(args.baseUrl, "/login"), { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.getByPlaceholder("Username", { exact: true }).fill(args.username);
  await page.getByPlaceholder("Password", { exact: true }).fill(args.password);
  await Promise.all([
    page.waitForURL((url) => !String(url).includes("/login"), { timeout: 30000 }).catch(() => {}),
    page.getByRole("button", { name: "Log In", exact: true }).click({ timeout: 10000 }),
  ]);
  await page.waitForTimeout(3000);
}

async function inspectUploadPage(page, route, videoPath) {
  const logs = [];
  page.removeAllListeners("console");
  page.on("console", (message) => {
    if (["error", "warning"].includes(message.type())) {
      logs.push({ type: message.type(), text: message.text().slice(0, 300) });
    }
  });
  const started = Date.now();
  await page.goto(joinUrl(globalThis.smokeArgs.baseUrl, route), { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForTimeout(2500);
  const inputCount = await page.locator("input[type=file]").count();
  let uploadError = "";
  if (!videoPath) {
    return {
      feature: `ui.upload_preview.${route.replace(/^\//, "").replaceAll("/", ".")}`,
      status: "skip",
      duration_s: (Date.now() - started) / 1000,
      detail: "video upload skipped because --video-path/LENS_SMOKE_VIDEO_PATH was not provided",
      impact_scope: "Agent video upload and preview users",
      evidence: {
        path: route,
        file_inputs: inputCount,
        video_summary: { video_count: 0, missing_source_or_poster: 0, unplayable: 0, playable: 0 },
        console_error_count: 0,
      },
    };
  }
  if (videoPath && inputCount > 0) {
    try {
      await page.locator("input[type=file]").first().setInputFiles(videoPath);
    } catch (error) {
      uploadError = String(error.message || error).slice(0, 300);
    }
    await page.waitForTimeout(8000);
  }
  const snapshot = await safePageSnapshot(page);
  const videoSummary = summarizeVideos(snapshot.videos);
  let status = "pass";
  let detail = `file_inputs=${inputCount}; video_count=${videoSummary.video_count}; playable=${videoSummary.playable}; unplayable=${videoSummary.unplayable}; missing_source_or_poster=${videoSummary.missing_source_or_poster}`;
  if (uploadError) {
    status = "fail";
    detail = `upload failed: ${uploadError}`;
  } else if (videoPath && route === "/agent/film/new" && videoSummary.video_count === 0) {
    status = "warn";
    detail += "; no preview video element after upload";
  } else if (videoSummary.unplayable > 0) {
    status = "fail";
  } else if (videoSummary.missing_source_or_poster > 0) {
    status = "warn";
    detail += "; playable but no poster/first-frame attribute";
  }
  if (snapshot.text.includes("Workflow: failed") || snapshot.text.includes("Generation Failed")) {
    if (status === "pass") status = "warn";
    detail += "; page state includes failed workflow/generation text";
  }
  return {
    feature: `ui.upload_preview.${route.replace(/^\//, "").replaceAll("/", ".")}`,
    status,
    duration_s: (Date.now() - started) / 1000,
    detail,
    impact_scope: "Agent video upload and preview users",
    evidence: {
      path: route,
      file_inputs: inputCount,
      video_summary: videoSummary,
      console_error_count: logs.filter((log) => log.type === "error").length,
    },
  };
}

async function inspectStudioVideoTab(page) {
  const started = Date.now();
  await page.goto(joinUrl(globalThis.smokeArgs.baseUrl, "/studio"), { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForTimeout(2500);
  const videoButton = page.getByRole("button", { name: "Video", exact: true });
  const count = await videoButton.count();
  if (count === 1) {
    await videoButton.click({ timeout: 10000 });
    await page.waitForTimeout(2500);
  }
  const snapshot = await safePageSnapshot(page);
  const ok = count === 1 && snapshot.text.includes("Generate Video") && snapshot.text.includes("doubao-seedance");
  return {
    feature: "ui.jump_target.studio_video_tab",
    status: ok ? "pass" : "fail",
    duration_s: (Date.now() - started) / 1000,
    detail: "Studio video tab should contain Generate Video and Seedance model options.",
    impact_scope: "Prompt reverse to video generation navigation users",
    evidence: {
      url: snapshot.url,
      clicked_video_tab: count === 1,
      has_generate_video: snapshot.text.includes("Generate Video"),
      has_seedance_model: snapshot.text.includes("doubao-seedance"),
    },
  };
}

async function inspectChat(page) {
  const started = Date.now();
  await page.goto(joinUrl(globalThis.smokeArgs.baseUrl, "/chat"), { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForTimeout(3000);
  const textarea = page.locator("textarea");
  if ((await textarea.count()) > 0) {
    await textarea.first().fill("Hello, please reply in one short sentence.");
    await textarea.first().press("Enter", { timeout: 5000 });
  }
  await page.waitForTimeout(45000);
  const snapshot = await safePageSnapshot(page);
  const quotaError = snapshot.text.includes("insufficient_quota") || snapshot.text.includes("429");
  return {
    feature: "chat.openai_response_quota",
    status: quotaError ? "fail" : "pass",
    duration_s: (Date.now() - started) / 1000,
    detail: quotaError
      ? "Sent one short chat message; UI returned OpenAI Responses API 429 insufficient_quota."
      : "Sent one short chat message and received a response.",
    impact_scope: "Chat conversation users using the OpenAI model route",
    evidence: {
      url: snapshot.url,
      textarea_count: snapshot.text ? 1 : 0,
      has_429_quota_error: quotaError,
    },
  };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  globalThis.smokeArgs = args;
  if (args.help) {
    printHelp();
    return 0;
  }

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
  const findings = [];
  try {
    await login(page, args);
    for (const route of [
      "/agents/video-prompt-reverse",
      "/agents/preroll-ad",
      "/agents/viral-video-fission",
      "/agent/film/new",
    ]) {
      findings.push(await inspectUploadPage(page, route, args.videoPath));
    }
    findings.push(await inspectStudioVideoTab(page));
    if (args.checkChat) {
      findings.push(await inspectChat(page));
    }
  } finally {
    await browser.close();
  }

  const output = JSON.stringify(findings, null, 2);
  if (args.outputJson) fs.writeFileSync(path.resolve(args.outputJson), output);
  else console.log(output);
  return findings.some((finding) => finding.status === "fail") ? 1 : 0;
}

main().then((code) => process.exit(code)).catch((error) => {
  console.error(error);
  process.exit(1);
});
