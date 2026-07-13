#!/usr/bin/env node
/* eslint-disable no-console */

const fs = require("fs");
const os = require("os");
const path = require("path");

function parseArgs(argv) {
  const args = {
    baseUrl: process.env.LENS_SMOKE_BASE_URL || process.env.SMOKE_TEST_BASE_URL || "http://127.0.0.1:5410",
    username: process.env.SMOKE_TEST_USER_USERNAME || process.env.TEST_USER_USERNAME || "test_user",
    password: process.env.SMOKE_TEST_USER_PASSWORD || process.env.TEST_USER_PASSWORD || "",
    chromePath: process.env.LENS_SMOKE_CHROME_PATH || "",
    headless: process.env.LENS_SMOKE_HEADLESS === "1",
    strictLayout: false,
    outputJson: "",
    screenshotsDir: "",
    skipExport: false,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const key = argv[index];
    const value = argv[index + 1];
    if (key === "--base-url") args.baseUrl = value, index += 1;
    else if (key === "--username") args.username = value, index += 1;
    else if (key === "--password") args.password = value, index += 1;
    else if (key === "--chrome-path") args.chromePath = value, index += 1;
    else if (key === "--output-json") args.outputJson = value, index += 1;
    else if (key === "--screenshots-dir") args.screenshotsDir = value, index += 1;
    else if (key === "--headless") args.headless = true;
    else if (key === "--strict-layout") args.strictLayout = true;
    else if (key === "--skip-export") args.skipExport = true;
    else if (key === "--help") args.help = true;
  }
  return args;
}

