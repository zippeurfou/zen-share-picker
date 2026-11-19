"""The picker overlay (`src/glue/overlay.sys.mjs`) and its preview
(`src/glue/preview.sys.mjs`) in a real Zen, without the stock prompt.

Each test builds a model with `buildModel` from the real tabs of the window
(`here` is Work, Perso's tabs are the other space), opens the picker on it,
keeps every effect in `win.__effects`, and drives it with real keys."""

import re
import time

import pytest
from zen import CENTER_TOL_PX, KEY_NAMES, ZenScriptError

# Imports the modules into the chrome script: O (overlay), T (tabs), R (rows),
# C (config), K (captures). args[0] is the map of their URLs.
IMPORTS = """
const urls = args[0];
const O = ChromeUtils.importESModule(urls.overlay);
const T = ChromeUtils.importESModule(urls.tabs);
const R = ChromeUtils.importESModule(urls.rows);
const C = ChromeUtils.importESModule(urls.config);
const K = ChromeUtils.importESModule(urls.captures);
"""

# Opens the picker on the window's http tabs. args[1] is an options object:
# `previewMode` (default C.PREVIEW_MODE), `delayMs` (the arming delay, P33;
# default the overlay's), `site` (the asking site for the header, P37;
# default null) and `countCaptures` (wrap
# PageThumbs to count captures and the most in flight at once; `slowMs`
# delays each capture).
# For the Windows tab: `captures` (fake rows, a list of {deviceId, kind,
# title}, built with captureRows; default none), `os` (default
# {available: true, macos: true}), `tabs` (false builds no tab rows), `livePreview`, and
# `spyLive`: a `live` factory that never captures. It keeps in `win.__live`
# the `enabled` it was given and every target set; the test sets `frames`
# (the video has a frame) and `fail` (the start failed). Like the real one,
# it adds an empty `.zsp-live` element at the first target and hides it on
# a null one. `accel` follows the platform.
OPEN = """
const opts = args[1] || {};
const { PageThumbs } = ChromeUtils.importESModule("resource://gre/modules/PageThumbs.sys.mjs");
const byId = new Map();
const entries = [];
for (const w of Services.wm.getEnumerator("navigator:browser")) {
  for (const t of tabsOf(w)) {
    const b = t.linkedBrowser;
    if (!t.linkedPanel || !b || !b.currentURI?.spec.startsWith("http")) continue;
    const id = String(b.browserId);
    if (byId.has(id)) continue;
    byId.set(id, b);
    entries.push({ deviceId: id, mediaSource: "browser" });
  }
}
const facts = T.tabFacts(entries, win, null, Services);
if (!facts.ok) throw new Error("tabFacts: " + facts.reason);
const captures = K.captureRows(
  (opts.captures ?? []).map(c => ({ deviceId: c.deviceId, mediaSource: c.kind, label: c.title })),
  null,
  // captureRows takes only a Set of its own realm (the add-on's modules
  // share one); this script's Set is another realm's.
  { ok: true, ids: new (Cu.getGlobalForObject(K.captureRows).Set)() }
).rows;
const model = R.buildModel(
  opts.tabs === false ? [] : facts.facts,
  T.hereOf(win),
  T.spaceNamesOf(win),
  opts.os ?? { available: true, macos: true },
  captures
);
win.__effects = [];
win.__live = null;
let live;
if (opts.spyLive) {
  live = (w, container, o = {}) => {
    const rec = { calls: (win.__live?.calls ?? 0) + 1, enabled: o.enabled ?? null,
                  targets: [], stopped: false, frames: false, fail: false };
    win.__live = rec;
    let target = null;
    let el = null;
    return {
      setTarget(t) {
        target = t ? { deviceId: t.deviceId, mediaSource: t.mediaSource } : null;
        rec.targets.push(target);
        if (target && !el) {
          el = w.document.createElementNS("http://www.w3.org/1999/xhtml", "div");
          el.className = "zsp-live";
          container.append(el);
        }
        if (el) el.hidden = !target;
      },
      stop() {
        rec.stopped = true;
        target = null;
      },
      isLive: () => !rec.stopped && target !== null && !rec.fail,
      hasFrame: () => !rec.stopped && target !== null && !rec.fail && rec.frames,
    };
  };
}
win.__captures = { calls: 0, inFlight: 0, maxInFlight: 0 };
let thumbs = PageThumbs;
if (opts.countCaptures) {
  thumbs = {
    async captureTabPreviewThumbnail(browser, canvas) {
      const c = win.__captures;
      c.calls++;
      c.inFlight++;
      c.maxInFlight = Math.max(c.maxInFlight, c.inFlight);
      try {
        if (opts.slowMs) await new Promise(r => win.setTimeout(r, opts.slowMs));
        return await PageThumbs.captureTabPreviewThumbnail(browser, canvas);
      } finally {
        c.inFlight--;
      }
    },
  };
}
win.__picker = O.openPicker(win, model, {
  onEffect: e => win.__effects.push(e),
  browserFor: id => byId.get(id) ?? null,
  previewMode: opts.previewMode ?? C.PREVIEW_MODE,
  cssUrl: urls.css,
  PageThumbs: thumbs,
  site: opts.site ?? null,
  accel: Services.appinfo.OS == "Darwin" ? "meta" : "ctrl",
  ...(opts.delayMs === undefined ? {} : { delayMs: opts.delayMs }),
  ...(live ? { live } : {}),
  ...(opts.livePreview === undefined ? {} : { livePreview: opts.livePreview }),
});
const doc = win.document;
await waitFor(() => doc.getElementById("zen-share-picker"), "the picker");
return null;
"""

