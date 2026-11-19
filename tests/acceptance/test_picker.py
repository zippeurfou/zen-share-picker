"""The whole add-on against Zen's real screen-share prompt: the picker opens
on a screen-share request, shares through the stock Allow button, and leaves
the stock prompt as Zen built it whenever it cannot help.

Zen lists only each window's active space in the prompt (P13), so a test
that needs another space's rows opens a second window on that space (P14).
"""

import sys
import time

import pytest
from marionette_driver.addons import Addons
from zen import CENTER_TOL_PX, SECONDARY_LABEL, ZenScriptError

SHARE_PAGE = "http://meet.test/share"
DOCS = "http://docs.test/a"
WIKI = "http://wiki.test/a"
MAIL = "http://mail.test/a"
REVEAL = "Tab: show tabs from your other spaces"
NO_MATCH = "No match here. Tab to search other spaces."
# config.mjs TIMING.allowWindowMs and maxClicks.
ALLOW_WINDOW_S = 5
MAX_CLICKS = 2

# The picker as the tests see it, or None when it is not in the DOM.
PICKER = """
const root = win.document.getElementById("zen-share-picker");
if (!root) return null;
const rows = Array.from(root.querySelectorAll(".zsp-row"));
const sel = rows.find(r => r.getAttribute("aria-selected") == "true");
return {
  keys: rows.map(r => r.dataset.key),
  groups: rows.map(r => r.dataset.group),
  selected: sel ? sel.dataset.key : null,
  headers: Array.from(root.querySelectorAll(".zsp-space-header")).map(h => h.textContent),
  hints: Object.fromEntries(Array.from(root.querySelectorAll(".zsp-hint"))
    .map(h => [h.dataset.hint, h.textContent])),
  text: root.textContent,
  careful: rows.filter(r => r.querySelector(".zsp-careful")?.textContent == "careful")
    .map(r => r.dataset.key),
  focused: win.document.activeElement?.id ?? null,
  old: root.dataset.zspOld == "1",
  armed: !root.querySelector("#zen-share-picker-share").disabled,
  header: root.querySelector("#zen-share-picker-header")?.textContent ?? null,
};
"""

# The marker on the add-on's hiding style elements (P35).
CONCEAL_MARKER = "data-zen-share-picker-conceal"

# The stock prompt of the selected tab: open, never dismissed (P22), and
# whether Zen's panel is concealed (P35). `concealed` is the panel's
# computed style alone (test_platform.py S6a); `markers` counts the
# add-on's hiding style elements in the window.
PROMPT = """
const n = win.PopupNotifications.getNotification("webRTC-shareDevices",
                                                 win.gBrowser.selectedBrowser);
const s = win.getComputedStyle(win.PopupNotifications.panel);
return {
  exists: !!n,
  open: !!n && win.PopupNotifications.panel.state == "open",
  dismissed: n ? n.dismissed : null,
  concealed: s.opacity == "0" && s.pointerEvents == "none",
  markers: win.document.querySelectorAll("[" + args[0] + "]").length,
};
"""


def picker(zen):
    return zen.chrome(PICKER)


def wait_picker(zen, pred=lambda p: True, what="the picker", timeout=2.0):
    end = time.monotonic() + timeout
    while True:
        p = picker(zen)
        if p is not None and pred(p):
            return p
        if time.monotonic() > end:
            raise AssertionError(f"timed out waiting for {what}: {p}")
        time.sleep(0.05)


def wait_gone(zen, timeout=2.0):
    end = time.monotonic() + timeout
    while picker(zen) is not None:
        if time.monotonic() > end:
            raise AssertionError("the picker did not close")
        time.sleep(0.05)


