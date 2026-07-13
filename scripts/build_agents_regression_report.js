#!/usr/bin/env node
/* eslint-disable no-console */

const fs = require("fs");
const path = require("path");

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function imageDataUrl(imagePath) {
  const extension = path.extname(imagePath).toLowerCase();
  const mime = extension === ".jpg" || extension === ".jpeg" ? "image/jpeg" : extension === ".webp" ? "image/webp" : "image/png";
  return `data:${mime};base64,${fs.readFileSync(imagePath).toString("base64")}`;
}

function renderHtml(data) {
  const scenarios = (data.scenarios || []).map((scenario) => `
    <tr>
      <td>${escapeHtml(scenario.name)}</td>
      <td><span class="status ${escapeHtml(scenario.status)}">${escapeHtml(scenario.status)}</span></td>
      <td>${escapeHtml(scenario.detail)}</td>
      <td>${escapeHtml(scenario.evidence)}</td>
    </tr>`).join("");
  const issues = (data.issues || []).map((issue) => `
    <article class="issue ${escapeHtml(issue.severity)}">
      <b>${escapeHtml(issue.title)}</b>
      <p>${escapeHtml(issue.detail)}</p>
    </article>`).join("");
  const images = (data.images || []).map((image) => `
    <figure><img alt="${escapeHtml(image.label)}" src="${imageDataUrl(image.path)}"><figcaption>${escapeHtml(image.label)}</figcaption></figure>`).join("");
  return `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escapeHtml(data.title)}</title>
<style>
body{margin:0;background:#f3f5f9;color:#172033;font:15px/1.65 Arial,"Microsoft YaHei",sans-serif}.sheet{max-width:1120px;margin:28px auto;padding:42px;background:#fff;box-shadow:0 8px 28px #1b27401a;border-radius:16px}.hero{padding:30px;border-radius:14px;background:#101a2b;color:#fff}.hero h1{margin:0 0 8px;font-size:30px}.meta{color:#b8c7e6}.copy{float:right;border:0;border-radius:9px;padding:10px 16px;background:#41d49c;color:#082217;font-weight:700;cursor:pointer}h2{margin-top:34px}.summary{padding:15px 18px;background:#eef6ff;border-left:4px solid #4387ff;border-radius:6px}table{width:100%;border-collapse:collapse}th,td{padding:12px;border-bottom:1px solid #e5eaf2;text-align:left;vertical-align:top}th{background:#f7f9fc}.status{padding:3px 9px;border-radius:999px;font-weight:700;text-transform:uppercase;font-size:12px}.pass{background:#e5f9ef;color:#087443}.fail{background:#ffe8e8;color:#bc2f2f}.warn{background:#fff4d8;color:#9a6300}.issue{padding:15px 18px;margin:12px 0;border-radius:8px;background:#fff4f4;border-left:4px solid #dd4a4a}.issue.medium{background:#fff9e8;border-left-color:#d59613}.issue p{margin:5px 0 0}.evidence{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}.evidence figure{margin:0;border:1px solid #e5eaf2;border-radius:10px;overflow:hidden}.evidence img{width:100%;display:block}.evidence figcaption{padding:9px 12px;color:#546176;font-size:13px}@media print{body{background:#fff}.sheet{box-shadow:none;margin:0}}
</style></head><body><main class="sheet" id="report"><section class="hero"><button class="copy" onclick="copyReport()">复制整份报告</button><h1>${escapeHtml(data.title)}</h1><div class="meta">测试日期：${escapeHtml(data.generatedAt)} ｜ 环境：${escapeHtml(data.environment)}</div></section><p class="summary">${escapeHtml(data.summary)}</p><h2>逐项实际测试结果</h2><table><thead><tr><th>功能</th><th>结论</th><th>实际验证</th><th>证据</th></tr></thead><tbody>${scenarios}</tbody></table><h2>问题与风险</h2>${issues}<h2>截图证据（Base64 内嵌，可复制）</h2><section class="evidence">${images}</section></main><script>async function copyReport(){const n=document.getElementById('report');const h=n.outerHTML;try{await navigator.clipboard.write([new ClipboardItem({'text/html':new Blob([h],{type:'text/html'}),'text/plain':new Blob([n.innerText],{type:'text/plain'})})]);event.target.textContent='已复制';}catch(e){const r=document.createRange();r.selectNode(n);getSelection().removeAllRanges();getSelection().addRange(r);event.target.textContent='已选中，请复制';}}</script></body></html>`;
}

function parseArgs(argv) {
  const args = { data: "", output: "" };
  for (let index = 0; index < argv.length; index += 1) {
    if (argv[index] === "--data") args.data = argv[index + 1], index += 1;
    else if (argv[index] === "--output") args.output = argv[index + 1], index += 1;
  }
  return args;
}

if (require.main === module) {
  const args = parseArgs(process.argv.slice(2));
  if (!args.data || !args.output) throw new Error("Usage: node scripts/build_agents_regression_report.js --data DATA.json --output REPORT.html");
  const data = JSON.parse(fs.readFileSync(path.resolve(args.data), "utf8"));
  fs.writeFileSync(path.resolve(args.output), renderHtml(data), "utf8");
  console.log(`Report: ${path.resolve(args.output)}`);
}

module.exports = { renderHtml, parseArgs };