# The visible state of the picker.
STATE = """
const doc = win.document;
const root = doc.getElementById("zen-share-picker");
if (!root) return null;
const rows = Array.from(root.querySelectorAll(".zsp-row"));
const sel = rows.find(r => r.getAttribute("aria-selected") == "true");
const canvas = root.querySelector("#zen-share-picker-preview canvas");
const none = root.querySelector("#zen-share-picker-preview .zsp-no-preview");
return {
  rows: rows.map(r => ({
    key: r.dataset.key,
    group: r.dataset.group,
    title: r.querySelector(".zsp-title")?.textContent ?? null,
    host: r.querySelector(".zsp-host")?.textContent ?? null,
    careful: r.querySelector(".zsp-careful")?.textContent ?? null,
    kind: r.dataset.kind ?? null,
  })),
  view: root.dataset.view ?? null,
  tabs: Array.from(root.querySelectorAll("#zen-share-picker-tabs [role=tab]"))
    .map(t => t.textContent),
  tabSelected: root.querySelector('#zen-share-picker-tabs [aria-selected="true"]')
    ?.textContent ?? null,
  placeholder: root.querySelector("#zen-share-picker-search")?.placeholder ?? null,
  query: root.querySelector("#zen-share-picker-search")?.value ?? null,
  live: win.__live,
  headers: Array.from(root.querySelectorAll(".zsp-space-header")).map(h => h.textContent),
  selected: sel ? sel.querySelector(".zsp-title")?.textContent ?? null : null,
  selectedGroup: sel ? sel.dataset.group : null,
  hints: Object.fromEntries(Array.from(root.querySelectorAll(".zsp-hint"))
    .map(h => [h.dataset.hint, h.textContent])),
  canvasId: canvas?.dataset.deviceId ?? null,
  canvases: root.querySelectorAll("#zen-share-picker-preview canvas").length,
  noPreview: !!none && !none.hidden && none.textContent == "No preview",
  liveShown: (() => {
    const el = root.querySelector("#zen-share-picker-preview .zsp-live");
    return !!el && !el.hidden && win.getComputedStyle(el).visibility == "visible";
  })(),
  focused: doc.activeElement?.id ?? null,
  effects: win.__effects,
};
"""


def urls_of(zen):
    return {
        "overlay": zen.glue("glue/overlay.sys.mjs"),
        "tabs": zen.glue("glue/tabs.sys.mjs"),
        "rows": zen.glue("lib/rows.mjs"),
        "config": zen.glue("lib/config.mjs"),
        "captures": zen.glue("lib/captures.mjs"),
        "css": zen.glue("glue/picker.css"),
    }


def open_picker(zen, **opts):
    zen.chrome(IMPORTS + OPEN, urls_of(zen), opts)


def state(zen):
    return zen.chrome(STATE)


def wait_state(zen, pred, what, timeout=5):
    end = time.monotonic() + timeout
    while True:
        s = state(zen)
        if s is not None and pred(s):
            return s
        if time.monotonic() > end:
            raise AssertionError(f"timed out waiting for {what}: {s}")
        time.sleep(0.05)


def url_of_title(title):
    """Test pages are titled "<host> <name>" at http://<host>/<name>."""
    host, name = title.split(" ", 1)
    return f"http://{host}/{name}"


def two_spaces(zen):
    """Work (no container): docs.test/w1, wiki.test/w2. Perso (container
    "Perso"): mail.test/p1, shop.test/p2. Work active."""
    work = zen.make_space("Work", None)
    perso = zen.make_space("Perso", "Perso")
    zen.switch_space(perso)
    zen.visit("http://mail.test/p1")
    zen.visit("http://shop.test/p2")
    zen.switch_space(work)
    zen.visit("http://docs.test/w1")
    zen.visit("http://wiki.test/w2")
    return work, perso


PERSO_TEXT = ("mail.test", "shop.test", "Perso")


def test_opens_centered_with_focus_in_search(zen, site, addon):
    two_spaces(zen)
    zen.settle()
    open_picker(zen)
    zen.settle()
    got = zen.chrome(
        """
        const root = win.document.getElementById("zen-share-picker");
        await waitFor(() => {
          const r = root.getBoundingClientRect();
          return r.width > 200 && r.height > 200;
        }, "the picker to be laid out");
        const r = root.getBoundingClientRect();
        return {
          cx: r.left + r.width / 2, cy: r.top + r.height / 2,
          w: win.innerWidth, h: win.innerHeight,
          role: root.getAttribute("role"), modal: root.getAttribute("aria-modal"),
          ns: root.namespaceURI,
          active: win.document.activeElement?.id ?? null,
          focused: Services.focus.focusedElement?.id ?? null,
        };
        """
    )
    assert abs(got["cx"] - got["w"] / 2) <= CENTER_TOL_PX, got
    assert abs(got["cy"] - got["h"] / 2) <= CENTER_TOL_PX, got
    assert got["role"] == "dialog" and got["modal"] == "true", got
    assert got["ns"] == "http://www.w3.org/1999/xhtml", got
    assert got["active"] == "zen-share-picker-search", got
    assert got["focused"] == "zen-share-picker-search", got


# The header as the tests see it.
HEADER = """
const root = win.document.getElementById("zen-share-picker");
const h = root.querySelector("#zen-share-picker-header");
return {
  text: h?.textContent ?? null,
  children: h ? h.children.length : null,
  role: h?.getAttribute("role") ?? null,
  level: h?.getAttribute("aria-level") ?? null,
  first: root.querySelector(":scope > :not(link)") === h,
  label: root.getAttribute("aria-label"),
  labelledby: root.getAttribute("aria-labelledby"),
};
"""


def test_header_names_the_site_as_text(zen, site, addon):
    """P37: the header names the asking site, as text only, and names the
    dialog for assistive tools."""
    two_spaces(zen)
    open_picker(zen, site={"name": "<b>x</b>", "secondName": None})
    got = zen.chrome(HEADER)
    assert got == {
        "text": "<b>x</b> wants to see your screen",
        "children": 0,
        "role": "heading",
        "level": "2",
        "first": True,
        "label": None,
        "labelledby": "zen-share-picker-header",
    }, got
    zen.chrome("win.__picker.close();")
    open_picker(zen, site={"name": "meet.test", "secondName": "embed.test"})
    got = zen.chrome(HEADER)
    assert got["text"] == (
        "meet.test wants to give embed.test permission to see your screen"
    ), got
    assert got["children"] == 0, got


