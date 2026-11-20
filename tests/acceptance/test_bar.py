"""Firefox's sharing bar, restyled in place.

During a share Firefox opens its global sharing indicator, a separate
always-on-top window. The add-on restyles it in place (P75, P77): a sheet,
a label naming the share type and the site, a Hide button and "Stop
sharing". Every failure leaves the stock bar, with a `barProblems` code
(P80), and shutdown restores the stock bar. The picker's off switch leaves
the restyle on (P76). The restyle runs on macOS only: elsewhere every test
here skips, except one that checks the bar stays stock (P86).

The bar sits at the bottom center of the content area of the window
holding the latest share, 88px up when that share's tab is selected and
16px otherwise, until the user drags it (P73, P79, P83).

Hide hides the bar until a share starts that was not running at Hide, and
never shows a bar Firefox's own prefs keep hidden (P74, P78).

Each test shares a tab through Zen's stock prompt (no OS capture, so no
macOS alert) and reads computed values in the bar. Nothing here reads or
prints a page title, except the privacy test, which returns booleans only.
"""

import os
import sys
import time

import pytest
from pages import _capture_page
from test_picker import skip_if_capture_denied, status
from zen import (
    _ALLOW_AND_WAIT,
    _SELECT_TAB_ENTRY,
    CENTER_TOL_PX,
    ZenScriptError,
)

# The bar opens, moves and hides headless (platform test S10).
BAR_HEADLESS = True

pytestmark = pytest.mark.skipif(
    not BAR_HEADLESS and os.environ.get("HEADLESS") == "1",
    reason="the sharing bar opens only headful",
)

MACOS_ONLY = "the sharing bar restyle is macOS only"
OFF_MACOS_TEST = "test_bar_stays_stock_off_macos"


@pytest.fixture(autouse=True)
def macos_only(request):
    """P86: the restyle runs on macOS only, so off macOS every test here
    skips, before Zen starts, except the one that checks the bar stays
    stock."""
    if sys.platform != "darwin" and request.node.name != OFF_MACOS_TEST:
        pytest.skip(MACOS_ONLY)


NO_BAR = "Firefox opened no sharing bar here"
LOCKED = "the window could not become active (screen locked?)"
MARK = "data-zen-share-picker-bar"
SHARED = "http://docs.test/b"
LABEL = "Sharing a tab with meet.test"
SECRET = "Secret Title 123"
# Firefox caches the list of shareable tabs for 2 s (kCacheExpiryPeriodMs in
# VideoEngine.h), so a share prompt opened sooner after the last one shows
# the old list, without a tab opened since.
CAPTURE_LIST_CACHE_S = 2.1


def bar_or_skip(zen):
    """P85: waits up to 10 s for Firefox's sharing bar. On macOS a missing
    bar fails the test; elsewhere it skips."""
    try:
        zen.bar("return true;", timeout=10)
    except AssertionError:
        if sys.platform == "darwin":
            raise AssertionError("Firefox opened no sharing bar within 10 s") from None
        pytest.skip(NO_BAR)


def share(zen, url=SHARED, path="share", origin="http://meet.test"):
    """Shares the tab on `url` from `<origin>/<path>` and waits for the bar."""
    skip_if_capture_denied(zen)
    zen.settle()
    try:
        zen.share_tab(url, path, origin)
    except ZenScriptError as e:
        if "become active" in str(e) or "screen locked" in str(e):
            pytest.skip(LOCKED)
        raise
    bar_or_skip(zen)


def install(zen, addon_xpi):
    addon = zen.install_addon(str(addon_xpi))
    zen.wait_addon_active(addon)
    return addon


BAR_STATE = """
const doc = bar.document;
const root = doc.documentElement;
const label = doc.getElementById("zm-share-label");
const hide = doc.getElementById("zm-hide");
const stop = doc.getElementById("stop-sharing");
const body = bar.getComputedStyle(doc.body);
return {
  marked: root.hasAttribute(args[0]),
  shape: root.getAttribute("data-zm-shape"),
  label: label ? label.textContent : null,
  ariaLabel: label ? label.getAttribute("aria-label") : null,
  labelledBy: doc.getElementById("display-share").getAttribute("aria-labelledby"),
  stopText: stop.textContent,
  stopL10n: stop.getAttribute("data-l10n-id"),
  hideText: hide ? hide.textContent : null,
  bodyHeight: parseFloat(body.height),
  bodyRadius: body.borderTopLeftRadius,
  visible: root.getAttribute("visible"),
  hidden: root.hasAttribute("data-zm-hidden"),
  wrapped: !!bar.updateIndicatorState.zspWrapped,
};
"""


def bar_state(zen):
    return zen.bar(BAR_STATE, MARK)


def wait_bar_state(zen, pred, what, timeout=5.0):
    end = time.monotonic() + timeout
    while True:
        state = bar_state(zen)
        if pred(state):
            return state
        if time.monotonic() > end:
            raise AssertionError(f"timed out waiting for {what}: {state}")
        time.sleep(0.1)


def zm_elements(zen):
    """How many elements in the bar have a `zm-` id or class."""
    return zen.bar(
        'return bar.document.querySelectorAll(\'[id^="zm-"], [class*="zm-"]\').length;'
    )


# Computed values: args[0] maps a name to [selector, property]; each
# selector's first match is read.
STYLES = """
const out = {};
for (const [name, [sel, prop]] of Object.entries(args[0])) {
  const el = bar.document.querySelector(sel);
  out[name] = el ? bar.getComputedStyle(el).getPropertyValue(prop) : null;
}
return out;
"""


def styles(zen, wanted):
    return zen.bar(STYLES, wanted)


DARK = 'return bar.matchMedia("(prefers-color-scheme: dark)").matches;'

