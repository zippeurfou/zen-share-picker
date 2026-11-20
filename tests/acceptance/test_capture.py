"""Opt-in tests that preview or share a real window or the screen.

Any such capture makes macOS raise an alert on the owner's screen, so every
test here skips unless `ZSP_CAPTURE_TESTS=1` is set, and skips headless
(real windows exist only headful). Run them only with the owner at the
machine, to answer the alert. See README.md.

The tests read the picker through `Zen.picker_keys()` (keys, never a
title), reach a real window only by clicking its row's `data-key`, and
reach the screen only with Home: nothing arrows across the owner's windows.
The sharing bar tests turn the picker off and pick a window or screen in
the stock prompt by its device id, then read the bar's label and colors.
They print times and booleans only, and never copy a frame.
"""

import json
import os
import sys
import time

import pytest
from test_bar import bar_or_skip, bar_state, expected_fill
from test_picker import (
    headful_share,
    skip_if_capture_denied,
    status,
    wait_gone,
    wait_picker_keys,
    wait_status,
)
from zen import LIST_WINDOWS_PREFS

CAPTURE_REASON = (
    "captures a window or the screen, which raises a macOS alert: "
    "set ZSP_CAPTURE_TESTS=1 with the owner present"
)

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("ZSP_CAPTURE_TESTS") != "1", reason=CAPTURE_REASON
    ),
    pytest.mark.skipif(
        os.environ.get("HEADLESS") == "1", reason="needs real windows, run headful"
    ),
    pytest.mark.skipif(
        sys.platform != "darwin", reason="only macOS lists windows here"
    ),
]

SHARE_PAGE = "http://meet.test/share"
DOCS = "http://docs.test/a"
MOUNT = "zen-main-app-wrapper"

# Long enough for the owner to answer the macOS alert at a first frame.
FIRST_FRAME_S = 60
# How long a live track may take to stop after the highlight leaves.
STOP_S = 2

CAPTURE_PREFS = {**LIST_WINDOWS_PREFS, "media.getdisplaymedia.previews.enabled": True}


def record(name, data):
    """Print what a run saw: times, counts and booleans only."""
    print(f"CAPTURE {name}: {json.dumps(data, sort_keys=True)}")


def capture_zen(launch_zen, addon_xpi):
    """A test Zen that lists windows, with previews on and the add-on
    active. Skips when macOS denies Zen screen capture."""
    zen = launch_zen(CAPTURE_PREFS)
    addon = zen.install_addon(str(addon_xpi))
    zen.wait_addon_active(addon)
    skip_if_capture_denied(zen)
    return zen, addon


@pytest.fixture
def target(launch_zen):
    """A second, separate test Zen showing `DOCS`, and its window's
    `String(webrtcRawDeviceId)`. Its window belongs to another process, so
    the picker's own-window rule (P50) does not hide it."""
    other = launch_zen(LIST_WINDOWS_PREFS)
    other.visit(DOCS)
    wid = other.chrome("return String(win.windowUtils.webrtcRawDeviceId);")
    return other, wid


def open_windows_view(zen):
    """Request a share, wait for the picker, and switch to its Windows
    tab. Returns the picker's keys there."""
    zen.visit(DOCS)
    zen.settle()
    headful_share(zen)
    wait_picker_keys(zen, lambda k: k["view"] == "tabs", "the Tabs view")
    zen.chord("2")
    return wait_picker_keys(zen, lambda k: k["view"] == "windows", "the Windows view")


def first_screen(keys):
    screens = [key for key in keys["keys"] if key.startswith("screen:")]
    assert screens, f"{keys['count']} rows, no screen row"
    return screens[0]


def go_home(zen, keys):
    """Home: the first row, which is the first screen (screens come first)."""
    screen = first_screen(keys)
    assert keys["keys"][0] == screen, keys
    zen.press("Home")
    wait_picker_keys(zen, lambda k: k["selected"] == screen, "the screen row")
    return screen


