"""The picker overlay (`src/glue/overlay.sys.mjs`) and its preview
(`src/glue/preview.sys.mjs`) in a real Zen, without the stock prompt.

Each test builds a model with `buildModel` from the real tabs of the window
(`here` is Work, Perso's tabs are the other space), opens the picker on it,
keeps every effect in `win.__effects`, and drives it with real keys."""

import re
import time

import pytest
from zen import CENTER_TOL_PX, KEY_NAMES

# Imports the modules into the chrome script: O (overlay), T (tabs), R (rows),
# C (config). args[0] is the map of their URLs.
IMPORTS = """
const urls = args[0];
const O = ChromeUtils.importESModule(urls.overlay);
const T = ChromeUtils.importESModule(urls.tabs);
const R = ChromeUtils.importESModule(urls.rows);
const C = ChromeUtils.importESModule(urls.config);
"""

# Opens the picker on the window's http tabs. args[1] is an options object:
# `previewMode` (default C.PREVIEW_MODE), `delayMs` (the arming delay, P33;
# default the overlay's), `site` (the asking site for the header, P37;
# default null) and `countCaptures` (wrap
# PageThumbs to count captures and the most in flight at once; `slowMs`
# delays each capture).
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
const model = R.buildModel(facts.facts, T.hereOf(win), T.spaceNamesOf(win), { available: true });
win.__effects = [];
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
  ...(opts.delayMs === undefined ? {} : { delayMs: opts.delayMs }),
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
  })),
  headers: Array.from(root.querySelectorAll(".zsp-space-header")).map(h => h.textContent),
  selected: sel ? sel.querySelector(".zsp-title")?.textContent ?? null : null,
  selectedGroup: sel ? sel.dataset.group : null,
  hints: Object.fromEntries(Array.from(root.querySelectorAll(".zsp-hint"))
    .map(h => [h.dataset.hint, h.textContent])),
  canvasId: canvas?.dataset.deviceId ?? null,
  canvases: root.querySelectorAll("#zen-share-picker-preview canvas").length,
  noPreview: !!none && !none.hidden && none.textContent == "No preview",
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
    assert [r["group"] for r in s["rows"]] == ["here", "here", "os"], s
    assert first == s["rows"][0]["title"], s
    zen.press("ArrowDown")
    s = state(zen)
    assert s["selected"] == s["rows"][1]["title"] != first, s
    zen.type_text("wiki")
    s = wait_state(zen, lambda s: len(s["rows"]) == 2, "the filter")
    assert [(r["host"], r["group"]) for r in s["rows"]] == [
        ("wiki.test", "here"),
        (None, "os"),
    ], s
    assert s["rows"][1]["title"] == "Apps, windows or a screen...", s
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
    assert s["rows"][-1]["group"] == "os", s
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
    assert s["effects"] == [{"type": "share", "deviceId": target}], s


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
    assert got["rows"] == 61, got
    assert got["index"] == 58, got
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
    zen.press("End", "ArrowUp")
    assert state(zen)["selectedGroup"] == "other"
    follows()
    zen.press("End")
    s = wait_state(
        zen, lambda s: s["noPreview"] and s["canvasId"] is None, "No preview", timeout=2
    )
    assert s["selectedGroup"] == "os", s
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
        const model = { here: [row], others: [], os: { key: "os", label: "OS", available: true } };
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