# The Stop fill accentTokens gives for the color args[1] ([r, g, b]), or for
# the bar's own AccentColor when args[1] is null, as rgb(), and Stop's
# computed background.
EXPECTED_FILL = """
const { accentTokens } = ChromeUtils.importESModule(args[0]);
const doc = bar.document;
let rgb = args[1];
if (!rgb) {
  const probe = doc.createElementNS("http://www.w3.org/1999/xhtml", "span");
  probe.style.color = "AccentColor";
  doc.documentElement.append(probe);
  rgb = bar.getComputedStyle(probe).color.match(/\\d+/g).slice(0, 3).map(Number);
  probe.remove();
}
const dark = bar.matchMedia("(prefers-color-scheme: dark)").matches;
const hex = accentTokens(rgb, dark).fill;
const expected = "rgb(" + [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16)).join(", ") + ")";
const got = bar.getComputedStyle(doc.getElementById("stop-sharing")).backgroundColor;
return { expected, got };
"""


def expected_fill(zen, rgb=None):
    return zen.bar(EXPECTED_FILL, zen.glue("lib/bar.mjs"), rgb)


def test_bar_is_restyled_during_a_tab_share(zen, site, addon):
    share(zen)
    s = bar_state(zen)
    assert s["marked"], s
    assert s["shape"] == "pill", s
    got = styles(
        zen,
        {
            "bodyHeight": ["body", "height"],
            "bodyRadius": ["body", "border-top-left-radius"],
            "padTop": ["body", "padding-top"],
            "padRight": ["body", "padding-right"],
            "padBottom": ["body", "padding-bottom"],
            "padLeft": ["body", "padding-left"],
            "labelSize": ["#zm-share-label", "font-size"],
            "siteWeight": ["#zm-share-label .zm-site", "font-weight"],
            "hideHeight": ["#zm-hide", "height"],
            "hideRadius": ["#zm-hide", "border-top-left-radius"],
            "hideWeight": ["#zm-hide", "font-weight"],
            "stopHeight": ["#stop-sharing", "height"],
            "stopRadius": ["#stop-sharing", "border-top-left-radius"],
            "stopWeight": ["#stop-sharing", "font-weight"],
        },
    )
    assert got == {
        "bodyHeight": "44px",
        "bodyRadius": "22px",
        "padTop": "0px",
        "padRight": "6px",
        "padBottom": "0px",
        "padLeft": "12px",
        "labelSize": "13.5px",
        "siteWeight": "600",
        "hideHeight": "32px",
        "hideRadius": "16px",
        "hideWeight": "500",
        "stopHeight": "32px",
        "stopRadius": "16px",
        "stopWeight": "600",
    }, got
    layout = zen.bar(
        """
        const doc = bar.document;
        const hidden = ["#device-share", "#window-controls", "#window-share-info",
                        "#browser-window-share-info", "#screen-share-info"];
        const display = el => bar.getComputedStyle(el).display;
        const left = sel => doc.querySelector(sel).getBoundingClientRect().left;
        return {
          hidden: hidden.map(sel => display(doc.querySelector(sel))),
          separators: Array.from(doc.querySelectorAll(".separator"), display),
          lefts: ["#drag-indicator", "#display-share-icon", "#zm-share-label",
                  "#zm-hide", "#stop-sharing"].map(left),
        };
        """
    )
    assert layout["hidden"] == ["none"] * 5, layout
    assert layout["separators"] == ["none", "none"], layout
    lefts = layout["lefts"]
    assert lefts == sorted(lefts) and len(set(lefts)) == 5, layout
    assert status(zen, addon)["barProblems"] == []


def test_bar_label_names_the_tab_share_and_site(zen, site, addon):
    share(zen)
    s = bar_state(zen)
    assert s["label"] == LABEL, s
    assert s["ariaLabel"] == LABEL, s
    assert s["labelledBy"] == "zm-share-label", s
    assert s["stopText"] == "Stop sharing", s
    assert s["stopL10n"] is None, s
    assert s["hideText"] == "Hide", s


def test_two_sites_drop_the_site(launch_zen, site, addon_xpi):
    zen = launch_zen({"dom.securecontext.allowlist": "meet.test,shop.test"})
    addon = install(zen, addon_xpi)
    page = "http://shop.test/share"
    site.serve(page, _capture_page("share"), "text/html; charset=utf-8")
    try:
        share(zen)
        share(zen, "http://wiki.test/b2", origin="http://shop.test")
        s = wait_bar_state(zen, lambda s: s["label"] == "Sharing a tab", "no site")
        assert s["ariaLabel"] == "Sharing a tab", s
        assert status(zen, addon)["barProblems"] == []
    finally:
        site.unserve(page)


def test_whole_screen_state_is_amber(zen, site, addon):
    share(zen)
    dark = zen.bar(DARK)
    before = expected_fill(zen)
    got = zen.bar(
        """
        const doc = bar.document;
        doc.documentElement.setAttribute("sharingscreen", "true");
        const cs = sel => bar.getComputedStyle(doc.querySelector(sel));
        return { fill: cs("#display-share-icon").fill, edge: cs("body").boxShadow };
        """
    )
    assert got["fill"] == ("rgb(255, 196, 107)" if dark else "rgb(179, 98, 0)"), got
    assert "rgba(214, 130, 0, 0.55)" in got["edge"], got
    after = expected_fill(zen)
    assert after["got"] == before["got"] == after["expected"], (before, after)


@pytest.mark.parametrize("dark", [0, 1])
def test_light_and_dark_surfaces(launch_zen, site, addon_xpi, dark):
    """`ui.systemUsesDarkTheme` sets the bar's color scheme (platform test
    S13)."""
    zen = launch_zen({"ui.systemUsesDarkTheme": dark})
    install(zen, addon_xpi)
    share(zen)
    assert zen.bar(DARK) is bool(dark)
    got = styles(zen, {"bg": ["body", "background-color"], "color": ["body", "color"]})
    if dark:
        assert got == {"bg": "rgb(42, 42, 46)", "color": "rgb(245, 245, 247)"}, got
    else:
        assert got == {"bg": "rgb(247, 247, 248)", "color": "rgb(29, 29, 31)"}, got


# The bar's scheme, its Hide tint and the tint accentTokens gives for the
# bar's own AccentColor in that scheme.
TINT = """
const { accentTokens } = ChromeUtils.importESModule(args[0]);
const doc = bar.document;
const probe = doc.createElementNS("http://www.w3.org/1999/xhtml", "span");
probe.style.color = "AccentColor";
doc.documentElement.append(probe);
const rgb = bar.getComputedStyle(probe).color.match(/\\d+/g).slice(0, 3).map(Number);
probe.remove();
const dark = bar.matchMedia("(prefers-color-scheme: dark)").matches;
return {
  dark,
  tint: doc.documentElement.style.getPropertyValue("--zm-tint"),
  expected: accentTokens(rgb, dark).tint,
};
"""


