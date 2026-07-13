#!/usr/bin/env node
/* eslint-disable no-console */

const fs = require("fs");
const path = require("path");

function parseArgs(argv) {
  const args = {
    baseUrl: process.env.LENS_SMOKE_BASE_URL || process.env.SMOKE_TEST_BASE_URL || "http://127.0.0.1:5410",
    username: process.env.SMOKE_TEST_USER_USERNAME || process.env.TEST_USER_USERNAME || "test_user",
    password: process.env.SMOKE_TEST_USER_PASSWORD || process.env.TEST_USER_PASSWORD || "",
    scriptFile: process.env.LENS_SMOKE_WORKBENCH_DOCX || "",
    chromePath: process.env.LENS_SMOKE_CHROME_PATH || "",
    headless: process.env.LENS_SMOKE_HEADLESS === "1",
    confirmImport: false,
    checkAssets: false,
    strictAssets: false,
    previewTimeoutSeconds: Number(process.env.LENS_SMOKE_WORKBENCH_PREVIEW_TIMEOUT || 360),
    assetTimeoutSeconds: Number(process.env.LENS_SMOKE_WORKBENCH_ASSET_TIMEOUT || 600),
    outputJson: "",
    screenshotsDir: "",
  };
  for (let index = 0; index < argv.length; index += 1) {
    const key = argv[index];
    const value = argv[index + 1];
    if (key === "--base-url") args.baseUrl = value, index += 1;
    else if (key === "--username") args.username = value, index += 1;
    else if (key === "--password") args.password = value, index += 1;
    else if (key === "--script-file") args.scriptFile = value, index += 1;
    else if (key === "--chrome-path") args.chromePath = value, index += 1;
    else if (key === "--preview-timeout") args.previewTimeoutSeconds = Number(value), index += 1;
    else if (key === "--asset-timeout") args.assetTimeoutSeconds = Number(value), index += 1;
    else if (key === "--output-json") args.outputJson = value, index += 1;
    else if (key === "--screenshots-dir") args.screenshotsDir = value, index += 1;
    else if (key === "--headless") args.headless = true;
    else if (key === "--confirm-import") args.confirmImport = true;
    else if (key === "--check-assets") args.checkAssets = true, args.confirmImport = true;
    else if (key === "--strict-assets") args.strictAssets = true;
    else if (key === "--help") args.help = true;
  }
  return args;
}

function printHelp() {
  console.log(`Usage: node scripts/lens-workbench-smoke-playwright.js [options]

Options:
  --script-file PATH       DOCX/TXT/CSV/XLSX/PDF script to import (required).
  --base-url URL           LensRhyme main site URL.
  --username NAME          Test username. Defaults to SMOKE_TEST_USER_USERNAME / TEST_USER_USERNAME.
  --password VALUE         Test password. Prefer SMOKE_TEST_USER_PASSWORD / TEST_USER_PASSWORD.
  --chrome-path PATH       Local Chrome/Edge executable path.
  --headless               Run browser headlessly.
  --confirm-import         Confirm the live preview and verify Workbench overview persistence.
  --check-assets           Confirm import, trigger generated assets, and inspect asset file sizes.
  --strict-assets          Fail instead of warn when generated assets are empty.
  --preview-timeout SEC    Preview wait limit. Default: 360.
  --asset-timeout SEC      Generated-asset task wait limit. Default: 600.
  --output-json PATH       Write redacted JSON findings to this path.
  --screenshots-dir DIR    Optionally write screenshots outside the repository.
`);
}

function joinUrl(baseUrl, route) {
  return `${baseUrl.replace(/\/$/, "")}/${route.replace(/^\//, "")}`;
}

function redact(value) {
  return String(value || "")
    .replace(/token=[^\s&]+/gi, "token=[redacted]")
    .replace(/(authorization:\s*bearer\s+)[^\s]+/gi, "$1[redacted]")
    .slice(0, 500);
}

function extractCount(text, label) {
  const match = String(text || "").match(new RegExp(`${label}\\s*[:：]?\\s*(\\d+)`, "i"));
  return match ? Number(match[1]) : 0;
}