# The computed background of Share and Cancel, after setting
# `--zen-primary-color` on the picker root to args[0], and the computed
# `AccentColor` of a probe element.
BUTTON_COLOURS = """
const doc = win.document;
const root = doc.getElementById("zen-share-picker");
root.style.setProperty("--zen-primary-color", args[0]);
const probe = doc.createElementNS("http://www.w3.org/1999/xhtml", "div");
probe.style.backgroundColor = "AccentColor";
root.append(probe);
const bg = id => win.getComputedStyle(doc.getElementById(id)).backgroundColor;
try {
  return {
    share: bg("zen-share-picker-share"),
    shareText: win.getComputedStyle(doc.getElementById("zen-share-picker-share")).color,
    cancel: bg("zen-share-picker-cancel"),
    accent: win.getComputedStyle(probe).backgroundColor,
  };
} finally {
  probe.remove();
}
"""


def test_share_uses_the_accent_and_cancel_is_neutral(zen, site, addon):
    """P37: Share takes Zen's `--zen-primary-color`, falling back to
    `AccentColor`, with text in its contrast color; Cancel does not."""
    two_spaces(zen)
    open_picker(zen, delayMs=0)
    zen.wait_picker_armed()
    got = zen.chrome(BUTTON_COLOURS, "rgb(1, 2, 3)")
    assert got["share"] == "rgb(1, 2, 3)", got
    assert got["cancel"] != "rgb(1, 2, 3)", got
    # Share's text stays readable on the accent, dark or light.
    assert got["shareText"] == "rgb(255, 255, 255)", got
    light = zen.chrome(BUTTON_COLOURS, "rgb(250, 250, 250)")
    assert light["share"] == "rgb(250, 250, 250)", light
    assert light["shareText"] == "rgb(0, 0, 0)", light
    fallback = zen.chrome(BUTTON_COLOURS, "initial")
    assert fallback["share"] == fallback["accent"], fallback
    assert fallback["cancel"] != fallback["accent"], fallback


# Share's disabled state and computed opacity.
SHARE_LOOK = """
const b = win.document.getElementById("zen-share-picker-share");
return { disabled: b.disabled, opacity: win.getComputedStyle(b).opacity };
"""


def test_share_looks_disabled_until_armed(zen, site, addon):
    """P33, P37: Share is disabled, and looks it, until the picker arms."""
    two_spaces(zen)
    open_picker(zen, delayMs=3000)
    assert zen.chrome(SHARE_LOOK) == {"disabled": True, "opacity": "0.5"}
    zen.wait_picker_armed()
    assert zen.chrome(SHARE_LOOK) == {"disabled": False, "opacity": "1"}


def test_keyboard_moves_filters_and_reveals(zen, site, addon):
    two_spaces(zen)
    open_picker(zen)
    s = state(zen)
    first = s["selected"]
    assert [r["group"] for r in s["rows"]] == ["here", "here"], s
    assert first == s["rows"][0]["title"], s
    zen.press("ArrowDown")
    s = state(zen)
    assert s["selected"] == s["rows"][1]["title"] != first, s
    zen.type_text("wiki")
    s = wait_state(zen, lambda s: len(s["rows"]) == 1, "the filter")
    assert [(r["host"], r["group"]) for r in s["rows"]] == [("wiki.test", "here")], s
    for _ in "wiki":
        zen.press("Backspace")
    zen.press("Tab")
    s = wait_state(zen, lambda s: s["headers"], "the reveal")
    assert s["headers"] == ["Perso"], s
    assert s["focused"] == "zen-share-picker-search", s
    other = [r for r in s["rows"] if r["group"] == "other"]
    assert sorted(r["host"] for r in other) == ["mail.test", "shop.test"], s
    assert all(r["careful"] == "careful" for r in other), s
    assert all(r["careful"] is None for r in s["rows"] if r["group"] != "other"), s
    assert "os" not in [r["group"] for r in s["rows"]], s
    assert "reveal" not in s["hints"], s


def test_shift_tab_is_swallowed(zen, site, addon):
    """P10: Shift+Tab reveals nothing, keeps focus, dispatches nothing."""
    two_spaces(zen)
    open_picker(zen)
    seq = zen.client.actions.sequence("key", "keyboard")
    seq.key_down(KEY_NAMES["Shift"]).key_down(KEY_NAMES["Tab"])
    seq.key_up(KEY_NAMES["Tab"]).key_up(KEY_NAMES["Shift"]).perform()
    zen.client.actions.release()
    time.sleep(0.3)
    s = state(zen)
    assert not s["headers"], s
    assert "reveal" in s["hints"], s
    assert s["focused"] == "zen-share-picker-search", s
    assert s["effects"] == [], s


def test_hidden_space_absent_from_dom_until_tab(zen, site, addon):
    two_spaces(zen)
    perso_ids = [
        zen.browser_id("http://mail.test/p1"),
        zen.browser_id("http://shop.test/p2"),
    ]
    open_picker(zen)
    dump = """
    const root = win.document.getElementById("zen-share-picker");
    return {
      text: root.textContent,
      markup: new win.XMLSerializer().serializeToString(root),
      canvases: Array.from(win.document.querySelectorAll("canvas"))
        .map(c => c.dataset.deviceId ?? null),
    };
    """
    # Let the preview loop run on the highlight for a while.
    time.sleep(1.5)
    before = zen.chrome(dump)
    for word in PERSO_TEXT:
        assert word not in before["text"], word
        assert word not in before["markup"], word
    for i in perso_ids:
        assert i not in before["canvases"], before["canvases"]
        assert f'"{i}"' not in before["markup"], i
    hint = state(zen)["hints"]["reveal"]
    assert not re.search(r"\d", hint), hint
    zen.press("Tab")
    wait_state(zen, lambda s: s["headers"], "the reveal")
    after = zen.chrome(dump)
    for word in PERSO_TEXT:
        assert word in after["text"], word


def test_enter_twice_for_revealed_row(zen, site, addon):
    two_spaces(zen)
    open_picker(zen)
    zen.press("Tab")
    zen.press("End", "ArrowUp")
    s = state(zen)
    assert s["selectedGroup"] == "other", s
    target = zen.browser_id(url_of_title(s["selected"]))
    zen.wait_picker_armed()
    zen.press("Enter")
    s = state(zen)
    assert s["effects"] == [], s
    assert "confirm" in s["hints"], s
    assert "Perso" in s["hints"]["confirm"], s
    zen.press("Enter")
    s = state(zen)
    assert s["effects"] == [{"type": "share", "kind": "tab", "deviceId": target}], s