def test_appearance_change_refreshes_the_colors(launch_zen, site, addon_xpi):
    """A flip of the color scheme mid-share refreshes Hide's tint with no
    update from Firefox."""
    zen = launch_zen({"ui.systemUsesDarkTheme": 0})
    install(zen, addon_xpi)
    share(zen)
    before = zen.bar(TINT, zen.glue("lib/bar.mjs"))
    assert not before["dark"] and before["tint"] == before["expected"], before
    zen.chrome('Services.prefs.setIntPref("ui.systemUsesDarkTheme", 1);')
    end = time.monotonic() + 5
    while True:
        after = zen.bar(TINT, zen.glue("lib/bar.mjs"))
        if after["dark"] and after["tint"] == after["expected"]:
            break
        assert time.monotonic() < end, (before, after)
        time.sleep(0.1)
    assert after["tint"] != before["tint"], (before, after)


def test_accent_from_the_pref(launch_zen, site, addon_xpi):
    zen = launch_zen({"zen.theme.accent-color": "#af52de"})
    install(zen, addon_xpi)
    share(zen)
    got = expected_fill(zen, [175, 82, 222])
    assert got["got"] == got["expected"], got


def test_default_accent_is_the_system_accent(zen, site, addon):
    share(zen)
    got = expected_fill(zen)
    assert got["got"] == got["expected"], got


def test_bad_accent_pref_falls_back(launch_zen, site, addon_xpi):
    zen = launch_zen({"zen.theme.accent-color": "notacolor"})
    addon = install(zen, addon_xpi)
    share(zen)
    got = expected_fill(zen)
    assert got["got"] == got["expected"], got
    assert status(zen, addon)["barProblems"] == []


# For each id in args[0]: whether the element at its center is that element,
# so nothing covers it.
ON_TOP = """
const doc = bar.document;
return args[0].map(id => {
  const el = doc.getElementById(id);
  const r = el.getBoundingClientRect();
  return doc.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2) === el;
});
"""


def test_stop_sharing_still_stops(zen, site, addon):
    share(zen)
    on_top = zen.bar(ON_TOP, ["stop-sharing", "zm-hide"])
    assert on_top == [True, True], on_top
    zen.bar('bar.document.getElementById("stop-sharing").click();')
    end = time.monotonic() + 5
    while zen.sharing_device_ids() or zen.bar_open():
        assert time.monotonic() < end, "the share or the bar outlived Stop sharing"
        time.sleep(0.1)


def test_text_survives_fluent(zen, site, addon):
    share(zen)
    zen.bar("await bar.document.l10n.translateRoots();")
    s = bar_state(zen)
    assert s["label"] == LABEL, s
    assert s["stopText"] == "Stop sharing", s


def test_square_shape_fallback(zen, site, addon):
    share(zen)
    s = bar_state(zen)
    assert s["marked"] and s["shape"] == "pill", s
    pill = styles(zen, {"pad": [":root", "padding-top"]})
    assert pill == {"pad": "6px"}, pill
    zen.bar('bar.document.documentElement.setAttribute("data-zm-shape", "square");')
    got = styles(
        zen,
        {
            "padTop": [":root", "padding-top"],
            "padLeft": [":root", "padding-left"],
            "radius": ["body", "border-top-left-radius"],
        },
    )
    assert got == {"padTop": "0px", "padLeft": "0px", "radius": "0px"}, got


def test_already_open_bar_is_restyled_on_install(zen, site, addon_xpi):
    share(zen)
    assert not bar_state(zen)["marked"]
    install(zen, addon_xpi)
    s = wait_bar_state(zen, lambda s: s["marked"], "the restyle")
    assert s["label"] == LABEL, s
    assert s["wrapped"], s


def test_leftovers_of_an_older_version_are_cleared(zen, site, addon_xpi):
    share(zen)
    addon = install(zen, addon_xpi)
    wait_bar_state(zen, lambda s: s["marked"], "the restyle")
    zen.set_addon_enabled(addon, False)
    wait_bar_state(zen, lambda s: not s["marked"], "the stock bar")
    zen.bar(
        """
        const doc = bar.document;
        doc.documentElement.setAttribute(args[0],
          "resource://zen-share-picker-0-0-1/src/glue/bar.css");
        const span = doc.createElementNS("http://www.w3.org/1999/xhtml", "span");
        span.id = "zm-share-label";
        doc.getElementById("display-share-icon").after(span);
        """,
        MARK,
    )
    zen.set_addon_enabled(addon, True)
    wait_bar_state(zen, lambda s: s["marked"], "the restyle")
    counts = zen.bar(
        """
        const doc = bar.document;
        return [doc.querySelectorAll("#zm-share-label").length,
                doc.querySelectorAll("#zm-hide").length];
        """
    )
    assert counts == [1, 1], counts
    assert bar_state(zen)["label"] == LABEL


def test_unknown_markup_leaves_the_stock_bar(zen, site, addon_xpi):
    share(zen)
    zen.bar('bar.document.getElementById("window-controls").remove();')
    before = bar_state(zen)
    addon = install(zen, addon_xpi)
    s = bar_state(zen)
    assert not s["marked"], s
    assert zm_elements(zen) == 0
    assert s["bodyHeight"] == before["bodyHeight"], (before, s)
    assert s["stopText"] == before["stopText"], (before, s)
    assert not s["wrapped"], s
    assert status(zen, addon)["barProblems"] == ["bar-unknown-markup"]


# The bar's theme read throws, so the add-on's part of the next update
# throws after Firefox's part ran.
BREAK_RENDER = 'bar.matchMedia = () => { throw new Error("x"); };'


def assert_stock_after_internal_error(zen, addon):
    s = wait_bar_state(zen, lambda s: not s["marked"], "the stock bar")
    assert zm_elements(zen) == 0
    assert not s["wrapped"], s
    assert not s["hidden"], s
    assert s["visible"] == "true", s
    assert status(zen, addon)["barProblems"] == ["bar-internal"]
    assert zen.bar_open()
    assert zen.sharing_device_ids()