function extractPreviewCounts(text) {
  const previewText = String(text || "").split(/Script preview|脚本预览/i).slice(-1)[0];
  return {
    acts: extractCount(previewText, "ACTS"),
    scenes: extractCount(previewText, "SCENES"),
    storyboards: extractCount(previewText, "STORYBOARDS"),
  };
}

function validatePreview(preview) {
  const ok = preview.acts > 0 && preview.scenes > 0 && preview.storyboards > 0 && preview.confirmVisible;
  return { ok, reason: ok ? "preview contains structure and confirmation action" : "preview requires acts, scenes, storyboards, and confirmation action" };
}

function validateConfirmation(confirmation) {
  const ok = confirmation.approvalObserved && confirmation.approvalOk
    && confirmation.storyboards > 0 && confirmation.structureVisible;
  return {
    ok,
    reason: ok
      ? "approval request succeeded and the confirmed structure is visible"
      : "confirmation requires a successful approval request and persisted structure",
  };
}

function validateAssets(assets) {
  if (!assets.length) return { ok: false, reason: "no generated asset records" };
  const empty = assets.filter((asset) => Number(asset.size || 0) <= 0);
  return empty.length ? { ok: false, reason: `${empty.length}/${assets.length} assets are 0 B` } : { ok: true, reason: "all generated assets have a non-zero size" };
}