def click_window(zen, keys, wid):
    key = "window:" + wid
    assert key in keys["keys"], "the target window has no row"
    zen.click_row(key)
    wait_picker_keys(zen, lambda k: k["selected"] == key, "the target window row")
    return key


# Samples Zen.live_tracks() every 50 ms in chrome, keeping the maximum in
# win.__maxTracks, until STOP_SAMPLER.
START_SAMPLER = """
win.__maxTracks = 0;
const count = () => Array.from(win.document.querySelectorAll("webrtc-preview"))
  .flatMap(el => el.videoEl?.srcObject?.getVideoTracks() ?? [])
  .filter(t => t.readyState == "live").length;
win.__sampler = win.setInterval(() => {
  win.__maxTracks = Math.max(win.__maxTracks, count());
}, 50);
"""

STOP_SAMPLER = """
win.clearInterval(win.__sampler);
return win.__maxTracks;
"""

# Milliseconds until the picker's live preview has a frame, or null after
# args[0] ms.
PICKER_FRAME = """
const t0 = ChromeUtils.now();
try {
  await waitFor(() => {
    const el = win.document.querySelector("#zen-share-picker-preview webrtc-preview");
    return el && !el.hidden && (el.videoEl?.videoWidth ?? 0) > 0;
  }, "a first frame", args[0]);
} catch (e) {
  return null;
}
return Math.round(ChromeUtils.now() - t0);
"""


def picker_frame_ms(zen):
    return zen.chrome(PICKER_FRAME, FIRST_FRAME_S * 1000, timeout=FIRST_FRAME_S + 5)


def wait_tracks(zen, n, timeout):
    end = time.monotonic() + timeout
    while True:
        got = zen.live_tracks()
        if got == n:
            return
        if time.monotonic() > end:
            raise AssertionError(f"{got} live tracks, wanted {n}")
        time.sleep(0.05)


# The system principal's MediaManagerVideo permission: what is stored, and
# what it reads as (always ALLOW for the system principal).
PREVIEW_PERMISSION = """
const perms = Services.perms;
const system = Services.scriptSecurityManager.getSystemPrincipal();
return {
  stored: perms.all.filter(p => p.type == "MediaManagerVideo").length,
  read: perms.testExactPermissionFromPrincipal(system, "MediaManagerVideo"),
  allow: perms.ALLOW_ACTION,
};
"""

# Firefox's <webrtc-preview> of a screen, in chrome, outside the picker,
# with no permission written. Waits up to args[2] ms for a first frame. The
# video is never copied.
CHROME_SCREEN_PREVIEW = """
const [mount, deviceId, ms] = args;
const doc = win.document;
const div = doc.createElementNS("http://www.w3.org/1999/xhtml", "div");
div.style.cssText = "position: fixed; top: 0; left: 0; width: 427px; height: 240px; " +
  "z-index: 2147483647;";
const el = doc.createElement("webrtc-preview");
div.append(el);
doc.getElementById(mount).append(div);
try {
  await el.updateComplete;
  const t0 = ChromeUtils.now();
  let started = true;
  try {
    await el.startPreview({ deviceId, mediaSource: "screen", showPreviewControlButtons: false });
  } catch (e) {
    started = false;
  }
  let frame = false;
  if (started) {
    try {
      await waitFor(() => el.videoEl.videoWidth > 0, "a first frame",
                    Math.max(0, ms - (ChromeUtils.now() - t0)));
      frame = true;
    } catch (e) {}
  }
  const elapsed = Math.round(ChromeUtils.now() - t0);
  const stream = el.videoEl.srcObject;
  const tracks = stream ? stream.getTracks() : [];
  el.stopPreview();
  return { started, frame, ms: elapsed,
           ended: tracks.filter(t => t.readyState == "ended").length,
           tracks: tracks.length };
} finally {
  div.remove();
}
"""


