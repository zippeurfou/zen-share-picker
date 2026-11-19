import test from "node:test";
import assert from "node:assert/strict";
import { buildModel } from "../../src/lib/rows.mjs";
import {
  initialState,
  visibleRows,
  hints,
  reduce,
} from "../../src/lib/state.mjs";

function fact(key, over = {}) {
  return {
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
  };
}

const names = new Map([["work", "Work"], ["perso", "Perso"]]);
const here = { spaceId: "work", ucid: 1 };

function model(extraOthers = 1) {
  const facts = [
    fact("a", { lastAccessed: 30 }),
    fact("b", { lastAccessed: 20 }),
    fact("req", { lastAccessed: 99, requesting: true }),
  ];
  for (let i = 0; i < extraOthers; i++) {
    facts.push(fact("o" + i, { spaceId: "perso", lastAccessed: 10 - i }));
  }
  return buildModel(facts, here, names, { available: true });
}

const keys = (m, s) => visibleRows(m, s).map(r => r.key);
const press = (m, s, key) => reduce(m, s, { type: "key", key });
const codes = (m, s) => hints(m, s).map(h => h.code);

test("initial_highlight_is_tab_used_before_requesting_tab", () => {
  const m = model();
  assert.equal(initialState(m).highlight, "a");
});

test("requesting_tab_never_preselected", () => {
  const only = buildModel([fact("req", { requesting: true })], here, names, { available: true });
  assert.equal(initialState(only).highlight, null);
  const m = model();
  const s = initialState(m);
  const onlyReq = reduce(m, { ...s, highlight: "a" }, { type: "query", text: "req" }).state;
  assert.deepEqual(keys(m, onlyReq), ["req", "os"]);
  assert.equal(onlyReq.highlight, null);
  const viaReq = reduce(m, { ...s, highlight: "req" }, { type: "query", text: "req" }).state;
  assert.equal(viaReq.highlight, "req");
});

test("query_moves_highlight_to_first_visible_tab_or_keeps_it", () => {
  const m = model();
  const s = initialState(m);
  assert.equal(reduce(m, s, { type: "query", text: "b" }).state.highlight, "b");
  const kept = reduce(m, { ...s, highlight: "b" }, { type: "query", text: "e" }).state;
  assert.equal(kept.highlight, "b");
  const os = reduce(m, { ...s, highlight: "os" }, { type: "query", text: "zzz" }).state;
  assert.equal(os.highlight, "os");
});

test("hidden_other_rows_cannot_be_clicked_confirmed_or_shared", () => {
  const m = model();
  const s = initialState(m);
  const clicked = reduce(m, s, { type: "click", key: "o0" });
  assert.equal(clicked.state.highlight, "a");
  assert.equal(clicked.effect, null);
  const unknown = reduce(m, s, { type: "click", key: "nope" });
  assert.equal(unknown.state.highlight, "a");
  const forced = { ...s, highlight: "o0" };
  for (const action of [{ type: "key", key: "Enter" }, { type: "share" }]) {
    const r = reduce(m, forced, action);
    assert.equal(r.effect, null);
    assert.equal(r.state.confirming, null);
    assert.deepEqual(hints(m, r.state).map(h => h.code), ["reveal", "asleep"]);
  }
  const confirming = { ...forced, confirming: "o0" };
  assert.equal(reduce(m, confirming, { type: "share" }).effect, null);
});

test("others_absent_from_visible_rows_until_tab", () => {
  const m = model();
  let s = initialState(m);
  assert.deepEqual(keys(m, s), ["a", "b", "req", "os"]);
  s = press(m, s, "Tab").state;
  assert.deepEqual(keys(m, s), ["a", "b", "req", "o0", "os"]);
});

test("query_never_reveals_and_shows_no_match_hint", () => {
  const m = model();
  let s = initialState(m);
  s = reduce(m, s, { type: "query", text: "o0" }).state;
  assert.equal(s.revealed, false);
  assert.deepEqual(keys(m, s), ["os"]);
  assert.equal(s.highlight, null);
  assert.deepEqual(codes(m, s), ["no-match", "asleep"]);
  assert.equal(hints(m, s)[0].text, "No match here. Tab to search other spaces.");
});