SHARE_DISABLED = (
    'return win.document.getElementById("zen-share-picker-share").disabled;'
)


def test_commit_waits_until_armed(zen, site, addon):
    """P33: before the delay, Enter (even the first one that would only ask
    for confirmation) and Share change nothing; moving still works."""
    two_spaces(zen)
    open_picker(zen, delayMs=3000)
    assert zen.chrome(SHARE_DISABLED) is True
    zen.press("Tab")
    zen.press("End", "ArrowUp")
    s = state(zen)
    assert s["selectedGroup"] == "other", s
    zen.press("Enter")
    s = state(zen)
    assert s["effects"] == [], s
    assert "confirm" not in s["hints"], s
    zen.press("Home")
    zen.press("Enter")
    zen.chrome('win.document.getElementById("zen-share-picker-share").click();')
    s = state(zen)
    assert s["effects"] == [], s
    assert s["selectedGroup"] == "here", s
    assert zen.chrome(SHARE_DISABLED) is True
    zen.wait_picker_armed()
    zen.press("Enter")
    assert len(state(zen)["effects"]) == 1


def test_auto_repeat_never_commits(zen, site, addon):
    """P33: a held Enter (keydown with `repeat`) never commits, even once
    armed. Events built by chrome code are trusted, so the same keydown
    without `repeat` is the control. Untrusted events cannot be built here;
    tests/unit/arming.test.mjs covers them."""
    two_spaces(zen)
    open_picker(zen, delayMs=0)
    zen.wait_picker_armed()
    got = zen.chrome(
        """
        const search = win.document.getElementById("zen-share-picker-search");
        const init = { key: "Enter", bubbles: true, cancelable: true };
        const held = new win.KeyboardEvent("keydown", { ...init, repeat: true });
        search.dispatchEvent(held);
        const afterHeld = win.__effects.length;
        const once = new win.KeyboardEvent("keydown", init);
        search.dispatchEvent(once);
        return { trusted: held.isTrusted && once.isTrusted, afterHeld,
                 afterOnce: win.__effects.length };
        """
    )
    assert got == {"trusted": True, "afterHeld": 0, "afterOnce": 1}, got


def test_held_escape_does_nothing(zen, site, addon):
    """P36: a held Esc (keydown with `repeat`) never cancels, even before
    arming. The same keydown without `repeat` is the control."""
    two_spaces(zen)
    open_picker(zen, delayMs=3000)
    got = zen.chrome(
        """
        const search = win.document.getElementById("zen-share-picker-search");
        const init = { key: "Escape", bubbles: true, cancelable: true };
        const held = new win.KeyboardEvent("keydown", { ...init, repeat: true });
        search.dispatchEvent(held);
        const afterHeld = { effects: win.__effects.slice(), open: win.__picker.isOpen() };
        const once = new win.KeyboardEvent("keydown", init);
        search.dispatchEvent(once);
        return { trusted: held.isTrusted && once.isTrusted, afterHeld,
                 afterOnce: { effects: win.__effects.slice(), open: win.__picker.isOpen() } };
        """
    )
    assert got == {
        "trusted": True,
        "afterHeld": {"effects": [], "open": True},
        "afterOnce": {"effects": [{"type": "cancel"}], "open": False},
    }, got


def test_close_clears_the_arming_timer(zen, site, addon):
    """P33: closing before the delay leaves no timer that touches the
    closed picker's Share button."""
    two_spaces(zen)
    open_picker(zen, delayMs=600)
    got = zen.chrome(
        """
        const share = win.document.getElementById("zen-share-picker-share");
        win.__picker.close();
        await new Promise(r => win.setTimeout(r, 1000));
        return { disabled: share.disabled, connected: share.isConnected };
        """
    )
    assert got == {"disabled": True, "connected": False}, got


def test_escape_closes_and_reports_cancel(zen, site, addon):
    two_spaces(zen)
    zen.chrome(
        """
        const b = win.document.createElementNS("http://www.w3.org/1999/xhtml", "button");
        b.id = "zsp-test-before";
        b.textContent = "before";
        win.document.getElementById("zen-main-app-wrapper").append(b);
        b.focus();
        await waitFor(() => win.document.activeElement == b, "the test button to have focus");
        """
    )
    open_picker(zen)
    assert state(zen)["focused"] == "zen-share-picker-search"
    zen.press("Escape")
    got = zen.chrome(
        """
        await waitFor(() => !win.document.getElementById("zen-share-picker"), "the picker to close");
        const out = { effects: win.__effects, active: win.document.activeElement?.id ?? null,
                      open: win.__picker.isOpen() };
        win.document.getElementById("zsp-test-before").remove();
        return out;
        """
    )
    assert got == {
        "effects": [{"type": "cancel"}],
        "active": "zsp-test-before",
        "open": False,
    }


def test_titles_render_as_text(zen, site, addon):
    payload = '<img src=x onerror="window.__xss=1">'
    url = "http://docs.test/xss"
    site.serve(
        url,
        (
            b"<!doctype html><html><head><meta charset='utf-8'><title>"
            b'&lt;img src=x onerror="window.__xss=1"&gt;'
            b"</title></head><body>xss</body></html>"
        ),
        "text/html; charset=utf-8",
    )
    try:
        two_spaces(zen)
        zen.visit(url)
    finally:
        site.unserve(url)
    open_picker(zen)
    s = state(zen)
    assert payload in [r["title"] for r in s["rows"]], s
    got = zen.chrome(
        """
        const root = win.document.getElementById("zen-share-picker");
        return {
          stray: root.querySelectorAll(".zsp-row img:not(.zsp-icon)").length,
          most: Math.max(...Array.from(root.querySelectorAll(".zsp-row"))
                           .map(r => r.querySelectorAll("img").length)),
          xss: typeof win.__xss,
        };
        """
    )
    assert got == {"stray": 0, "most": 1, "xss": "undefined"}, got