def test_an_update_that_throws_leaves_the_stock_bar(zen, site, addon):
    share(zen)
    assert bar_state(zen)["marked"]
    zen.bar(BREAK_RENDER + "\nbar.updateIndicatorState();")
    assert_stock_after_internal_error(zen, addon)


def test_an_update_that_throws_shows_a_hidden_bar(zen, site, addon):
    share(zen)
    hide(zen)
    zen.bar(BREAK_RENDER + "\nbar.updateIndicatorState();")
    assert_stock_after_internal_error(zen, addon)


def test_a_restyle_that_throws_leaves_the_stock_bar(zen, site, addon_xpi):
    """The add-on can't put its wrapper in: the restyle throws and is
    undone."""
    share(zen)
    zen.bar('Object.defineProperty(bar, "updateIndicatorState", { writable: false });')
    addon = install(zen, addon_xpi)
    end = time.monotonic() + 5
    while status(zen, addon)["barProblems"] != ["bar-style-failed"]:
        assert time.monotonic() < end, status(zen, addon)["barProblems"]
        time.sleep(0.1)
    s = wait_bar_state(zen, lambda s: s["stopText"] == "Stop Sharing", "Firefox's text")
    assert not s["marked"], s
    assert s["shape"] is None, s
    assert zm_elements(zen) == 0
    assert not s["wrapped"], s
    assert s["stopL10n"] == "webrtc-stop-sharing-button", s
    assert s["visible"] == "true", s
    assert zen.sharing_device_ids()


def test_mute_toggles_leave_the_bar_stock(launch_zen, site, addon_xpi):
    zen = launch_zen({"privacy.webrtc.globalMuteToggles": True})
    addon = install(zen, addon_xpi)
    zen.addon_call(addon, "setDebug", True)
    share(zen)
    s = bar_state(zen)
    assert not s["marked"], s
    assert not s["wrapped"], s
    assert zm_elements(zen) == 0
    assert status(zen, addon)["barProblems"] == []
    assert "bar stock mute-toggles" in zen.addon_call(addon, "getLog")


def test_bar_stays_stock_off_macos(zen, site, addon):
    """P86: off macOS the add-on leaves Firefox's bar as it is."""
    if sys.platform == "darwin":
        pytest.skip("checks the stock bar off macOS")
    zen.addon_call(addon, "setDebug", True)
    share(zen)
    s = bar_state(zen)
    assert not s["marked"], s
    assert zm_elements(zen) == 0
    assert not s["wrapped"], s
    assert status(zen, addon)["barProblems"] == []
    assert "bar stock platform" in zen.addon_call(addon, "getLog")


def test_hidden_indicator_pref_keeps_the_bar_hidden(launch_zen, site, addon_xpi):
    zen = launch_zen({"privacy.webrtc.hideGlobalIndicator": True})
    addon = install(zen, addon_xpi)
    share(zen)
    s = bar_state(zen)
    assert s["marked"], s
    assert s["visible"] == "false", s
    zen.bar("bar.updateIndicatorState();")
    assert bar_state(zen)["visible"] == "false"
    zen.set_addon_enabled(addon, False)
    s = wait_bar_state(zen, lambda s: not s["marked"], "the stock bar")
    assert s["visible"] == "false", s


def test_disabling_the_addon_restores_the_stock_bar(zen, site, addon):
    share(zen)
    assert bar_state(zen)["marked"]
    zen.set_addon_enabled(addon, False)
    s = wait_bar_state(
        zen, lambda s: s["stopText"] == "Stop Sharing", "Firefox's text", timeout=2
    )
    assert not s["marked"], s
    assert s["shape"] is None, s
    assert zm_elements(zen) == 0
    assert not s["wrapped"], s
    assert s["stopL10n"] == "webrtc-stop-sharing-button", s
    assert s["bodyHeight"] < 32, s
    assert s["visible"] == "true", s
    assert zen.bar_open()
    assert zen.sharing_device_ids()


def test_off_switch_keeps_the_restyle(zen, site, addon):
    """P76: the picker's off switch leaves the restyle on."""
    share(zen)
    assert zen.addon_call(addon, "setEnabled", False)["state"] == "disabled"
    assert bar_state(zen)["marked"]
    share(zen, "http://wiki.test/b2")
    s = bar_state(zen)
    assert s["marked"], s
    assert s["wrapped"], s


# Booleans only: whether args[0] is anywhere in the bar's text, title or
# attribute values.
TITLE_IN_BAR = """
const doc = bar.document;
const attrs = Array.from(doc.querySelectorAll("*"))
  .flatMap(el => Array.from(el.attributes, a => a.value));
return {
  text: doc.documentElement.textContent.includes(args[0]),
  title: doc.title.includes(args[0]),
  attrs: attrs.some(v => v.includes(args[0])),
};
"""


def test_bar_never_shows_a_title(zen, site, addon):
    secret = "http://docs.test/secret"
    site.serve(
        secret,
        f"<!doctype html><title>{SECRET}</title><h1>{SECRET}</h1>".encode(),
        "text/html; charset=utf-8",
    )
    try:
        zen.addon_call(addon, "setDebug", True)
        share(zen, secret)
        assert bar_state(zen)["marked"]
        found = zen.bar(TITLE_IN_BAR, SECRET)
        assert found == {"text": False, "title": False, "attrs": False}, found
        lines = zen.addon_call(addon, "getLog")
        assert not any(SECRET in line for line in lines), "the log holds the title"
    finally:
        site.unserve(secret)


# -- placement ------------------------------------------------------------------

