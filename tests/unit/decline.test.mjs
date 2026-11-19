import test from "node:test";
import assert from "node:assert/strict";
import { runDecline } from "../../src/lib/decline.mjs";
import { TIMING } from "../../src/lib/config.mjs";

// A fake stock prompt on a virtual clock: `sleep` advances time, nothing
// waits for real.
//   current       isCurrent() before the abandon
//   goneOnAbandon abandon() takes the notification away
//   goneAt        the notification goes on its own at this time (or never)
//   abandonThrows abandon() throws, after taking it away when goneOnAbandon
function setup(over = {}) {
  const cfg = {
    current: true,
    goneOnAbandon: true,
    goneAt: Infinity,
    abandonThrows: false,
    ...over,
  };
  const s = { t: 0, gone: false, calls: [], abandons: 0, reveals: 0 };
  const clock = {
    now: () => s.t,
    sleep: async ms => {
      assert.ok(ms > 0, "sleep(" + ms + ")");
      s.calls.push("wait");
      s.t += ms;
    },
  };
  const port = {
    isCurrent: () => {
      s.calls.push("current");
      return cfg.current;
    },
    abandon: () => {
      s.calls.push("abandon");
      s.abandons += 1;
      if (cfg.goneOnAbandon) {
        s.gone = true;
      }
      if (cfg.abandonThrows) {
        throw new Error("x");
      }
    },
    isGone: () => {
      s.calls.push("gone");
      return s.gone || s.t >= cfg.goneAt;
    },
  };
  const lines = [];
  const run = () =>
    runDecline({
      port,
      clock,
      timing: TIMING,
      log: line => lines.push(line),
      reveal: () => {
        s.calls.push("reveal");
        s.reveals += 1;
      },
    });
  return { s, lines, run };
}

const PATHS = {
  declined: {},
  gone_later: { goneOnAbandon: false, goneAt: 200 },
  kept: { current: false },
  stays: { goneOnAbandon: false },
  throw_gone: { abandonThrows: true },
  throw_stays: { abandonThrows: true, goneOnAbandon: false },
};

test("declines_with_one_abandon", async () => {
  const { s, lines, run } = setup();
  assert.equal(await run(), "declined");
  assert.equal(s.abandons, 1);
  assert.equal(s.reveals, 1);
  assert.ok(lines.includes("decline: abandon"), lines.join("|"));
  assert.ok(lines.includes("decline: declined"), lines.join("|"));
});

test("checks_and_abandon_run_in_one_step", async () => {
  for (const [name, over] of Object.entries(PATHS)) {
    const { s, run } = setup(over);
    await run();
    const at = s.calls.indexOf("abandon");
    if (at >= 0) {
      assert.ok(!s.calls.slice(0, at).includes("wait"), name + ": " + s.calls.join(","));
      assert.equal(s.calls[at - 1], "current", name + ": " + s.calls.join(","));
    }
  }
});

test("gone_is_checked_before_any_sleep", async () => {
  const { s, run } = setup();
  assert.equal(await run(), "declined");
  assert.ok(!s.calls.includes("wait"), s.calls.join(","));
  assert.deepEqual(s.calls, ["current", "abandon", "gone", "reveal"]);
  // When it is not gone at once, the first check still comes before a sleep,
  // and the reveal right after it.
  const later = setup(PATHS.gone_later);
  assert.equal(await later.run(), "declined");
  assert.deepEqual(later.s.calls.slice(0, 4), ["current", "abandon", "gone", "reveal"]);
  assert.ok(later.s.t >= 200 && later.s.t < TIMING.goneWaitMs, String(later.s.t));
});

test("gone_prompt_is_never_abandoned", async () => {
  const { s, lines, run } = setup(PATHS.kept);
  assert.equal(await run(), "kept");
  assert.equal(s.abandons, 0);
  assert.equal(s.reveals, 1);
  assert.ok(lines.includes("decline: kept not-current"), lines.join("|"));
});

test("a_prompt_that_stays_fails_after_one_abandon", async () => {
  const { s, lines, run } = setup(PATHS.stays);
  assert.equal(await run(), "failed");
  assert.equal(s.abandons, 1);
  assert.ok(s.t >= TIMING.goneWaitMs, String(s.t));
  assert.ok(s.t < TIMING.goneWaitMs + 2 * TIMING.pollMs, String(s.t));
  assert.equal(s.reveals, 1);
  assert.ok(lines.includes("decline: failed not-gone"), lines.join("|"));
});

test("a_throw_in_abandon_is_checked_for_gone", async () => {
  const gone = setup(PATHS.throw_gone);
  assert.equal(await gone.run(), "declined");
  assert.equal(gone.s.abandons, 1);
  // The log reads in the order things happened: the abandon, then its error.
  assert.deepEqual(gone.lines, ["decline: abandon", "decline: error Error", "decline: declined"]);
  assert.ok(!gone.s.calls.includes("wait"), gone.s.calls.join(","));

  const stays = setup(PATHS.throw_stays);
  assert.equal(await stays.run(), "failed");
  assert.equal(stays.s.abandons, 1);
  assert.ok(stays.lines.includes("decline: failed error"), stays.lines.join("|"));
});

test("a_throw_while_checking_fails_after_reveal", async () => {
  for (const where of ["isCurrent", "isGone"]) {
    const { s, run } = setup();
    const port = { isCurrent: () => true, abandon: () => s.abandons++, isGone: () => false };
    port[where] = () => {
      throw new Error("x");
    };
    const lines = [];
    const out = await runDecline({
      port,
      clock: { now: () => s.t, sleep: async ms => (s.t += ms) },
      timing: TIMING,
      log: line => lines.push(line),
      reveal: () => s.reveals++,
    });
    assert.equal(out, "failed", where);
    assert.equal(s.reveals, 1, where);
    assert.ok(s.abandons <= 1, where);
  }
});

test("reveal_runs_exactly_once", async () => {
  for (const [name, over] of Object.entries(PATHS)) {
    const { s, run } = setup(over);
    await run();
    assert.equal(s.reveals, 1, name);
    assert.ok(s.abandons <= 1, name);
  }
});
