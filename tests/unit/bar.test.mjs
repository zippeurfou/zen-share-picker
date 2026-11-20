import test from "node:test";
import assert from "node:assert/strict";
import {
  GAP_OTHER,
  GAP_SELECTED,
  accentTokens,
  barLabel,
  barPosition,
  contrast,
  hasNewShare,
  isUserMove,
  labelMaxPx,
  parseRgb,
  pruneKeys,
  shareKeys,
  topCenter,
} from "../../src/lib/bar.mjs";

const MEET = "https://meet.google.com/abc-defg-hij";
const tab = { mediaSource: "browser", scary: false };
const screen = { mediaSource: "screen", scary: true };
const zenWindow = { mediaSource: "window", scary: true };
const otherWindow = { mediaSource: "window", scary: false };
const app = { mediaSource: "application", scary: false };
const camera = { mediaSource: "camera", scary: false };
const mic = { mediaSource: "microphone", scary: false };

const stream = (id, uri, ...devices) => ({ id, uri, devices });

// labels

test("tab_label_names_the_site", () => {
  assert.deepEqual(barLabel([stream("1", MEET, tab)]), {
    kind: "tab",
    verb: "Sharing a tab with",
    site: "meet.google.com",
    text: "Sharing a tab with meet.google.com",
  });
});

test("zen_window_is_a_scary_window", () => {
  const label = barLabel([stream("1", MEET, zenWindow)]);
  assert.equal(label.kind, "zen-window");
  assert.equal(label.text, "Sharing a Zen window with meet.google.com");
});

test("other_window_label", () => {
  const label = barLabel([stream("1", MEET, otherWindow)]);
  assert.equal(label.kind, "window");
  assert.equal(label.text, "Sharing a window with meet.google.com");
  assert.equal(barLabel([stream("1", MEET, app)]).kind, "window");
});

test("screen_label", () => {
  const label = barLabel([stream("1", MEET, screen)]);
  assert.equal(label.kind, "screen");
  assert.equal(label.verb, "Sharing your entire screen with");
  assert.equal(label.text, "Sharing your entire screen with meet.google.com");
});

test("screen_wins_over_everything", () => {
  const label = barLabel([stream("1", MEET, tab, otherWindow, zenWindow), stream("2", MEET, screen)]);
  assert.equal(label.kind, "screen");
});

test("zen_window_wins_over_tab", () => {
  assert.equal(barLabel([stream("1", MEET, tab), stream("2", MEET, zenWindow)]).kind, "zen-window");
});

test("tab_wins_over_other_window", () => {
  assert.equal(barLabel([stream("1", MEET, otherWindow), stream("2", MEET, tab)]).kind, "tab");
});

test("two_sites_drop_the_site", () => {
  const label = barLabel([stream("1", MEET, tab), stream("2", "https://example.com/", tab)]);
  assert.deepEqual(label, { kind: "tab", verb: "Sharing a tab", site: "", text: "Sharing a tab" });
  // Two streams of one site keep it.
  assert.equal(
    barLabel([stream("1", MEET, tab), stream("2", "https://meet.google.com/other", tab)]).site,
    "meet.google.com",
  );
  // A camera on another site does not count.
  assert.equal(
    barLabel([stream("1", MEET, tab), stream("2", "https://example.com/", camera)]).site,
    "meet.google.com",
  );
});

test("file_and_about_pages_have_no_site", () => {
  assert.equal(barLabel([stream("1", "file:///tmp/page.html", tab)]).text, "Sharing a tab");
  assert.equal(barLabel([stream("1", "about:blank", tab)]).text, "Sharing a tab");
  assert.equal(barLabel([stream("1", "not a uri", tab)]).text, "Sharing a tab");
  // Any counted stream without a web host drops the site.
  assert.equal(barLabel([stream("1", MEET, tab), stream("2", "about:blank", tab)]).site, "");
});

test("camera_only_streams_give_no_label", () => {
  const none = { kind: null, verb: "", site: "", text: "" };
  assert.deepEqual(barLabel([stream("1", MEET, camera, mic)]), none);
  assert.deepEqual(barLabel([]), none);
});

test("stream_without_devices_counts_nothing", () => {
  const bare = { id: "1", uri: MEET };
  assert.deepEqual(barLabel([bare]), { kind: null, verb: "", site: "", text: "" });
  assert.equal(shareKeys([bare]).size, 0);
  assert.equal(barLabel([bare, stream("2", MEET, tab)]).text, "Sharing a tab with meet.google.com");
});