def test_long_list_keeps_highlight_in_view(zen, site, addon):
    zen.chrome(
        """
        const tabs = [];
        for (let i = 0; i < 60; i++) {
          tabs.push(win.gBrowser.addTab("http://docs.test/n" + i, {
            triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal(),
            userContextId: win.gZenWorkspaces.getCurrentSpaceContainerId(),
          }));
        }
        await waitFor(() => tabs.every(t => t.linkedBrowser.contentTitle), "60 tabs to load", 60000);
        """,
        timeout=90,
    )
    open_picker(zen)
    zen.press("End", "ArrowUp", "ArrowUp")
    got = zen.chrome(
        """
        const list = win.document.getElementById("zen-share-picker-list");
        const rows = Array.from(list.querySelectorAll(".zsp-row"));
        const sel = list.querySelector('.zsp-row[aria-selected="true"]');
        await waitFor(() => {
          const r = sel.getBoundingClientRect();
          return r.height > 0;
        }, "layout");
        const l = list.getBoundingClientRect();
        const r = sel.getBoundingClientRect();
        return {
          rows: rows.length, index: rows.indexOf(sel),
          scrolls: list.scrollHeight > list.clientHeight, scrollTop: list.scrollTop,
          inside: r.top >= l.top - 0.5 && r.bottom <= l.bottom + 0.5 &&
                  r.left >= l.left - 0.5 && r.right <= l.right + 0.5,
        };
        """
    )
    assert got["rows"] == 60, got
    assert got["index"] == 57, got
    assert got["scrolls"] and got["scrollTop"] > 0, got
    assert got["inside"], got
    zen.press("Home")
    got = zen.chrome(
        """
        const list = win.document.getElementById("zen-share-picker-list");
        const sel = list.querySelector('.zsp-row[aria-selected="true"]');
        const l = list.getBoundingClientRect();
        const r = sel.getBoundingClientRect();
        return r.top >= l.top - 0.5 && r.bottom <= l.bottom + 0.5;
        """
    )
    assert got


def snapshot_mode(zen):
    mode = zen.chrome(
        "return ChromeUtils.importESModule(args[0]).PREVIEW_MODE;",
        zen.glue("lib/config.mjs"),
    )
    if mode != "snapshot":
        pytest.skip(f"PREVIEW_MODE is {mode}")


def test_preview_follows_highlight(zen, site, addon):
    two_spaces(zen)
    snapshot_mode(zen)
    open_picker(zen)

    def follows():
        s = state(zen)
        target = zen.browser_id(url_of_title(s["selected"]))
        return wait_state(
            zen,
            lambda s: s["canvasId"] == target and not s["noPreview"],
            f"the preview of {s['selected']}",
            timeout=2,
        )

    follows()
    zen.press("ArrowDown")
    follows()
    zen.press("Tab")
    zen.press("End")
    assert state(zen)["selectedGroup"] == "other"
    follows()
    zen.press("ArrowUp")
    s = follows()
    assert s["canvases"] == 1, s


def test_stop_preview_ends_the_loop(zen, site, addon):
    """P19: stopPreview stops the snapshot loop for good, even when the
    highlight moves afterwards. A slow capture never overlaps another."""
    two_spaces(zen)
    snapshot_mode(zen)
    open_picker(zen, countCaptures=True, slowMs=300)
    zen.press("ArrowDown", "ArrowUp", "ArrowDown")
    time.sleep(2.5)
    c1 = zen.chrome("return win.__captures;")
    assert c1["calls"] >= 3, c1
    assert c1["maxInFlight"] == 1, c1
    zen.chrome("win.__picker.stopPreview();")
    time.sleep(0.5)
    c2 = zen.chrome("return win.__captures;")
    zen.press("ArrowUp")
    time.sleep(2.5)
    c3 = zen.chrome("return win.__captures;")
    assert c3["calls"] == c2["calls"], (c2, c3)
    assert c3["inFlight"] == 0, c3
    s = state(zen)
    assert s["noPreview"] and s["canvasId"] is None, s
    assert zen.chrome("return win.__picker.isOpen();")


def test_no_preview_mode_never_captures(zen, site, addon):
    two_spaces(zen)
    open_picker(zen, previewMode="none", countCaptures=True)
    zen.press("ArrowDown")
    time.sleep(1.5)
    s = state(zen)
    assert s["noPreview"] and s["canvasId"] is None, s
    assert zen.chrome("return win.__captures.calls;") == 0


def test_one_picker_per_window(zen, site, addon):
    """P22: openPicker refuses a second picker in a window; after close, a
    new one opens."""
    two_spaces(zen)
    open_picker(zen)
    with pytest.raises(Exception, match="already-open"):
        open_picker(zen)
    assert (
        zen.chrome('return win.document.querySelectorAll("#zen-share-picker").length;')
        == 1
    )
    assert zen.chrome("return win.__picker.isOpen();")
    zen.chrome("win.__picker.close();")
    open_picker(zen)
    assert zen.chrome("return win.__picker.isOpen();")


def test_a_throw_after_mount_leaves_no_picker(zen, site, addon):
    """When the first render throws, openPicker removes what it mounted
    and rethrows, so a later prompt can still get a picker."""
    two_spaces(zen)
    got = zen.chrome(
        IMPORTS
        + """
        const row = { key: "k", deviceId: "1", title: "t", host: "h", group: "here",
                      requesting: false, spaceLabel: "Work",
                      get icon() { throw new Error("render-boom"); } };
        const model = { here: [row], others: [], os: { key: "os", label: "OS", available: true },
                        captures: [] };
        let error = null;
        try {
          O.openPicker(win, model, {
            onEffect() {}, browserFor: () => null, previewMode: "none", cssUrl: urls.css,
          });
        } catch (e) {
          error = String(e?.message);
        }
        return { error, roots: win.document.querySelectorAll("#zen-share-picker").length };
        """,
        urls_of(zen),
    )
    assert got == {"error": "render-boom", "roots": 0}, got
    open_picker(zen)
    assert zen.chrome("return win.__picker.isOpen();")


