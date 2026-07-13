const assert = require("assert");

const canvas = require("./lens-canvas-smoke-playwright.js");

function testParseArgsSupportsCredentialAliasesAndStrictLayout() {
  const originalUser = process.env.TEST_USER_USERNAME;
  const originalPassword = process.env.TEST_USER_PASSWORD;
  try {
    process.env.TEST_USER_USERNAME = "canvas_test_user";
    process.env.TEST_USER_PASSWORD = "canvas_test_password";
    const args = canvas.parseArgs(["--headless", "--strict-layout"]);
    assert.strictEqual(args.username, "canvas_test_user");
    assert.strictEqual(args.password, "canvas_test_password");
    assert.strictEqual(args.headless, true);
    assert.strictEqual(args.strictLayout, true);
  } finally {
    if (originalUser === undefined) delete process.env.TEST_USER_USERNAME;
    else process.env.TEST_USER_USERNAME = originalUser;
    if (originalPassword === undefined) delete process.env.TEST_USER_PASSWORD;
    else process.env.TEST_USER_PASSWORD = originalPassword;
  }
}

function testPersistenceRequiresNewNodesAndConnection() {
  const before = { nodes: [], edges: [] };
  const after = {
    nodes: [{ id: "text-1", type: "text" }, { id: "script-1", type: "script" }],
    edges: [{ id: "edge-text-1-script-1" }],
  };
  const reloaded = JSON.parse(JSON.stringify(after));
  assert.strictEqual(canvas.validateCanvasPersistence(before, after, reloaded).ok, true);
  assert.strictEqual(canvas.validateCanvasPersistence(before, after, { nodes: after.nodes, edges: [] }).ok, false);
}

function testOverlapDetectionIgnoresSeparatedAndTouchingNodes() {
  const nodes = [
    { id: "text", left: 0, top: 0, right: 100, bottom: 100 },
    { id: "script", left: 100, top: 0, right: 180, bottom: 100 },
    { id: "image", left: 80, top: 20, right: 160, bottom: 120 },
  ];
  const overlaps = canvas.findNodeOverlaps(nodes);
  assert.deepStrictEqual(overlaps, [{ first: "text", second: "image" }, { first: "script", second: "image" }]);
}

function run() {
  [
    testParseArgsSupportsCredentialAliasesAndStrictLayout,
    testPersistenceRequiresNewNodesAndConnection,
    testOverlapDetectionIgnoresSeparatedAndTouchingNodes,
  ].forEach((test) => test());
  console.log("lens canvas smoke unit tests passed");
}

run();
