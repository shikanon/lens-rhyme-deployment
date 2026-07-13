const assert = require("assert");
const fs = require("fs");
const os = require("os");
const path = require("path");

const report = require("./build_agents_regression_report.js");

function testRendersUtf8CopyableHtmlWithEmbeddedEvidence() {
  const imagePath = path.join(os.tmpdir(), `agents-report-test-${Date.now()}.png`);
  fs.writeFileSync(imagePath, Buffer.from("iVBORw0KGgo=", "base64"));
  try {
    const html = report.renderHtml({
      title: "LensRhyme Agents 实际回归报告",
      generatedAt: "2026-07-13",
      environment: "Local Docker Compose",
      summary: "真实提交与后台任务状态交叉验证。",
      scenarios: [{ id: "agents.prompt_reverse", name: "视频提示词反推", status: "pass", detail: "生成了本轮提示词。", evidence: "任务 completed" }],
      issues: [{ severity: "high", title: "广告前贴超时", detail: "上游处理视频 URL 超时。" }],
      images: [{ label: "反推结果", path: imagePath }],
    });
    assert.match(html, /<meta charset="utf-8">/i);
    assert.match(html, /复制整份报告/);
    assert.match(html, /data:image\/png;base64,/);
    assert.match(html, /视频提示词反推/);
    assert.match(html, /广告前贴超时/);
  } finally {
    fs.unlinkSync(imagePath);
  }
}

testRendersUtf8CopyableHtmlWithEmbeddedEvidence();
console.log("agents regression report tests passed");
