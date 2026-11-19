import test from "node:test";
import assert from "node:assert/strict";
import { delayOf, isArmed, isCancel, isCommit, mayDispatch } from "../../src/lib/arming.mjs";

const times = { openedAt: 1000, activatedAt: null, delayMs: 500 };
const real = { trusted: true, repeat: false };
const enter = { type: "key", key: "Enter" };
const share = { type: "share" };

test("not_armed_before_the_delay_armed_after", () => {
  assert.equal(isArmed(times, 1000), false);
  assert.equal(isArmed(times, 1499), false);
  assert.equal(isArmed(times, 1500), true);
  assert.equal(isArmed(times, 9000), true);
});

test("activate_restarts_the_delay", () => {
  const t = { ...times, activatedAt: 4000 };
  assert.equal(isArmed(t, 3000), false);
  assert.equal(isArmed(t, 4499), false);
  assert.equal(isArmed(t, 4500), true);
  // An activate before the open changes nothing.
  assert.equal(isArmed({ ...times, activatedAt: 200 }, 1500), true);
});

test("a_zero_delay_arms_at_once", () => {
  assert.equal(isArmed({ ...times, delayMs: 0 }, 1000), true);
});

test("unreadable_times_never_arm", () => {
  assert.equal(isArmed({ ...times, openedAt: NaN }, 1e9), false);
  assert.equal(isArmed({ ...times, delayMs: NaN }, 1e9), false);
  assert.equal(isArmed(times, NaN), false);
  assert.equal(isArmed(null, 1e9), false);
});

test("delay_of_respects_the_pref_and_falls_back", () => {
  assert.equal(delayOf(0, 500), 0);
  assert.equal(delayOf(1200, 500), 1200);
  assert.equal(delayOf(-5, 500), 0);
  assert.equal(delayOf(undefined, 500), 500);
  assert.equal(delayOf(NaN, 500), 500);
  assert.equal(delayOf("700", 500), 500);
});

test("commits_are_enter_and_share_only", () => {
  assert.equal(isCommit(enter), true);
  assert.equal(isCommit(share), true);
  for (const a of [
    { type: "key", key: "ArrowDown" },
    { type: "key", key: "Tab" },
    { type: "key", key: "Escape" },
    { type: "click", key: "k" },
    { type: "query", text: "x" },
    { type: "cancel" },
  ]) {
    assert.equal(isCommit(a), false, JSON.stringify(a));
  }
});

test("commit_waits_for_arming", () => {
  assert.equal(mayDispatch(enter, real, times, 1100), false);
  assert.equal(mayDispatch(share, real, times, 1100), false);
  assert.equal(mayDispatch(enter, real, times, 1500), true);
  assert.equal(mayDispatch(share, real, times, 1500), true);
});

test("commit_is_disarmed_again_by_activate", () => {
  const t = { ...times, activatedAt: 5000 };
  assert.equal(mayDispatch(enter, real, t, 5100), false);
  assert.equal(mayDispatch(enter, real, t, 5500), true);
});

test("auto_repeat_never_commits", () => {
  const held = { trusted: true, repeat: true };
  assert.equal(mayDispatch(enter, held, times, 99999), false);
  // A held arrow still moves the highlight.
  assert.equal(mayDispatch({ type: "key", key: "ArrowDown" }, held, times, 1100), true);
});

test("untrusted_events_never_commit", () => {
  assert.equal(mayDispatch(enter, { trusted: false, repeat: false }, times, 99999), false);
  assert.equal(mayDispatch(share, { trusted: false }, times, 99999), false);
  assert.equal(mayDispatch(share, {}, times, 99999), false);
});

const cancel = { type: "cancel" };
const escape = { type: "key", key: "Escape" };

test("cancel_is_never_gated_by_arming", () => {
  for (const a of [cancel, escape]) {
    assert.equal(mayDispatch(a, real, times, 1000), true, JSON.stringify(a));
    assert.equal(mayDispatch(a, real, { ...times, openedAt: NaN }, NaN), true);
  }
});

test("held_escape_never_cancels", () => {
  for (const a of [cancel, escape]) {
    assert.equal(mayDispatch(a, { trusted: true, repeat: true }, times, 99999), false);
  }
});

test("untrusted_cancel_is_ignored", () => {
  for (const a of [cancel, escape]) {
    assert.equal(mayDispatch(a, { trusted: false }, times, 99999), false, JSON.stringify(a));
    assert.equal(mayDispatch(a, {}, times, 99999), false, JSON.stringify(a));
    assert.equal(mayDispatch(a, undefined, times, 99999), false, JSON.stringify(a));
  }
});

test("cancels_are_cancel_and_escape_only", () => {
  assert.equal(isCancel(cancel), true);
  assert.equal(isCancel(escape), true);
  for (const a of [
    enter,
    share,
    { type: "key", key: "ArrowDown" },
    { type: "key", key: "Tab" },
    { type: "click", key: "k" },
    { type: "query", text: "Escape" },
  ]) {
    assert.equal(isCancel(a), false, JSON.stringify(a));
  }
});

test("other_actions_pass_before_arming", () => {
  for (const a of [
    { type: "key", key: "ArrowDown" },
    { type: "key", key: "Escape" },
    { type: "click", key: "k" },
    { type: "query", text: "x" },
    { type: "cancel" },
  ]) {
    assert.equal(mayDispatch(a, real, times, 1000), true, JSON.stringify(a));
  }
});