def test_screen_preview_without_a_grant(launch_zen, site, addon_xpi):
    """S9's screen half, with no grant (the add-on writes no
    permission). Records whether Firefox's preview of the first screen gets
    a frame within 60 s; asserts only that no permission was stored and
    that the preview's tracks end when it stops."""
    zen, _addon = capture_zen(launch_zen, addon_xpi)
    keys = open_windows_view(zen)
    screen_id = first_screen(keys).removeprefix("screen:")
    assert keys["selected"] is None, keys
    before = zen.chrome(PREVIEW_PERMISSION)
    seen = zen.chrome(
        CHROME_SCREEN_PREVIEW,
        MOUNT,
        screen_id,
        FIRST_FRAME_S * 1000,
        timeout=FIRST_FRAME_S + 10,
    )
    after = zen.chrome(PREVIEW_PERMISSION)
    record("screen-preview-no-grant", {**seen, "before": before, "after": after})
    assert before["stored"] == 0 and after == before, (before, after)
    assert seen["ended"] == seen["tracks"], seen
    assert zen.live_tracks() == 0


def test_live_preview_follows_the_highlight(launch_zen, site, addon_xpi, target):
    """P51: one live preview, of the highlighted window or screen only. A
    click on the target window's row starts it, Home moves it to the
    screen, Accel+1 stops it, the Windows tab starts nothing until Home,
    and Esc stops it. Never more than one live track."""
    _other, wid = target
    zen, _addon = capture_zen(launch_zen, addon_xpi)
    keys = open_windows_view(zen)
    zen.chrome(START_SAMPLER)
    assert zen.live_tracks() == 0
    click_window(zen, keys, wid)
    window_ms = picker_frame_ms(zen)
    assert window_ms is not None, "no frame of the target window"
    assert zen.live_tracks() == 1
    go_home(zen, keys)
    screen_ms = picker_frame_ms(zen)
    assert screen_ms is not None, "no frame of the screen"
    wait_tracks(zen, 1, STOP_S)
    zen.chord("1")
    wait_picker_keys(zen, lambda k: k["view"] == "tabs", "the Tabs view")
    wait_tracks(zen, 0, STOP_S)
    zen.chord("2")
    wait_picker_keys(zen, lambda k: k["view"] == "windows", "the Windows view")
    time.sleep(1)
    assert zen.live_tracks() == 0
    go_home(zen, keys)
    wait_tracks(zen, 1, FIRST_FRAME_S)
    zen.press("Escape")
    wait_gone(zen)
    wait_tracks(zen, 0, STOP_S)
    max_tracks = zen.chrome(STOP_SAMPLER)
    record(
        "live-preview",
        {"window_ms": window_ms, "screen_ms": screen_ms, "max_tracks": max_tracks},
    )
    assert max_tracks <= 1, max_tracks


# The meet.test page's active stream devices, as {mediaSource, rawId}.
# Never a device name: a window's name is its title.
SHARED_DEVICES = """
const { webrtcUI } = ChromeUtils.importESModule("resource:///modules/webrtcUI.sys.mjs");
const browser = findTab(args[0]).linkedBrowser;
return webrtcUI.getActiveStreams(true, true, true, true, true)
  .filter(s => s.browser == browser)
  .flatMap(s => s.devices ?? [])
  .map(d => ({ mediaSource: String(d.mediaSource), rawId: String(d.rawId) }));
"""


def share_and_check(zen, addon, kind, device_id):
    """Armed Enter on the highlighted row; the share must be verified, with
    a `kind` device of `device_id` on the meet.test page, and at most one
    live preview track throughout. The first frame comes first, so the
    owner has answered any macOS alert before Enter."""
    frame_ms = picker_frame_ms(zen)
    # No frame may mean an unanswered macOS alert: never press Enter then.
    assert frame_ms is not None, "no frame of the highlighted row"
    zen.wait_picker_armed(timeout=FIRST_FRAME_S)
    zen.press("Enter")
    wait_gone(zen)
    s = wait_status(
        zen,
        addon,
        lambda s: s["lastOutcome"] is not None,
        "an outcome",
        FIRST_FRAME_S,
    )
    max_tracks = zen.chrome(STOP_SAMPLER)
    devices = zen.chrome(SHARED_DEVICES, SHARE_PAGE)
    record(
        f"share-{kind}",
        {
            "frame_ms": frame_ms,
            "outcome": s["lastOutcome"],
            "devices": len(devices),
            "max_tracks": max_tracks,
        },
    )
    assert s["lastOutcome"] == "shared", s["lastOutcome"]
    assert {"mediaSource": kind, "rawId": device_id} in devices, devices
    assert max_tracks <= 1, max_tracks