# Where the bar is and where it should be, computed here with the add-on's
# own barPosition and topCenter (args[0]) on the live content area: the
# selected browser of the window holding the latest share, inside the
# available rect of that window's screen.
BAR_GEOMETRY = """
const { barPosition, topCenter, labelMaxPx } = ChromeUtils.importESModule(args[0]);
const { webrtcUI } = ChromeUtils.importESModule("resource:///modules/webrtcUI.sys.mjs");
const streams = webrtcUI.getActiveStreams(true, true, true, true, true);
const owner = streams[streams.length - 1].browser.documentGlobal;
const r = owner.gBrowser.selectedBrowser.getBoundingClientRect();
const content = { x: owner.mozInnerScreenX + r.left, y: owner.mozInnerScreenY + r.top,
                  width: r.width, height: r.height };
const b = bar.document.documentElement.getBoundingClientRect();
const size = { width: b.width, height: b.height };
const s = owner.screen;
const screen = { left: s.availLeft, top: s.availTop, width: s.availWidth, height: s.availHeight };
const at = selected => barPosition({ content, size, selected, margin: 6, screen });
return {
  x: bar.screenX, y: bar.screenY, width: size.width, height: size.height, screen,
  expected88: at(true), expected16: at(false), top: topCenter({ content, size }),
  contentCenter: content.x + content.width / 2,
  contentWidth: content.width,
  labelMax: labelMaxPx(content.width),
  labelMaxProp: bar.document.documentElement.style.getPropertyValue("--zm-label-max"),
};
"""


def bar_geometry(zen):
    return zen.bar(BAR_GEOMETRY, zen.glue("lib/bar.mjs"))


def near(g, want):
    return (
        abs(g["x"] - want["x"]) <= CENTER_TOL_PX
        and abs(g["y"] - want["y"]) <= CENTER_TOL_PX
    )


def wait_placed(zen, key, timeout=5.0):
    """Waits until the bar sits at bar_geometry's `key` position."""
    end = time.monotonic() + timeout
    while True:
        g = bar_geometry(zen)
        if near(g, g[key]):
            return g
        if time.monotonic() > end:
            raise AssertionError(f"the bar is not at {key}: {g}")
        time.sleep(0.1)


SELECT_TAB = "win.gBrowser.selectedTab = findTab(args[0]);"
MEET = "http://meet.test/share"


def select(zen, url):
    zen.chrome(SELECT_TAB, url)


def log(zen, addon):
    return zen.addon_call(addon, "getLog")


def test_bar_sits_88px_up_when_the_call_tab_is_selected(zen, site, addon):
    zen.addon_call(addon, "setDebug", True)
    share(zen)
    select(zen, MEET)
    wait_placed(zen, "expected88")
    assert "bar placed 88" in log(zen, addon)


def test_bar_drops_to_16px_on_another_tab_and_back(zen, site, addon):
    zen.addon_call(addon, "setDebug", True)
    share(zen)
    select(zen, MEET)
    wait_placed(zen, "expected88")
    select(zen, SHARED)
    wait_placed(zen, "expected16")
    assert "bar placed 16" in log(zen, addon)
    select(zen, MEET)
    wait_placed(zen, "expected88")


def test_bar_is_centered_on_the_content_area(zen, site, addon):
    share(zen)
    g = wait_placed(zen, "expected88")
    center = g["x"] + g["width"] / 2
    assert abs(center - g["contentCenter"]) <= CENTER_TOL_PX, g


RESIZE = "win.resizeTo(win.outerWidth - args[0], win.outerHeight - args[1]);"


def test_bar_follows_an_anchor_window_resize(zen, site, addon):
    share(zen)
    before = wait_placed(zen, "expected88")
    zen.chrome(RESIZE, 200, 100)
    after = wait_placed(zen, "expected88")
    assert after["expected88"] != before["expected88"], (before, after)


# Moves the window down until half of it hangs below its screen's
# available rect, and returns its new bottom and that rect's bottom.
HANG_BELOW = """
const s = win.screen;
const bottom = s.availTop + s.availHeight;
win.moveTo(win.screenX, bottom - Math.round(win.outerHeight / 2));
await waitFor(() => win.screenY + win.outerHeight > bottom + 200, "the window to move down");
return [win.screenY + win.outerHeight, bottom];
"""


def test_bar_stays_on_screen_when_the_window_hangs_below_it(zen, site, addon):
    share(zen)
    wait_placed(zen, "expected88")
    window_bottom, screen_bottom = zen.chrome(HANG_BELOW)
    assert window_bottom > screen_bottom + 200, (window_bottom, screen_bottom)
    zen.bar("bar.updateIndicatorState();")
    g = wait_placed(zen, "expected88")
    s = g["screen"]
    tol = CENTER_TOL_PX
    assert g["x"] >= s["left"] - tol, g
    assert g["y"] >= s["top"] - tol, g
    assert g["x"] + g["width"] <= s["left"] + s["width"] + tol, g
    assert g["y"] + g["height"] <= s["top"] + s["height"] + tol, g


# A press on the grip, as a user's drag starts, then the move. Chrome code
# dispatches it, so it is trusted.
DRAG = """
const grip = bar.document.getElementById("drag-indicator");
const r = grip.getBoundingClientRect();
const at = { bubbles: true, button: 0, clientX: r.left + r.width / 2, clientY: r.top + r.height / 2 };
const down = new bar.MouseEvent("mousedown", at);
grip.dispatchEvent(down);
if (!down.isTrusted) throw new Error("the press is not trusted");
grip.dispatchEvent(new bar.MouseEvent("mouseup", at));
bar.moveTo(args[0], args[1]);
return [bar.screenX, bar.screenY];
"""


def test_bar_stays_where_the_user_dropped_it(zen, site, addon):
    zen.addon_call(addon, "setDebug", True)
    share(zen)
    g = wait_placed(zen, "expected88")
    dropped = zen.bar(DRAG, g["x"] + 40, g["y"] - 30)
    assert dropped == [g["x"] + 40, g["y"] - 30], (g, dropped)
    select(zen, SHARED)
    zen.bar("bar.updateIndicatorState();")
    time.sleep(0.3)
    after = bar_geometry(zen)
    assert [after["x"], after["y"]] == dropped, (dropped, after)
    assert "bar dragged" in log(zen, addon)


def test_a_move_without_a_press_is_not_a_drag(zen, site, addon):
    """Firefox's own moves (its clamp to the screen on every update) come
    with no press on the bar, so they never count as a drag."""
    zen.addon_call(addon, "setDebug", True)
    share(zen)
    g = wait_placed(zen, "expected88")
    zen.bar("bar.moveTo(args[0], args[1]);", g["x"] + 40, g["y"] - 30)
    zen.bar("bar.updateIndicatorState();")
    wait_placed(zen, "expected88")
    assert "bar dragged" not in log(zen, addon)