function printHelp() {
  console.log(`Usage: node scripts/lens-canvas-smoke-playwright.js [options]

Options:
  --base-url URL         LensRhyme main site URL.
  --username NAME        Test username. Defaults to SMOKE_TEST_USER_USERNAME / TEST_USER_USERNAME.
  --password VALUE       Test password. Prefer SMOKE_TEST_USER_PASSWORD / TEST_USER_PASSWORD.
  --chrome-path PATH     Local Chrome/Edge executable path.
  --headless             Run browser headlessly.
  --strict-layout        Fail when newly created nodes overlap. Default: emit a warning.
  --skip-export          Skip the package-export assertion.
  --output-json PATH     Write redacted JSON findings to this path.
  --screenshots-dir DIR  Optionally write screenshots outside the repository.

Install playwright-core outside this repository or in the CI image.
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

function findNodeOverlaps(nodes) {
  const overlaps = [];
  for (let firstIndex = 0; firstIndex < nodes.length; firstIndex += 1) {
    for (let secondIndex = firstIndex + 1; secondIndex < nodes.length; secondIndex += 1) {
      const first = nodes[firstIndex];
      const second = nodes[secondIndex];
      const overlapsHorizontally = first.left < second.right && first.right > second.left;
      const overlapsVertically = first.top < second.bottom && first.bottom > second.top;
      if (overlapsHorizontally && overlapsVertically) {
        overlaps.push({ first: first.id, second: second.id });
      }
    }
  }
  return overlaps;
}

function validateCanvasPersistence(before, after, reloaded) {
  const createdNodes = after.nodes.length - before.nodes.length;
  const createdEdges = after.edges.length - before.edges.length;
  const reloadedNodeIds = new Set(reloaded.nodes.map((node) => node.id));
  const reloadedEdgeIds = new Set(reloaded.edges.map((edge) => edge.id));
  const newNodesPersisted = after.nodes.slice(before.nodes.length).every((node) => reloadedNodeIds.has(node.id));
  const newEdgesPersisted = after.edges.slice(before.edges.length).every((edge) => reloadedEdgeIds.has(edge.id));
  return {
    ok: createdNodes >= 2 && createdEdges >= 1 && newNodesPersisted && newEdgesPersisted,
    created_nodes: createdNodes,
    created_edges: createdEdges,
    new_nodes_persisted: newNodesPersisted,
    new_edges_persisted: newEdgesPersisted,
  };
}

async function clickFirst(locator, message) {
  if ((await locator.count()) < 1) throw new Error(message);
  await locator.first().click({ timeout: 15000 });
}

async function login(page, args) {
  if (!args.password) {
    throw new Error("missing password: set SMOKE_TEST_USER_PASSWORD or TEST_USER_PASSWORD, or pass --password");
  }
  await page.goto(joinUrl(args.baseUrl, "/login"), { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.locator('input[placeholder="Username"], input[name="username"]').first().fill(args.username);
  await page.locator('input[type="password"], input[placeholder="Password"]').first().fill(args.password);
  await clickFirst(page.getByRole("button", { name: /log in|login|登录/i }), "login button was not found");
  await page.waitForURL((url) => !String(url).includes("/login"), { timeout: 30000 });
}

async function canvasState(page) {
  return page.evaluate(() => ({
    nodes: Array.from(document.querySelectorAll(".react-flow__node")).map((node) => {
      const rect = node.getBoundingClientRect();
      return {
        id: node.getAttribute("data-id") || "",
        type: Array.from(node.classList).find((className) => className.startsWith("react-flow__node-")) || "",
        left: Math.round(rect.left), top: Math.round(rect.top), right: Math.round(rect.right), bottom: Math.round(rect.bottom),
      };
    }),
    edges: Array.from(document.querySelectorAll(".react-flow__edge")).map((edge) => ({ id: edge.getAttribute("data-id") || "" })),
    active_errors: (document.body?.innerText || "").match(/Application error|Client-side exception|Unhandled Runtime Error/gi) || [],
  }));
}

async function zoomLabel(page) {
  const fitView = page.getByRole("button", { name: /fit view|适应视图/i });
  return (await fitView.count()) ? (await fitView.first().innerText()).trim() : "";
}

async function waitForCanvasReady(page) {
  await page.waitForLoadState("networkidle", { timeout: 30000 }).catch(() => {});
  await page.getByRole("button", { name: /add nodes|添加节点/i }).first().waitFor({ state: "visible", timeout: 30000 });
  // The editor uses client-side hydration for the node-card click handlers.
  await page.waitForTimeout(750);
}

async function createCanvas(page, args) {
  await page.goto(joinUrl(args.baseUrl, "/canvas"), { waitUntil: "domcontentloaded", timeout: 60000 });
  await clickFirst(page.getByRole("button", { name: /new canvas|新建画布/i }), "New Canvas button was not found");
  const stamp = new Date().toISOString().replace(/[-:.TZ]/g, "").slice(0, 14);
  const name = `CANVAS-SMOKE-${stamp}`;
  await page.locator('input[placeholder="Project Name"], input[placeholder="项目名称"]').first().fill(name);
  const description = page.locator('textarea[placeholder="Description"], textarea[placeholder="描述"]');
  if ((await description.count()) > 0) await description.first().fill("Automated Canvas smoke test. Created by the regression script.");
  await clickFirst(page.getByRole("button", { name: /create|创建/i }), "Create Canvas button was not found");
  await page.getByText(name, { exact: true }).waitFor({ timeout: 30000 });
  const projectCard = page.getByText(name, { exact: true }).locator('xpath=ancestor::div[.//button[normalize-space()="Enter Canvas"]][1]');
  await clickFirst(projectCard.getByRole("button", { name: /enter canvas|进入画布/i }), "Enter Canvas button for the new project was not found");
  await page.waitForURL(/\/canvas\/[^/?#]+/, { timeout: 30000 });
  await waitForCanvasReady(page);
  return { name, url: page.url() };
}

async function addNode(page, nodeType) {
  await clickFirst(page.getByRole("button", { name: /add nodes|添加节点/i }), "Add Nodes button was not found");
  await clickFirst(page.getByTestId(`canvas-add-node-${nodeType}`), `node card was not found: ${nodeType}`);
  await page.waitForTimeout(500);
}

async function connectTextToScript(page) {
  const textNode = page.locator(".react-flow__node-text").last();
  const scriptNode = page.locator(".react-flow__node-script").last();
  const source = textNode.locator('.react-flow__handle.source[data-handleid="output-text"]');
  const target = scriptNode.locator('.react-flow__handle.target[data-handleid="input-text"]');
  const sourceBox = await source.boundingBox();
  const targetBox = await target.boundingBox();
  if (!sourceBox || !targetBox) throw new Error("text/script connection handles were not measurable");
  await page.mouse.move(sourceBox.x + sourceBox.width / 2, sourceBox.y + sourceBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(targetBox.x + targetBox.width / 2, targetBox.y + targetBox.height / 2, { steps: 14 });
  await page.mouse.up();
  await page.waitForTimeout(800);
}

async function inspectControls(page, args) {
  const result = { zoom_changed: false, zoom_before: "", zoom_after_out: "", zoom_after_in: "", export_bytes: 0 };
  const zoomIn = page.getByRole("button", { name: /zoom in|放大/i });
  const zoomOut = page.getByRole("button", { name: /zoom out|缩小/i });
  if ((await zoomIn.count()) && (await zoomOut.count())) {
    const before = await zoomLabel(page);
    await zoomOut.first().click();
    let afterOut = before;
    for (let attempt = 0; attempt < 20 && afterOut === before; attempt += 1) {
      await page.waitForTimeout(250);
      afterOut = await zoomLabel(page);
    }
    await zoomIn.first().click();
    let afterIn = afterOut;
    for (let attempt = 0; attempt < 20 && afterIn === afterOut; attempt += 1) {
      await page.waitForTimeout(250);
      afterIn = await zoomLabel(page);
    }
    result.zoom_before = before;
    result.zoom_after_out = afterOut;
    result.zoom_after_in = afterIn;
    result.zoom_changed = before !== afterOut && afterOut !== afterIn;
  }
  if (!args.skipExport) {
    const exportButton = page.getByRole("button", { name: /export package|导出包/i });
    const downloadPromise = page.waitForEvent("download", { timeout: 20000 });
    await clickFirst(exportButton, "Export Package button was not found");
    const download = await downloadPromise;
    const tempPath = path.join(os.tmpdir(), `lens-canvas-export-${Date.now()}.zip`);
    await download.saveAs(tempPath);
    result.export_bytes = fs.statSync(tempPath).size;
    fs.unlinkSync(tempPath);
  }
  return result;
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
  try {
    ({ chromium } = require("playwright-core"));
  } catch (error) {
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
    if (["error", "warning"].includes(message.type())) warnings.push({ type: message.type(), text: redact(message.text()) });
  });
  page.on("response", (response) => {
    if (response.url().includes("/api/")) api.push({ method: response.request().method(), path: new URL(response.url()).pathname, status: response.status() });
  });

  const findings = [];
  try {
    await login(page, args);
    const project = await createCanvas(page, args);
    const before = await canvasState(page);
    await addNode(page, "text");
    await addNode(page, "script");
    await connectTextToScript(page);
    const connected = await canvasState(page);
    const screenshot = await maybeScreenshot(page, args, "canvas-connected.png");
    await page.reload({ waitUntil: "domcontentloaded" });
    await waitForCanvasReady(page);
    const reloaded = await canvasState(page);
    const persistence = validateCanvasPersistence(before, connected, reloaded);
    await page.goto(project.url, { waitUntil: "networkidle", timeout: 60000 });
    await waitForCanvasReady(page);
    const controls = await inspectControls(page, args);
    const overlaps = findNodeOverlaps(connected.nodes.slice(before.nodes.length));
    findings.push({
      feature: "canvas.create_connect_persist",
      status: persistence.ok && connected.active_errors.length === 0 ? "pass" : "fail",
      detail: persistence.ok ? "Created Text and Script nodes, connected them, and verified persistence after reload." : "Node or edge persistence check failed.",
      evidence: { project_name: project.name, persistence, active_errors: connected.active_errors, screenshot: screenshot ? path.basename(screenshot) : "" },
    });
    findings.push({
      feature: "canvas.controls.zoom_export",
      status: controls.zoom_changed && (args.skipExport || controls.export_bytes > 0) ? "pass" : "fail",
      detail: `zoom_changed=${controls.zoom_changed}; export_bytes=${controls.export_bytes}`,
      evidence: controls,
    });
    findings.push({
      feature: "canvas.layout.node_overlap",
      status: overlaps.length === 0 ? "pass" : args.strictLayout ? "fail" : "warn",
      detail: overlaps.length === 0 ? "Newly created nodes do not overlap." : `${overlaps.length} newly created node overlap(s) detected. Use --strict-layout to fail this check.`,
      evidence: { overlaps },
    });
  } finally {
    await browser.close();
  }

  const safeOutput = { generated_at: new Date().toISOString(), findings, browser_warnings: warnings, api_requests: api };
  const output = JSON.stringify(safeOutput, null, 2);
  if (args.outputJson) fs.writeFileSync(path.resolve(args.outputJson), output, "utf8");
  else console.log(output);
  return findings.some((finding) => finding.status === "fail") ? 1 : 0;
}

if (require.main === module) {
  main().then((code) => process.exit(code)).catch((error) => {
    console.error(redact(error.stack || error));
    process.exit(1);
  });
}

module.exports = { parseArgs, findNodeOverlaps, validateCanvasPersistence };