def test_enter_shares_a_window(launch_zen, site, addon_xpi, target):
    _other, wid = target
    zen, addon = capture_zen(launch_zen, addon_xpi)
    keys = open_windows_view(zen)
    zen.chrome(START_SAMPLER)
    click_window(zen, keys, wid)
    share_and_check(zen, addon, "window", wid)


def test_enter_shares_the_screen(launch_zen, site, addon_xpi):
    zen, addon = capture_zen(launch_zen, addon_xpi)
    keys = open_windows_view(zen)
    zen.chrome(START_SAMPLER)
    screen = go_home(zen, keys)
    share_and_check(zen, addon, "screen", screen.removeprefix("screen:"))


# -- the sharing bar ----------------------------------------------------------

# Selects the entry of device id args[0] in the open share prompt.
SELECT_ENTRY = """
const list = win.document.getElementById("webRTC-selectWindow-menulist");
const el = win.document.getElementById("webRTC-shareDevices-notification");
const item = Array.from(list.menupopup.children).find(i => String(i.deviceId) == args[0]);
if (!item) throw new Error("no entry for the device");
list.selectedItem = item;
item.doCommand();
if (el.hasAttribute("invalidselection")) {
  item.dispatchEvent(new win.Event("command", { bubbles: true }));
}
if (el.hasAttribute("invalidselection")) throw new Error("the entry is invalid");
"""

# Presses the prompt's real Allow once the enable delay has passed, and
# waits until a device of mediaSource args[0] and rawId args[1] is shared.
# Long enough for the owner to answer the macOS alert.
ALLOW_AND_WAIT = """
const { webrtcUI } = ChromeUtils.importESModule("resource:///modules/webrtcUI.sys.mjs");
const n = shareNotification();
const el = win.document.getElementById("webRTC-shareDevices-notification");
const delay = Services.prefs.getIntPref("security.notification_enable_delay", 500);
await waitFor(() => ChromeUtils.now() - n.timeShown >= delay, "the enable delay", 5000);
el.button.click();
await waitFor(() => webrtcUI.getActiveStreams(true, true, true, true, true)
                      .flatMap(s => s.devices ?? [])
                      .some(d => d.mediaSource == args[0] && String(d.rawId) == args[1]),
              "the device to be shared", args[2]);
"""

# Booleans and colors only: the bar's state attributes, the share icon's
# fill and the body's edge, and the accent accentTokens derives from the
# bar's own AccentColor (the test profile sets no accent pref).
BAR_COLORS = """
const { accentTokens } = ChromeUtils.importESModule(args[0]);
const doc = bar.document;
const root = doc.documentElement;
const probe = doc.createElementNS("http://www.w3.org/1999/xhtml", "span");
probe.style.color = "AccentColor";
root.append(probe);
const rgb = bar.getComputedStyle(probe).color.match(/\\d+/g).slice(0, 3).map(Number);
probe.remove();
const dark = bar.matchMedia("(prefers-color-scheme: dark)").matches;
const hex = accentTokens(rgb, dark).accent;
const accent = "rgb(" + [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16)).join(", ") + ")";
const cs = sel => bar.getComputedStyle(doc.querySelector(sel));
return {
  dark,
  sharingwindow: root.getAttribute("sharingwindow") == "true",
  sharingscreen: root.getAttribute("sharingscreen") == "true",
  accent,
  fill: cs("#display-share-icon").fill,
  edge: cs("body").boxShadow,
};
"""


