import test from "node:test";
import assert from "node:assert/strict";
import { buildModel } from "../../src/lib/rows.mjs";
import {
  initialState,
  visibleRows,
  hints,
  reduce,
  hasTabs,
  windowRows,
  hasWindows,
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
  assert.deepEqual(keys(m, onlyReq), ["req"]);
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
  const none = reduce(m, { ...s, highlight: "b" }, { type: "query", text: "zzz" }).state;
  assert.equal(none.highlight, null);
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
  assert.deepEqual(keys(m, s), ["a", "b", "req"]);
  s = press(m, s, "Tab").state;
  assert.deepEqual(keys(m, s), ["a", "b", "req", "o0"]);
});

test("query_never_reveals_and_shows_no_match_hint", () => {
  const m = model();
  let s = initialState(m);
  s = reduce(m, s, { type: "query", text: "o0" }).state;
  assert.equal(s.revealed, false);
  assert.deepEqual(keys(m, s), []);
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
  assert.deepEqual(r.effect, { type: "share", kind: "tab", deviceId: "dev-a" });
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
  assert.deepEqual(r.effect, { type: "share", kind: "tab", deviceId: "dev-o0" });
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
  assert.equal(s.highlight, "req");
  s = press(m, s, "ArrowDown").state;
  assert.equal(s.highlight, "req");
  s = press(m, s, "Home").state;
  assert.equal(s.highlight, "a");
  const from = { ...s, highlight: null };
  assert.equal(press(m, from, "ArrowUp").state.highlight, "a");
});