def assert_no_picker_for(zen, seconds=2.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        p = picker(zen)
        assert p is None, p
        time.sleep(0.1)


def prompt(zen):
    return zen.chrome(PROMPT, CONCEAL_MARKER)


def assert_prompt_untouched(zen):
    """The stock prompt as Zen built it: open, not dismissed, visible."""
    p = prompt(zen)
    expected = {
        "exists": True,
        "open": True,
        "dismissed": False,
        "concealed": False,
        "markers": 0,
    }
    assert p == expected, p


def wait_concealed(zen, timeout=1.0):
    """The prompt state once the panel's computed style shows it hidden, or
    after `timeout`. Off macOS, popup.css transitions the panel's opacity,
    so the hiding takes effect over that transition."""
    end = time.monotonic() + timeout
    while True:
        p = prompt(zen)
        if p["concealed"] or time.monotonic() > end:
            return p
        time.sleep(0.05)


def assert_prompt_concealed(zen):
    """The stock prompt open and not dismissed, its panel hidden by the
    add-on's one marker while the picker is open (P35)."""
    p = wait_concealed(zen)
    expected = {
        "exists": True,
        "open": True,
        "dismissed": False,
        "concealed": True,
        "markers": 1,
    }
    assert p == expected, p


def assert_not_concealed(zen, timeout=2.0):
    """Nothing hides Zen's panel, whether or not the prompt is still there.

    Polled: a share reveals once its sequence settles, a little after the
    page has its stream. And off macOS, popup.css fades a closing panel out
    with `pointer-events: none` while it animates."""
    end = time.monotonic() + timeout
    while True:
        p = prompt(zen)
        if (p["concealed"], p["markers"]) == (False, 0):
            return
        if time.monotonic() > end:
            raise AssertionError(f"the panel is still concealed: {p}")
        time.sleep(0.05)


def status(zen, addon):
    return zen.addon_call(addon, "getStatus")


def wait_status(zen, addon, pred, what, timeout):
    end = time.monotonic() + timeout
    while True:
        s = status(zen, addon)
        if pred(s):
            return s
        if time.monotonic() > end:
            raise AssertionError(f"timed out waiting for {what}: {s}")
        time.sleep(0.1)


def key_of(zen, url):
    """Row.key of the tab on `url` (P9): its synced DOM id, this window first."""
    return zen.chrome(
        """
        const t = findTab(args[0]);
        return t.id || "browser:" + t.linkedBrowser.browserId;
        """,
        url,
    )


def wait_title(zen, url, title, timeout=5.0):
    end = time.monotonic() + timeout
    while zen.page_title(url) != title:
        assert time.monotonic() < end, zen.page_title(url)
        time.sleep(0.1)


def assert_no_stream(zen):
    assert zen.sharing_device_ids() == []
    assert zen.page_title(SHARE_PAGE) != "shared"


def spaces(zen):
    """Spaces Work (no container, active) and Perso (container "Perso").
    Work tabs docs.test/a then wiki.test/a, a Perso tab mail.test/a."""
    work = zen.make_space("Work", None)
    perso = zen.make_space("Perso", "Perso")
    zen.switch_space(perso)
    zen.visit(MAIL)
    zen.switch_space(work)
    zen.visit(DOCS)
    zen.visit(WIKI)
    return work, perso


def perso_window(zen, perso):
    """A second synced window on Perso, showing the Perso tab, so the prompt
    lists it (P13, P14). The first window stays selected. Returns the
    second window's handle."""
    first = zen.window
    second = zen.open_window()
    zen.switch_space(perso)
    zen.chrome(
        """
        const tab = tabsOf(win).find(t => t.linkedBrowser?.currentURI?.spec == args[0]);
        win.gBrowser.selectedTab = tab;
        await waitFor(() => tab.linkedPanel, "the Perso tab to have a browser");
        """,
        MAIL,
    )
    zen.use_window(first)
    return second


def listed_browser_id(zen, handle, url):
    """String(browserId) of the copy of the tab on `url` in window `handle`."""
    back = zen.window
    zen.use_window(handle)
    try:
        return zen.browser_id(url)
    finally:
        zen.use_window(back)


def setup(zen, *, other_window=False):
    _work, perso = spaces(zen)
    second = perso_window(zen, perso) if other_window else None
    zen.request_share()
    return second


def show_prompt_again(zen):
    """Switch to the docs tab and back to Meet: Zen hides the prompt and
    shows it again (a new PanelUpdated for the same notification)."""
    zen.chrome("win.gBrowser.selectedTab = findTab(args[0]);", DOCS)
    zen.chrome(
        """
        win.gBrowser.selectedTab = findTab(args[0]);
        await waitFor(() => shareNotification() &&
                            win.PopupNotifications.panel.state == "open",
                      "the prompt to show again");
        """,
        SHARE_PAGE,
    )


def count_allow(zen):
    """Count clicks on Allow in win.__allowSeen, without blocking them."""
    zen.chrome(
        """
        const el = win.document.getElementById("webRTC-shareDevices-notification");
        win.__allowSeen = 0;
        el.addEventListener("buttoncommand", () => win.__allowSeen++, { capture: true });
        """
    )


def block_allow(zen):
    """Count clicks on Allow and keep Zen from acting on them: a capturing
    `buttoncommand` listener on the prompt calls preventDefault
    (popupnotification.js customEventDelegator)."""
    zen.chrome(
        """
        const el = win.document.getElementById("webRTC-shareDevices-notification");
        win.__allowClicks = 0;
        el.addEventListener("buttoncommand", e => {
          win.__allowClicks++;
          e.preventDefault();
        }, { capture: true });
        """
    )


def allow_clicks(zen):
    return zen.chrome("return win.__allowClicks;")


# Wraps PopupNotifications.remove: counts in win.__removes the calls that
# abandon the share prompt (`remove(n, true)` on a webRTC-shareDevices
# notification). For those calls, "pass" calls the real method, "noop" does
# nothing and "throw" throws. Every other call goes to the real method.
SPY_REMOVE = """
const PN = win.PopupNotifications;
const orig = PN.remove;
const mode = args[0];
win.__removes = 0;
PN.remove = function (n, withoutUserResponse, ...rest) {
  if (n?.id == "webRTC-shareDevices" && withoutUserResponse === true) {
    win.__removes++;
    if (mode == "noop") return undefined;
    if (mode == "throw") throw new Error("x");
  }
  return orig.call(this, n, withoutUserResponse, ...rest);
};
"""


def spy_remove(zen, mode: str = "pass") -> None:
    assert mode in ("pass", "noop", "throw"), mode
    zen.chrome(SPY_REMOVE, mode)


def removes(zen) -> int:
    return zen.chrome("return win.__removes;")


# The page's title once Zen denied its request (test_platform.py S7).
REJECTED = "share failed NotAllowedError"


def assert_rejected_without_permission(zen, timeout=2.0):
    """The page's share request was rejected, the prompt is gone, and no
    "screen" permission was set for the site (P38)."""
    end = time.monotonic() + timeout
    while zen.page_title(SHARE_PAGE) != REJECTED:
        assert time.monotonic() < end, zen.page_title(SHARE_PAGE)
        time.sleep(0.05)
    assert zen.chrome("return !!shareNotification();") is False
    assert zen.screen_permission() == 0


# Runs onEffect(session, {type: "cancel"}) through the add-on's API object.
# args[0] is the add-on id; the session is win.__session, stored by
# KEEP_SESSION.
KEEP_SESSION = """
const { ExtensionParent } = ChromeUtils.importESModule(
  "resource://gre/modules/ExtensionParent.sys.mjs");
const extension = ExtensionParent.GlobalManager.getExtension(args[0]);
const api = extension.apiManager.getAPI("sharePicker", extension, "addon_parent");
win.__session = api._picker.sessions.get(win);
if (!win.__session) throw new Error("no session");
"""

CANCEL_AGAIN = """
const { ExtensionParent } = ChromeUtils.importESModule(
  "resource://gre/modules/ExtensionParent.sys.mjs");
const extension = ExtensionParent.GlobalManager.getExtension(args[0]);
const api = extension.apiManager.getAPI("sharePicker", extension, "addon_parent");
api._picker.onEffect(win.__session, { type: "cancel" });
"""


def click(zen, selector):
    """A real mouse click (WebDriver pointer actions) on the middle of the
    chrome element `selector`."""
    x, y = zen.chrome(
        """
        const el = win.document.querySelector(args[0]);
        if (!el) throw new Error("no element " + args[0]);
        const r = el.getBoundingClientRect();
        return [r.left + r.width / 2, r.top + r.height / 2];
        """,
        selector,
    )
    zen._click(x, y)


def wrap_append_item(zen, how):
    """Wrap the stock menulist's appendItem, before the prompt is built, so
    each item it returns gets an accessor (eval is not allowed in chrome):

    - "prefix-device-id": `deviceId` stores "x" + the value;
    - "numeric-media-source": `mediaSource` stores the value and reads 42;
    - "drop-tab-entries": an item whose `mediaSource` is set to "browser"
      leaves the list, as when the prompt offers no tabs.
    """
    zen.chrome(
        """
        const how = args[0];
        const list = win.document.getElementById("webRTC-selectWindow-menulist");
        const orig = list.appendItem;
        list.appendItem = function (...a) {
          const item = orig.apply(this, a);
          let stored;
          if (how == "prefix-device-id") {
            Object.defineProperty(item, "deviceId", {
              configurable: true,
              get: () => stored,
              set: v => { stored = "x" + v; },
            });
          } else if (how == "numeric-media-source") {
            Object.defineProperty(item, "mediaSource", {
              configurable: true,
              get: () => 42,
              set: v => { stored = v; },
            });
          } else if (how == "drop-tab-entries") {
            Object.defineProperty(item, "mediaSource", {
              configurable: true,
              get: () => stored,
              set: v => {
                stored = v;
                if (v == "browser") item.remove();
              },
            });
          } else {
            throw new Error("unknown wrap " + how);
          }
          return item;
        };
        """,
        how,
    )


def count_captures(zen):
    """Count PageThumbs captures from now on, in win.__captures."""
    zen.chrome(
        """
        const { PageThumbs } = ChromeUtils.importESModule(
          "resource://gre/modules/PageThumbs.sys.mjs");
        win.__captures = 0;
        const orig = PageThumbs.captureTabPreviewThumbnail;
        PageThumbs.captureTabPreviewThumbnail = function (...a) {
          win.__captures++;
          return orig.apply(this, a);
        };
        """
    )


def captures(zen):
    return zen.chrome("return win.__captures;")


def skip_if_capture_denied(zen):
    if zen.screen_capture_denied():
        pytest.skip("macOS denies Zen screen capture; Allow would raise a macOS dialog")


# -- opening ------------------------------------------------------------------


def test_picker_opens_for_a_screen_share(zen, site, addon):
    setup(zen)
    p = wait_picker(zen)
    expected = [key_of(zen, WIKI), key_of(zen, DOCS), key_of(zen, SHARE_PAGE), "os"]
    assert p["keys"] == expected, p
    assert p["selected"] == key_of(zen, WIKI), p
    assert p["groups"][-1] == "os", p
    assert p["focused"] == "zen-share-picker-search", p
    assert p["header"] == "meet.test wants to see your screen", p
    assert_prompt_concealed(zen)
    s = status(zen, addon)
    assert s["state"] == "active", s
    assert s["promptProblems"] == [], s


# The picker's centre against the window's, and what is under the middle of
# its search box. Both after layout.
CENTRE = """
const doc = win.document;
const root = doc.getElementById("zen-share-picker");
await waitFor(() => root.getBoundingClientRect().height > 200, "layout");
const r = root.getBoundingClientRect();
const search = doc.getElementById("zen-share-picker-search").getBoundingClientRect();
const hit = doc.elementFromPoint(search.left + search.width / 2,
                                 search.top + search.height / 2);
return {
  dx: r.left + r.width / 2 - win.innerWidth / 2,
  dy: r.top + r.height / 2 - win.innerHeight / 2,
  w: win.innerWidth,
  h: win.innerHeight,
  hit: hit?.id ?? null,
};
"""


def assert_centred(got):
    assert abs(got["dx"]) <= CENTER_TOL_PX, got
    assert abs(got["dy"]) <= CENTER_TOL_PX, got


def test_picker_is_centred_over_the_concealed_panel(zen, site, addon):
    """P37: Zen's panel is concealed while the picker is open, so the picker
    sits in the middle of the window, and stays there on a resize."""
    spaces(zen)
    zen.settle()
    zen.request_share()
    wait_picker(zen)
    zen.settle()
    got = zen.chrome(CENTRE)
    assert_centred(got)
    assert got["hit"] == "zen-share-picker-search", got
    assert_prompt_concealed(zen)
    # Measured right after the resize, then once the window settled: a
    # tiling window manager may size the window again.
    moved = zen.chrome(
        """
        const w0 = win.innerWidth;
        win.resizeTo(win.outerWidth - 200, win.outerHeight);
        await waitFor(() => win.innerWidth <= w0 - 150, "the window to resize");
        await new Promise(r => win.requestAnimationFrame(r));
        """
        + CENTRE
    )
    assert_centred(moved)
    zen.settle()
    assert_centred(zen.chrome(CENTRE))
    zen.type_text("wiki")
    value = zen.chrome(
        'return win.document.getElementById("zen-share-picker-search").value;'
    )
    assert value == "wiki"


def test_other_spaces_stay_hidden(zen, site, addon):
    setup(zen, other_window=True)
    p = wait_picker(zen)
    assert "mail.test" not in p["text"], p
    assert "Perso" not in p["text"], p
    assert p["hints"]["reveal"] == REVEAL, p
    zen.press("Tab")
    p = wait_picker(zen, lambda p: p["headers"], "the reveal")
    assert p["headers"] == ["Perso"], p
    assert "mail.test" in p["text"], p
    mail = key_of(zen, MAIL)
    i = p["keys"].index(mail)
    assert p["groups"][i] == "other", p
    assert mail in p["careful"], p


def test_typing_never_reveals_other_spaces(zen, site, addon):
    setup(zen, other_window=True)
    wait_picker(zen)
    zen.type_text("mail")
    p = wait_picker(zen, lambda p: "no-match" in p["hints"], "the no-match hint")
    assert p["hints"]["no-match"] == NO_MATCH, p
    assert "mail.test" not in p["text"], p
    assert p["keys"] == ["os"], p


# -- sharing ------------------------------------------------------------------


def test_enter_shares_the_chosen_tab(zen, site, addon):
    skip_if_capture_denied(zen)
    setup(zen)
    wait_picker(zen)
    zen.press("ArrowDown")
    wait_picker(zen, lambda p: p["selected"] == key_of(zen, DOCS), "docs highlighted")
    zen.wait_picker_armed()
    zen.press("Enter")
    wait_gone(zen)
    wait_title(zen, SHARE_PAGE, "shared")
    assert zen.sharing_device_ids() == [zen.browser_id(DOCS)]
    s = wait_status(zen, addon, lambda s: s["lastOutcome"] == "shared", "shared", 5)
    assert s["promptProblems"] == [], s
    assert_not_concealed(zen)


# -- arming (P33) -----------------------------------------------------------------

# A user-set delay long enough that a test acts well inside it.
SLOW_DELAY = {"security.notification_enable_delay": 3000}


def slow_zen(launch_zen, addon_xpi):
    zen = launch_zen(SLOW_DELAY)
    addon = zen.install_addon(str(addon_xpi))
    zen.wait_addon_active(addon)
    return zen, addon


def assert_nothing_committed(zen, addon):
    p = picker(zen)
    assert p is not None, "the picker closed"
    assert_prompt_concealed(zen)
    assert zen.chrome("return win.__allowSeen;") == 0
    assert status(zen, addon)["lastOutcome"] is None
    assert_no_stream(zen)


def test_enter_at_open_shares_nothing(launch_zen, site, addon_xpi):
    """P33: an Enter sent at once after the picker opens is ignored."""
    zen, addon = slow_zen(launch_zen, addon_xpi)
    setup(zen)
    count_allow(zen)
    p = wait_picker(zen)
    assert not p["armed"], p
    zen.press("Enter")
    time.sleep(1)
    p = picker(zen)
    assert p is not None and not p["armed"], p
    assert p["selected"] == key_of(zen, WIKI), p
    assert_nothing_committed(zen, addon)


def test_share_click_at_open_shares_nothing(launch_zen, site, addon_xpi):
    """P33: Share stays disabled until armed; a click on it does nothing."""
    zen, addon = slow_zen(launch_zen, addon_xpi)
    setup(zen)
    count_allow(zen)
    wait_picker(zen)
    click(zen, "#zen-share-picker-share")
    time.sleep(1)
    assert_nothing_committed(zen, addon)


def test_enter_after_the_delay_shares(launch_zen, site, addon_xpi):
    """P33: the same Enter, once the user-set delay has passed, shares."""
    zen, addon = slow_zen(launch_zen, addon_xpi)
    skip_if_capture_denied(zen)
    setup(zen)
    wait_picker(zen)
    zen.press("Enter")
    time.sleep(1)
    assert picker(zen) is not None
    assert status(zen, addon)["lastOutcome"] is None
    zen.wait_picker_armed()
    zen.press("Enter")
    wait_gone(zen)
    wait_title(zen, SHARE_PAGE, "shared")
    assert zen.sharing_device_ids() == [zen.browser_id(WIKI)]
    wait_status(zen, addon, lambda s: s["lastOutcome"] == "shared", "shared", 5)


def test_reactivated_window_ignores_an_immediate_enter(launch_zen, site, addon_xpi):
    """P33: the delay restarts when the window is activated again."""
    zen, addon = slow_zen(launch_zen, addon_xpi)
    setup(zen)
    count_allow(zen)
    wait_picker(zen)
    zen.wait_picker_armed()
    first = zen.window
    zen.open_window()
    zen.chrome(
        """
        win.focus();
        await waitFor(() => Services.focus.activeWindow == win, "window 2 active", 10000);
        """
    )
    zen.use_window(first)
    zen.chrome(
        """
        win.focus();
        await waitFor(() => Services.focus.activeWindow == win, "window 1 active", 10000);
        """
    )
    p = picker(zen)
    assert p is not None and not p["armed"], p
    zen.press("Enter")
    time.sleep(1)
    assert_nothing_committed(zen, addon)
    zen.wait_picker_armed()


def test_addon_refuses_an_unarmed_share(launch_zen, site, addon_xpi):
    """P33 defense in depth: api.js refuses a share or os effect that
    reaches it before the session is armed, whatever the overlay did."""
    zen, addon = slow_zen(launch_zen, addon_xpi)
    setup(zen)
    count_allow(zen)
    wait_picker(zen)
    wiki = zen.browser_id(WIKI)
    zen.chrome(
        """
        const { ExtensionParent } = ChromeUtils.importESModule(
          "resource://gre/modules/ExtensionParent.sys.mjs");
        const extension = ExtensionParent.GlobalManager.getExtension(args[0]);
        const api = extension.apiManager.getAPI("sharePicker", extension, "addon_parent");
        const p = api._picker;
        const session = p.sessions.get(win);
        if (!session) throw new Error("no session");
        p.onEffect(session, { type: "share", deviceId: args[1] });
        p.onEffect(session, { type: "os" });
        """,
        addon,
        wiki,
    )
    time.sleep(1)
    assert_nothing_committed(zen, addon)


def test_esc_at_open_declines(launch_zen, site, addon_xpi):
    """P36: Esc is not a commit, so arming never holds it back."""
    zen, addon = slow_zen(launch_zen, addon_xpi)
    setup(zen)
    p = wait_picker(zen)
    assert not p["armed"], p
    spy_remove(zen)
    zen.press("Escape")
    wait_gone(zen)
    assert_declined(zen, addon)
    p = picker(zen)
    assert p is None, p


def test_revealed_tab_needs_a_second_enter(zen, site, addon):
    skip_if_capture_denied(zen)
    second = setup(zen, other_window=True)
    target = listed_browser_id(zen, second, MAIL)
    mail = key_of(zen, MAIL)
    wait_picker(zen)
    zen.press("Tab")
    wait_picker(zen, lambda p: p["headers"], "the reveal")
    for _ in range(5):
        if picker(zen)["selected"] == mail:
            break
        zen.press("ArrowDown")
    assert picker(zen)["selected"] == mail
    zen.wait_picker_armed()
    zen.press("Enter")
    p = wait_picker(zen, lambda p: "confirm" in p["hints"], "the confirm hint")
    assert "Perso" in p["hints"]["confirm"], p
    assert_prompt_concealed(zen)
    assert_no_stream(zen)
    zen.press("Enter")
    wait_gone(zen)
    wait_title(zen, SHARE_PAGE, "shared")
    assert zen.sharing_device_ids() == [target]
    wait_status(zen, addon, lambda s: s["lastOutcome"] == "shared", "shared", 5)


# -- declining (P36, P38) --------------------------------------------------------

# config.mjs TIMING.goneWaitMs.
GONE_WAIT_S = 1
CAMERA = pytest.mark.parametrize("camera", [True, False], ids=["camera", "no-camera"])


def assert_declined(zen, addon):
    """One abandon of the share prompt, the page's request rejected with no
    permission set, the panel no longer hidden, and nothing shared."""
    s = wait_status(
        zen,
        addon,
        lambda s: s["lastOutcome"] == "declined",
        "declined",
        GONE_WAIT_S + 1,
    )
    assert removes(zen) == 1
    assert_rejected_without_permission(zen)
    assert_not_concealed(zen)
    assert s["promptProblems"] == [], s
    assert_no_stream(zen)


def wait_decline_failed(zen, addon):
    return wait_status(
        zen,
        addon,
        lambda s: "decline-failed" in s["promptProblems"],
        "decline-failed",
        GONE_WAIT_S + 1,
    )


@CAMERA
def test_esc_declines_the_request(zen, site, addon, camera):
    """P36: Esc abandons the request through Zen's own path, whether Zen's
    secondary button would read "Not now" (camera allowed) or "Block"."""
    if camera:
        zen.allow_camera()
    setup(zen)
    assert zen.secondary_label() == SECONDARY_LABEL[camera]
    wait_picker(zen)
    spy_remove(zen)
    zen.press("Escape")
    wait_gone(zen)
    assert_declined(zen, addon)


@pytest.mark.parametrize("silencing", [True, False], ids=["silencing", "no-silencing"])
def test_ticked_checkbox_still_declines_without_a_permission(
    launch_zen, site, addon_xpi, silencing
):
    """P38: abandoning ignores the prompt's checkbox, even ticked."""
    zen = launch_zen({"privacy.webrtc.allowSilencingNotifications": silencing})
    addon = zen.install_addon(str(addon_xpi))
    zen.wait_addon_active(addon)
    zen.allow_camera()
    setup(zen)
    wait_picker(zen)
    spy_remove(zen)
    # Ticked as a user's tick: the command event lets Zen record it
    # (PopupNotifications _onCheckboxCommand).
    ticked = zen.chrome(
        """
        const el = win.document.getElementById("webRTC-shareDevices-notification");
        el.checkbox.checked = true;
        el.checkbox.doCommand();
        return el.checkbox.checked;
        """
    )
    assert ticked is True
    zen.press("Escape")
    wait_gone(zen)
    wait_status(
        zen,
        addon,
        lambda s: s["lastOutcome"] == "declined",
        "declined",
        GONE_WAIT_S + 1,
    )
    assert removes(zen) == 1
    assert_rejected_without_permission(zen)


def test_a_prompt_that_stays_is_shown(zen, site, addon):
    """P36: when the abandoned notification stays, Zen's prompt shows again
    and the user decides there; the request is still pending."""
    setup(zen)
    wait_picker(zen)
    spy_remove(zen, "noop")
    zen.press("Escape")
    wait_gone(zen)
    s = wait_decline_failed(zen, addon)
    assert s["lastOutcome"] == "cancelled", s
    assert_prompt_untouched(zen)
    assert removes(zen) == 1
    assert zen.page_title(SHARE_PAGE) == "meet.test share"
    # The prompt shown again gets no picker.
    show_prompt_again(zen)
    assert_no_picker_for(zen, 2)
    assert removes(zen) == 1
    assert_no_stream(zen)


def test_a_throw_while_declining_shows_the_prompt(zen, site, addon):
    """P36: a throw from the abandon, after the panel was hidden, shows Zen's
    prompt again."""
    setup(zen)
    wait_picker(zen)
    assert_prompt_concealed(zen)
    spy_remove(zen, "throw")
    zen.press("Escape")
    wait_gone(zen)
    s = wait_decline_failed(zen, addon)
    assert s["lastOutcome"] == "cancelled", s
    assert_prompt_untouched(zen)
    assert removes(zen) == 1
    assert zen.page_title(SHARE_PAGE) == "meet.test share"


def test_second_cancel_on_a_session_removes_once(zen, site, addon):
    """A second cancel on the same session, while the first one waits for
    the notification to go, abandons nothing more. It goes through the API
    object: once the picker closed, a real Esc reaches Zen's own panel."""
    setup(zen)
    wait_picker(zen)
    zen.chrome(KEEP_SESSION, addon)
    spy_remove(zen, "noop")
    zen.press("Escape")
    zen.chrome(CANCEL_AGAIN, addon)
    time.sleep(GONE_WAIT_S + 1)
    assert removes(zen) == 1
    wait_decline_failed(zen, addon)
    zen.chrome(CANCEL_AGAIN, addon)
    time.sleep(0.5)
    assert removes(zen) == 1


def test_inactive_window_still_declines(zen, site, addon):
    """P38: declining needs no active window."""
    setup(zen)
    wait_picker(zen)
    spy_remove(zen)
    zen.chrome(KEEP_SESSION, addon)
    first = zen.window
    zen.open_window()
    zen.chrome(
        """
        win.focus();
        await waitFor(() => Services.focus.activeWindow == win, "window 2 active", 10000);
        """
    )
    zen.use_window(first)
    assert zen.chrome("return Services.focus.activeWindow != win;") is True
    zen.chrome(CANCEL_AGAIN, addon)
    assert_declined(zen, addon)
    assert prompt(zen)["markers"] == 0


# -- Esc and focus while the panel is hidden (P44) ------------------------------

# A point on the page below the open picker, clear of Zen's panel.
BELOW_PICKER = """
const b = win.gBrowser.selectedBrowser.getBoundingClientRect();
const p = win.document.getElementById("zen-share-picker").getBoundingClientRect();
if (b.bottom - p.bottom < 8) throw new Error("no page below the picker");
return [b.left + b.width / 2, (p.bottom + b.bottom) / 2];
"""

# Where keyboard focus is. `inPanel` walks out through shadow roots, as
# Zen's own Esc handler does (PopupNotifications.sys.mjs:309-317).
FOCUS = """
const panel = win.PopupNotifications.panel;
const f = Services.focus.focusedElement;
let inPanel = false;
for (let el = f; el; el = el.parentNode ?? el.host) {
  if (el === panel) {
    inPanel = true;
    break;
  }
}
return {
  inPanel,
  onBrowser: f === win.gBrowser.selectedBrowser,
  id: f?.id ?? null,
  name: f?.localName ?? null,
};
"""

# Moves focus to the Allow button of Zen's share prompt, as a script or an
# assistive tool could, then reports where focus is.
FOCUS_ALLOW = (
    """
win.document.getElementById("webRTC-shareDevices-notification").button.focus();
"""
    + FOCUS
)

# With full keyboard access (macOS) every control takes focus, Zen's panel
# buttons included.
FULL_KEYBOARD = {"accessibility.tabfocus": 7}

# Headless Linux: a script cannot focus the panel's Allow button even with
# the panel shown, so the focus guard has nothing to catch there.
NO_PANEL_FOCUS = "the panel's Allow button takes no focus here, even shown (control)"


def focus(zen):
    return zen.chrome(FOCUS)


def settled_setup(zen):
    """setup(), with the window and Zen's panel settled before the share
    request and after the picker opens, for headful runs."""
    spaces(zen)
    zen.settle()
    zen.request_share()
    wait_picker(zen)
    zen.settle()


def click_page(zen, below_picker=True):
    """A real click on the page: below the picker, or in the middle. The
    page's share button is disabled first, so the click puts focus on the
    page and asks for nothing more."""
    zen.content('document.getElementById("go").disabled = true;')
    if below_picker:
        x, y = zen.chrome(BELOW_PICKER)
    else:
        x, y = zen.chrome(
            """
            const b = win.gBrowser.selectedBrowser.getBoundingClientRect();
            return [b.left + b.width / 2, b.top + b.height / 2];
            """
        )
    zen._click(x, y)
    got = focus(zen)
    assert got["onBrowser"], got


@CAMERA
def test_esc_with_focus_on_the_page_declines(zen, site, addon, camera):
    """P44: while the panel is hidden, Esc is the picker's, wherever focus
    is. With focus on the page, Zen's own Esc handler would act on the
    hidden prompt: "Block", a temporary block, without a camera grant."""
    if camera:
        zen.allow_camera()
    settled_setup(zen)
    assert zen.secondary_label() == SECONDARY_LABEL[camera]
    wait_picker(zen)
    assert_prompt_concealed(zen)
    spy_remove(zen)
    click_page(zen)
    assert picker(zen) is not None
    zen.press("Escape")
    wait_gone(zen)
    assert_declined(zen, addon)


def test_esc_during_the_allow_wait_does_nothing(zen, site, addon):
    """P44: while a share waits to press the hidden panel's Allow, Esc does
    nothing, focus never rests in the panel, and the share goes through."""
    skip_if_capture_denied(zen)
    settled_setup(zen)
    wait_picker(zen)
    zen.wait_picker_armed()
    spy_remove(zen)
    # Zen restarts its enable delay from timeShown; this makes the share
    # wait about 2.5 s before its Allow click is taken.
    zen.chrome("shareNotification().timeShown = ChromeUtils.now() + 2000;")
    zen.press("Enter")
    wait_gone(zen)
    got = prompt(zen)
    assert (got["exists"], got["markers"]) == (True, 1), got
    click_page(zen, below_picker=False)
    got = zen.chrome(FOCUS_ALLOW)
    assert not got["inPanel"] and got["onBrowser"], got
    zen.press("Escape")
    got = prompt(zen)
    assert (got["exists"], got["markers"]) == (True, 1), got
    assert status(zen, addon)["lastOutcome"] is None
    wait_title(zen, SHARE_PAGE, "shared")
    wait_status(zen, addon, lambda s: s["lastOutcome"] == "shared", "shared", 5)
    assert removes(zen) == 0
    assert zen.screen_permission() == 0
    assert_not_concealed(zen)


def test_focus_never_rests_in_the_hidden_panel(launch_zen, site, addon_xpi):
    """P44: focus sent into the hidden panel, by F6 or by a script, lands
    in the picker's search box, so Space never reaches the unseen Allow.
    The control takes the add-on's hiding element out: the same focus then
    stays in the panel."""
    zen = launch_zen(FULL_KEYBOARD)
    addon = zen.install_addon(str(addon_xpi))
    zen.wait_addon_active(addon)
    settled_setup(zen)
    count_allow(zen)
    wait_picker(zen)
    zen.wait_picker_armed()
    assert_prompt_concealed(zen)
    for _ in range(3):
        zen.press("F6")
        got = focus(zen)
        assert not got["inPanel"], got
    got = zen.chrome(FOCUS_ALLOW)
    assert not got["inPanel"], got
    zen.press(" ")
    time.sleep(1)
    assert_nothing_committed(zen, addon)
    zen.chrome(TOGGLE_CONCEAL, False, CONCEAL_MARKER)
    control = zen.chrome(FOCUS_ALLOW)
    if not control["inPanel"]:
        pytest.skip(NO_PANEL_FOCUS)
    assert got["id"] == "zen-share-picker-search", got


# The access keys of the share prompt's buttons, as Zen set them (en-US:
# Allow "A", Block "B", Not now "N").
ACCESS_KEYS = """
const el = win.document.getElementById("webRTC-shareDevices-notification");
return { main: el.getAttribute("buttonaccesskey"),
         secondary: el.getAttribute("secondarybuttonaccesskey") };
"""


def access_keys(zen):
    keys = zen.chrome(ACCESS_KEYS)
    assert keys["main"] and keys["secondary"], keys
    return keys


def assert_chord_did_nothing(zen, addon):
    """After an access-key chord: the prompt still there, hidden, nothing
    pressed, removed or shared, no permission, the picker still open."""
    time.sleep(1)
    assert zen.chrome("return !!shareNotification();") is True
    assert zen.chrome("return win.__allowSeen;") == 0
    assert zen.chrome("return win.__secondarySeen;") == 0
    assert removes(zen) == 0
    assert zen.screen_permission() == 0
    assert picker(zen) is not None
    assert_prompt_concealed(zen)
    assert status(zen, addon)["lastOutcome"] is None
    assert_no_stream(zen)


# Counts presses of the prompt's secondary button in win.__secondarySeen,
# without blocking them.
COUNT_SECONDARY = """
const el = win.document.getElementById("webRTC-shareDevices-notification");
win.__secondarySeen = 0;
el.addEventListener("secondarybuttoncommand", () => win.__secondarySeen++, { capture: true });
"""


def chord_setup(zen):
    settled_setup(zen)
    count_allow(zen)
    zen.chrome(COUNT_SECONDARY)
    spy_remove(zen)
    zen.wait_picker_armed()
    return access_keys(zen)


@pytest.mark.parametrize("which", ["secondary", "main"])
def test_access_key_chords_on_the_page_press_nothing(zen, site, addon, which):
    """P47: with focus on the page, the chrome access-key chord of a hidden
    prompt button (Block "B", Allow "A") presses nothing."""
    if which == "main":
        skip_if_capture_denied(zen)
    keys = chord_setup(zen)
    click_page(zen)
    zen.press_access_chord(keys[which])
    assert_chord_did_nothing(zen, addon)


def test_access_key_chords_in_the_search_box_press_nothing(zen, site, addon):
    """P47: with focus in the search box, the same chords press nothing and
    leave the search as it was."""
    skip_if_capture_denied(zen)
    keys = chord_setup(zen)
    assert picker(zen)["focused"] == "zen-share-picker-search"
    for key in (keys["secondary"], keys["main"]):
        zen.press_access_chord(key)
    assert_chord_did_nothing(zen, addon)
    p = picker(zen)
    assert p["focused"] == "zen-share-picker-search", p


def test_access_key_chord_presses_a_shown_prompt(zen, site, addon):
    """Control for P47: with the picker off and Zen's prompt in view, the
    same chord on the page presses Block, so the chord is real."""
    zen.addon_call(addon, "setEnabled", False)
    spaces(zen)
    zen.request_share()
    keys = access_keys(zen)
    click_page(zen, below_picker=False)
    zen.press_access_chord(keys["secondary"])
    end = time.monotonic() + 2
    while zen.page_title(SHARE_PAGE) != REJECTED and time.monotonic() < end:
        time.sleep(0.05)
    if zen.page_title(SHARE_PAGE) != REJECTED:
        pytest.skip("the access-key chord does not reach Zen's prompt here")
    assert zen.screen_permission() == 2


# Hides the panel through the add-on's module, with no session behind it,
# then sends an untrusted Esc and moves focus into the panel: once while
# hidden, once after `how` ("restore" or "sweep") showed it again.
GUARDS = """
const { concealPanel, revealPanel } = ChromeUtils.importESModule(args[0]);
const how = args[1];
const doc = win.document;
const panel = win.PopupNotifications.panel;
let escapes = 0;
const esc = () => {
  const e = new win.KeyboardEvent("keydown",
    { key: "Escape", keyCode: 27, bubbles: true, cancelable: true });
  doc.documentElement.dispatchEvent(e);
  return e.defaultPrevented;
};
// An untrusted access-key chord for the prompt's secondary button: it
// presses nothing, but shows whether the guard cancels it (P47).
const chord = () => {
  const mask = Services.prefs.getIntPref("ui.key.chromeAccess", -1);
  const key = doc.getElementById("webRTC-shareDevices-notification")
    .getAttribute("secondarybuttonaccesskey").toLowerCase();
  const e = new win.KeyboardEvent("keydown", {
    key, code: "Key" + key.toUpperCase(), bubbles: true, cancelable: true,
    shiftKey: !!(mask & 1), ctrlKey: !!(mask & 2), altKey: !!(mask & 4), metaKey: !!(mask & 8),
  });
  doc.documentElement.dispatchEvent(e);
  return e.defaultPrevented;
};
const focusAllow = () => {
  doc.getElementById("webRTC-shareDevices-notification").button.focus();
  for (let el = Services.focus.focusedElement; el; el = el.parentNode ?? el.host) {
    if (el === panel) return true;
  }
  return false;
};
const handle = concealPanel(win, {
  escape: () => { escapes++; },
  focusTarget: () => win.gBrowser.selectedBrowser,
});
const hidden = { prevented: esc(), escapes, chord: chord(), inPanel: focusAllow() };
if (how == "restore") handle.restore(); else revealPanel(win);
const shown = { prevented: esc(), escapes, chord: chord(), inPanel: focusAllow() };
return { hidden, shown };
"""


@pytest.mark.parametrize("how", ["restore", "sweep"])
def test_the_key_and_focus_guards_go_with_the_hiding(launch_zen, site, addon_xpi, how):
    """P44, P47, P35: the Esc, access-key and focus guards come with the
    hiding element and go with it, through its own restore or a sweep of the window."""
    zen = launch_zen(FULL_KEYBOARD)
    addon = zen.install_addon(str(addon_xpi))
    zen.wait_addon_active(addon)
    zen.addon_call(addon, "setEnabled", False)
    zen.settle()
    zen.request_share()
    zen.settle()
    got = zen.chrome(GUARDS, zen.glue("glue/conceal.sys.mjs"), how)
    hidden, shown = got["hidden"], got["shown"]
    assert (hidden["prevented"], hidden["escapes"], hidden["chord"]) == (
        True,
        1,
        True,
    ), got
    assert (shown["prevented"], shown["escapes"], shown["chord"]) == (
        False,
        1,
        False,
    ), got
    assert not hidden["inPanel"], got
    if not shown["inPanel"]:
        pytest.skip(NO_PANEL_FOCUS)


# The meet tab's share notification is still there, wherever it shows.
STILL_PENDING = """
return !!win.PopupNotifications.getNotification("webRTC-shareDevices",
                                                findTab(args[0]).linkedBrowser);
"""


def assert_still_pending(zen):
    assert removes(zen) == 0
    assert zen.chrome(STILL_PENDING, SHARE_PAGE) is True
    assert zen.page_title(SHARE_PAGE) == "meet.test share"


def test_closing_paths_never_decline(zen, site, addon):
    """Only Esc and Cancel decline: a tab switch, a space switch and the off
    switch close the picker and leave the request pending."""
    work, perso = spaces(zen)
    zen.request_share()
    wait_picker(zen)
    spy_remove(zen)
    zen.chrome("win.gBrowser.selectedTab = findTab(args[0]);", DOCS)
    wait_gone(zen)
    assert_still_pending(zen)
    zen.chrome("win.gBrowser.selectedTab = findTab(args[0]);", SHARE_PAGE)
    wait_picker(zen, timeout=5)
    assert_still_pending(zen)
    zen.switch_space(perso)
    wait_gone(zen)
    assert_still_pending(zen)
    zen.switch_space(work)
    show_prompt_again(zen)
    wait_picker(zen, timeout=5)
    assert_still_pending(zen)
    s = zen.addon_call(addon, "setEnabled", False)
    assert s["state"] == "disabled", s
    wait_gone(zen)
    time.sleep(GONE_WAIT_S)
    assert_still_pending(zen)
    # Zen marks a prompt dismissed when its panel hides on a tab switch.
    got = prompt(zen)
    assert (got["open"], got["concealed"], got["markers"]) == (True, False, 0), got


# -- hidden from the first frame (P48) -------------------------------------------

# The add-on's record that it set `nonnative` on Zen's panel ("added") or
# found Gecko's own ("kept").
NATIVE_MARK = "data-zen-share-picker-nonnative"

# Records, in win.__firstFrame, the panel as it is when it has shown
# (`popupshown`, capturing on the window, so before any listener on the
# panel): the add-on's hiding elements, its `nonnative` record, `nonnative`
# itself, and the computed styles Zen's own panel rules fight over. With
# args[0] true it also takes `nonnative` off as the panel starts to show, as
# a headful macOS Gecko leaves it (headless Gecko sets it on every anchored
# popup).
WATCH_FIRST_FRAME = """
const panel = win.PopupNotifications.panel;
const [asNative, marker, mark] = args;
win.__firstFrame = [];
win.__geckoNonnative = null;
win.addEventListener("popupshowing", e => {
  if (e.target !== panel) return;
  if (asNative) panel.removeAttribute("nonnative");
  win.__geckoNonnative ??= panel.hasAttribute("nonnative");
}, true);
win.addEventListener("popupshown", e => {
  if (e.target !== panel) return;
  const s = win.getComputedStyle(panel);
  win.__firstFrame.push({
    markers: win.document.querySelectorAll("[" + marker + "]").length,
    mark: panel.getAttribute(mark),
    nonnative: panel.hasAttribute("nonnative"),
    opacity: s.opacity,
    appearance: s.appearance,
    background: s.backgroundColor,
  });
}, true);
"""

# The panel's `nonnative` and the add-on's record of it, now.
NATIVE_NOW = """
const panel = win.PopupNotifications.panel;
return { mark: panel.getAttribute(args[0]), nonnative: panel.hasAttribute("nonnative") };
"""


def watch_first_frame(zen, as_native=False):
    zen.chrome(WATCH_FIRST_FRAME, as_native, CONCEAL_MARKER, NATIVE_MARK)


def first_frame(zen):
    frames = zen.chrome("return win.__firstFrame;")
    assert frames, "the panel never showed"
    return frames[0]


def native_now(zen):
    return zen.chrome(NATIVE_NOW, NATIVE_MARK)


def expected_mark(zen):
    """ "kept" when Gecko had set `nonnative` itself as the panel started to
    show (headless), "added" when the add-on had to (a native popover)."""
    gecko = zen.chrome("return win.__geckoNonnative;")
    assert gecko is not None, "the panel never started to show"
    return "kept" if gecko else "added"


def assert_hidden_from_the_first_frame(frame, mark):
    """Off macOS, popup.css fades the panel's opacity in, so at its first
    frame the rule is there but the opacity is still on its way to 0."""
    expected = {
        "markers": 1,
        "mark": mark,
        "nonnative": True,
        "opacity": "0" if sys.platform == "darwin" else frame["opacity"],
        "appearance": "none",
        "background": "rgba(0, 0, 0, 0)",
    }
    assert frame == expected, frame


def assert_not_hidden_at_first_frame(zen):
    frame = first_frame(zen)
    assert (frame["markers"], frame["mark"]) == (0, None), frame


@pytest.mark.parametrize("as_native", [False, True], ids=["gecko-nonnative", "native"])
def test_a_handled_prompt_is_hidden_from_its_first_frame(zen, site, addon, as_native):
    """P48: the panel of a prompt the picker handles is a plain window
    (`nonnative`) and hidden, by a rule that beats Zen's own panel rules,
    by the time it has shown. The add-on records whether it set `nonnative`
    itself, and on `popuphidden` takes off only its own."""
    spaces(zen)
    watch_first_frame(zen, as_native)
    zen.request_share()
    wait_picker(zen)
    mark = expected_mark(zen)
    if as_native:
        assert mark == "added"
    assert_hidden_from_the_first_frame(first_frame(zen), mark)
    assert native_now(zen) == {"mark": mark, "nonnative": True}
    assert_prompt_concealed(zen)
    # A tab switch hides the panel (and closes the picker).
    zen.chrome("win.gBrowser.selectedTab = findTab(args[0]);", DOCS)
    wait_gone(zen)
    zen.chrome(
        'await waitFor(() => win.PopupNotifications.panel.state == "closed", "hidden");'
    )
    assert native_now(zen) == {"mark": None, "nonnative": mark == "kept"}
    assert_not_concealed(zen)


@pytest.mark.parametrize("as_native", [False, True], ids=["gecko-nonnative", "native"])
def test_turning_off_restores_only_the_addons_nonnative(zen, site, addon, as_native):
    """P48: the off switch removes the add-on's `nonnative` and its record,
    and leaves Gecko's own `nonnative` alone."""
    spaces(zen)
    watch_first_frame(zen, as_native)
    zen.request_share()
    wait_picker(zen)
    assert_prompt_concealed(zen)
    mark = expected_mark(zen)
    assert native_now(zen) == {"mark": mark, "nonnative": True}
    s = zen.addon_call(addon, "setEnabled", False)
    assert s["state"] == "disabled", s
    wait_gone(zen)
    assert native_now(zen) == {"mark": None, "nonnative": mark == "kept"}
    got = prompt(zen)
    assert (got["open"], got["concealed"], got["markers"]) == (True, False, 0), got


# -- the sidebar stays as it was (P67) --------------------------------------------

# Compact mode on from startup, so Zen slides the sidebar out for a panel
# anchored in it (panel.js on_popupshowing).
COMPACT = {"zen.view.compact.enable-at-startup": True}

# The add-on's record that it set `no-open-on-anchor` on Zen's panel.
ANCHOR_MARK = "data-zen-share-picker-no-open-on-anchor"

# What Zen's panel.js does to the sidebar and toolbar for the panel: the
# toolbox's `zen-compact-mode-active` (the sidebar slid out), `open` on the
# panel's anchor root, and the URL bar's `has-popup-open`.
SIDEBAR = """
const tb = win.gNavToolbox;
const panel = win.PopupNotifications.panel;
const icon = win.document.getElementById("notification-popup-box");
const anchor = panel.anchorNode ?? icon;
const root = anchor.closest("toolbarbutton, .anchor-root") || anchor;
return {
  active: tb.hasAttribute("zen-compact-mode-active"),
  open: root.hasAttribute("open"),
  urlbar: !!win.gURLBar?.hasAttribute("has-popup-open"),
  mark: panel.getAttribute(args[0]),
  noOpen: panel.hasAttribute("no-open-on-anchor"),
};
"""

# Records, in win.__panelJs, what a non-capturing popupshowing listener on
# the panel sees. panel.js added its own when the panel was built, so this
# one runs after it: it sees what panel.js did.
AFTER_PANEL_JS = """
const panel = win.PopupNotifications.panel;
win.__panelJs = [];
panel.addEventListener("popupshowing", e => {
  if (e.target !== panel) return;
  win.__panelJs.push({
    noOpen: panel.hasAttribute("no-open-on-anchor"),
    active: win.gNavToolbox.hasAttribute("zen-compact-mode-active"),
  });
});
"""

STILL = {"active": False, "open": False, "urlbar": False}


def compact_zen(launch_zen, addon_xpi, prefs=None):
    zen = launch_zen({**COMPACT, **(prefs or {})})
    addon = zen.install_addon(str(addon_xpi))
    zen.wait_addon_active(addon)
    zen.chrome(
        'await waitFor(() => win.gZenCompactModeManager.preference, "compact mode", 10000);'
    )
    return zen, addon


def sidebar(zen):
    return zen.chrome(SIDEBAR, ANCHOR_MARK)


def sidebar_still(zen):
    got = sidebar(zen)
    return {k: got[k] for k in STILL}


def wait_sidebar(zen, want, timeout=2.0):
    end = time.monotonic() + timeout
    while True:
        got = sidebar_still(zen)
        if got == want or time.monotonic() > end:
            return got
        time.sleep(0.05)


def test_a_camera_prompt_slides_the_sidebar_out(launch_zen, site, addon_xpi):
    """P67 control: a prompt the picker does not take keeps Zen's own
    behavior, so the test can see the sidebar slide out."""
    zen, _addon = compact_zen(
        launch_zen, addon_xpi, {"media.navigator.streams.fake": True}
    )
    zen.visit(DOCS)
    assert sidebar_still(zen) == STILL
    zen.request_share("camera")
    assert_no_picker_for(zen, 1)
    got = sidebar(zen)
    assert (got["active"], got["open"], got["mark"], got["noOpen"]) == (
        True,
        True,
        None,
        False,
    ), got


@pytest.mark.parametrize("end", ["decline", "share"])
def test_a_handled_prompt_leaves_the_sidebar_as_it_was(
    launch_zen, site, addon_xpi, end
):
    """P67: while the add-on hides the panel, Zen does not slide the sidebar
    out for it, and the picker's end (a decline or a share) leaves nothing
    behind. The add-on's no-open-on-anchor is there before panel.js acts."""
    zen, addon = compact_zen(launch_zen, addon_xpi)
    if end == "share":
        skip_if_capture_denied(zen)
    spaces(zen)
    zen.chrome(AFTER_PANEL_JS)
    assert sidebar_still(zen) == STILL
    zen.request_share()
    wait_picker(zen)
    assert zen.chrome("return win.__panelJs;") == [{"noOpen": True, "active": False}]
    got = sidebar(zen)
    assert got == {**STILL, "mark": "added", "noOpen": True}, got
    time.sleep(0.5)
    assert sidebar_still(zen) == STILL
    if end == "decline":
        spy_remove(zen)
        zen.press("Escape")
        wait_gone(zen)
        assert_declined(zen, addon)
    else:
        zen.wait_picker_armed()
        zen.press("Enter")
        wait_gone(zen)
        wait_title(zen, SHARE_PAGE, "shared")
        wait_status(zen, addon, lambda s: s["lastOutcome"] == "shared", "shared", 5)
    zen.chrome(
        'await waitFor(() => win.PopupNotifications.panel.state == "closed", "closed");'
    )
    time.sleep(0.5)
    got = sidebar(zen)
    assert got == {**STILL, "mark": None, "noOpen": False}, got


@pytest.mark.parametrize("how", ["assist", "decline-failed", "off"])
def test_a_revealed_prompt_slides_the_sidebar_out(launch_zen, site, addon_xpi, how):
    """P67: when the add-on shows a still-open prompt again, it shows as in
    stock Zen: the anchor open and the sidebar out."""
    zen, addon = compact_zen(launch_zen, addon_xpi)
    spaces(zen)
    zen.request_share()
    wait_picker(zen)
    assert sidebar_still(zen) == STILL
    if how == "assist":
        block_allow(zen)
        zen.wait_picker_armed()
        zen.press("Enter")
        wait_gone(zen)
        wait_status(
            zen,
            addon,
            lambda s: s["lastOutcome"] == "assist",
            "assist",
            ALLOW_WINDOW_S + 2,
        )
    elif how == "decline-failed":
        spy_remove(zen, "noop")
        zen.press("Escape")
        wait_gone(zen)
        wait_decline_failed(zen, addon)
    else:
        zen.addon_call(addon, "setEnabled", False)
        wait_gone(zen)
    assert_prompt_untouched(zen)
    want = {"active": True, "open": True, "urlbar": True}
    got = wait_sidebar(zen, want)
    assert got == want, got
    assert sidebar(zen)["mark"] is None and not sidebar(zen)["noOpen"]
    # Zen's own cleanup runs when the prompt goes.
    zen.chrome(
        """
        win.PopupNotifications.remove(shareNotification());
        await waitFor(() => win.PopupNotifications.panel.state == "closed", "closed");
        """
    )
    got = wait_sidebar(zen, {"active": False, "open": False, "urlbar": False})
    assert got["open"] is False and got["urlbar"] is False, got


def test_a_prompt_already_shown_natively_gets_no_picker(zen, site, addon):
    """P64 (a): a prompt whose panel opened before the add-on could make it
    a plain window (here, the picker was off) keeps Zen's normal prompt when
    the picker would take it later: no picker, nothing hidden, and the
    silent code `shown-native` in the debug log."""
    zen.addon_call(addon, "setEnabled", False)
    spaces(zen)
    zen.request_share()
    assert native_now(zen)["mark"] is None
    s = zen.addon_call(addon, "setEnabled", True)
    assert s["state"] == "active", s
    zen.addon_call(addon, "setDebug", True)
    # Zen updates the open panel in place with the same prompt.
    got = zen.chrome(RESHOW, "replace")
    assert got["same"] is False, got
    assert_no_picker_for(zen, 2)
    assert_prompt_untouched(zen)
    s = status(zen, addon)
    assert s["promptProblems"] == [], s
    assert "prompt shown-native" in zen.addon_call(addon, "getLog")


# Keeps PanelUpdated from reaching the panel's own listeners (the add-on's
# included), as if the panel's `popupshown` never came.
BLOCK_PANEL_UPDATED = """
win.addEventListener("PanelUpdated", e => {
  if (e.target === win.PopupNotifications.panel) e.stopPropagation();
}, true);
"""


def test_an_early_hide_never_outlives_three_seconds(zen, site, addon):
    """P64 (c): when nothing adopts or ends the hiding taken as the panel
    started to show, it ends by itself after 3 s, with a problem code."""
    spaces(zen)
    zen.chrome(BLOCK_PANEL_UPDATED)
    zen.request_share()
    time.sleep(1)
    got = prompt(zen)
    assert (got["open"], got["markers"]) == (True, 1), got
    assert picker(zen) is None
    s = wait_status(
        zen,
        addon,
        lambda s: "hide-timeout" in s["promptProblems"],
        "hide-timeout",
        4,
    )
    assert s["lastOutcome"] is None, s
    assert_not_concealed(zen)
    assert picker(zen) is None
    assert zen.chrome("return !!shareNotification();") is True


def test_a_prompt_the_picker_skips_is_never_hidden_at_its_first_frame(zen, site, addon):
    """P48: a prompt the picker will not take (here, one with no tab
    entries) shows as Zen built it from its first frame."""
    zen.visit(DOCS)
    wrap_append_item(zen, "drop-tab-entries")
    watch_first_frame(zen, True)
    zen.request_share()
    assert_not_hidden_at_first_frame(zen)
    assert native_now(zen)["mark"] is None
    assert_no_picker_for(zen, 1)
    assert_prompt_untouched(zen)


def test_headful_panel_is_a_plain_hidden_window(zen, site, addon):
    """P48, headful macOS: Zen shows its panel as a native popover, which
    no style reaches. The add-on's `nonnative` makes it a plain window: it
    has a real rect, unlike a popover's backing window, and the hiding
    rule's window opacity applies to it."""
    skip_unless_macos_headful(zen)
    spaces(zen)
    zen.settle()
    watch_first_frame(zen)
    try:
        zen.request_share()
    except ZenScriptError as e:
        if "the window to become active" in str(e):
            pytest.skip("the screen is locked")
        raise
    wait_picker(zen)
    zen.settle()
    frame = first_frame(zen)
    assert frame["nonnative"], frame
    assert frame["markers"] == 1 and frame["opacity"] == "0", frame
    left, top, right, bottom = zen.panel_rect()
    assert right - left > 0 and bottom - top > 0, (left, top, right, bottom)
    window_opacity = zen.chrome(
        """
        return win.getComputedStyle(win.PopupNotifications.panel)
          .getPropertyValue("-moz-window-opacity");
        """
    )
    # Gecko does not expose -moz-window-opacity to getComputedStyle (it
    # reads ""); when it does, it must be 0.
    assert window_opacity in ("", "0"), window_opacity
    geometry = zen.chrome(PANEL_GEOMETRY)
    assert_no_visible_panel_window(window_list(zen), geometry["rect"])
    assert_prompt_concealed(zen)


# The panel's rect in screen pixels, `nonnative`, and its anchor's rect.
PANEL_GEOMETRY = """
const panel = win.PopupNotifications.panel;
const r = panel.getOuterScreenRect();
const a = win.document.getElementById("webRTC-shareDevices-notification-icon");
const ar = a?.getBoundingClientRect();
return {
  state: panel.state,
  nonnative: panel.hasAttribute("nonnative"),
  rect: [r.left, r.top, r.width, r.height],
  anchor: ar ? [ar.left + win.mozInnerScreenX, ar.top + win.mozInnerScreenY,
                ar.width, ar.height] : null,
};
"""


def other_windows(windows):
    """The window server's windows of this Zen other than its browser window
    (the largest)."""
    main = max(windows, key=lambda w: w["bounds"][2] * w["bounds"][3])
    return [w for w in windows if w is not main]


NO_WINDOW_LIST = (
    "the macOS window list could not be read, so this check cannot tell a "
    "popover from a plain window"
)


def window_list(zen):
    """This Zen's windows from the macOS window server. The only check that
    tells a popover from a plain window (both have a non-zero rect), so a
    list that cannot be read fails the test rather than pass it unchecked."""
    windows = zen.os_windows()
    if windows is None:
        pytest.fail(NO_WINDOW_LIST)
    return windows


def skip_unless_macos_headful(zen):
    if zen.headless:
        pytest.skip(
            "headful only: headless Gecko shows every anchored popup as a plain window"
        )
    if sys.platform != "darwin":
        pytest.skip("macOS only: the native popover and the window list are macOS's")


def assert_no_visible_panel_window(windows, rect):
    """macOS draws nothing for the panel: its only window is the plain
    one, at the panel's size and at alpha 0. A native popover would be
    another, visible window (the bubble AppKit draws)."""
    others = other_windows(windows)
    assert [w for w in others if w["alpha"] > 0] == [], windows
    sizes = [w["bounds"][2:] for w in others]
    assert rect[2:] in sizes, (windows, rect)


def headful_share(zen, path="share"):
    """request_share() in a headful run; skips when the window cannot
    become active."""
    try:
        zen.request_share(path)
    except ZenScriptError as e:
        if "the window to become active" in str(e):
            pytest.skip("the window could not become active (screen locked?)")
        raise


def test_headful_panel_is_a_plain_window_after_a_native_show(
    launch_zen, site, addon_xpi
):
    """P64 (b), headful macOS: in a user's Zen the panel has usually shown
    natively before (a camera or location prompt), as a popover. A share
    prompt the picker takes after that still opens as a plain, hidden
    window."""
    zen = launch_zen({"media.navigator.streams.fake": True})
    skip_unless_macos_headful(zen)
    addon = zen.install_addon(str(addon_xpi))
    zen.wait_addon_active(addon)
    spaces(zen)
    zen.settle()
    # The warm-up: a camera prompt, which the picker never takes (P34),
    # shown natively, then closed.
    headful_share(zen, "camera")
    zen.settle()
    warm = zen.chrome(PANEL_GEOMETRY)
    warm_windows = window_list(zen)
    assert warm["state"] == "open" and not warm["nonnative"], warm
    assert prompt(zen)["markers"] == 0
    zen.chrome(
        """
        win.PopupNotifications.remove(shareNotification());
        await waitFor(() => win.PopupNotifications.panel.state == "closed", "closed");
        """
    )
    watch_first_frame(zen)
    headful_share(zen)
    wait_picker(zen)
    zen.settle()
    frame = first_frame(zen)
    shown = zen.chrome(PANEL_GEOMETRY)
    print(
        "SPIKE P64b",
        {
            "warm": warm,
            "warm_windows": warm_windows,
            "frame": frame,
            "shown": shown,
            "windows": window_list(zen),
        },
    )
    # Control: the native warm-up showed as a visible window of its own.
    assert [w for w in other_windows(warm_windows) if w["alpha"] > 0], warm_windows
    assert frame["nonnative"] and frame["markers"] == 1, frame
    assert frame["mark"] == "added", frame
    assert shown["nonnative"] and shown["state"] == "open", shown
    assert shown["rect"][2] > 0 and shown["rect"][3] > 0, shown
    assert_no_visible_panel_window(window_list(zen), shown["rect"])
    assert_prompt_concealed(zen)


# -- per-prompt failures --------------------------------------------------------


def test_unmappable_entries_leave_the_stock_prompt(zen, site, addon):
    spaces(zen)
    wrap_append_item(zen, "prefix-device-id")
    zen.request_share()
    before = zen.stock_selected()
    assert_no_picker_for(zen, 2)
    assert "unmapped-entry" in status(zen, addon)["promptProblems"]
    assert_prompt_untouched(zen)
    assert zen.stock_selected() == before


def test_unknown_entry_shape_leaves_the_stock_prompt(zen, site, addon):
    spaces(zen)
    wrap_append_item(zen, "numeric-media-source")
    zen.request_share()
    before = zen.stock_selected()
    assert_no_picker_for(zen, 2)
    assert "bad-entry" in status(zen, addon)["promptProblems"]
    assert_prompt_untouched(zen)
    assert zen.stock_selected() == before


def test_a_conceal_failure_leaves_the_prompt_as_built(zen, site, addon):
    """P35: when the panel cannot be hidden, no picker opens, the failure is
    a problem code, and the stock prompt stays as Zen built it, visible."""
    spaces(zen)
    zen.chrome(
        """
        win.document.documentElement.append = () => {
          throw new Error("test: no append");
        };
        """
    )
    zen.request_share()
    assert_no_picker_for(zen, 2)
    assert "conceal-failed" in status(zen, addon)["promptProblems"]
    assert_prompt_untouched(zen)


def test_broken_space_api_makes_the_addon_inert(zen, site, addon_xpi):
    zen.chrome(
        """
        Object.defineProperty(win.gZenWorkspaces, "getWorkspaces",
          { value: undefined, configurable: true, writable: true });
        """
    )
    addon = zen.install_addon(str(addon_xpi))
    s = status(zen, addon)
    assert s["state"] == "inert", s
    assert "zen-spaces" in s["failedChecks"], s
    # Zen's own API is back; the add-on stays inert.
    zen.chrome("delete win.gZenWorkspaces.getWorkspaces;")
    zen.visit(DOCS)
    zen.request_share()
    assert_no_picker_for(zen, 2)
    assert_prompt_untouched(zen)
    assert any(e["mediaSource"] == "browser" for e in zen.stock_entries())
    assert status(zen, addon)["promptProblems"] == []


def test_no_tab_entries_means_no_picker(zen, site, addon):
    """A prompt that offers no tabs. Zen 1.24.2b lists tabs whatever
    media.getusermedia.browser.enabled says, so the tab items are taken out
    of the list as Zen builds it."""
    zen.visit(DOCS)
    wrap_append_item(zen, "drop-tab-entries")
    zen.request_share()
    entries = zen.stock_entries()
    assert entries and not any(e["mediaSource"] == "browser" for e in entries), entries
    assert_no_picker_for(zen, 2)
    assert_prompt_untouched(zen)
    assert status(zen, addon)["promptProblems"] == []


def test_camera_request_opens_no_picker(launch_zen, site, addon_xpi):
    zen = launch_zen({"media.navigator.streams.fake": True})
    addon = zen.install_addon(str(addon_xpi))
    zen.wait_addon_active(addon)
    zen.visit(DOCS)
    watch_first_frame(zen, True)
    zen.request_share("camera")
    assert_not_hidden_at_first_frame(zen)
    assert_no_picker_for(zen, 2)
    assert status(zen, addon)["promptProblems"] == []
    assert_not_concealed(zen)


@pytest.mark.parametrize(
    "page, prefs, mic",
    [
        ("screen-and-mic", {"media.navigator.streams.fake": True}, True),
        (
            "screen-and-audio-capture",
            {"media.getusermedia.audio.capture.enabled": True},
            False,
        ),
    ],
)
def test_screen_request_with_audio_opens_no_picker(
    launch_zen, site, addon_xpi, page, prefs, mic
):
    """P34: a screen request that also asks for a microphone or audio
    capture is a silent per-prompt skip. One Enter must not also grant audio
    the picker never showed."""
    zen = launch_zen(prefs)
    addon = zen.install_addon(str(addon_xpi))
    zen.wait_addon_active(addon)
    spaces(zen)
    watch_first_frame(zen, True)
    zen.request_share(page)
    assert_not_hidden_at_first_frame(zen)
    shown = zen.chrome(
        """
        const doc = win.document;
        return {
          screen: !doc.getElementById("webRTC-selectWindowOrScreen").hidden,
          mic: !doc.getElementById("webRTC-selectMicrophone").hidden,
        };
        """
    )
    assert shown == {"screen": True, "mic": mic}, shown
    assert any(e["mediaSource"] == "browser" for e in zen.stock_entries())
    before = zen.stock_selected()
    assert_no_picker_for(zen, 2)
    assert_prompt_untouched(zen)
    assert zen.stock_selected() == before
    assert status(zen, addon)["promptProblems"] == []


# -- the OS row and a rejected Allow -------------------------------------------


def test_os_row_selects_the_os_entry(zen, site, addon):
    skip_if_capture_denied(zen)
    setup(zen)
    block_allow(zen)
    os_entry = zen.chrome(
        """
        const item = win.document.getElementById("webRTC-selectWindow-menulist").selectedItem;
        return item && item.deviceId != undefined && item.mediaSource != "browser"
          ? String(item.deviceId) : null;
        """
    )
    wait_picker(zen)
    zen.press("End")
    wait_picker(zen, lambda p: p["selected"] == "os", "the OS row")
    zen.wait_picker_armed()
    zen.press("Enter")
    wait_gone(zen)
    if os_entry is not None:
        s = wait_status(
            zen, addon, lambda s: s["lastOutcome"] is not None, "an outcome", 10
        )
        assert zen.stock_selected() == os_entry, s
        assert allow_clicks(zen) >= 1, s
    else:
        time.sleep(1)
        assert allow_clicks(zen) == 0
        assert status(zen, addon)["lastOutcome"] == "stock"
    assert_prompt_untouched(zen)


def test_rejected_allow_leaves_the_choice_selected(zen, site, addon):
    skip_if_capture_denied(zen)
    setup(zen)
    block_allow(zen)
    wait_picker(zen)
    zen.press("ArrowDown")
    wait_picker(zen, lambda p: p["selected"] == key_of(zen, DOCS), "docs highlighted")
    zen.wait_picker_armed()
    zen.press("Enter")
    wait_gone(zen)
    wait_status(
        zen, addon, lambda s: s["lastOutcome"] == "assist", "assist", ALLOW_WINDOW_S + 2
    )
    assert_prompt_untouched(zen)
    assert zen.stock_selected() == zen.browser_id(DOCS)
    assert allow_clicks(zen) == MAX_CLICKS
    assert_no_stream(zen)
    # Nothing runs the share again, and the picker does not come back,
    # even when the prompt shows again (P18).
    assert_no_picker_for(zen, 1.5)
    show_prompt_again(zen)
    assert_no_picker_for(zen, 2)
    assert allow_clicks(zen) == MAX_CLICKS
    assert_no_stream(zen)


# -- closing without sharing ---------------------------------------------------


# Re-shows the open share prompt in place, with its anchor unchanged, so Zen
# updates the open panel without hiding it and WebRTC rebuilds the dropdown.
# "replace": a new notification under the same id, built from the old one;
# the old one's "removed" callback is skipped, so the page's request stays
# pending. "refresh": a second notification on the same anchor, which makes
# Zen show the panel again with both.
RESHOW = """
const n = shareNotification();
win.__oldNotification = n;
const PN = win.PopupNotifications;
if (args[0] == "replace") {
  const cb = n.options.eventCallback;
  n.options.eventCallback = function (topic, ...rest) {
    return topic == "removed" ? false : cb.call(this, topic, ...rest);
  };
  PN.show(n.browser, n.id, n.message, n.anchorID, n.mainAction, n.secondaryActions,
          { ...n.options, eventCallback: cb });
} else {
  PN.show(n.browser, "zen-share-picker-test-other", "Another prompt", n.anchorID,
          { label: "OK", accessKey: "O", callback() {} }, null, { persistent: true });
}
await waitFor(() => PN.panel.state == "open", "the panel to stay open");
return { same: shareNotification() === n };
"""

# The rows of the open picker map to tab items of the current dropdown.
ROWS_MATCH_ITEMS = """
const list = win.document.getElementById("webRTC-selectWindow-menulist");
const items = new Set(Array.from(list.menupopup.children)
  .filter(i => i.mediaSource == "browser" && i.parentNode.parentNode === list)
  .map(i => String(i.deviceId)));
const keys = Array.from(win.document.querySelectorAll("#zen-share-picker .zsp-row"))
  .map(r => r.dataset.key).filter(k => k != "os");
const ids = keys.map(k => {
  const t = tabsOf(win).find(t => t.id == k);
  return t ? String(t.linkedBrowser.browserId) : null;
});
return keys.length > 0 && ids.every(id => id !== null && items.has(id));
"""


@pytest.mark.parametrize("shape", ["replace", "refresh"])
def test_a_reshown_prompt_gets_a_fresh_picker(zen, site, addon, shape):
    """Review fix: Zen can update the open panel in place, rebuilding the
    dropdown, with no popuphidden. The stale picker closes without declining
    the prompt, and a fresh one opens on the current items; Enter then
    shares."""
    skip_if_capture_denied(zen)
    setup(zen)
    wait_picker(zen)
    count_allow(zen)
    zen.chrome('win.document.getElementById("zen-share-picker").dataset.zspOld = "1";')
    got = zen.chrome(RESHOW, shape)
    assert got["same"] is (shape == "refresh"), got
    p = wait_picker(zen, lambda p: not p["old"], "a fresh picker", timeout=3)
    assert p["selected"] == key_of(zen, WIKI), p
    assert zen.chrome(ROWS_MATCH_ITEMS)
    if shape == "replace":
        assert_prompt_concealed(zen)
    else:
        # The panel also holds another notification: no hiding (P35).
        got = prompt(zen)
        assert (got["open"], got["concealed"], got["markers"]) == (True, False, 0), got
    assert zen.chrome(
        "return shareNotification() && shareNotification().dismissed === false;"
    )
    s = status(zen, addon)
    assert s["lastOutcome"] is None, s
    assert s["promptProblems"] == [], s
    assert zen.chrome("return win.__allowSeen;") == 0
    assert_no_stream(zen)
    zen.wait_picker_armed()
    zen.press("Enter")
    wait_gone(zen)
    wait_title(zen, SHARE_PAGE, "shared")
    assert zen.sharing_device_ids() == [zen.browser_id(WIKI)]
    wait_status(zen, addon, lambda s: s["lastOutcome"] == "shared", "shared", 5)
    assert_not_concealed(zen)


def test_a_joining_notification_shows_the_panel_during_a_share(zen, site, addon):
    """P43 (b): while a share waits on the hidden panel's Allow, another
    notification joining the panel shows the panel at once."""
    setup(zen)
    block_allow(zen)
    wait_picker(zen)
    zen.wait_picker_armed()
    zen.press("Enter")
    wait_gone(zen)
    zen.chrome(
        """
        await waitFor(() => win.__allowClicks >= 1, "the first Allow click", 5000);
        """
    )
    before = prompt(zen)
    assert (before["open"], before["markers"]) == (True, 1), before
    got = zen.chrome(
        """
        const n = shareNotification();
        const PN = win.PopupNotifications;
        PN.show(n.browser, "zen-share-picker-test-other", "Another prompt", n.anchorID,
                { label: "OK", accessKey: "O", callback() {} }, null, { persistent: true });
        const s = win.getComputedStyle(PN.panel);
        return {
          open: PN.panel.state == "open",
          shown: Array.from(PN.panel.children).filter(c => !c.hidden).map(c => c.id),
          markers: win.document.querySelectorAll("[" + args[0] + "]").length,
          concealed: s.opacity == "0" && s.pointerEvents == "none",
        };
        """,
        CONCEAL_MARKER,
    )
    assert got["open"] and len(got["shown"]) == 2, got
    assert (got["markers"], got["concealed"]) == (0, False), got
    # The share was still running: the reveal came from the join.
    assert status(zen, addon)["lastOutcome"] is None
    assert_no_stream(zen)


# Makes webrtcUI report no stream, so a share's verification runs its full
# time; args[0] true puts the real method back.
HIDE_STREAMS = """
const { webrtcUI } = ChromeUtils.importESModule("resource:///modules/webrtcUI.sys.mjs");
if (args[0]) {
  if (win.__realStreams) webrtcUI.getActiveStreams = win.__realStreams;
} else {
  win.__realStreams = webrtcUI.getActiveStreams;
  webrtcUI.getActiveStreams = () => [];
}
"""


def test_the_panel_shows_once_the_shared_prompt_is_gone(zen, site, addon):
    """P43 (a): once Allow took the prompt away, the hiding ends before the
    add-on checks that the stream started, so nothing queued in the panel
    sits hidden during that check."""
    skip_if_capture_denied(zen)
    setup(zen)
    wait_picker(zen)
    assert_prompt_concealed(zen)
    zen.chrome(HIDE_STREAMS, False)
    try:
        zen.wait_picker_armed()
        zen.press("Enter")
        wait_gone(zen)
        zen.chrome(
            """
            await waitFor(() => !shareNotification(), "Allow to take the prompt", 5000);
            """
        )
        assert_not_concealed(zen, timeout=0.5)
        # Still verifying: with no stream reported, that takes 5 s.
        assert status(zen, addon)["lastOutcome"] is None
    finally:
        zen.chrome(HIDE_STREAMS, True)
    wait_status(zen, addon, lambda s: s["lastOutcome"] is not None, "an outcome", 10)
    assert_not_concealed(zen)


def test_tab_switch_closes_picker_without_sharing(zen, site, addon):
    """Also P22: the picker reopens in the same window, and no capture runs
    while it is closed."""
    setup(zen)
    count_captures(zen)
    wait_picker(zen)
    zen.chrome("win.gBrowser.selectedTab = findTab(args[0]);", DOCS)
    wait_gone(zen)
    assert_not_concealed(zen)
    assert_no_stream(zen)
    closed_at = captures(zen)
    time.sleep(2.5)
    assert captures(zen) == closed_at
    zen.chrome("win.gBrowser.selectedTab = findTab(args[0]);", SHARE_PAGE)
    p = wait_picker(zen, timeout=5)
    # docs is now the tab used just before Meet.
    assert p["selected"] == key_of(zen, DOCS), p
    # Zen marks a prompt dismissed when its panel hides on a tab switch
    # (PopupNotifications _onPopupHidden), and shows it again on return.
    got = wait_concealed(zen)
    assert got["exists"] and got["open"], got
    assert (got["concealed"], got["markers"]) == (True, 1), got
    zen.press("Escape")
    wait_gone(zen)
    gone_at = captures(zen)
    assert gone_at > closed_at
    time.sleep(2.5)
    assert captures(zen) == gone_at
    assert_no_stream(zen)


def test_space_switch_closes_picker_without_sharing(zen, site, addon):
    _work, perso = spaces(zen)
    zen.request_share()
    wait_picker(zen)
    zen.switch_space(perso)
    wait_gone(zen)
    assert_not_concealed(zen)
    assert_no_stream(zen)


def test_space_switch_keeping_the_tab_closes_picker(zen, site, addon):
    """A switch between two spaces of one container keeps an Essential
    selected, so no TabSelect fires; the picker still closes, without
    sharing. Zen keeps the tab when it was the last one selected in the
    space switched to (ZenSpaceManager.mjs _handleTabSelection)."""
    zen.make_space("Work", None)
    home = zen.make_space("Home", "Perso")
    hobby = zen.make_space("Hobby", "Perso")
    zen.switch_space(home)
    zen.make_essential(SHARE_PAGE, "Perso")
    zen.switch_space(hobby)
    zen.chrome("win.gBrowser.selectedTab = findTab(args[0]);", SHARE_PAGE)
    zen.switch_space(home)
    x, y = zen.chrome(
        """
        if (win.gBrowser.selectedTab !== findTab(args[0])) {
          throw new Error("Zen did not keep the Essential selected");
        }
        const r = win.gBrowser.selectedBrowser.getBoundingClientRect();
        return [r.left + r.width / 2, r.top + r.height / 2];
        """,
        SHARE_PAGE,
    )
    zen._click(x, y)
    zen.chrome(
        """
        await waitFor(() => shareNotification() &&
                            win.PopupNotifications.panel.state == "open",
                      "the share prompt to open");
        win.__selects = 0;
        win.gBrowser.tabContainer.addEventListener("TabSelect", () => win.__selects++);
        win.__shareTab = win.gBrowser.selectedTab;
        """
    )
    wait_picker(zen)
    zen.switch_space(hobby)
    wait_gone(zen)
    kept = zen.chrome(
        "return [win.__selects, win.gBrowser.selectedTab === win.__shareTab];"
    )
    assert kept == [0, True], kept
    assert_prompt_untouched(zen)
    assert status(zen, addon)["lastOutcome"] is None
    assert_no_stream(zen)


def test_navigation_closes_picker_without_sharing(zen, site, addon):
    setup(zen)
    wait_picker(zen)
    zen.chrome(
        """
        win.gBrowser.selectedBrowser.fixupAndLoadURIString("http://meet.test/other", {
          triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal(),
        });
        """
    )
    wait_gone(zen, timeout=5)
    assert_not_concealed(zen)
    assert zen.sharing_device_ids() == []


def test_closing_the_highlighted_tab_then_enter_shares_nothing(zen, site, addon):
    """P11."""
    setup(zen)
    p = wait_picker(zen)
    assert p["selected"] == key_of(zen, WIKI), p
    zen.chrome("win.gBrowser.removeTab(findTab(args[0]), { animate: false });", WIKI)
    wait_gone(zen)
    assert_not_concealed(zen)
    zen.press("Enter")
    time.sleep(1.5)
    assert_no_stream(zen)
    assert status(zen, addon)["lastOutcome"] is None


def test_sleeping_a_listed_tab_closes_picker(zen, site, addon):
    """P11: a listed tab put to sleep (discarded) closes the picker."""
    setup(zen)
    wait_picker(zen)
    zen.chrome(
        """
        const tab = findTab(args[0]);
        await win.gBrowser.explicitUnloadTabs([tab]);
        await waitFor(() => !tab.linkedPanel, "the tab to sleep");
        """,
        DOCS,
    )
    wait_gone(zen)
    assert_not_concealed(zen)
    assert_no_stream(zen)


# -- mouse ----------------------------------------------------------------------


def test_clicking_a_row_highlights_it_and_keeps_the_prompt(zen, site, addon):
    """P11, P22 (b): a click on a row only highlights it, the stock prompt
    stays, and focus stays in the search box, so Enter then shares it."""
    skip_if_capture_denied(zen)
    setup(zen)
    docs = key_of(zen, DOCS)
    wait_picker(zen)
    click(zen, f'.zsp-row[data-key="{docs}"]')
    p = wait_picker(zen, lambda p: p["selected"] == docs, "docs highlighted")
    assert p["focused"] == "zen-share-picker-search", p
    assert_prompt_concealed(zen)
    assert_no_stream(zen)
    zen.wait_picker_armed()
    zen.press("Enter")
    wait_gone(zen)
    wait_title(zen, SHARE_PAGE, "shared")
    assert zen.sharing_device_ids() == [zen.browser_id(DOCS)]


# Records each mousedown in the window as {inPanel, onUnder} and stops it,
# so the click does nothing beneath (test_platform.py S6b). `composedPath()`
# crosses shadow roots. A synthetic mousedown on the panel's shadow content
# is the spy's own control.
HIT_SPY = """
const panel = win.PopupNotifications.panel;
win.__hits = [];
win.addEventListener("mousedown", e => {
  const path = e.composedPath();
  win.__hits.push({
    inPanel: path.includes(panel),
    onUnder: !!win.__under && path.includes(win.__under),
  });
  e.preventDefault();
  e.stopPropagation();
}, true);
const inner = panel.shadowRoot?.querySelector("*:not(style, link)");
if (!inner) throw new Error("the panel has no shadow content");
inner.dispatchEvent(new win.MouseEvent("mousedown", { bubbles: true, composed: true }));
return win.__hits.splice(0).map(h => h.inPanel);
"""

# Takes the add-on's hiding element out (args[0] false) or puts the same
# element back (true), then lets the panel restyle.
TOGGLE_CONCEAL = """
if (args[0]) {
  win.document.documentElement.append(win.__conceal);
} else {
  const els = win.document.querySelectorAll("[" + args[1] + "]");
  if (els.length != 1) throw new Error("expected one hiding element, got " + els.length);
  win.__conceal = els[0];
  win.__conceal.remove();
}
await new Promise(r => win.setTimeout(r, 300));
"""


def test_concealed_panel_lets_clicks_through(zen, site, addon):
    """P35: a click where the concealed panel sits does not land in it.
    The control takes the add-on's own hiding element out for one click,
    which must land in the panel, then puts it back."""
    spaces(zen)
    zen.settle()
    zen.request_share()
    wait_picker(zen)
    zen.settle()
    assert_prompt_concealed(zen)
    assert zen.chrome(HIT_SPY) == [True]
    left, top, right, bottom = zen.panel_rect()
    x, y = (left + right) / 2, (top + bottom) / 2
    zen.chrome(TOGGLE_CONCEAL, False, CONCEAL_MARKER)
    zen._click(x, y)
    control = zen.chrome("return win.__hits.slice();")
    zen.chrome(TOGGLE_CONCEAL, True, CONCEAL_MARKER)
    assert_prompt_concealed(zen)
    if [h["inPanel"] for h in control] != [True]:
        pytest.skip("pointer actions do not reach the panel here")
    under = zen.chrome(
        """
        win.__under = win.document.elementFromPoint(args[0], args[1]);
        return { name: win.__under?.localName ?? null,
                 inPanel: !!win.__under && win.PopupNotifications.panel.contains(win.__under) };
        """,
        x,
        y,
    )
    zen._click(x, y)
    hits = zen.chrome("return win.__hits.slice();")
    assert len(hits) == 2, hits
    assert not hits[1]["inPanel"], hits
    assert under["name"] and not under["inPanel"], under
    assert hits[1]["onUnder"], (hits, under)
    assert picker(zen) is not None
    assert_prompt_concealed(zen)


def test_clicking_share_shares_the_highlighted_tab(zen, site, addon):
    """P11, P22 (b): runShare only clicks Allow while the prompt is open and
    current, so a share proves the click on Share kept the panel open."""
    skip_if_capture_denied(zen)
    setup(zen)
    wait_picker(zen)
    zen.wait_picker_armed()
    click(zen, "#zen-share-picker-share")
    wait_gone(zen)
    wait_title(zen, SHARE_PAGE, "shared")
    assert zen.sharing_device_ids() == [zen.browser_id(WIKI)]
    wait_status(zen, addon, lambda s: s["lastOutcome"] == "shared", "shared", 5)


@CAMERA
def test_clicking_cancel_declines(zen, site, addon, camera):
    """P11, P22 (b), P36: a click on Cancel declines the request."""
    if camera:
        zen.allow_camera()
    setup(zen)
    assert zen.secondary_label() == SECONDARY_LABEL[camera]
    wait_picker(zen)
    spy_remove(zen)
    click(zen, "#zen-share-picker-cancel")
    wait_gone(zen)
    assert_declined(zen, addon)
    assert_no_picker_for(zen, 1.5)


# -- windows and Essentials ------------------------------------------------------

# How many shares the add-on still counts as running. args[0] is its id.
RUNNING = """
const { ExtensionParent } = ChromeUtils.importESModule(
  "resource://gre/modules/ExtensionParent.sys.mjs");
const extension = ExtensionParent.GlobalManager.getExtension(args[0]);
const api = extension.apiManager.getAPI("sharePicker", extension, "addon_parent");
return api._picker.running.size;
"""


def test_closing_a_window_mid_share_forgets_its_share(zen, site, addon):
    """A window closed while its share waits on the hidden panel's Allow
    takes that share with it: its timers never fire again, so only the
    window's uninstall can drop it."""
    first = zen.window
    zen.open_window()
    zen.request_share()
    block_allow(zen)
    wait_picker(zen)
    zen.wait_picker_armed()
    zen.chrome("shareNotification().timeShown = ChromeUtils.now() + 10000;")
    zen.press("Enter")
    wait_gone(zen)
    assert zen.chrome(RUNNING, addon) == 1
    zen.chrome("win.setTimeout(() => win.close(), 0);")
    zen.use_window(first)
    end = time.monotonic() + 2
    while (running := zen.chrome(RUNNING, addon)) != 0:
        assert time.monotonic() < end, running
        time.sleep(0.1)
    assert status(zen, addon)["lastOutcome"] is None


def test_two_synced_windows_show_one_row_per_tab(zen, site, addon):
    spaces(zen)
    first = zen.window
    zen.open_window()
    # Selecting docs in the second window moves its content there; Zen then
    # lists the tab once per window.
    zen.chrome(
        """
        const tab = tabsOf(win).find(t => t.linkedBrowser?.currentURI?.spec == args[0]);
        win.gBrowser.selectedTab = tab;
        await waitFor(() => tab.linkedPanel && tab._zenContentsVisible, "docs in window 2");
        """,
        DOCS,
    )
    zen.use_window(first)
    zen.request_share()
    tabs = [e for e in zen.stock_entries() if e["mediaSource"] == "browser"]
    p = wait_picker(zen)
    assert len(tabs) > len(p["keys"]) - 1, (tabs, p)
    keys = p["keys"]
    assert len(keys) == len(set(keys)), p
    for url in (DOCS, WIKI, SHARE_PAGE):
        assert keys.count(key_of(zen, url)) == 1, (url, p)


def test_essential_from_another_container_is_hidden(zen, site, addon):
    _work, perso = spaces(zen)
    essential = "http://shop.test/e"
    zen.make_essential(essential, "Perso")
    first = zen.window
    zen.open_window()
    zen.switch_space(perso)
    zen.chrome(
        """
        const tab = tabsOf(win).find(t => t.linkedBrowser?.currentURI?.spec == args[0]);
        win.gBrowser.selectedTab = tab;
        await waitFor(() => tab.linkedPanel, "the Essential to have a browser");
        """,
        essential,
    )
    zen.use_window(first)
    zen.request_share()
    key = key_of(zen, essential)
    p = wait_picker(zen)
    assert key not in p["keys"], p
    assert "shop.test" not in p["text"], p
    zen.press("Tab")
    p = wait_picker(zen, lambda p: "Essentials" in p["headers"], "the Essentials")
    assert key in p["keys"], p
    assert key in p["careful"], p


def test_removing_the_addon_closes_the_picker(zen, site, addon):
    """Shutdown closes every picker without sharing and stops its preview."""
    setup(zen)
    count_captures(zen)
    wait_picker(zen)
    Addons(zen.client).uninstall(addon)
    wait_gone(zen)
    assert_prompt_untouched(zen)
    stopped_at = captures(zen)
    time.sleep(2.5)
    assert captures(zen) == stopped_at
    assert_no_stream(zen)
