import test from "node:test";
import assert from "node:assert/strict";
import { captureRows } from "../../src/lib/captures.mjs";

const e = (mediaSource, deviceId, label) => ({ mediaSource, deviceId, label });
const none = { ok: true, ids: new Set() };

test("screens_first_then_windows_in_zen_order", () => {
  const rows = captureRows(
    [
      e("window", "w1", "Win one"),
      e("screen", "s1", "Screen one"),
      e("window", "w2", "Win two"),
      e("screen", "s2", "Screen two"),
    ],
    null,
    none
  );
  assert.deepEqual(
    rows.rows.map(r => r.key),
    ["screen:s1", "screen:s2", "window:w1", "window:w2"]
  );
  assert.equal(rows.hidden, 0);
  assert.deepEqual(rows.rows[0], {
    key: "screen:s1",
    deviceId: "s1",
    kind: "screen",
    title: "Screen one",
    host: "",
    group: "capture",
  });
});

test("os_entry_tabs_and_applications_are_not_rows", () => {
  const r = captureRows(
    [
      e("screen", "os-id", "Apps"),
      e("window", "os-id", "Apps window"),
      e("browser", "t1", "A tab"),
      e("application", "a1", "An app"),
      e("window", "w1", "Win"),
    ],
    "os-id",
    none
  );
  assert.deepEqual(r.rows.map(x => x.key), ["window:w1"]);
  assert.equal(r.hidden, 0);
});

test("zen_windows_are_hidden_and_counted", () => {
  const r = captureRows(
    [e("window", "z1", "Zen"), e("window", "w1", "Other"), e("window", "z2", "Zen 2"), e("screen", "z1", "Screen")],
    null,
    { ok: true, ids: new Set(["z1", "z2"]) }
  );
  assert.deepEqual(r.rows.map(x => x.key), ["screen:z1", "window:w1"]);
  assert.equal(r.hidden, 2);
});

test("unreadable_zen_ids_hide_every_window_but_keep_screens", () => {
  const r = captureRows(
    [e("screen", "s1", "S"), e("window", "w1", "A"), e("window", "w2", "B")],
    null,
    { ok: false }
  );
  assert.deepEqual(r.rows.map(x => x.key), ["screen:s1"]);
  assert.equal(r.hidden, 2);
});

test("keys_are_kind_and_device_id", () => {
  const r = captureRows([e("window", "7", "W"), e("screen", "7", "S")], null, none);
  assert.deepEqual(r.rows.map(x => x.key), ["screen:7", "window:7"]);
});

test("empty_label_reads_untitled_window", () => {
  const r = captureRows([e("window", "w1", ""), e("screen", "s1", "")], null, none);
  const w = r.rows.find(x => x.kind === "window");
  assert.equal(w.title, "Untitled window");
  assert.equal(r.rows.find(x => x.kind === "screen").title, "");
});

// Anything but a readable answer (ok exactly true and a Set of ids)
// is unknown, and hides every window.
test("captures_fail_closed_on_any_unreadable_zen_answer", () => {
  const entries = [e("screen", "s1", "S"), e("window", "w1", "A")];
  for (const zen of [
    undefined,
    null,
    {},
    { ok: "yes", ids: new Set() },
    { ok: 1, ids: new Set() },
    { ok: true },
    { ok: true, ids: ["z1"] },
    { ok: true, ids: new Map() },
  ]) {
    const r = captureRows(entries, null, zen);
    assert.deepEqual(r.rows.map(x => x.key), ["screen:s1"], JSON.stringify(zen));
    assert.equal(r.hidden, 1);
  }
});