def bar_zen(launch_zen, addon_xpi):
    """A test Zen that lists windows (no previews), with the add-on active
    and the picker off, so a share request opens the stock prompt. The
    restyle stays on (P76). Skips when macOS denies Zen screen capture."""
    zen = launch_zen(LIST_WINDOWS_PREFS)
    addon = zen.install_addon(str(addon_xpi))
    zen.wait_addon_active(addon)
    skip_if_capture_denied(zen)
    assert zen.addon_call(addon, "setEnabled", False)["state"] == "disabled"
    return zen, addon


def open_stock_prompt(zen):
    """Requests a share from meet.test and waits for the stock prompt. Its
    entries exist only while it is open: read `stock_ids()` after this."""
    zen.visit(DOCS)
    zen.settle()
    headful_share(zen)


def stock_share(zen, kind, device_id):
    """In the open stock prompt, picks `device_id` by id, presses Allow and
    waits for the share and the bar."""
    zen.chrome(SELECT_ENTRY, device_id)
    zen.chrome(
        ALLOW_AND_WAIT,
        kind,
        device_id,
        FIRST_FRAME_S * 1000,
        timeout=FIRST_FRAME_S + 10,
    )
    bar_or_skip(zen)


def bar_colors(zen):
    return zen.bar(BAR_COLORS, zen.glue("lib/bar.mjs"))


def test_bar_for_a_window_share(launch_zen, site, addon_xpi, target):
    _other, wid = target
    zen, addon = bar_zen(launch_zen, addon_xpi)
    try:
        open_stock_prompt(zen)
        assert wid in zen.stock_ids("window"), "the target window has no entry"
        stock_share(zen, "window", wid)
        s = bar_state(zen)
        c = bar_colors(zen)
        seen = {
            "label": s["label"] == "Sharing a window with meet.test",
            "marked": s["marked"],
            "sharingwindow": c["sharingwindow"],
            "accent_icon": c["fill"] == c["accent"],
            "no_problems": status(zen, addon)["barProblems"] == [],
        }
        record("bar-window", seen)
        assert all(seen.values()), seen
    finally:
        zen.stop_all_shares()


def test_bar_for_a_zen_window_share(launch_zen, site, addon_xpi):
    zen, addon = bar_zen(launch_zen, addon_xpi)
    try:
        open_stock_prompt(zen)
        windows = zen.stock_ids("window")
        own = [i for i in zen.zen_window_ids() if i in windows]
        assert own, "no entry for this Zen's own window"
        stock_share(zen, "window", own[0])
        s = bar_state(zen)
        c = bar_colors(zen)
        seen = {
            "label": s["label"] == "Sharing a Zen window with meet.test",
            "marked": s["marked"],
            "sharingwindow": c["sharingwindow"],
            "no_problems": status(zen, addon)["barProblems"] == [],
        }
        record("bar-zen-window", seen)
        assert all(seen.values()), seen
    finally:
        zen.stop_all_shares()


def test_bar_for_the_whole_screen(launch_zen, site, addon_xpi):
    zen, addon = bar_zen(launch_zen, addon_xpi)
    try:
        open_stock_prompt(zen)
        screens = zen.stock_ids("screen")
        assert screens, "no screen entry"
        stock_share(zen, "screen", screens[0])
        s = bar_state(zen)
        c = bar_colors(zen)
        stop = expected_fill(zen)
        amber = "rgb(255, 196, 107)" if c["dark"] else "rgb(179, 98, 0)"
        seen = {
            "label": s["label"] == "Sharing your entire screen with meet.test",
            "marked": s["marked"],
            "sharingscreen": c["sharingscreen"],
            "amber_icon": c["fill"] == amber,
            "amber_edge": "rgba(214, 130, 0, 0.55)" in c["edge"],
            "stop_accent": stop["got"] == stop["expected"],
            "no_problems": status(zen, addon)["barProblems"] == [],
        }
        record("bar-screen", seen)
        assert all(seen.values()), seen
    finally:
        zen.stop_all_shares()
