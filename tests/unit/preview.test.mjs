import test from "node:test";
import assert from "node:assert/strict";
import { startLive, liveTarget, dwellTargets, LIVE_DWELL_MS } from "../../src/glue/preview.sys.mjs";
import { buildModel } from "../../src/lib/rows.mjs";
import { captureRows } from "../../src/lib/captures.mjs";
import { initialState, reduce } from "../../src/lib/state.mjs";

function deferred() {
  let resolve;
  let reject;
  const d = { settled: false };
  d.promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  d.resolve = v => {
    d.settled = true;
    resolve(v);
  };
  d.reject = e => {
    d.settled = true;
    reject(e);
  };
  return d;
}

const flush = () => new Promise(r => setImmediate(r));

// A fake <webrtc-preview>. Each `updateComplete` read and each startPreview
// call hands out a promise the test settles. A start is open from its
// startPreview call until the next stopPreview; `maxOpen` is the most open at
// once. Unlike the real element, startPreview does not stop the previous
// capture, so the controller alone must keep captures to one.
function fakeWin({ auto = true } = {}) {
  const h = {
    log: [],
    created: [],
    open: 0,
    maxOpen: 0,
    updates: [],
    starts: [],
    throwOnStart: false,
  };
  function makeEl(tag) {
    const classes = new Set();
    const el = {
      tag,
      hidden: false,
      removed: false,
      classList: { add: c => classes.add(c), contains: c => classes.has(c) },
      get updateComplete() {
        const d = deferred();
        h.updates.push(d);
        if (auto) {
          d.resolve(true);
        }
        return d.promise;
      },
      startPreview(opts) {
        h.log.push(["start", opts.deviceId, opts.mediaSource]);
        if (h.throwOnStart) {
          throw new Error("boom");
        }
        h.open++;
        h.maxOpen = Math.max(h.maxOpen, h.open);
        const d = deferred();
        h.starts.push(d);
        if (auto) {
          d.resolve();
        }
        return d.promise;
      },
      stopPreview() {
        h.log.push(["stop"]);
        h.open = 0;
      },
      remove() {
        el.removed = true;
      },
    };
    return el;
  }
  const container = { children: [], append: el => container.children.push(el) };
  const win = {
    document: {
      createElement(tag) {
        const el = makeEl(tag);
        h.created.push(el);
        return el;
      },
    },
  };
  return { win, container, h };
}

const W1 = { deviceId: "w1", mediaSource: "window" };
const W2 = { deviceId: "w2", mediaSource: "window" };
const S1 = { deviceId: "s1", mediaSource: "screen" };
const T1 = { deviceId: "t1", mediaSource: "browser" };

test("nothing_is_created_or_started_until_a_target", async () => {
  const { win, container, h } = fakeWin();
  const live = startLive(win, container);
  await live.setTarget(null);
  assert.equal(h.created.length, 0);
  assert.equal(container.children.length, 0);
  assert.deepEqual(h.log, []);
  assert.equal(live.isLive(), false);
  await live.setTarget(W1);
  assert.equal(h.created.length, 1);
  const el = h.created[0];
  assert.equal(el.tag, "webrtc-preview");
  assert.ok(el.classList.contains("zsp-live"));
  assert.deepEqual(container.children, [el]);
  assert.deepEqual(h.log.at(-1), ["start", "w1", "window"]);
  assert.equal(live.isLive(), true);
});

test("the_same_target_is_a_no_op", async () => {
  const { win, container, h } = fakeWin();
  const live = startLive(win, container);
  await live.setTarget(W1);
  const before = h.log.length;
  await live.setTarget({ ...W1 });
  assert.equal(h.log.length, before);
  await live.setTarget({ deviceId: "w1", mediaSource: "screen" });
  assert.deepEqual(h.log.at(-1), ["start", "w1", "screen"]);
});

test("a_new_target_stops_the_old_before_starting", async () => {
  const { win, container, h } = fakeWin();
  const live = startLive(win, container);
  await live.setTarget(W1);
  h.log.length = 0;
  await live.setTarget(S1);
  assert.deepEqual(h.log, [["stop"], ["start", "s1", "screen"]]);
  assert.equal(h.created.length, 1);
});