async function apiJson(args, method, apiPath, token, body) {
  const response = await fetch(joinUrl(args.baseUrl, `/api/v1/${apiPath.replace(/^\//, "")}`), {
    method,
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  let data;
  try { data = text ? JSON.parse(text) : {}; } catch (error) { data = { raw: redact(text) }; }
  if (!response.ok) throw new Error(`${method} ${apiPath} returned ${response.status}: ${redact(text)}`);
  return data;
}

async function apiLogin(args) {
  const result = await apiJson(args, "POST", "/auth/login", "", { username: args.username, password: args.password });
  if (!result.access_token) throw new Error("API login response did not contain an access token");
  return result.access_token;
}

async function pollTask(args, token, taskId) {
  const deadline = Date.now() + args.assetTimeoutSeconds * 1000;
  let latest = {};
  while (Date.now() < deadline) {
    latest = await apiJson(args, "GET", `/tasks/${taskId}`, token);
    const state = String(latest.status || "").toLowerCase();
    if (["completed", "success", "succeeded"].includes(state)) return { ok: true, task: latest };
    if (["failed", "error", "aborted", "cancelled", "canceled"].includes(state)) return { ok: false, task: latest };
    await new Promise((resolve) => setTimeout(resolve, 5000));
  }
  return { ok: false, task: latest, timeout: true };
}

async function clickFirst(locator, message) {
  if ((await locator.count()) < 1) throw new Error(message);
  await locator.first().click({ timeout: 15000 });
}

async function login(page, args) {
  if (!args.password) throw new Error("missing password: set SMOKE_TEST_USER_PASSWORD or TEST_USER_PASSWORD, or pass --password");
  await page.goto(joinUrl(args.baseUrl, "/login"), { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.locator('input[placeholder="Username"], input[name="username"]').first().fill(args.username);
  await page.locator('input[type="password"], input[placeholder="Password"]').first().fill(args.password);
  await clickFirst(page.getByRole("button", { name: /log in|login|登录/i }), "login button was not found");
  await page.waitForURL((url) => !String(url).includes("/login"), { timeout: 30000 });
}

async function createProject(page, args) {
  await page.goto(joinUrl(args.baseUrl, "/workbench"), { waitUntil: "networkidle", timeout: 60000 });
  await clickFirst(page.getByRole("button", { name: /new project|新建项目/i }), "New Project button was not found");
  const name = `WORKBENCH-SMOKE-${new Date().toISOString().replace(/[-:.TZ]/g, "").slice(0, 14)}`;
  await page.locator('input[placeholder*="Project Name" i], input[placeholder*="项目名称"]').first().fill(name);
  const description = page.locator('textarea[placeholder*="Description" i], textarea[placeholder*="描述"]');
  if ((await description.count()) > 0) await description.first().fill("Automated Workbench smoke test. Created by the regression script.");
  const create = page.getByRole("button", { name: /create project|创建项目/i });
  if ((await create.count()) > 0) await create.first().click();
  else await clickFirst(page.getByRole("button", { name: /create|创建/i }), "Create Project button was not found");
  await page.waitForTimeout(1000);
  const projectCard = page.getByText(name, { exact: true });
  if ((await projectCard.count()) > 0) await projectCard.first().click();
  await page.waitForURL(/\/workbench\/[^/?#]+/, { timeout: 30000 });
  return { name, url: page.url(), id: page.url().match(/\/workbench\/([^/?#]+)/)?.[1] || "" };
}

async function importScript(page, args, projectId) {
  if (!args.scriptFile || !fs.existsSync(args.scriptFile)) throw new Error("missing script file: set --script-file or LENS_SMOKE_WORKBENCH_DOCX");
  const entry = page.getByRole("button", { name: /import script|导入脚本/i });
  await clickFirst(entry, "Import Script button was not found");
  const fileInput = page.locator('input[type="file"]');
  await fileInput.first().setInputFiles(args.scriptFile);
  const action = page.getByRole("button", { name: /import script|导入脚本/i });
  const importResponse = page.waitForResponse((response) => response.request().method() === "POST"
    && new URL(response.url()).pathname.endsWith(`/workbench/projects/${projectId}/script/import`), { timeout: 30000 });
  await action.last().click({ timeout: 15000 });
  const response = await importResponse;
  const result = await response.json();
  return { taskId: result.task_id || "" };
}

async function previewState(page) {
  const text = await page.locator("body").innerText();
  const counts = extractPreviewCounts(text);
  return {
    ...counts,
    confirmVisible: /Confirm Import|确认导入/i.test(text),
    failed: /Import failed|导入失败/i.test(text),
    text,
  };
}

async function waitForPreview(page, timeoutSeconds) {
  const deadline = Date.now() + timeoutSeconds * 1000;
  let latest = await previewState(page);
  while (Date.now() < deadline) {
    if (latest.confirmVisible || latest.failed) return latest;
    await page.waitForTimeout(5000);
    latest = await previewState(page);
  }
  return latest;
}

async function confirmImport(page, projectId, importTaskId) {
  const approvalPath = `/workbench/projects/${projectId}/script/import/${importTaskId}/approve`;
  const replacement = page.getByRole("button", { name: "Confirm and replace draft", exact: true });
  const basic = page.getByRole("button", { name: "Confirm import", exact: true });
  const localizedReplacement = page.getByRole("button", { name: /确认并替换草稿/i });
  const localizedBasic = page.getByRole("button", { name: /确认导入/i });
  const approvalResponse = page.waitForResponse((response) => response.request().method() === "POST"
    && new URL(response.url()).pathname.endsWith(approvalPath), { timeout: 30000 });
  if ((await replacement.count()) > 0) await replacement.first().click({ timeout: 15000 });
  else if ((await basic.count()) > 0) await basic.first().click({ timeout: 15000 });
  else if ((await localizedReplacement.count()) > 0) await localizedReplacement.first().click({ timeout: 15000 });
  else await clickFirst(localizedBasic, "Confirm Import button was not found");
  const response = await approvalResponse;
  await page.waitForTimeout(1200);
  const text = await page.locator("body").innerText();
  return {
    approvalObserved: true,
    approvalOk: response.ok(),
    approvalStatus: response.status(),
    storyboards: extractCount(text, "TOTAL STORYBOARDS"),
    structureVisible: /STRUCTURE|结构/i.test(text),
  };
}

async function maybeScreenshot(page, args, name) {
  if (!args.screenshotsDir) return "";
  fs.mkdirSync(args.screenshotsDir, { recursive: true });
  const target = path.join(args.screenshotsDir, name);
  await page.screenshot({ path: target, fullPage: true });
  return target;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    printHelp();
    return 0;
  }
  let chromium;
  try { ({ chromium } = require("playwright-core")); } catch (error) {
    console.error("Missing dependency: install playwright-core outside this repository or in your CI image.");
    return 1;
  }
  const launchOptions = { headless: args.headless };
  if (args.chromePath) launchOptions.executablePath = args.chromePath;
  const browser = await chromium.launch(launchOptions);
  const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
  const warnings = [];
  const api = [];
  page.on("console", (message) => {
    if (["warning", "error"].includes(message.type())) warnings.push({ type: message.type(), text: redact(message.text()) });
  });
  page.on("response", (response) => {
    if (response.url().includes("/api/")) api.push({ method: response.request().method(), path: new URL(response.url()).pathname, status: response.status() });
  });
  const findings = [];
  try {
    await login(page, args);
    const project = await createProject(page, args);
    const imported = await importScript(page, args, project.id);
    const preview = await waitForPreview(page, args.previewTimeoutSeconds);
    const previewResult = validatePreview(preview);
    const screenshot = await maybeScreenshot(page, args, "workbench-preview.png");
    findings.push({
      feature: "workbench.script_import_preview",
      status: previewResult.ok && !preview.failed ? "pass" : "fail",
      detail: previewResult.reason,
      evidence: { project_name: project.name, acts: preview.acts, scenes: preview.scenes, storyboards: preview.storyboards, confirm_visible: preview.confirmVisible, screenshot: screenshot ? path.basename(screenshot) : "" },
    });
    let confirmationResult = null;
    if (args.confirmImport && previewResult.ok) {
      const confirmed = await confirmImport(page, project.id, imported.taskId);
      confirmationResult = validateConfirmation(confirmed);
      findings.push({ feature: "workbench.confirmed_structure", status: confirmationResult.ok ? "pass" : "fail", detail: confirmationResult.reason, evidence: confirmed });
    } else if (previewResult.ok) {
      await page.reload({ waitUntil: "networkidle", timeout: 60000 });
      const afterReload = await previewState(page);
      findings.push({
        feature: "workbench.preview_reload_recovery",
        status: afterReload.confirmVisible ? "pass" : "warn",
        detail: afterReload.confirmVisible ? "Import preview remains confirmable after reload." : "Import preview confirmation is not restored after reload.",
        evidence: { confirm_visible_after_reload: afterReload.confirmVisible },
      });
    }
    if (args.checkAssets && previewResult.ok) {
      if (!confirmationResult?.ok) {
        findings.push({ feature: "workbench.generated_assets", status: "fail", detail: "Generated assets require a successful import confirmation.", evidence: {} });
      } else if (!imported.taskId) {
        findings.push({ feature: "workbench.generated_assets", status: "fail", detail: "Script import response did not contain a task id.", evidence: {} });
      } else {
        const token = await apiLogin(args);
        const trigger = await apiJson(args, "POST", `/workbench/projects/${project.id}/script/import/${imported.taskId}/generate-assets`, token, {});
        const assetTaskId = trigger.task_id || "";
        const task = assetTaskId ? await pollTask(args, token, assetTaskId) : { ok: false, task: {} };
        const assets = task.ok ? await apiJson(args, "GET", `/workbench/projects/${project.id}/assets`, token) : [];
        const assetResult = validateAssets(Array.isArray(assets) ? assets : []);
        await page.goto(joinUrl(args.baseUrl, `/workbench/${project.id}/assets`), { waitUntil: "networkidle", timeout: 60000 });
        const assetPageText = await page.locator("body").innerText();
        const status = task.ok && assetResult.ok ? "pass" : args.strictAssets ? "fail" : "warn";
        findings.push({ feature: "workbench.generated_assets", status, detail: task.ok ? assetResult.reason : "Generated-asset task did not complete successfully.", evidence: { task_completed: task.ok, asset_count: Array.isArray(assets) ? assets.length : 0, zero_byte_visible: /0 B/.test(assetPageText), strict_assets: args.strictAssets } });
      }
    }
  } finally {
    await browser.close();
  }
  const safeOutput = { generated_at: new Date().toISOString(), findings, browser_warnings: warnings, api_requests: api };
  const output = JSON.stringify(safeOutput, null, 2);
  if (args.outputJson) fs.writeFileSync(path.resolve(args.outputJson), output, "utf8");
  else console.log(output);
  return findings.some((finding) => finding.status === "fail") ? 1 : 0;
}

if (require.main === module) main().then((code) => process.exit(code)).catch((error) => { console.error(redact(error.stack || error)); process.exit(1); });

module.exports = { parseArgs, extractPreviewCounts, validatePreview, validateConfirmation, validateAssets };
