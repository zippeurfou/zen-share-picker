import { test } from "node:test";
import assert from "node:assert/strict";

import { KEY_INPUT, PREVIEW_MODE, SHARE_MODE, TIMING } from "../../src/lib/config.mjs";

test("SHARE_MODE is click or assist", () => {
  assert.ok(["click", "assist"].includes(SHARE_MODE), SHARE_MODE);
});

test("PREVIEW_MODE is snapshot, live or none", () => {
  assert.ok(["snapshot", "live", "none"].includes(PREVIEW_MODE), PREVIEW_MODE);
});

test("KEY_INPUT is webdriver or synthetic", () => {
  assert.ok(["webdriver", "synthetic"].includes(KEY_INPUT), KEY_INPUT);
});

test("every TIMING value is a positive integer", () => {
  const names = [
    "snapshotMs",
    "allowWindowMs",
    "goneWaitMs",
    "verifyMs",
    "pollMs",
    "maxClicks",
    "defaultDelayMs",
  ];
  assert.deepEqual(Object.keys(TIMING).sort(), [...names].sort());
  for (const [name, value] of Object.entries(TIMING)) {
    assert.ok(Number.isInteger(value) && value > 0, `${name} = ${value}`);
  }
});

test("Allow is clicked at most twice", () => {
  assert.equal(TIMING.maxClicks, 2);
});