def test_buttons_keep_focus_in_search(zen, site, addon):
    """P22: a mouse press on Share or Cancel leaves focus in the search box."""
    two_spaces(zen)
    open_picker(zen)
    zen.wait_picker_armed()
    for button in ("#zen-share-picker-share", "#zen-share-picker-cancel"):
        x, y = zen.chrome(
            """
            const r = win.document.querySelector(args[0]).getBoundingClientRect();
            return [r.left + r.width / 2, r.top + r.height / 2];
            """,
            button,
        )
        mouse = zen.client.actions.sequence(
            "pointer", "mouse", {"pointerType": "mouse"}
        )
        mouse.pointer_move(int(x), int(y)).pointer_down().perform()
        try:
            assert state(zen)["focused"] == "zen-share-picker-search", button
        finally:
            # Moving away before the release keeps it from being a click.
            mouse = zen.client.actions.sequence(
                "pointer", "mouse", {"pointerType": "mouse"}
            )
            mouse.pointer_move(1, 1).pointer_up().perform()
            zen.client.actions.release()
    s = state(zen)
    assert s is not None and s["effects"] == [], s


# The Windows tab, on fake capture rows and a spy `live` that never captures.
CAPTURES = [
    {"deviceId": "zsp-screen-a", "kind": "screen", "title": "Screen A"},
    {"deviceId": "zsp-window-b", "kind": "window", "title": "Window B"},
    {"deviceId": "zsp-window-c", "kind": "window", "title": "Window C"},
]
SCREEN_A = {"deviceId": "zsp-screen-a", "mediaSource": "screen"}
WINDOW_B = {"deviceId": "zsp-window-b", "mediaSource": "window"}

SELECTED_TAB = "return String(win.gBrowser.selectedBrowser.browserId);"


def open_windows_picker(zen, **opts):
    opts.setdefault("captures", CAPTURES)
    opts.setdefault("spyLive", True)
    open_picker(zen, **opts)


def live_targets(s):
    return [t for t in (s["live"] or {}).get("targets", []) if t is not None]


def to_windows(zen):
    zen.chord("2")
    return wait_state(zen, lambda s: s["view"] == "windows", "the Windows view")


def test_tab_strip_shows_both_tabs_and_starts_on_tabs(zen, site, addon):
    two_spaces(zen)
    open_windows_picker(zen)
    s = state(zen)
    assert s["tabs"] == ["Tabs", "Windows"], s
    assert s["view"] == "tabs" and s["tabSelected"] == "Tabs", s
    assert s["placeholder"] == "Search tabs", s
    assert "asleep" in s["hints"], s
    got = zen.chrome(
        """
        const strip = win.document.getElementById("zen-share-picker-tabs");
        return {
          role: strip.getAttribute("role"),
          ids: Array.from(strip.children).map(b => [b.id, b.getAttribute("role")]),
        };
        """
    )
    assert got == {
        "role": "tablist",
        "ids": [
            ["zen-share-picker-tab-tabs", "tab"],
            ["zen-share-picker-tab-windows", "tab"],
        ],
    }, got
    s = to_windows(zen)
    assert s["tabSelected"] == "Windows" and s["placeholder"] == "Search windows", s
    assert [(r["title"], r["group"], r["kind"]) for r in s["rows"]] == [
        ("Screen A", "capture", "screen"),
        ("Window B", "capture", "window"),
        ("Window C", "capture", "window"),
        ("Open the macOS picker (apps, windows or a screen)", "os", None),
    ], s
    assert all(r["host"] is None for r in s["rows"]), s
    assert "asleep" not in s["hints"], s
    s = wait_state(zen, lambda s: s["canvasId"] is None, "no tab snapshot")
    assert s["noPreview"], s


def test_accel_switches_and_is_swallowed(zen, site, addon):
    two_spaces(zen)
    open_windows_picker(zen)
    before = zen.chrome(SELECTED_TAB)
    s = to_windows(zen)
    assert zen.chrome(SELECTED_TAB) == before
    assert zen.chrome("return win.__picker.isOpen();")
    assert s["effects"] == [], s
    zen.chord("1")
    s = wait_state(zen, lambda s: s["view"] == "tabs", "the Tabs view")
    assert zen.chrome(SELECTED_TAB) == before
    assert zen.chrome("return win.__picker.isOpen();")
    assert s["focused"] == "zen-share-picker-search", s
    assert s["effects"] == [], s


# A point on the page outside the picker, as [x, y].
PAGE_POINT = """
const b = win.gBrowser.selectedBrowser.getBoundingClientRect();
const p = win.document.getElementById("zen-share-picker").getBoundingClientRect();
const spots = [
  [b.left + b.width / 2, (Math.max(b.top, p.bottom) + b.bottom) / 2, b.bottom - p.bottom],
  [b.left + b.width / 2, (b.top + Math.min(b.bottom, p.top)) / 2, p.top - b.top],
  [(b.left + Math.min(b.right, p.left)) / 2, b.top + b.height / 2, p.left - b.left],
  [(Math.max(b.left, p.right) + b.right) / 2, b.top + b.height / 2, b.right - p.right],
];
const best = spots.sort((x, y) => y[2] - x[2])[0];
return best[2] >= 10 ? [Math.round(best[0]), Math.round(best[1])] : null;
"""


def test_accel_switches_with_focus_on_the_page(zen, site, addon):
    two_spaces(zen)
    open_windows_picker(zen)
    point = zen.chrome(PAGE_POINT)
    assert point is not None, "no page area outside the picker"
    zen._click(*point)
    zen.chrome(
        """
        await waitFor(() => win.document.activeElement == win.gBrowser.selectedBrowser,
                      "focus on the page");
        """
    )
    before = zen.chrome(SELECTED_TAB)
    s = to_windows(zen)
    assert zen.chrome(SELECTED_TAB) == before
    assert zen.chrome("return win.__picker.isOpen();")
    assert s["effects"] == [], s