test("the_os_row_cannot_be_reached_from_tabs", () => {
  const m = model();
  const s = initialState(m);
  assert.equal(reduce(m, s, { type: "click", key: "os" }).state.highlight, "a");
  const forced = { ...s, highlight: "os" };
  assert.equal(press(m, forced, "Enter").effect, null);
  assert.equal(reduce(m, forced, { type: "share" }).effect, null);
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

test("tab_rows_no_longer_end_with_the_os_row", () => {
  const m = model();
  let s = initialState(m);
  assert.equal(m.os.available, true);
  assert.deepEqual(keys(m, s), ["a", "b", "req"]);
  s = press(m, s, "Tab").state;
  assert.equal(keys(m, s).includes("os"), false);
  s = reduce(m, s, { type: "query", text: "zzz" }).state;
  assert.deepEqual(keys(m, s), []);
  const w = reduce(m, s, { type: "switch", view: "windows" }).state;
  assert.deepEqual(keys(m, w), ["os"]);
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

const cap = (kind, id, title) => ({
  key: kind + ":" + id,
  deviceId: id,
  kind,
  title,
  host: "",
  group: "capture",
});
const CAPS = [cap("screen", "s1", "Main display"), cap("window", "w1", "Editor"), cap("window", "w2", "Notes")];

function wmodel({ tabs = true, os = true, caps = CAPS } = {}) {
  const facts = tabs ? [fact("a", { lastAccessed: 30 }), fact("o0", { spaceId: "perso" })] : [];
  return buildModel(facts, here, names, { available: os }, caps);
}
const toWindows = (m, s = initialState(m)) => reduce(m, s, { type: "switch", view: "windows" }).state;

test("opens_on_windows_with_nothing_highlighted_when_there_are_no_tabs", () => {
  const m = wmodel({ tabs: false });
  const s = initialState(m);
  assert.equal(s.view, "windows");
  assert.equal(s.windowHighlight, null);
  assert.equal(s.highlight, null);
  assert.deepEqual(keys(m, s), ["screen:s1", "window:w1", "window:w2", "os"]);
});

test("opens_on_tabs_when_any_tab_row_exists", () => {
  const s = initialState(wmodel());
  assert.equal(s.view, "tabs");
  assert.equal(s.windowHighlight, null);
  const noWindows = wmodel({ tabs: false, os: false, caps: [] });
  assert.equal(initialState(noWindows).view, "tabs");
  assert.equal(hasTabs(noWindows), false);
  assert.equal(hasWindows(noWindows), false);
  assert.equal(hasTabs(wmodel()), true);
  const requestingOnly = buildModel([fact("req", { requesting: true })], here, names, { available: false });
  assert.equal(hasTabs(requestingOnly), true);
});

test("window_rows_are_captures_then_os_when_available", () => {
  assert.deepEqual(windowRows(wmodel()).map(r => r.key), ["screen:s1", "window:w1", "window:w2", "os"]);
  assert.deepEqual(windowRows(wmodel({ os: false })).map(r => r.key), ["screen:s1", "window:w1", "window:w2"]);
  assert.equal(hasWindows(wmodel({ os: true, caps: [] })), true);
  assert.equal(hasWindows(wmodel({ os: false, caps: [] })), false);
});

test("switch_to_windows_never_highlights", () => {
  const m = wmodel();
  let s = toWindows(m);
  assert.equal(s.view, "windows");
  s = press(m, s, "ArrowDown").state;
  assert.equal(s.windowHighlight, "screen:s1");
  s = reduce(m, s, { type: "switch", view: "tabs" }).state;
  assert.equal(s.view, "tabs");
  assert.equal(s.highlight, "a");
  s = toWindows(m, s);
  assert.equal(s.windowHighlight, null);
});

test("switch_to_absent_windows_is_ignored", () => {
  const m = wmodel({ os: false, caps: [] });
  const s = initialState(m);
  const r = reduce(m, s, { type: "switch", view: "windows" });
  assert.deepEqual(r.state, s);
  assert.equal(r.effect, null);
  const same = reduce(wmodel(), initialState(wmodel()), { type: "switch", view: "tabs" });
  assert.deepEqual(same.state, initialState(wmodel()));
});

test("switch_clears_query_and_confirming", () => {
  const m = wmodel();
  let s = reduce(m, initialState(m), { type: "query", text: "zzz" }).state;
  s = { ...s, confirming: "o0" };
  const w = reduce(m, s, { type: "switch", view: "windows" }).state;
  assert.equal(w.query, "");
  assert.equal(w.confirming, null);
  const back = reduce(m, { ...w, query: "ed", confirming: "x" }, { type: "switch", view: "tabs" }).state;
  assert.equal(back.query, "");
  assert.equal(back.confirming, null);
});

test("typing_in_windows_never_sets_a_highlight", () => {
  const m = wmodel();
  let s = toWindows(m);
  s = reduce(m, s, { type: "query", text: "edit" }).state;
  assert.deepEqual(keys(m, s), ["window:w1", "os"]);
  assert.equal(s.windowHighlight, null);
  s = reduce(m, s, { type: "key", key: "ArrowDown" }).state;
  assert.equal(s.windowHighlight, "window:w1");
  assert.equal(reduce(m, s, { type: "query", text: "ed" }).state.windowHighlight, "window:w1");
  assert.equal(reduce(m, s, { type: "query", text: "notes" }).state.windowHighlight, null);
  assert.equal(reduce(m, s, { type: "query", text: "zzz" }).state.windowHighlight, null);
  assert.equal(s.highlight, "a");
});

test("arrow_highlights_a_capture_row", () => {
  const m = wmodel();
  let s = toWindows(m);
  s = press(m, s, "ArrowDown").state;
  assert.equal(s.windowHighlight, "screen:s1");
  s = press(m, s, "ArrowDown").state;
  assert.equal(s.windowHighlight, "window:w1");
  s = press(m, s, "End").state;
  assert.equal(s.windowHighlight, "os");
  s = press(m, s, "Home").state;
  assert.equal(s.windowHighlight, "screen:s1");
  s = reduce(m, s, { type: "click", key: "window:w2" }).state;
  assert.equal(s.windowHighlight, "window:w2");
  assert.equal(reduce(m, s, { type: "click", key: "o0" }).state.windowHighlight, "window:w2");
  assert.equal(s.highlight, "a");
});

test("enter_shares_window_with_kind_in_one_press", () => {
  const m = wmodel();
  let s = reduce(m, toWindows(m), { type: "click", key: "window:w1" }).state;
  const r = press(m, s, "Enter");
  assert.deepEqual(r.effect, { type: "share", kind: "window", deviceId: "w1" });
  assert.deepEqual(reduce(m, s, { type: "share" }).effect, r.effect);
  s = reduce(m, s, { type: "click", key: "screen:s1" }).state;
  assert.deepEqual(press(m, s, "Enter").effect, { type: "share", kind: "screen", deviceId: "s1" });
});

test("enter_on_os_row_in_windows_is_os", () => {
  const m = wmodel();
  const s = reduce(m, toWindows(m), { type: "click", key: "os" }).state;
  assert.deepEqual(press(m, s, "Enter").effect, { type: "os" });
});

test("enter_with_nothing_highlighted_does_nothing", () => {
  const m = wmodel();
  const s = toWindows(m);
  assert.equal(press(m, s, "Enter").effect, null);
  assert.equal(reduce(m, s, { type: "share" }).effect, null);
  const hidden = { ...s, windowHighlight: "window:w1", query: "notes" };
  assert.equal(press(m, hidden, "Enter").effect, null);
});

test("tab_does_nothing_in_windows", () => {
  const m = wmodel();
  const s = { ...reduce(m, toWindows(m), { type: "click", key: "window:w1" }).state, confirming: "x" };
  const r = press(m, s, "Tab");
  assert.deepEqual(r.state, { ...s, confirming: null });
  assert.equal(r.state.revealed, false);
  assert.equal(r.effect, null);
});

test("no_hints_in_windows", () => {
  const m = wmodel();
  assert.deepEqual(hints(m, toWindows(m)), []);
});

test("no_tabs_hint_on_the_empty_tabs_view", () => {
  const m = wmodel({ tabs: false });
  const s = reduce(m, initialState(m), { type: "switch", view: "tabs" }).state;
  assert.equal(s.view, "tabs");
  const h = hints(m, s);
  assert.deepEqual(h.map(x => x.code), ["no-tabs", "asleep"]);
  assert.equal(h[0].text, "There are no tabs to share here.");
});

test("arrows_in_an_empty_windows_list_leave_no_highlight", () => {
  const m = wmodel({ os: false });
  const s = reduce(m, toWindows(m), { type: "query", text: "zzz" }).state;
  assert.equal(press(m, s, "ArrowDown").state.windowHighlight, null);
  assert.equal(press(m, s, "End").state.windowHighlight, null);
});

test("os_row_survives_any_query_in_windows", () => {
  const m = wmodel();
  let s = toWindows(m);
  s = reduce(m, s, { type: "query", text: "zzz" }).state;
  assert.deepEqual(keys(m, s), ["os"]);
  assert.equal(s.windowHighlight, null);
  const onOs = reduce(m, { ...s, query: "", windowHighlight: "os" }, { type: "query", text: "zzz" }).state;
  assert.equal(onOs.windowHighlight, "os");
  const none = wmodel({ os: false });
  assert.deepEqual(keys(none, reduce(none, toWindows(none), { type: "query", text: "zzz" }).state), []);
});

test("switch_to_tabs_clears_the_window_highlight", () => {
  const m = wmodel();
  let s = press(m, toWindows(m), "ArrowDown").state;
  assert.equal(s.windowHighlight, "screen:s1");
  s = reduce(m, s, { type: "switch", view: "tabs" }).state;
  assert.equal(s.windowHighlight, null);
});

test("switch_back_to_tabs_reseeds_a_lost_highlight", () => {
  const m = wmodel();
  let s = reduce(m, initialState(m), { type: "query", text: "zzz" }).state;
  assert.equal(s.highlight, null);
  s = toWindows(m, s);
  s = reduce(m, s, { type: "switch", view: "tabs" }).state;
  assert.equal(s.highlight, "a");
  assert.deepEqual(press(m, s, "Enter").effect, { type: "share", kind: "tab", deviceId: "dev-a" });
  const kept = reduce(m, { ...toWindows(m), highlight: "o0", revealed: true }, { type: "switch", view: "tabs" });
  assert.equal(kept.state.highlight, "o0");
  const none = wmodel({ tabs: false });
  assert.equal(reduce(none, initialState(none), { type: "switch", view: "tabs" }).state.highlight, null);
});

test("a_highlighted_screen_shows_the_caution_hint", () => {
  const m = wmodel();
  let s = press(m, toWindows(m), "ArrowDown").state;
  assert.equal(s.windowHighlight, "screen:s1");
  assert.deepEqual(hints(m, s), [
    { code: "screen", text: "Careful: everything on this screen will be visible." },
  ]);
  s = press(m, s, "ArrowDown").state;
  assert.equal(s.windowHighlight, "window:w1");
  assert.deepEqual(hints(m, s), []);
  assert.deepEqual(hints(m, { ...s, windowHighlight: "os" }), []);
  assert.deepEqual(hints(m, { ...s, windowHighlight: "screen:s1", query: "notes" }), []);
  assert.equal(codes(m, { ...s, view: "tabs", windowHighlight: "screen:s1" }).includes("screen"), false);
});
