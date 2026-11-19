import test from "node:test";
import assert from "node:assert/strict";
import { runShare } from "../../src/lib/share.mjs";
import { TIMING } from "../../src/lib/config.mjs";

const DELAY = 500;
const TARGET = { kind: "tab", deviceId: "42" };

// A fake stock prompt on a virtual clock: `sleep` advances time, nothing
// waits for real. Each option is a function of the current time `t`.
function setup(over = {}) {
  const cfg = {
    current: () => true,
    active: () => true,
    enabled: () => true,
    shownAt: () => 0,
    selectOk: true,
    // What the dropdown reads back; null means what `select` set.
    readback: () => null,
    // Whether an Allow click at time t is taken (the prompt goes).
    accepts: t => t >= DELAY,
    shows: () => true,
    // Devices of the active streams, as {mediaSource, rawId}; null means
    // the selected device, as the target's own kind.
    devices: null,
    throws: null,
    ...over,
  };
  const s = {
    t: 0,
    selected: "initial",
    gone: false,
    clicks: [],
    calls: [],
    kinds: [],
    verifyKinds: [],
  };
  const rec = name => {
    if (cfg.throws === name) {
      throw new Error("boom " + name);
    }
    s.calls.push(name);
  };
  const clock = {
    now: () => s.t,
    sleep: async ms => {
      assert.ok(ms > 0, "sleep(" + ms + ")");
      s.calls.push("wait");
      s.t += ms;
    },
  };
  const port = {
    isCurrent: () => !s.gone && cfg.current(s.t),
    selectedDeviceId: () => cfg.readback(s.t) ?? s.selected,
    select: (id, kind) => {
      rec("select");
      s.kinds.push(kind);
      if (!cfg.selectOk) {
        return false;
      }
      s.selected = id;
      return true;
    },
    restore: () => {
      rec("restore");
      s.selected = "initial";
    },
    allowEnabled: () => {
      if (cfg.throws === "allowEnabled") {
        throw new Error("boom allowEnabled");
      }
      return cfg.enabled(s.t);
    },
    windowActive: () => cfg.active(s.t),
    msSinceShown: () => s.t - cfg.shownAt(s.t),
    delayMs: () => DELAY,
    clickAllow: () => {
      rec("click");
      s.clicks.push({ t: s.t, shownAt: cfg.shownAt(s.t), active: cfg.active(s.t) });
      if (cfg.accepts(s.t) && cfg.active(s.t) && s.t - cfg.shownAt(s.t) >= DELAY) {
        s.gone = true;
      }
    },
    // As the real port: tab maps to "browser", window and screen to
    // themselves.
    sharingShows: (id, kind) => {
      rec("verify");
      s.verifyKinds.push(kind);
      const source = kind === "tab" ? "browser" : kind;
      const devices = cfg.devices ?? [{ mediaSource: source, rawId: s.selected }];
      return (
        cfg.shows(s.t) && devices.some(d => d.mediaSource === source && String(d.rawId) === id)
      );
    },
  };
  const lines = [];
  const run = (args = {}) =>
    runShare({
      port,
      clock,
      mode: "click",
      target: TARGET,
      closePicker: () => s.calls.push("close"),
      stopPreview: () => s.calls.push("stopPreview"),
      timing: TIMING,
      log: line => lines.push(line),
      ...args,
    });
  return { s, run, lines, port };
}

// The calls in order, with repeats in a row folded into one.
function folded(calls) {
  return calls.filter((c, i) => c !== calls[i - 1]);
}

test("selects_closes_waits_then_clicks_once", async () => {
  const { s, run } = setup();
  const outcome = await run();
  assert.equal(outcome, "shared");
  assert.deepEqual(folded(s.calls), [
    "stopPreview",
    "select",
    "close",
    "wait",
    "click",
    "verify",
  ]);
  assert.equal(s.clicks.length, 1);
  assert.ok(s.clicks[0].t - s.clicks[0].shownAt >= DELAY, JSON.stringify(s.clicks));
});

test("never_clicks_before_the_delay_when_it_restarts", async () => {
  const { s, run } = setup({ shownAt: t => (t < 300 ? 0 : 300) });
  const outcome = await run();
  assert.equal(outcome, "shared");
  assert.equal(s.clicks.length, 1);
  assert.ok(s.clicks[0].t >= 800, JSON.stringify(s.clicks));
});

test("never_clicks_while_the_window_is_inactive", async () => {
  const { s, run } = setup({ active: t => t >= 2000 });
  const outcome = await run();
  assert.equal(outcome, "shared");
  assert.ok(s.clicks.length >= 1);
  for (const c of s.clicks) {
    assert.ok(c.t >= 2000 && c.active, JSON.stringify(s.clicks));
  }
});

test("assist_when_the_window_stays_inactive", async () => {
  const { s, run } = setup({ active: () => false });
  const outcome = await run();
  assert.equal(outcome, "assist");
  assert.equal(s.clicks.length, 0);
  assert.ok(s.t >= TIMING.allowWindowMs, "gave up at " + s.t);
  assert.ok(s.t < TIMING.allowWindowMs + 1000, "gave up at " + s.t);
});

test("retries_a_rejected_click_once_then_assists", async () => {
  const { s, run } = setup({ accepts: () => false });
  const outcome = await run();
  assert.equal(outcome, "assist");
  assert.equal(s.clicks.length, 2);
  assert.equal(TIMING.maxClicks, 2);
  assert.equal(s.selected, TARGET.deviceId, "the choice stays selected");
});