def test_accel_from_the_page_moves_focus_to_the_picker(zen, site, addon):
    """After an Accel switch from the page, the arrows reach the picker."""
    two_spaces(zen)
    open_windows_picker(zen)
    point = zen.chrome(PAGE_POINT)
    assert point is not None, "no page area outside the picker"
    zen._click(*point)
    zen.chrome(
        """
        await waitFor(() => win.document.activeElement == win.gBrowser.selectedBrowser,
                      "focus on the page");
        """
    )
    to_windows(zen)
    s = wait_state(
        zen, lambda s: s["focused"] == "zen-share-picker-search", "focus in the picker"
    )
    zen.press("ArrowDown")
    s = wait_state(zen, lambda s: s["selected"] == "Screen A", "Screen A highlighted")
    # The live target follows after the dwell (P71).
    s = wait_state(zen, lambda s: live_targets(s), "a live target")
    assert s["live"]["targets"][-1] == SCREEN_A, s


def test_accel_two_without_a_windows_tab_does_nothing(zen, site, addon):
    two_spaces(zen)
    open_windows_picker(zen, captures=[], os={"available": False})
    s = state(zen)
    assert s["tabs"] == ["Tabs"], s
    before = zen.chrome(SELECTED_TAB)
    zen.chord("2")
    time.sleep(0.5)
    s = state(zen)
    assert s["view"] == "tabs", s
    assert zen.chrome(SELECTED_TAB) == before
    assert zen.chrome("return win.__picker.isOpen();")
    assert s["effects"] == [], s


def test_windows_tab_opens_with_nothing_highlighted_and_no_capture(zen, site, addon):
    two_spaces(zen)
    open_windows_picker(zen)
    s = to_windows(zen)
    time.sleep(0.3)
    s = state(zen)
    assert s["selected"] is None, s
    assert s["live"]["calls"] == 1, s
    assert live_targets(s) == [], s


def test_arrow_starts_one_live_preview_and_moves_it(zen, site, addon):
    two_spaces(zen)
    open_windows_picker(zen)
    to_windows(zen)
    zen.press("ArrowDown")
    s = wait_state(zen, lambda s: live_targets(s), "a live target")
    assert s["selected"] == "Screen A", s
    assert s["live"]["targets"][-1] == SCREEN_A, s
    assert s["hints"] == {
        "screen": "Careful: everything on this screen will be visible."
    }, s
    zen.press("ArrowDown")
    s = wait_state(zen, lambda s: s["live"]["targets"][-1] == WINDOW_B, "Window B")
    assert s["selected"] == "Window B", s
    assert s["hints"] == {}, s
    assert s["live"]["calls"] == 1, s
    assert live_targets(s) == [SCREEN_A, WINDOW_B], s


# Clicks the given rows one after the other in one task, well inside the
# dwell, then waits for it to pass; then clicks the OS row. Returns the
# spy's targets at each step.
QUICK_PASS = """
const root = win.document.getElementById("zen-share-picker");
const row = key => root.querySelector(`.zsp-row[data-key="${key}"]`);
for (const key of args[0]) row(key).click();
const during = win.__live.targets.slice();
await new Promise(r => win.setTimeout(r, 400));
const rested = win.__live.targets.slice();
row("os").click();
const stopped = win.__live.targets.slice();
return { during, rested, stopped };
"""


def test_a_quick_pass_starts_no_live_preview(zen, site, addon):
    """P71: a live capture starts only once the highlight rests on a row
    for the dwell; rows passed over start none, and a null target stops the
    capture at once."""
    two_spaces(zen)
    open_windows_picker(zen)
    to_windows(zen)
    keys = ["screen:zsp-screen-a", "window:zsp-window-b", "window:zsp-window-c"]
    got = zen.chrome(QUICK_PASS, keys)
    assert [t for t in got["during"] if t is not None] == [], got
    window_c = {"deviceId": "zsp-window-c", "mediaSource": "window"}
    assert [t for t in got["rested"] if t is not None] == [window_c], got
    assert got["stopped"][-1] is None, got


def test_switch_and_close_stop_the_live_preview(zen, site, addon):
    two_spaces(zen)
    open_windows_picker(zen)
    to_windows(zen)
    zen.press("ArrowDown")
    wait_state(zen, lambda s: live_targets(s), "a live target")
    zen.chord("1")
    s = wait_state(zen, lambda s: s["view"] == "tabs", "the Tabs view")
    assert s["live"]["targets"][-1] is None, s
    to_windows(zen)
    s = state(zen)
    assert s["selected"] is None and s["live"]["targets"][-1] is None, s
    zen.press("ArrowDown")
    wait_state(zen, lambda s: s["live"]["targets"][-1] == SCREEN_A, "Screen A")
    zen.chrome("win.__picker.stopPreview();")
    s = state(zen)
    assert s["live"]["stopped"], s
    n = len(s["live"]["targets"])
    zen.press("ArrowDown")
    time.sleep(0.3)
    s = state(zen)
    assert len(s["live"]["targets"]) == n, s
    assert s["noPreview"], s
    zen.chrome("win.__picker.close();")
    open_windows_picker(zen)
    to_windows(zen)
    zen.press("ArrowDown")
    wait_state(zen, lambda s: live_targets(s), "a live target")
    zen.chrome("win.__picker.close();")
    assert zen.chrome("return win.__live.stopped;")


def test_typing_on_windows_never_starts_a_preview(zen, site, addon):
    two_spaces(zen)
    open_windows_picker(zen)
    to_windows(zen)
    zen.type_text("Window")
    s = wait_state(zen, lambda s: s["query"] == "Window", "the query")
    time.sleep(0.3)
    s = state(zen)
    assert [r["title"] for r in s["rows"]][:2] == ["Window B", "Window C"], s
    assert s["selected"] is None, s
    assert live_targets(s) == [], s


def test_previews_off_never_set_a_target(zen, site, addon):
    two_spaces(zen)
    open_windows_picker(zen, livePreview=False)
    to_windows(zen)
    zen.press("ArrowDown")
    s = wait_state(zen, lambda s: s["selected"] == "Screen A", "Screen A")
    time.sleep(0.3)
    s = state(zen)
    assert s["live"]["enabled"] is False, s
    assert s["live"]["targets"] == [], s
    assert s["noPreview"], s


