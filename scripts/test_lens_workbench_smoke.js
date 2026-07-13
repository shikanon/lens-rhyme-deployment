const assert = require("assert");

const workbench = require("./lens-workbench-smoke-playwright.js");

function testParseArgsSupportsCredentialAliasesAndAssetOption() {
  const originalUser = process.env.TEST_USER_USERNAME;
  const originalPassword = process.env.TEST_USER_PASSWORD;
  try {
    process.env.TEST_USER_USERNAME = "workbench_test_user";
    process.env.TEST_USER_PASSWORD = "workbench_test_password";
    const args = workbench.parseArgs(["--headless", "--check-assets", "--script-file", "sample.docx"]);
    assert.strictEqual(args.username, "workbench_test_user");
    assert.strictEqual(args.password, "workbench_test_password");
    assert.strictEqual(args.checkAssets, true);
    assert.strictEqual(args.scriptFile, "sample.docx");
  } finally {
    if (originalUser === undefined) delete process.env.TEST_USER_USERNAME;
    else process.env.TEST_USER_USERNAME = originalUser;
    if (originalPassword === undefined) delete process.env.TEST_USER_PASSWORD;
    else process.env.TEST_USER_PASSWORD = originalPassword;
  }
}

function testPreviewValidationNeedsStructureAndConfirmation() {
  assert.strictEqual(workbench.validatePreview({ acts: 1, scenes: 1, storyboards: 9, confirmVisible: true }).ok, true);
  assert.strictEqual(workbench.validatePreview({ acts: 1, scenes: 1, storyboards: 0, confirmVisible: true }).ok, false);
  assert.strictEqual(workbench.validatePreview({ acts: 1, scenes: 1, storyboards: 9, confirmVisible: false }).ok, false);
}

function testConfirmationRequiresARealApprovalResponseAndPersistedStructure() {
  assert.strictEqual(workbench.validateConfirmation({ approvalObserved: true, approvalOk: true, storyboards: 9, structureVisible: true }).ok, true);
  assert.strictEqual(workbench.validateConfirmation({ approvalObserved: false, approvalOk: false, storyboards: 9, structureVisible: true }).ok, false);
  assert.strictEqual(workbench.validateConfirmation({ approvalObserved: true, approvalOk: true, storyboards: 0, structureVisible: true }).ok, false);
}

function testPreviewCountersIgnoreOverviewStoryboards() {
  const text = "TOTAL STORYBOARDS\n0\nScript preview\nACTS\n1\nSCENES\n1\nSTORYBOARDS\n9";
  assert.deepStrictEqual(workbench.extractPreviewCounts(text), { acts: 1, scenes: 1, storyboards: 9 });
}

function testAssetValidationRejectsEmptyFiles() {
  const empty = workbench.validateAssets([{ name: "Hero.png", size: 0 }, { name: "Scene.png", size: 0 }]);
  const ready = workbench.validateAssets([{ name: "Hero.png", size: 5120 }, { name: "Scene.png", size: 6200 }]);
  assert.strictEqual(empty.ok, false);
  assert.match(empty.reason, /0 B/);
  assert.strictEqual(ready.ok, true);
}

function run() {
  [testParseArgsSupportsCredentialAliasesAndAssetOption, testPreviewValidationNeedsStructureAndConfirmation, testConfirmationRequiresARealApprovalResponseAndPersistedStructure, testPreviewCountersIgnoreOverviewStoryboards, testAssetValidationRejectsEmptyFiles]
    .forEach((test) => test());
  console.log("lens workbench smoke unit tests passed");
}

run();