test("label_never_reads_other_fields", () => {
  const guard = (obj, allowed) =>
    new Proxy(obj, {
      get(target, key) {
        if (typeof key === "string" && !allowed.includes(key)) {
          throw new Error(`read a field it must not read: ${key}`);
        }
        return target[key];
      },
    });
  const device = guard({ mediaSource: "browser", scary: false, name: "Secret Title 123" }, [
    "mediaSource",
    "scary",
  ]);
  const s = guard({ id: "1", uri: MEET, title: "Secret Title 123", devices: [device] }, [
    "id",
    "uri",
    "devices",
  ]);
  const label = barLabel([s]);
  assert.equal(label.text, "Sharing a tab with meet.google.com");
  assert.ok(!JSON.stringify(label).includes("Secret"));
  assert.ok(!label.text.includes("Secret Title 123"));
});

// keys

test("keys_are_browser_and_source", () => {
  const keys = shareKeys([stream("7", MEET, tab, camera, mic), stream("9", MEET, zenWindow, screen)]);
  assert.deepEqual([...keys].sort(), ["7|browser", "9|screen", "9|window"]);
});

test("new_share_is_a_key_not_remembered", () => {
  assert.equal(hasNewShare(new Set(["7|browser"]), new Set(["7|browser", "9|screen"])), true);
  assert.equal(hasNewShare(new Set(), new Set(["7|browser"])), true);
  assert.equal(hasNewShare(new Set(["7|browser"]), new Set(["7|browser"])), false);
});

test("fewer_shares_are_not_new", () => {
  assert.equal(hasNewShare(new Set(["7|browser", "9|screen"]), new Set(["9|screen"])), false);
  assert.equal(hasNewShare(new Set(["7|browser"]), new Set()), false);
});

test("prune_keeps_only_current", () => {
  const pruned = pruneKeys(new Set(["7|browser", "9|screen"]), new Set(["9|screen", "4|window"]));
  assert.deepEqual([...pruned], ["9|screen"]);
});

// placement

const content = { x: 100, y: 50, width: 1200, height: 800 };
const size = { width: 500, height: 56 };

test("selected_tab_sits_88px_up", () => {
  assert.equal(GAP_SELECTED, 88);
  assert.deepEqual(barPosition({ content, size, selected: true, margin: 6 }), { x: 450, y: 712 });
});

test("other_tab_sits_16px_up", () => {
  assert.equal(GAP_OTHER, 16);
  assert.deepEqual(barPosition({ content, size, selected: false, margin: 6 }), { x: 450, y: 784 });
});

test("margin_zero_moves_down_by_six", () => {
  assert.deepEqual(barPosition({ content, size, selected: true, margin: 0 }), { x: 450, y: 706 });
  assert.deepEqual(barPosition({ content, size, selected: false, margin: 0 }), { x: 450, y: 778 });
});

const avail = { left: 0, top: 25, width: 1440, height: 875 };

test("on_screen_position_is_unchanged", () => {
  assert.deepEqual(barPosition({ content, size, selected: true, margin: 6, screen: avail }), {
    x: 450,
    y: 712,
  });
});

test("content_below_the_screen_clamps_the_bar_up", () => {
  const low = { x: 100, y: 400, width: 1200, height: 800 };
  // Unclamped y is 1062; the screen's bottom is 900.
  assert.deepEqual(barPosition({ content: low, size, selected: true, margin: 6, screen: avail }), {
    x: 450,
    y: 844,
  });
});

test("content_half_off_the_right_edge_clamps_the_bar_left", () => {
  const right = { x: 1000, y: 50, width: 1200, height: 800 };
  // Unclamped x is 1350; the screen's right edge is 1440.
  assert.deepEqual(barPosition({ content: right, size, selected: false, margin: 6, screen: avail }), {
    x: 940,
    y: 784,
  });
});

test("content_off_the_left_and_top_clamps_the_bar_in", () => {
  const off = { x: -2000, y: -900, width: 1200, height: 800 };
  assert.deepEqual(barPosition({ content: off, size, selected: true, margin: 6, screen: avail }), {
    x: 0,
    y: 25,
  });
});

test("top_center_is_firefox_spot", () => {
  assert.deepEqual(topCenter({ content, size }), { x: 450, y: 50 });
});