def test_window_preview_says_no_preview_without_a_frame(zen, site, addon):
    """The live preview shows "No preview" until a real frame arrives,
    and at once after a failed start, which is never retried."""
    two_spaces(zen)
    open_windows_picker(zen)
    to_windows(zen)
    zen.press("ArrowDown")
    s = wait_state(zen, lambda s: live_targets(s), "a live target")
    assert s["liveShown"], s
    s = wait_state(
        zen, lambda s: s["noPreview"], "No preview without a frame", timeout=4
    )
    # No empty video box next to "No preview".
    assert not s["liveShown"], s
    zen.chrome("win.__live.frames = true;")
    s = wait_state(zen, lambda s: not s["noPreview"], "the frame")
    assert s["liveShown"], s
    zen.chrome("win.__live.fail = true;")
    s = wait_state(
        zen, lambda s: s["noPreview"], "No preview after a failure", timeout=1
    )
    assert not s["liveShown"], s
    n = len(s["live"]["targets"])
    time.sleep(0.5)
    s = state(zen)
    assert len(s["live"]["targets"]) == n, s


def test_click_on_the_windows_tab_switches(zen, site, addon):
    two_spaces(zen)
    open_windows_picker(zen)
    for button, view in (
        ("#zen-share-picker-tab-windows", "windows"),
        ("#zen-share-picker-tab-tabs", "tabs"),
    ):
        x, y = zen.chrome(
            """
            const r = win.document.querySelector(args[0]).getBoundingClientRect();
            return [r.left + r.width / 2, r.top + r.height / 2];
            """,
            button,
        )
        zen._click(int(x), int(y))
        s = wait_state(zen, lambda s, v=view: s["view"] == v, view)
        assert s["focused"] == "zen-share-picker-search", s
        assert s["effects"] == [], s


def test_click_on_the_os_row_shows_selected_in_windows(zen, site, addon):
    two_spaces(zen)
    open_windows_picker(zen)
    to_windows(zen)
    zen.press("ArrowDown")
    wait_state(zen, lambda s: live_targets(s), "a live target")
    zen.chrome(
        "win.document.querySelector('#zen-share-picker .zsp-row[data-group=\"os\"]').click();"
    )
    s = wait_state(zen, lambda s: s["selectedGroup"] == "os", "the OS row selected")
    assert s["live"]["targets"][-1] is None, s
    assert s["noPreview"], s


def test_enter_on_a_window_row_reports_a_share_with_kind(zen, site, addon):
    two_spaces(zen)
    open_windows_picker(zen, delayMs=0)
    to_windows(zen)
    zen.press("ArrowDown", "ArrowDown")
    wait_state(zen, lambda s: s["selected"] == "Window B", "Window B")
    zen.wait_picker_armed()
    zen.press("Enter")
    s = state(zen)
    assert s["effects"][-1] == {
        "type": "share",
        "kind": "window",
        "deviceId": "zsp-window-b",
    }, s


def test_tab_key_does_nothing_on_windows(zen, site, addon):
    two_spaces(zen)
    open_windows_picker(zen)
    to_windows(zen)
    zen.press("ArrowDown")
    zen.press("Tab")
    time.sleep(0.3)
    s = state(zen)
    assert s["view"] == "windows" and s["selected"] == "Screen A", s
    assert not s["headers"], s
    assert all(r["group"] in ("capture", "os") for r in s["rows"]), s
    assert s["focused"] == "zen-share-picker-search", s
    assert s["effects"] == [], s
    zen.chord("1")
    s = wait_state(zen, lambda s: s["view"] == "tabs", "the Tabs view")
    assert not s["headers"], s
    assert "reveal" in s["hints"], s


def test_windows_only_picker_opens_on_windows(zen, site, addon):
    two_spaces(zen)
    open_windows_picker(zen, tabs=False)
    s = state(zen)
    assert s["view"] == "windows", s
    assert s["selected"] is None, s
    assert [r["group"] for r in s["rows"]] == ["capture", "capture", "capture", "os"], s
    assert live_targets(s) == [], s
    zen.chord("1")
    s = wait_state(zen, lambda s: s["view"] == "tabs", "the Tabs view")
    assert "no-tabs" in s["hints"], s
    assert s["rows"] == [], s


def test_failed_window_preview_says_no_preview_at_once(zen, site, addon):
    """A failed start shows "No preview" well before the frame wait."""
    two_spaces(zen)
    open_windows_picker(zen)
    to_windows(zen)
    got = zen.chrome(
        """
        const root = win.document.getElementById("zen-share-picker");
        const none = root.querySelector(".zsp-no-preview");
        root.querySelector('.zsp-row[data-kind="window"]').click();
        const blank = none.hidden;
        // The target arrives after the dwell (P71), then the frame watch
        // sees it live.
        await waitFor(() => win.__live.targets.some(t => t), "the live target");
        await new Promise(r => win.setTimeout(r, 150));
        const t0 = ChromeUtils.now();
        win.__live.fail = true;
        await waitFor(() => !none.hidden, "No preview");
        return { blank, ms: ChromeUtils.now() - t0, targets: win.__live.targets.length };
        """
    )
    assert got["blank"] is True, got
    assert got["ms"] < 1000, got
    time.sleep(0.5)
    assert len(state(zen)["live"]["targets"]) == got["targets"]


def test_click_row_clicks_only_a_row_it_can_reach(zen, site, addon):
    """The harness's click_row clicks the row by key, and refuses, before
    any click, when something else is at the row's centre."""
    two_spaces(zen)
    open_windows_picker(zen)
    to_windows(zen)
    zen.click_row("window:zsp-window-c")
    wait_state(zen, lambda s: s["selected"] == "Window C", "Window C")
    zen.chrome(
        """
        const row = win.document.querySelector(
          '#zen-share-picker .zsp-row[data-key="window:zsp-window-b"]');
        const r = row.getBoundingClientRect();
        const cover = win.document.createElementNS("http://www.w3.org/1999/xhtml", "div");
        cover.id = "zsp-test-cover";
        cover.style.cssText = `position: fixed; left: ${r.left}px; top: ${r.top}px; ` +
          `width: ${r.width}px; height: ${r.height}px; z-index: 2147483647;`;
        win.document.documentElement.append(cover);
        """
    )
    with pytest.raises(ZenScriptError, match="not on that row"):
        zen.click_row("window:zsp-window-b")
    s = state(zen)
    assert s["selected"] == "Window C", s