test("restores_and_aborts_when_readback_differs", async () => {
  const { s, run } = setup({ readback: () => "7" });
  const outcome = await run();
  assert.equal(outcome, "aborted");
  assert.ok(s.calls.includes("restore"));
  assert.ok(s.calls.includes("close"));
  assert.equal(s.clicks.length, 0);
});

test("restores_and_aborts_when_select_fails", async () => {
  const { s, run } = setup({ selectOk: false });
  const outcome = await run();
  assert.equal(outcome, "aborted");
  assert.ok(s.calls.includes("restore"));
  assert.equal(s.clicks.length, 0);
});

test("aborts_without_click_when_the_prompt_is_gone_before_select", async () => {
  const { s, run } = setup({ current: () => false });
  const outcome = await run();
  assert.equal(outcome, "aborted");
  assert.ok(!s.calls.includes("select"));
  assert.ok(s.calls.includes("close"));
  assert.equal(s.clicks.length, 0);
});

test("aborts_without_click_when_the_prompt_changes", async () => {
  // Current for the select, then replaced while the delay runs.
  const { s, run } = setup({ current: t => t < 100 });
  const outcome = await run();
  assert.equal(outcome, "aborted");
  assert.equal(s.clicks.length, 0);
});

test("assists_without_click_when_the_user_changes_the_selection", async () => {
  const { s, run } = setup({ readback: t => (t >= 100 ? "7" : null) });
  const outcome = await run();
  assert.equal(outcome, "assist");
  assert.equal(s.clicks.length, 0);
  assert.ok(!s.calls.includes("restore"), "the user's own choice is kept");
});

test("assist_mode_never_clicks", async () => {
  const { s, run } = setup();
  const outcome = await run({ mode: "assist" });
  assert.equal(outcome, "assist");
  assert.equal(s.clicks.length, 0);
  assert.deepEqual(s.calls, ["stopPreview", "select", "close"]);
  assert.equal(s.selected, TARGET.deviceId);
});

test("unverified_when_sharing_state_never_shows_the_tab", async () => {
  const { s, run } = setup({ shows: () => false });
  const outcome = await run();
  assert.equal(outcome, "unverified");
  assert.equal(s.clicks.length, 1);
  assert.ok(s.calls.includes("verify"));
});

test("os_target_is_handed_off_without_checking_sharing", async () => {
  const { s, run } = setup();
  const outcome = await run({ target: { kind: "os", deviceId: "0" } });
  assert.equal(outcome, "handed-off");
  assert.equal(s.clicks.length, 1);
  assert.ok(!s.calls.includes("verify"));
});

test("allow_disabled_throughout_means_assist_without_click", async () => {
  const { s, run } = setup({ enabled: () => false });
  const outcome = await run();
  assert.equal(outcome, "assist");
  assert.equal(s.clicks.length, 0);
});

test("a_throwing_port_never_clicks_and_closes_the_picker", async () => {
  const { s, run, lines } = setup({ throws: "select" });
  const outcome = await run();
  assert.equal(outcome, "aborted");
  assert.equal(s.clicks.length, 0);
  assert.ok(s.calls.includes("close"));
  assert.ok(lines.length > 0);
});

// P19: stopPreview is required; without it nothing is selected or clicked.
test("a_missing_stop_preview_aborts_before_select", async () => {
  const { s, run } = setup();
  const outcome = await run({ stopPreview: undefined });
  assert.equal(outcome, "aborted");
  assert.ok(!s.calls.includes("select"), JSON.stringify(s.calls));
  assert.ok(s.calls.includes("close"));
  assert.equal(s.clicks.length, 0);
});

// P19: the port gets the target kind, so it can check it against the entry.
test("select_gets_the_target_kind", async () => {
  const { s, run } = setup();
  await run({ target: { kind: "os", deviceId: "0" } });
  assert.deepEqual(s.kinds, ["os"]);
});

// P18: a throw after a click is never reported as assist, which would tell
// the user to press Allow again.
test("a_throw_after_a_click_is_unverified_not_assist", async () => {
  const { s, run } = setup({ throws: "verify" });
  const outcome = await run();
  assert.equal(outcome, "unverified");
  assert.equal(s.clicks.length, 1);
});

test("a_throw_after_close_but_before_a_click_is_assist", async () => {
  const { s, run } = setup({ throws: "allowEnabled" });
  const outcome = await run();
  assert.equal(outcome, "assist");
  assert.equal(s.clicks.length, 0);
});

// A window share is verified by kind: a tab stream with the same id (a
// window id can equal a tab's browserId) is not that window.
test("verifies_a_window_by_kind", async () => {
  const target = { kind: "window", deviceId: "42" };
  const tab = setup({ devices: [{ mediaSource: "browser", rawId: 42 }] });
  assert.equal(await tab.run({ target }), "unverified");
  assert.deepEqual([...new Set(tab.s.verifyKinds)], ["window"]);
  const win = setup({ devices: [{ mediaSource: "window", rawId: 42 }] });
  assert.equal(await win.run({ target }), "shared");
  assert.deepEqual([...new Set(win.s.verifyKinds)], ["window"]);
});

test("screen_target_runs_the_same_sequence", async () => {
  const { s, run } = setup();
  const outcome = await run({ target: { kind: "screen", deviceId: "3" } });
  assert.equal(outcome, "shared");
  assert.deepEqual(folded(s.calls), ["stopPreview", "select", "close", "wait", "click", "verify"]);
  assert.deepEqual(s.kinds, ["screen"]);
  assert.equal(s.verifyKinds[0], "screen");
  assert.equal(s.clicks.length, 1);
});