function mulberry32(seed) {
  let a = seed;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

test("never_two_captures_at_once", async () => {
  for (const seed of [1, 7, 42]) {
    const rand = mulberry32(seed);
    const { win, container, h } = fakeWin({ auto: false });
    const live = startLive(win, container);
    const targets = [null, W1, W2, S1, T1];
    const pending = [];
    for (let i = 0; i < 200; i++) {
      pending.push(live.setTarget(targets[Math.floor(rand() * targets.length)]));
      // Settle a random handful of the open promises, out of order.
      const open = [...h.updates, ...h.starts].filter(d => !d.settled);
      for (let k = Math.floor(rand() * 3); k > 0 && open.length > 0; k--) {
        const d = open.splice(Math.floor(rand() * open.length), 1)[0];
        if (rand() < 0.15) {
          d.reject(new Error("no"));
        } else {
          d.resolve(true);
        }
      }
      await flush();
      assert.ok(h.open <= 1, `seed ${seed} step ${i}: ${h.open} open`);
    }
    for (let round = 0; round < 10; round++) {
      for (const d of [...h.updates, ...h.starts]) {
        if (!d.settled) {
          d.resolve(true);
        }
      }
      await flush();
    }
    await Promise.all(pending);
    assert.ok(h.maxOpen <= 1, `seed ${seed}: max ${h.maxOpen} open`);
  }
});

test("a_start_that_resolves_after_a_move_is_halted", async () => {
  const { win, container, h } = fakeWin({ auto: false });
  const live = startLive(win, container);
  const first = live.setTarget(W1);
  h.updates[0].resolve(true);
  await flush();
  assert.deepEqual(h.log, [["start", "w1", "window"]]);
  live.setTarget(null);
  h.log.length = 0;
  h.starts[0].resolve();
  await first;
  assert.deepEqual(h.log, [["stop"]]);
  assert.equal(live.isLive(), false);
});

test("a_late_start_never_stops_the_newer_one", async () => {
  const { win, container, h } = fakeWin({ auto: false });
  const live = startLive(win, container);
  const first = live.setTarget(W1);
  h.updates[0].resolve(true);
  await flush();
  const second = live.setTarget(S1);
  h.updates[1].resolve(true);
  await flush();
  assert.deepEqual(h.log.slice(-2), [["stop"], ["start", "s1", "screen"]]);
  h.log.length = 0;
  h.starts[0].resolve();
  h.starts[1].resolve();
  await Promise.all([first, second]);
  assert.deepEqual(h.log, []);
  assert.equal(live.isLive(), true);
});

test("a_start_after_update_complete_is_skipped_when_moved", async () => {
  const { win, container, h } = fakeWin({ auto: false });
  const live = startLive(win, container);
  const first = live.setTarget(W1);
  live.setTarget(null);
  h.updates[0].resolve(true);
  await flush();
  assert.ok(!h.log.some(e => e[0] === "start"));
  await first;
});

test("null_target_halts_and_hides", async () => {
  const { win, container, h } = fakeWin();
  const live = startLive(win, container);
  await live.setTarget(W1);
  const el = h.created[0];
  assert.equal(el.hidden, false);
  h.log.length = 0;
  const p = live.setTarget(null);
  // At once, before any await.
  assert.deepEqual(h.log, [["stop"]]);
  assert.equal(el.hidden, true);
  assert.equal(live.isLive(), false);
  await p;
  await live.setTarget(W1);
  assert.equal(el.hidden, false);
});

test("stop_removes_the_element_and_ignores_later_targets", async () => {
  const { win, container, h } = fakeWin();
  const live = startLive(win, container);
  await live.setTarget(W1);
  const el = h.created[0];
  h.log.length = 0;
  live.stop();
  assert.deepEqual(h.log, [["stop"]]);
  assert.equal(el.removed, true);
  assert.equal(live.isLive(), false);
  await live.setTarget(S1);
  live.stop();
  assert.deepEqual(h.log, [["stop"]]);
  assert.equal(h.created.length, 1);
});

test("stop_before_any_target_creates_nothing", async () => {
  const { win, container, h } = fakeWin();
  const live = startLive(win, container);
  live.stop();
  await live.setTarget(W1);
  assert.equal(h.created.length, 0);
  assert.deepEqual(h.log, []);
});

test("disabled_never_creates_nor_starts", async () => {
  const { win, container, h } = fakeWin();
  const live = startLive(win, container, { enabled: false });
  for (const t of [W1, S1, T1, null, W2]) {
    await live.setTarget(t);
  }
  live.stop();
  assert.equal(h.created.length, 0);
  assert.deepEqual(h.log, []);
  assert.equal(live.isLive(), false);
});

test("a_window_start_writes_no_permission", async () => {
  const touched = [];
  const spy = new Proxy(
    {},
    {
      get(_, prop) {
        touched.push(String(prop));
        return spy;
      },
      apply() {
        touched.push("call");
        return spy;
      },
    }
  );
  globalThis.Services = spy;
  try {
    const { win, container } = fakeWin();
    const live = startLive(win, container, { beforeStart: () => touched.push("hook") });
    await live.setTarget(W1);
    await live.setTarget(S1);
    live.stop();
  } finally {
    delete globalThis.Services;
  }
  assert.deepEqual(touched, []);
});

test("a_throw_in_start_preview_halts", async () => {
  const { win, container, h } = fakeWin();
  const live = startLive(win, container);
  h.throwOnStart = true;
  await live.setTarget(W1);
  assert.deepEqual(h.log, [["start", "w1", "window"], ["stop"]]);
  assert.equal(live.isLive(), false);
  assert.equal(h.created[0].hidden, true);
});

test("a_rejected_start_halts", async () => {
  const { win, container, h } = fakeWin({ auto: false });
  const live = startLive(win, container);
  const p = live.setTarget(S1);
  h.updates[0].resolve(true);
  await flush();
  h.starts[0].reject(new Error("denied"));
  await p;
  assert.deepEqual(h.log, [["start", "s1", "screen"], ["stop"]]);
  assert.equal(live.isLive(), false);
  assert.equal(h.created[0].hidden, true);
});

// The contract: a window or screen is a target only while the Windows view
// shows and its highlighted key is visible.

const here = { spaceId: "work", ucid: 1 };
const names = new Map([["work", "Work"]]);
const tab = (key, over = {}) => ({
  deviceId: "dev-" + key,
  syncKey: key,
  inPromptWindow: true,
  contentsVisible: true,
  lastAccessed: 0,
  title: "Title " + key,
  host: key + ".example",
  icon: "",
  spaceId: "work",
  essential: false,
  ucid: null,
  requesting: false,
  ...over,
});
const entry = (mediaSource, deviceId, label) => ({ mediaSource, deviceId, label });
const noZen = { ok: true, ids: new Set() };

function windowsModel(entries = [entry("screen", "s1", "Screen"), entry("window", "w1", "Alpha"), entry("window", "w2", "Beta")]) {
  return buildModel([tab("a")], here, names, { available: true }, captureRows(entries, null, noZen).rows);
}

test("contract_only_the_visible_window_highlight_is_a_target", () => {
  const m = windowsModel();
  const s = initialState(m);
  assert.equal(s.view, "tabs");
  assert.equal(liveTarget(m, s), null);
  assert.equal(liveTarget(m, { ...s, windowHighlight: "window:w1" }), null);
  const w = { ...s, view: "windows", windowHighlight: null };
  assert.equal(liveTarget(m, w), null);
  assert.deepEqual(liveTarget(m, { ...w, windowHighlight: "window:w1" }), W1);
  assert.deepEqual(liveTarget(m, { ...w, windowHighlight: "screen:s1" }), S1);
  assert.equal(liveTarget(m, { ...w, windowHighlight: "os" }), null);
  assert.equal(liveTarget(m, { ...w, windowHighlight: "a" }), null);
  assert.equal(liveTarget(m, { ...w, windowHighlight: "window:gone" }), null);
  assert.equal(liveTarget(m, { ...w, windowHighlight: "window:w1", query: "beta" }), null);
  assert.deepEqual(liveTarget(m, { ...w, windowHighlight: "window:w2", query: "beta" }), W2);
});

function follow(m, s, live) {
  return live.setTarget(liveTarget(m, s));
}

test("contract_switching_to_windows_starts_nothing_until_a_highlight", async () => {
  const m = windowsModel();
  const { win, container, h } = fakeWin();
  const live = startLive(win, container);
  let s = initialState(m);
  await follow(m, s, live);
  s = reduce(m, s, { type: "switch", view: "windows" }).state;
  await follow(m, s, live);
  assert.equal(h.created.length, 0);
  s = reduce(m, s, { type: "key", key: "ArrowDown" }).state;
  await follow(m, s, live);
  assert.deepEqual(h.log, [["start", "s1", "screen"]]);
});

test("contract_a_switch_to_tabs_stops_at_once", async () => {
  const m = windowsModel();
  const { win, container, h } = fakeWin();
  const live = startLive(win, container);
  let s = reduce(m, initialState(m), { type: "switch", view: "windows" }).state;
  s = reduce(m, s, { type: "click", key: "window:w1" }).state;
  await follow(m, s, live);
  assert.equal(live.isLive(), true);
  h.log.length = 0;
  s = reduce(m, s, { type: "switch", view: "tabs" }).state;
  follow(m, s, live);
  assert.deepEqual(h.log, [["stop"]]);
  assert.equal(live.isLive(), false);
});

test("contract_a_hidden_or_vanished_row_stops_at_once", async () => {
  const m = windowsModel();
  const { win, container, h } = fakeWin();
  const live = startLive(win, container);
  let s = reduce(m, initialState(m), { type: "switch", view: "windows" }).state;
  s = reduce(m, s, { type: "click", key: "window:w1" }).state;
  await follow(m, s, live);
  h.log.length = 0;
  follow(m, { ...s, query: "beta" }, live);
  assert.deepEqual(h.log, [["stop"]]);
  await follow(m, s, live);
  h.log.length = 0;
  const reshown = windowsModel([entry("screen", "s1", "Screen"), entry("window", "w2", "Beta")]);
  follow(reshown, s, live);
  assert.deepEqual(h.log, [["stop"]]);
  assert.equal(live.isLive(), false);
});

test("contract_holds_over_a_random_walk", async () => {
  const models = [
    windowsModel(),
    windowsModel([entry("window", "w2", "Beta")]),
    windowsModel([entry("screen", "s1", "Screen"), entry("window", "w1", "Alpha")]),
  ];
  const actions = [
    { type: "switch", view: "windows" },
    { type: "switch", view: "tabs" },
    { type: "key", key: "ArrowDown" },
    { type: "key", key: "ArrowUp" },
    { type: "key", key: "Home" },
    { type: "key", key: "End" },
    { type: "query", text: "" },
    { type: "query", text: "al" },
    { type: "query", text: "beta" },
    { type: "click", key: "window:w1" },
    { type: "click", key: "screen:s1" },
    { type: "click", key: "os" },
  ];
  const rand = mulberry32(2026);
  const { win, container, h } = fakeWin();
  const live = startLive(win, container);
  let m = models[0];
  let s = initialState(m);
  for (let i = 0; i < 300; i++) {
    if (rand() < 0.1) {
      m = models[Math.floor(rand() * models.length)];
    } else {
      s = reduce(m, s, actions[Math.floor(rand() * actions.length)]).state;
    }
    const t = liveTarget(m, s);
    const p = follow(m, s, live);
    if (t === null) {
      assert.equal(h.open, 0, `step ${i}: a capture outlived its highlight`);
      assert.equal(live.isLive(), false);
    } else {
      assert.equal(s.view, "windows");
    }
    await p;
    if (t !== null) {
      const last = h.log.findLast(e => e[0] === "start");
      assert.deepEqual(last, ["start", t.deviceId, t.mediaSource], `step ${i}`);
      assert.equal(live.isLive(), true);
    }
    assert.ok(h.maxOpen <= 1);
  }
});

test("has_frame_only_while_live_with_a_sized_video", async () => {
  const { win, container, h } = fakeWin();
  const live = startLive(win, container);
  assert.equal(live.hasFrame(), false);
  await live.setTarget(W1);
  const el = h.created[0];
  assert.equal(live.hasFrame(), false);
  el.videoEl = { videoWidth: 0 };
  assert.equal(live.hasFrame(), false);
  el.videoEl.videoWidth = 640;
  assert.equal(live.hasFrame(), true);
  await live.setTarget(null);
  assert.equal(live.hasFrame(), false);
  await live.setTarget(S1);
  assert.equal(live.hasFrame(), true);
  live.stop();
  assert.equal(live.hasFrame(), false);
});

test("has_frame_is_false_after_a_failed_start", async () => {
  const { win, container, h } = fakeWin();
  h.throwOnStart = true;
  const live = startLive(win, container);
  await live.setTarget(W1);
  h.created[0].videoEl = { videoWidth: 640 };
  assert.equal(live.isLive(), false);
  assert.equal(live.hasFrame(), false);
});

// A fake clock: timers fire only when the test advances time.
function fakeClock() {
  let now = 0;
  let next = 0;
  const timers = new Map();
  return {
    setTimeout(fn, ms) {
      timers.set(++next, { at: now + ms, fn });
      return next;
    },
    clearTimeout(id) {
      timers.delete(id);
    },
    advance(ms) {
      now += ms;
      const due = [...timers].filter(([, t]) => t.at <= now).sort((a, b) => a[1].at - b[1].at);
      for (const [id, t] of due) {
        timers.delete(id);
        t.fn();
      }
    },
    pending: () => timers.size,
  };
}

function dwelling() {
  const clock = fakeClock();
  const applied = [];
  const d = dwellTargets(clock, t => applied.push(t), LIVE_DWELL_MS);
  return { clock, applied, d };
}

test("dwell_is_150_ms", () => {
  assert.equal(LIVE_DWELL_MS, 150);
});

test("dwell_a_quick_pass_starts_no_capture", () => {
  const { clock, applied, d } = dwelling();
  for (const t of [S1, W1, W2]) {
    d.set(t);
    clock.advance(LIVE_DWELL_MS - 1);
  }
  assert.deepEqual(applied, []);
  clock.advance(1);
  assert.deepEqual(applied, [W2]);
});

test("dwell_resting_starts_exactly_one", () => {
  const { clock, applied, d } = dwelling();
  d.set(W1);
  clock.advance(LIVE_DWELL_MS);
  assert.deepEqual(applied, [W1]);
  clock.advance(10 * LIVE_DWELL_MS);
  assert.deepEqual(applied, [W1]);
  assert.equal(clock.pending(), 0);
});

test("dwell_a_null_stops_at_once", () => {
  const { clock, applied, d } = dwelling();
  d.set(W1);
  clock.advance(LIVE_DWELL_MS);
  d.set(null);
  assert.deepEqual(applied, [W1, null]);
  d.set(W2);
  d.set(null);
  clock.advance(10 * LIVE_DWELL_MS);
  assert.deepEqual(applied, [W1, null]);
});

test("dwell_a_move_stops_the_old_capture_at_once", () => {
  const { clock, applied, d } = dwelling();
  d.set(W1);
  clock.advance(LIVE_DWELL_MS);
  d.set(S1);
  assert.deepEqual(applied, [W1, null]);
  clock.advance(LIVE_DWELL_MS);
  assert.deepEqual(applied, [W1, null, S1]);
});

test("dwell_cancel_drops_a_pending_target", () => {
  const { clock, applied, d } = dwelling();
  d.set(W1);
  d.cancel();
  clock.advance(10 * LIVE_DWELL_MS);
  assert.deepEqual(applied, []);
});

test("dwell_over_the_live_controller_a_quick_pass_starts_nothing", async () => {
  const clock = fakeClock();
  const { win, container, h } = fakeWin();
  const live = startLive(win, container);
  const d = dwellTargets(clock, t => live.setTarget(t), LIVE_DWELL_MS);
  for (const t of [S1, W1, W2, S1]) {
    d.set(t);
    clock.advance(50);
  }
  await flush();
  assert.equal(h.created.length, 0);
  assert.deepEqual(h.log, []);
  clock.advance(LIVE_DWELL_MS);
  await flush();
  assert.deepEqual(h.log.filter(e => e[0] === "start"), [["start", "s1", "screen"]]);
});