# A trusted mouse event args[1] on the element matching args[0].
MOUSE = """
const el = bar.document.querySelector(args[0]);
const r = el.getBoundingClientRect();
const event = new bar.MouseEvent(args[1], {
  bubbles: true, button: 0, clientX: r.left + r.width / 2, clientY: r.top + r.height / 2,
});
el.dispatchEvent(event);
return event.isTrusted;
"""


def test_a_slow_drag_still_counts(zen, site, addon):
    """Nothing measured from the press expires: a user who presses, pauses,
    then drags has dragged."""
    zen.addon_call(addon, "setDebug", True)
    share(zen)
    g = wait_placed(zen, "expected88")
    assert zen.bar(MOUSE, "#drag-indicator", "mousedown")
    time.sleep(1.5)
    dropped = zen.bar(
        "bar.moveTo(args[0], args[1]); return [bar.screenX, bar.screenY];",
        g["x"] + 40,
        g["y"] - 30,
    )
    assert zen.bar(MOUSE, "#drag-indicator", "mouseup")
    assert "bar dragged" in log(zen, addon)
    select(zen, SHARED)
    zen.bar("bar.updateIndicatorState();")
    time.sleep(0.3)
    after = bar_geometry(zen)
    assert [after["x"], after["y"]] == dropped, (dropped, after)


def test_a_press_without_a_drag_keeps_placement_live(zen, site, addon):
    """A press on the label that never drags, followed by the add-on's own
    resize and moves and by Firefox's update, is no drag."""
    zen.addon_call(addon, "setDebug", True)
    share(zen)
    g = wait_placed(zen, "expected88")
    assert zen.bar(MOUSE, "#zm-share-label", "mousedown")
    # Narrow enough that the label limit drops below its 720px cap, so the
    # add-on resizes the bar, then places it.
    zen.chrome(RESIZE, max(0, round(g["contentWidth"]) - 800), 0)
    end = time.monotonic() + 5
    while bar_geometry(zen)["labelMax"] == g["labelMax"]:
        assert time.monotonic() < end, "the content area did not narrow"
        time.sleep(0.1)
    wait_placed(zen, "expected88")
    zen.bar("bar.updateIndicatorState();")
    select(zen, SHARED)
    wait_placed(zen, "expected16")
    assert zen.bar(MOUSE, "#zm-share-label", "mouseup")
    assert "bar dragged" not in log(zen, addon)


def test_label_change_keeps_placement_live(launch_zen, site, addon_xpi):
    zen = launch_zen({"dom.securecontext.allowlist": "meet.test,shop.test"})
    addon = install(zen, addon_xpi)
    zen.addon_call(addon, "setDebug", True)
    page = "http://shop.test/share"
    site.serve(page, _capture_page("share"), "text/html; charset=utf-8")
    try:
        share(zen)
        before = wait_placed(zen, "expected88")
        share(zen, "http://wiki.test/b2", origin="http://shop.test")
        wait_bar_state(zen, lambda s: s["label"] == "Sharing a tab", "no site")
        after = wait_placed(zen, "expected88")
        assert after["width"] < before["width"], (before, after)
        assert "bar dragged" not in log(zen, addon)
    finally:
        site.unserve(page)


CLOSE_OTHER_WINDOWS = """
for (const w of Array.from(Services.wm.getEnumerator("navigator:browser"))) {
  if (w != win) w.close();
}
await waitFor(() => Array.from(Services.wm.getEnumerator("navigator:browser"))
                      .every(w => w == win), "the other window to close");
"""


def test_anchor_moves_when_its_window_closes(zen, site, addon):
    """The latest share is the anchor (webrtcUI appends streams), so the
    second window's share makes it the anchor; closing it moves the anchor
    back to the first window, whose tab switches place the bar again."""
    first = zen.window
    share(zen)
    wait_placed(zen, "expected88")
    zen.open_window(synced=False)
    zen.chrome(RESIZE, 300, 150)
    share(zen, "http://wiki.test/b2")
    on_second = wait_placed(zen, "expected88")
    zen.use_window(first)
    zen.chrome(CLOSE_OTHER_WINDOWS)
    end = time.monotonic() + 10
    while (n := len(zen.sharing_device_ids())) != 1:
        assert time.monotonic() < end, f"{n} tab shares after the close, not 1"
        time.sleep(0.1)
    g = wait_placed(zen, "expected88")
    assert g["expected88"] != on_second["expected88"], (on_second, g)
    assert status(zen, addon)["barProblems"] == []
    select(zen, SHARED)
    wait_placed(zen, "expected16")


def test_label_width_follows_the_content_area(zen, site, addon):
    share(zen)
    g = wait_placed(zen, "expected88")
    assert g["labelMaxProp"] == f"{g['labelMax']}px", g
    # Narrow enough that the label limit drops below its 720px cap.
    zen.chrome(RESIZE, max(0, round(g["contentWidth"]) - 800), 0)
    end = time.monotonic() + 5
    while True:
        after = bar_geometry(zen)
        if after["labelMax"] != g["labelMax"] and after["labelMaxProp"] == (
            f"{after['labelMax']}px"
        ):
            break
        assert time.monotonic() < end, (g, after)
        time.sleep(0.1)


def test_disabling_puts_the_bar_back_on_top(zen, site, addon):
    share(zen)
    wait_placed(zen, "expected88")
    zen.set_addon_enabled(addon, False)
    wait_bar_state(zen, lambda s: not s["marked"], "the stock bar")
    wait_placed(zen, "top")


# -- hide -----------------------------------------------------------------------

HIDE = 'bar.document.getElementById("zm-hide").click();'


def hide(zen):
    """Clicks Hide, as chrome code (a trusted click), and waits for it."""
    zen.bar(HIDE)
    return wait_bar_state(zen, lambda s: s["hidden"], "the bar to hide")


def current_browser_id(zen):
    return zen.chrome("return String(win.gBrowser.selectedBrowser.browserId);")


