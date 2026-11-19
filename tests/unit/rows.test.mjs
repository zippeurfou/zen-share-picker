import test from "node:test";
import assert from "node:assert/strict";
import {
  belongsHere,
  dedupe,
  buildModel,
  matches,
} from "../../src/lib/rows.mjs";

let n = 0;
function fact(over = {}) {
  n++;
  return {
    deviceId: "dev" + n,
    syncKey: "k" + n,
    inPromptWindow: true,
    contentsVisible: true,
    lastAccessed: n,
    title: "Title " + n,
    host: "host" + n + ".example",
    icon: "",
    spaceId: "work",
    essential: false,
    ucid: null,
    requesting: false,
    ...over,
  };
}

const names = new Map([
  ["work", "Work"],
  ["perso", "Perso"],
]);
const os = { available: true, macos: true };
const here = { spaceId: "work", ucid: 1 };

test("captures_pass_through_build_model", () => {
  const cap = [{ key: "window:1", deviceId: "1", kind: "window", title: "W", host: "", group: "capture" }];
  assert.deepEqual(buildModel([fact()], here, names, os, cap).captures, cap);
  assert.deepEqual(buildModel([fact()], here, names, os).captures, []);
});

test("essential_counts_here_only_in_its_container", () => {
  const e = fact({ essential: true, ucid: 1, spaceId: null });
  assert.equal(belongsHere(e, here), true);
  assert.equal(belongsHere({ ...e, ucid: null }, here), false);
});

test("belongsHere_d2_cases", () => {
  const ess = (o) => fact({ essential: true, ...o });
  assert.equal(belongsHere(ess({ spaceId: "work", ucid: 2 }), here), false);
  assert.equal(belongsHere(fact({ spaceId: "perso", ucid: 1 }), here), false);
  assert.equal(belongsHere(fact({ spaceId: "work", ucid: 2 }), here), true);
  assert.equal(belongsHere(fact({ spaceId: "work", ucid: null }), here), true);
  assert.equal(belongsHere(ess({ spaceId: null, ucid: 1 }), here), true);
});

test("null_here_space_rejects_even_matching_essential", () => {
  const nowhere = { spaceId: null, ucid: 1 };
  assert.equal(belongsHere(fact({ essential: true, ucid: 1, spaceId: null }), nowhere), false);
  assert.equal(belongsHere(fact({ spaceId: null }), nowhere), false);
  const m = buildModel([fact({ essential: true, ucid: 1, spaceId: null })], nowhere, names, os);
  assert.deepEqual(m.here, []);
});

test("perso_essential_from_work_is_another_space", () => {
  const e = fact({ essential: true, ucid: 2, spaceId: "perso" });
  assert.equal(belongsHere(e, here), false);
  const m = buildModel([e], here, names, os);
  assert.deepEqual(m.here, []);
  assert.equal(m.others[0].label, "Essentials");
});

test("unreadable_space_is_another_space", () => {
  const t = fact({ spaceId: null });
  assert.equal(belongsHere(t, here), false);
  const m = buildModel([t], here, names, os);
  assert.equal(m.others[0].label, "Other space");
  const u = fact({ spaceId: "gone" });
  assert.equal(buildModel([u], here, names, os).others[0].label, "Other space");
});

test("no_current_space_puts_everything_in_others", () => {
  const m = buildModel([fact()], { spaceId: null, ucid: null }, names, os);
  assert.deepEqual(m.here, []);
  assert.equal(m.others.length, 1);
});

test("dedupe_prefers_live_contents_then_prompt_window_then_recent", () => {
  const base = { syncKey: "same" };
  const live = fact({ ...base, deviceId: "live", contentsVisible: true, inPromptWindow: false, lastAccessed: 1 });
  const win = fact({ ...base, deviceId: "win", contentsVisible: false, inPromptWindow: true, lastAccessed: 2 });
  const recent = fact({ ...base, deviceId: "recent", contentsVisible: false, inPromptWindow: false, lastAccessed: 9 });
  assert.equal(dedupe([recent, win, live])[0].deviceId, "live");
  assert.equal(dedupe([recent, win])[0].deviceId, "win");
  const old = { ...recent, deviceId: "old", lastAccessed: 3 };
  assert.equal(dedupe([old, recent])[0].deviceId, "recent");
  const req = { ...win, requesting: true };
  const out = dedupe([live, req]);
  assert.equal(out.length, 1);
  assert.equal(out[0].deviceId, "live");
  assert.equal(out[0].requesting, true);
});

test("here_rows_most_recent_first_requesting_last", () => {
  const a = fact({ lastAccessed: 10 });
  const b = fact({ lastAccessed: 30 });
  const r = fact({ lastAccessed: 99, requesting: true });
  const c = fact({ lastAccessed: 20 });
  const m = buildModel([a, r, b, c], here, names, os);
  assert.deepEqual(m.here.map(x => x.key), [b.syncKey, c.syncKey, a.syncKey, r.syncKey]);
});

test("other_groups_labelled_and_ordered_by_recency", () => {
  const p1 = fact({ spaceId: "perso", lastAccessed: 5 });
  const e1 = fact({ essential: true, ucid: 7, spaceId: null, lastAccessed: 50 });
  const p2 = fact({ spaceId: "perso", lastAccessed: 8 });
  const m = buildModel([p1, e1, p2], here, names, os);
  assert.deepEqual(m.others.map(g => g.label), ["Essentials", "Perso"]);
  assert.deepEqual(m.others[1].rows.map(r => r.key), [p2.syncKey, p1.syncKey]);
  assert.equal(m.others[1].rows[0].spaceLabel, "Perso");
  assert.equal(m.others[1].rows[0].group, "other");
});

test("os_label_names_macos_only_on_macos", () => {
  const mac = buildModel([fact()], here, names, { available: true, macos: true });
  assert.deepEqual(mac.os, {
    key: "os",
    label: "Open the macOS picker (apps, windows or a screen)",
    available: true,
  });
  const other = buildModel([fact()], here, names, { available: false, macos: false });
  assert.deepEqual(other.os, {
    key: "os",
    label: "Open the system picker (apps, windows or a screen)",
    available: false,
  });
});

test("matches_title_or_host_case_insensitively", () => {
  const row = { title: "Quarterly Report", host: "Docs.Example.com" };
  assert.equal(matches(row, ""), true);
  assert.equal(matches(row, "  "), true);
  assert.equal(matches(row, " QUARTER "), true);
  assert.equal(matches(row, "docs.example"), true);
  assert.equal(matches(row, "nope"), false);
});