test("reveal_hint_has_no_count", () => {
  const text = "Tab: show tabs from your other spaces";
  for (const n of [1, 5]) {
    const m = model(n);
    assert.equal(hints(m, initialState(m))[0].text, text);
  }
  const none = model(0);
  assert.deepEqual(codes(none, initialState(none)), ["asleep"]);
});

test("enter_on_here_row_shares", () => {
  const m = model();
  const r = press(m, initialState(m), "Enter");
  assert.deepEqual(r.effect, { type: "share", deviceId: "dev-a" });
  assert.deepEqual(reduce(m, initialState(m), { type: "share" }).effect, r.effect);
});

test("enter_on_revealed_row_needs_second_enter", () => {
  const m = model();
  let s = press(m, initialState(m), "Tab").state;
  s = reduce(m, s, { type: "click", key: "o0" }).state;
  let r = press(m, s, "Enter");
  assert.equal(r.effect, null);
  assert.equal(r.state.confirming, "o0");
  assert.deepEqual(hints(m, r.state).map(h => h.code), ["confirm", "asleep"]);
  assert.equal(hints(m, r.state)[0].text, "Press Enter again to share a tab from Perso.");
  r = press(m, r.state, "Enter");
  assert.deepEqual(r.effect, { type: "share", deviceId: "dev-o0" });
});

test("moving_clears_confirm", () => {
  const m = model();
  let s = press(m, initialState(m), "Tab").state;
  s = reduce(m, s, { type: "click", key: "o0" }).state;
  s = press(m, s, "Enter").state;
  assert.equal(s.confirming, "o0");
  assert.equal(press(m, s, "ArrowUp").state.confirming, null);
  assert.equal(reduce(m, s, { type: "query", text: "" }).state.confirming, null);
  assert.equal(reduce(m, s, { type: "click", key: "a" }).state.confirming, null);
});

test("tab_that_changes_nothing_still_clears_confirm", () => {
  const m = model();
  let s = press(m, initialState(m), "Tab").state;
  s = reduce(m, s, { type: "click", key: "o0" }).state;
  s = press(m, s, "Enter").state;
  const r = press(m, s, "Tab");
  assert.equal(r.state.revealed, true);
  assert.equal(r.state.highlight, "o0");
  assert.equal(r.state.confirming, null);
  assert.equal(r.effect, null);
});

test("arrows_clamp_and_home_end", () => {
  const m = model();
  let s = initialState(m);
  s = press(m, s, "ArrowUp").state;
  assert.equal(s.highlight, "a");
  s = press(m, s, "End").state;
  assert.equal(s.highlight, "os");
  s = press(m, s, "ArrowDown").state;
  assert.equal(s.highlight, "os");
  s = press(m, s, "Home").state;
  assert.equal(s.highlight, "a");
  const from = { ...s, highlight: null };
  assert.equal(press(m, from, "ArrowUp").state.highlight, "a");
});

test("enter_on_os_row_hands_off", () => {
  const m = model();
  const s = reduce(m, initialState(m), { type: "click", key: "os" }).state;
  assert.deepEqual(press(m, s, "Enter").effect, { type: "os" });
});

test("enter_with_no_highlight_does_nothing", () => {
  const m = model();
  const s = { ...initialState(m), highlight: null };
  assert.equal(press(m, s, "Enter").effect, null);
});

test("escape_cancels", () => {
  const m = model();
  assert.deepEqual(press(m, initialState(m), "Escape").effect, { type: "cancel" });
  assert.deepEqual(reduce(m, initialState(m), { type: "cancel" }).effect, { type: "cancel" });
});

test("os_row_always_last_and_unfiltered", () => {
  const m = model();
  let s = initialState(m);
  assert.equal(keys(m, s).at(-1), "os");
  s = reduce(m, s, { type: "query", text: "zzz" }).state;
  assert.deepEqual(keys(m, s), ["os"]);
  s = press(m, s, "Tab").state;
  assert.deepEqual(keys(m, s), ["os"]);
});

test("asleep_hint_always_present", () => {
  const m = model();
  let s = initialState(m);
  const text = "Don't see a tab? Tabs that are asleep can't be shared; open it first.";
  for (const st of [s, press(m, s, "Tab").state, reduce(m, s, { type: "query", text: "zzz" }).state]) {
    const h = hints(m, st);
    assert.equal(h.at(-1).code, "asleep");
    assert.equal(h.at(-1).text, text);
  }
});