# Every MutationObserver callback on the bar root's `visible`, as the values
# set in that batch, in order: each record's successor's old value, then the
# value after the batch.
VISIBLE_WATCH = """
const root = bar.document.documentElement;
const batches = [];
const observer = new bar.MutationObserver(records => {
  batches.push([...records.slice(1).map(r => r.oldValue), root.getAttribute("visible")]);
});
observer.observe(root, { attributes: true, attributeOldValue: true,
                         attributeFilter: ["visible"] });
bar.zspTestVisible = { batches, observer };
"""

VISIBLE_READ = """
const watch = bar.zspTestVisible;
await new Promise(r => win.setTimeout(r, 300));
watch.observer.disconnect();
delete bar.zspTestVisible;
return watch.batches;
"""


def watch_visible(zen):
    zen.bar(VISIBLE_WATCH)


def read_visible(zen):
    return zen.bar(VISIBLE_READ)


def visible_batches(zen, action_js):
    """The `visible` batches (see VISIBLE_WATCH) while chrome code
    `action_js` runs, with `bar` bound, and for 300 ms after."""
    return zen.bar(
        VISIBLE_WATCH
        + "await (async () => {\n"
        + action_js
        + "\n})();\n"
        + VISIBLE_READ
    )


# Stops the shares of the tab whose browser id is args[0] alone, and waits
# until they ended.
STOP_SHARES_OF = """
const { webrtcUI } = ChromeUtils.importESModule("resource:///modules/webrtcUI.sys.mjs");
const all = () => webrtcUI.getActiveStreams(false, false, true, true, true);
const mine = () => all().filter(s => String(s.browser?.browserId) == args[0]);
webrtcUI.stopSharingStreams(mine(), false, false, true, true);
await waitFor(() => !mine().length, "the shares to stop", 10000);
"""


# Selects the tab whose browser id is args[0], loads args[1] in it when
# given, and waits for the load.
OPEN_IN = """
const tab = browserWindows().flatMap(tabsOf)
  .find(t => String(t.linkedBrowser?.browserId) == args[0]);
if (!tab) throw new Error("no tab with that browser");
win.gBrowser.selectedTab = tab;
if (args[1]) {
  const b = tab.linkedBrowser;
  const url = Services.io.newURI(args[1]).spec;
  b.fixupAndLoadURIString(url, {
    triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal(),
  });
  await waitFor(() => b.currentURI.spec == url && !b.webProgress?.isLoadingDocument &&
                      b.contentTitle, "the tab to load " + url);
}
"""

# Makes the window active and returns the selected browser's center.
CENTER = """
if (Services.focus.activeWindow != win) {
  win.focus();
  await waitFor(() => Services.focus.activeWindow == win,
                "the window to become active", 10000);
}
const r = win.gBrowser.selectedBrowser.getBoundingClientRect();
return [r.left + r.width / 2, r.top + r.height / 2];
"""

PROMPT_OPEN = """
await waitFor(() => shareNotification() && win.PopupNotifications.panel.state == "open",
              "the share prompt to open");
"""


def share_from(zen, browser_id, url, load=None):
    """Shares the tab on `url` from the capture page already in the tab of
    `browser_id` (after loading `load` there, when given), through the stock
    prompt, and waits for the share."""
    skip_if_capture_denied(zen)
    zen.settle()
    zen.visit(url)
    time.sleep(CAPTURE_LIST_CACHE_S)
    target = zen.browser_id(url)
    zen.chrome(OPEN_IN, browser_id, load)
    try:
        x, y = zen.chrome(CENTER)
    except ZenScriptError as e:
        if "become active" in str(e):
            pytest.skip(LOCKED)
        raise
    zen._click(x, y)
    zen.chrome(PROMPT_OPEN)
    zen.chrome(_SELECT_TAB_ENTRY, target)
    zen.chrome(_ALLOW_AND_WAIT, target)


def test_hide_hides_the_bar_and_keeps_the_share(zen, site, addon):
    zen.addon_call(addon, "setDebug", True)
    share(zen)
    assert bar_state(zen)["visible"] == "true"
    s = hide(zen)
    assert s["visible"] == "false", s
    assert s["marked"], s
    assert zen.bar_open()
    assert zen.sharing_device_ids()
    assert "bar hidden 1 shares" in log(zen, addon)
    zen.stop_all_shares()
    assert not zen.bar_open()
    assert zen.sharing_device_ids() == []


def test_hide_refuses_without_firefoxs_visible_attribute(zen, site, addon):
    """Without `visible` a hidden bar could never come back for a new share,
    so Hide does nothing."""
    zen.addon_call(addon, "setDebug", True)
    share(zen)
    zen.bar('bar.document.documentElement.removeAttribute("visible");')
    zen.bar(HIDE)
    time.sleep(0.3)
    s = bar_state(zen)
    assert s["marked"] and not s["hidden"], s
    assert "bar hide refused" in log(zen, addon)
    assert not any(line.startswith("bar hidden") for line in log(zen, addon))


def test_unrelated_update_never_shows_a_frame(zen, site, addon):
    """After Hide, each of Firefox's updates that brings no new share, a
    direct one and the one for a share that ends, sets `visible` to "true",
    and the add-on's re-hide sets it back to "false" in the same task: an
    observer sees both in one callback, every time."""
    share(zen)
    share(zen, "http://wiki.test/b2")
    second = current_browser_id(zen)
    hide(zen)
    batches = visible_batches(zen, "bar.updateIndicatorState();")
    assert batches == [["true", "false"]], batches
    watch_visible(zen)
    zen.chrome(STOP_SHARES_OF, second)
    batches = read_visible(zen)
    assert batches, "no update when a share ended"
    assert all(b == ["true", "false"] for b in batches), batches
    assert len(zen.sharing_device_ids()) == 1
    s = bar_state(zen)
    assert s["visible"] == "false" and s["hidden"], s


def test_a_second_share_from_the_same_tab_stays_hidden(zen, site, addon):
    share(zen)
    meet = current_browser_id(zen)
    hide(zen)
    share_from(zen, meet, "http://wiki.test/b2")
    time.sleep(0.3)
    s = bar_state(zen)
    assert s["visible"] == "false" and s["hidden"], s
    assert zen.browser_id("http://wiki.test/b2") in zen.sharing_device_ids()