test("user_move_needs_more_than_two_px", () => {
  const at = { x: 450, y: 712 };
  assert.equal(isUserMove(at, { x: 450, y: 712 }), false);
  assert.equal(isUserMove(at, { x: 452, y: 710 }), false);
  assert.equal(isUserMove(at, { x: 453, y: 712 }), true);
  assert.equal(isUserMove(at, { x: 450, y: 709 }), true);
  assert.equal(isUserMove(at, { x: 455, y: 712 }, 5), false);
});

test("no_expected_position_is_never_a_drag", () => {
  assert.equal(isUserMove(null, { x: 0, y: 0 }), false);
  assert.equal(isUserMove(null, { x: 9000, y: 9000 }), false);
});

test("label_max_is_clamped", () => {
  assert.equal(labelMaxPx(300), 120);
  assert.equal(labelMaxPx(1200), 720);
  assert.equal(labelMaxPx(800), 460);
});

// colors

const rgb = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));

const ACCENTS = [
  "#007aff",
  "#0a84ff",
  "#af52de",
  "#bf5af2",
  "#28cd41",
  "#ffcc00",
  "#8e8e93",
  "#000000",
  "#ffffff",
];

const eachToken = (fn) => {
  for (const accent of ACCENTS) {
    for (const dark of [false, true]) {
      fn(accentTokens(rgb(accent), dark), `${accent} ${dark ? "dark" : "light"}`);
    }
  }
};

test("parses_rgb_and_rgba", () => {
  assert.deepEqual(parseRgb("rgb(0, 122, 255)"), [0, 122, 255]);
  assert.deepEqual(parseRgb("rgba(10, 20, 30, 0.5)"), [10, 20, 30]);
  assert.deepEqual(parseRgb("rgb(0 122 255)"), [0, 122, 255]);
  assert.equal(parseRgb("#007aff"), null);
  assert.equal(parseRgb("AccentColor"), null);
  assert.equal(parseRgb("rgb(0, 300, 0)"), null);
  assert.equal(parseRgb(""), null);
  assert.equal(parseRgb(undefined), null);
});

// Within 2 per channel: the first 0.01 step that reaches 4.5:1 for macOS
// blue is 0.07 (#0071ed, 4.58:1), one step before the mockup's #0070eb.
const assertNear = (actual, expected) => {
  const a = rgb(actual);
  const e = rgb(expected);
  assert.ok(
    a.every((v, i) => Math.abs(v - e[i]) <= 2),
    `${actual} is not within 2 per channel of ${expected}`,
  );
};

test("macos_blue_light_fill_is_0070eb", () => {
  assertNear(accentTokens(rgb("#007aff"), false).fill, "#0070eb");
});

test("blue_light_tint_is_d9e8f9", () => {
  assertNear(accentTokens(rgb("#007aff"), false).tint, "#d9e8f9");
});

test("stop_text_reaches_4_5_on_every_fill_state", () => {
  eachToken((t, name) => {
    for (const state of ["fill", "fillHover", "fillPressed"]) {
      const ratio = contrast(rgb(t.fillText), rgb(t[state]));
      assert.ok(ratio >= 4.5, `${name} ${state}: ${ratio}`);
    }
  });
});

test("hide_ink_reaches_4_5_on_every_tint_state", () => {
  eachToken((t, name) => {
    const resting = contrast(rgb(t.ink), rgb(t.tint));
    assert.ok(resting >= 4.5, `${name} ink on tint: ${resting}`);
    for (const state of ["tint", "tintHover", "tintPressed"]) {
      const ratio = contrast(rgb(t.inkStrong), rgb(t[state]));
      assert.ok(ratio >= 4.5, `${name} inkStrong on ${state}: ${ratio}`);
    }
  });
});

test("yellow_switches_stop_to_dark_text", () => {
  for (const dark of [false, true]) {
    assert.equal(accentTokens(rgb("#ffcc00"), dark).fillText, "#16132a");
  }
  assert.equal(accentTokens(rgb("#007aff"), false).fillText, "#ffffff");
});

test("tokens_are_hex_strings", () => {
  const names = [
    "accent",
    "fill",
    "fillHover",
    "fillPressed",
    "fillText",
    "tint",
    "tintHover",
    "tintPressed",
    "ink",
    "inkStrong",
  ];
  eachToken((t, name) => {
    assert.deepEqual(Object.keys(t).sort(), [...names].sort(), name);
    for (const key of names) {
      assert.match(t[key], /^#[0-9a-f]{6}$/, `${name} ${key}`);
    }
  });
  assert.equal(accentTokens(rgb("#007aff"), false).accent, "#007aff");
});