def test_a_new_share_brings_the_bar_back(zen, site, addon):
    zen.addon_call(addon, "setDebug", True)
    share(zen)
    hide(zen)
    share(zen, "http://wiki.test/b2")
    s = wait_bar_state(zen, lambda s: not s["hidden"], "the bar to show")
    assert s["visible"] == "true", s
    assert len(zen.sharing_device_ids()) == 2
    assert "bar shown new-share" in log(zen, addon)


def test_after_all_shares_end_the_next_bar_shows(zen, site, addon):
    share(zen)
    hide(zen)
    share(zen, "http://wiki.test/b2")
    wait_bar_state(zen, lambda s: not s["hidden"], "the bar to show")
    hide(zen)
    zen.bar("bar.zspTestOld = true;")
    zen.stop_all_shares()
    # Firefox's shareable-tab cache: a share prompt opened sooner lists
    # only the tabs from before the stop.
    time.sleep(CAPTURE_LIST_CACHE_S)
    share(zen, "http://news.test/b3")
    assert zen.bar("return !bar.zspTestOld;"), "the old bar came back"
    s = bar_state(zen)
    assert s["visible"] == "true" and not s["hidden"], s


def test_a_share_that_restarts_brings_the_bar_back(zen, site, addon):
    """A share that ended while hidden and starts again from the same tab is
    a new share."""
    share(zen)
    first = current_browser_id(zen)
    share(zen, "http://wiki.test/b2")
    hide(zen)
    zen.chrome(OPEN_IN, first, "http://meet.test/away")
    end = time.monotonic() + 10
    while (n := len(zen.sharing_device_ids())) != 1:
        assert time.monotonic() < end, f"{n} tab shares after leaving the page, not 1"
        time.sleep(0.1)
    time.sleep(0.3)
    s = bar_state(zen)
    assert s["visible"] == "false" and s["hidden"], s
    share_from(zen, first, "http://news.test/b3", load=MEET)
    s = wait_bar_state(zen, lambda s: not s["hidden"], "the bar to show")
    assert s["visible"] == "true", s


def test_shutdown_shows_a_hidden_bar(zen, site, addon):
    share(zen)
    wait_placed(zen, "expected88")
    hide(zen)
    zen.set_addon_enabled(addon, False)
    s = wait_bar_state(zen, lambda s: not s["marked"], "the stock bar")
    assert s["visible"] == "true", s
    assert not s["hidden"], s
    assert zen.bar_open()
    assert zen.sharing_device_ids()
    wait_placed(zen, "top")


def test_a_dragged_bar_comes_back_where_it_was_dropped(zen, site, addon):
    zen.addon_call(addon, "setDebug", True)
    share(zen)
    g = wait_placed(zen, "expected88")
    dropped = zen.bar(DRAG, g["x"] + 40, g["y"] - 30)
    assert dropped == [g["x"] + 40, g["y"] - 30], (g, dropped)
    assert "bar dragged" in log(zen, addon)
    hide(zen)
    share(zen, "http://wiki.test/b2")
    s = wait_bar_state(zen, lambda s: not s["hidden"], "the bar to show")
    assert s["visible"] == "true", s
    time.sleep(0.3)
    after = bar_geometry(zen)
    assert [after["x"], after["y"]] == dropped, (dropped, after)


def test_hide_never_shows_a_pref_hidden_bar(launch_zen, site, addon_xpi):
    zen = launch_zen({"privacy.webrtc.hideGlobalIndicator": True})
    addon = install(zen, addon_xpi)
    share(zen)
    assert bar_state(zen)["visible"] == "false"
    watch_visible(zen)
    zen.bar(HIDE)
    s = bar_state(zen)
    assert s["marked"] and s["hidden"], s
    assert s["visible"] == "false", s
    share(zen, "http://wiki.test/b2")
    assert bar_state(zen)["visible"] == "false"
    batches = read_visible(zen)
    assert not any("true" in b for b in batches), batches
    zen.set_addon_enabled(addon, False)
    s = wait_bar_state(zen, lambda s: not s["marked"], "the stock bar")
    assert s["visible"] == "false", s


def bar_windows(zen, size):
    """The alphas of the test Zen's on-screen windows of `size` ([w, h],
    2 px slack), from the window server's list."""
    return [
        w["alpha"]
        for w in zen.os_windows() or []
        if abs(w["bounds"][2] - size[0]) <= 2 and abs(w["bounds"][3] - size[1]) <= 2
    ]


# Without waiting: switches the share's window to the tab on args[0] after
# 100 ms, then runs Firefox's update every 200 ms, 5 times.
SWITCH_AND_UPDATE = """
win.setTimeout(() => { win.gBrowser.selectedTab = findTab(args[0]); }, 100);
for (let i = 1; i <= 5; i++) {
  win.setTimeout(() => bar.updateIndicatorState(), 100 + 200 * i);
}
"""


def test_hide_removes_the_bar_from_the_screen(zen, site, addon):
    if os.environ.get("HEADLESS") == "1":
        pytest.skip("needs the window server, run headful")
    if sys.platform != "darwin":
        pytest.skip("reads the macOS window server's list")
    share(zen)
    size = zen.bar("return [bar.outerWidth, bar.outerHeight];")
    before = bar_windows(zen, size)
    assert any(a > 0 for a in before), (size, before)
    hide(zen)
    time.sleep(0.5)
    after = bar_windows(zen, size)
    assert not any(a > 0 for a in after), (size, after)
    # The hidden bar's placement runs on a tab switch (a resize and a move),
    # and Firefox's update sets its native window visible before the
    # re-hide: the window server never lists it, at any sample.
    zen.bar(SWITCH_AND_UPDATE, SHARED)
    samples = []
    end = time.monotonic() + 1.5
    while time.monotonic() < end:
        samples.append(bar_windows(zen, size))
    wait_placed(zen, "expected16")
    print(
        f"\nhidden samples: {len(samples)}, alphas: {sorted({a for s in samples for a in s})}"
    )
    assert len(samples) >= 3, samples
    assert not any(a > 0 for s in samples for a in s), (size, samples)
