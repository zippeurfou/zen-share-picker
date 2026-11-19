"""Platform tests: the Zen behavior the add-on depends on, with no add-on
installed. They decided the share and preview modes in `src/lib/config.mjs`
and stay as daily regression tests against new Zen releases.

Each test prints one `SPIKE <name>: <json>` line with what it saw (ids,
counts, timings). Run with `-rP` to read them.
"""

import json
import time

import pytest
from zen import SECONDARY_LABEL, key_input

# Zen's own wrapper around the browser UI, where the picker mounts.
MOUNT = "zen-main-app-wrapper"


def spike(name, data):
    print(f"SPIKE {name}: {json.dumps(data, sort_keys=True)}")


def two_spaces(zen):
    """Spaces Work (no container) and Perso (container "Perso"), two tabs in
    each, Work active and its last tab selected. Returns the space uuids
    and the tab URLs."""
    work = zen.make_space("Work", None)
    perso = zen.make_space("Perso", "Perso")
    urls = {
        "work": ["http://docs.test/w1", "http://wiki.test/w2"],
        "perso": ["http://mail.test/p1", "http://shop.test/p2"],
    }
    zen.switch_space(perso)
    for url in urls["perso"]:
        zen.visit(url)
    zen.switch_space(work)
    for url in urls["work"]:
        zen.visit(url)
    return work, perso, urls


# Every tab of every window: its window, DOM id (the sync key), browser id,
# space, container and whether it has content.
ALL_TABS = """
const out = [];
const windows = Array.from(Services.wm.getEnumerator("navigator:browser"));
windows.forEach((w, wi) => {
  const visible = new Set(w.gBrowser.visibleTabs);
  for (const t of tabsOf(w)) {
    out.push({
      window: wi,
      requesting: w == win,
      syncKey: t.id,
      browserId: String(t.linkedBrowser?.browserId),
      linkedPanel: !!t.linkedPanel,
      visible: visible.has(t),
      url: t.linkedBrowser?.currentURI?.spec ?? null,
      space: t.getAttribute("zen-workspace-id"),
      essential: t.hasAttribute("zen-essential"),
      ucid: Number(t.getAttribute("usercontextid") || 0),
      contentsVisible: !!t._zenContentsVisible,
    });
  }
});
return out;
"""


def test_tab_entries_map_to_tabs_by_browser_id(zen, site):
    """S1. Every tab entry of the stock prompt is a tab's browser id, every
    shareable tab of every window has an entry, and another space's tab is
    listed while Work is active in the requesting window.

    Firefox lists `gBrowser.visibleTabs` of every window
    (BrowserWindowTracker.getAllVisibleTabs), and in Zen that is the
    window's active space only. So another space's tab reaches the prompt
    through another window that shows that space, as here."""
    work, perso, urls = two_spaces(zen)
    first = zen.window
    zen.open_window()
    zen.switch_space(perso)
    shown = urls["perso"][0]
    zen.chrome(
        """
        const tab = tabsOf(win).find(t => t.linkedBrowser?.currentURI?.spec == args[0]);
        win.gBrowser.selectedTab = tab;
        await waitFor(() => tab.linkedPanel && tab._zenContentsVisible,
                      "the Perso tab to show its content in this window");
        """,
        shown,
    )
    zen.use_window(first)
    zen.request_share()

    entries = [e for e in zen.stock_entries() if e["mediaSource"] == "browser"]
    tabs = zen.chrome(ALL_TABS)
    assert entries, "no tab entries"
    by_id = {}
    for t in tabs:
        if t["linkedPanel"]:
            by_id.setdefault(t["browserId"], []).append(t)
    ids = [e["deviceId"] for e in entries]
    unmapped = [i for i in ids if i not in by_id]
    shareable = {t["browserId"] for t in tabs if t["linkedPanel"] and t["visible"]}
    missing = sorted(shareable - set(ids))
    copies: dict[str, list[dict]] = {}
    for t in tabs:
        copies.setdefault(t["syncKey"], []).append(t)
    synced = {
        k: [
            {
                "window": c["window"],
                "listed": c["browserId"] in ids,
                "linkedPanel": c["linkedPanel"],
                "contentsVisible": c["contentsVisible"],
            }
            for c in v
        ]
        for k, v in copies.items()
        if len(v) > 1 and v[0]["url"] and v[0]["url"].startswith("http")
    }
    listed = [t for i in ids for t in by_id.get(i, [])]
    spike(
        "S1",
        {
            "entries": len(entries),
            "tabs": len(tabs),
            "unmapped": unmapped,
            "missing": missing,
            "duplicate_ids": len(ids) - len(set(ids)),
            "synced_copies": synced,
            "listed": [[t["window"], t["url"], t["space"] == perso] for t in listed],
        },
    )
    assert not unmapped, f"entries that are no tab's browser id: {unmapped}"
    assert not missing, f"shareable tabs without an entry: {missing}"
    perso_listed = [t for t in listed if t["space"] == perso]
    assert shown in [t["url"] for t in perso_listed], listed
    assert zen.active_space()["uuid"] == work


def overlay_state(zen):
    return zen.chrome(
        """
        const n = shareNotification();
        const el = win.document.getElementById("webRTC-shareDevices-notification");
        return {
          same: !!n && n === win.__spikeNotification,
          panel: win.PopupNotifications.panel.state,
          activeWindow: Services.focus.activeWindow == win,
          inactive: el.matches(":-moz-window-inactive"),
          value: win.document.getElementById("zsp-spike-input")?.value ?? null,
          focused: Services.focus.focusedElement?.id ?? null,
          keys: win.__spikeKeys ?? [],
        };
        """
    )


def test_overlay_keeps_the_prompt_open_and_active(zen, site):
    """S2. A centered div with a focused input over Zen's UI keeps the
    stock prompt open, the same notification, and the window active, and
    Esc typed into the input does not dismiss the prompt."""
    zen.request_share()
    before = zen.chrome(
        """
        win.__spikeNotification = shareNotification();
        const el = win.document.getElementById("webRTC-shareDevices-notification");
        return { activeWindow: Services.focus.activeWindow == win,
                 inactive: el.matches(":-moz-window-inactive") };
        """
    )
    zen.chrome(
        """
        const doc = win.document;
        const div = doc.createElementNS("http://www.w3.org/1999/xhtml", "div");
        div.id = "zsp-spike";
        div.style.cssText = "position: fixed; top: 50%; left: 50%; " +
          "transform: translate(-50%, -50%); width: 600px; height: 400px; " +
          "z-index: 2147483647; background: white;";
        const input = doc.createElementNS("http://www.w3.org/1999/xhtml", "input");
        input.id = "zsp-spike-input";
        win.__spikeKeys = [];
        input.addEventListener("keydown", e => win.__spikeKeys.push([e.key, e.isTrusted]), true);
        div.append(input);
        doc.getElementById(args[0]).append(div);
        input.focus();
        await waitFor(() => Services.focus.focusedElement == input, "the input to have focus");
        """,
        MOUNT,
    )
    zen.press("a", "Escape")
    time.sleep(1)
    after = overlay_state(zen)
    zen.chrome('win.document.getElementById("zsp-spike").remove();')
    time.sleep(0.2)
    still = zen.stock_prompt_open()
    spike("S2", {"before": before, "after": after, "prompt_after_removal": still})
    assert after["value"] == "a", after
    # Escape reached the input, as a trusted key with WebDriver input, so
    # the prompt staying open below is a real non-dismissal.
    trusted = key_input() == "webdriver"
    assert ["Escape", trusted] in after["keys"], after
    assert after["same"], after
    assert after["panel"] == "open", after
    assert after["activeWindow"], after
    assert not after["inactive"], after
    assert still


BLANK = "about:blank"

# A background about:blank tab of the active space, kept in win.__spikeBlank
# (findTab would also match Zen's own empty tab).
OPEN_BLANK = """
const tab = win.gBrowser.addTab("about:blank", {
  triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal(),
  userContextId: win.gZenWorkspaces.getCurrentSpaceContainerId(),
});
win.__spikeBlank = tab;
await waitFor(() => tab.linkedBrowser.browsingContext?.currentWindowGlobal,
              "the blank tab to have a document");
"""

SNAPSHOT = """
const tab = args[0] == "about:blank" ? win.__spikeBlank : findTab(args[0]);
const canvas = win.document.createElementNS("http://www.w3.org/1999/xhtml", "canvas");
canvas.width = 560;
canvas.height = 280;
const { PageThumbs } = ChromeUtils.importESModule("resource://gre/modules/PageThumbs.sys.mjs");
const t0 = ChromeUtils.now();
const ok = await PageThumbs.captureTabPreviewThumbnail(tab.linkedBrowser, canvas);
const ms = Math.round(ChromeUtils.now() - t0);
const data = canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height).data;
let painted = 0;
const colors = new Set();
for (let i = 3; i < data.length; i += 4) {
  if (data[i] > 0) painted++;
  if (colors.size < 64) colors.add(data.slice(i - 3, i + 1).join(","));
}
return { ok, ms, painted, colors: colors.size, selected: tab.selected,
         space: tab.getAttribute("zen-workspace-id") };
"""


def test_background_tab_snapshot(zen, site):
    """S3. Firefox's tab hover preview capture works on a background tab of
    the active space and on another space's tab."""
    _work, _perso, urls = two_spaces(zen)
    zen.chrome(OPEN_BLANK)
    zen.request_share()
    background = zen.chrome(SNAPSHOT, urls["work"][0])
    other = zen.chrome(SNAPSHOT, urls["perso"][0])
    blank = zen.chrome(SNAPSHOT, BLANK)
    spike("S3", {"background": background, "other_space": other, "blank": blank})
    # Control: a blank page snapshots to one flat color, so more than one
    # color means real page content (the <h1> text antialiases).
    assert blank["ok"] is True, blank
    assert blank["colors"] == 1, blank
    for shot in (background, other):
        assert shot["ok"] is True, shot
        assert not shot["selected"], shot
        assert shot["painted"] > 0, shot
        assert shot["colors"] > 1, shot


def test_stock_share_flow(zen, site):
    """S4. Selecting a background tab in the stock prompt and pressing its
    real Allow button, once the enable delay has passed, shares that tab."""
    if zen.screen_capture_denied():
        pytest.skip("macOS denies Zen screen capture; Allow would raise a macOS dialog")
    background = "http://docs.test/s4"
    zen.visit(background)
    target = zen.browser_id(background)
    zen.request_share()
    active = zen.chrome(
        """
        win.focus();
        try {
          await waitFor(() => Services.focus.activeWindow == win, "the window to be active", 10000);
        } catch (e) {
          return false;
        }
        return true;
        """
    )
    if not active:
        pytest.skip("window could not become active")
    selected = zen.chrome(
        """
        const list = win.document.getElementById("webRTC-selectWindow-menulist");
        const el = win.document.getElementById("webRTC-shareDevices-notification");
        const item = Array.from(list.menupopup.children).find(i => String(i.deviceId) == args[0]);
        if (!item) throw new Error("no entry for the tab");
        list.selectedItem = item;
        item.doCommand();
        let how = "doCommand";
        if (el.hasAttribute("invalidselection")) {
          item.dispatchEvent(new win.Event("command", { bubbles: true }));
          how = "event";
        }
        return { how, invalid: el.hasAttribute("invalidselection"),
                 disabled: !!el.button.disabled || el.hasAttribute("mainactiondisabled") };
        """,
        target,
    )
    assert not selected["invalid"], selected
    assert not selected["disabled"], selected
    early = zen.chrome(
        """
        const n = shareNotification();
        const el = win.document.getElementById("webRTC-shareDevices-notification");
        const activeWindow = Services.focus.activeWindow == win &&
                             !el.matches(":-moz-window-inactive");
        const sinceShown = ChromeUtils.now() - n.timeShown;
        el.button.click();
        await new Promise(r => win.setTimeout(r, 100));
        return { sinceShown: Math.round(sinceShown), activeWindow,
                 stays: shareNotification() === n };
        """
    )
    # Rejected by the enable delay: the window was active, so the inactive
    # window check (PopupNotifications.sys.mjs:2036-2046) did not do it.
    assert early["activeWindow"], early
    assert early["sinceShown"] < 500, early
    assert early["stays"], early
    late = zen.chrome(
        """
        const n = shareNotification();
        const el = win.document.getElementById("webRTC-shareDevices-notification");
        await waitFor(() => ChromeUtils.now() - n.timeShown >= 500, "the enable delay", 5000);
        const t0 = ChromeUtils.now();
        el.button.click();
        let gone = false;
        try {
          await waitFor(() => !shareNotification(), "the notification to go", 1000);
          gone = true;
        } catch (e) {}
        return { gone, ms: Math.round(ChromeUtils.now() - t0),
                 activeWindow: Services.focus.activeWindow == win };
        """
    )
    spike("S4", {"select": selected, "early": early, "late": late})
    assert late["gone"], late
    deadline = time.monotonic() + 5
    while zen.page_title("http://meet.test/share") != "shared":
        assert time.monotonic() < deadline, zen.page_title("http://meet.test/share")
        time.sleep(0.1)
    assert target in zen.sharing_device_ids()


def test_space_data(zen, site):
    """S5. A tab's space and an Essential's container read back as set."""
    work, perso, urls = two_spaces(zen)
    zen.make_essential("http://news.test/e1", "Perso")
    data = zen.chrome(
        """
        const work = findTab(args[0]);
        const ess = findTab(args[1]);
        const persoTab = findTab(args[2]);
        return { workSpace: work.getAttribute("zen-workspace-id"),
                 persoSpace: persoTab.getAttribute("zen-workspace-id"),
                 essential: ess.hasAttribute("zen-essential"),
                 essentialSpace: ess.getAttribute("zen-workspace-id"),
                 essentialUcid: ess.userContextId };
        """,
        urls["work"][0],
        "http://news.test/e1",
        urls["perso"][0],
    )
    perso_ucid = zen.container_id("Perso")
    spike("S5", {**data, "work": work, "perso": perso, "perso_ucid": perso_ucid})
    assert work != perso
    assert data["workSpace"] == work
    assert data["persoSpace"] == perso
    assert data["essential"]
    assert perso_ucid != 0
    assert data["essentialUcid"] == perso_ucid


# How the add-on hides Zen's share panel while the panel stays open
# (src/glue/conceal.sys.mjs): no paint, no pointer hits, no window opacity
# or shadow, and none of the native menu look Zen gives a plain-window panel
# with `!important`, which the doubled id outranks. Collapsing the panel's
# size closed it instead.
CONCEAL_RULE = (
    "#notification-popup#notification-popup { opacity: 0 !important;"
    " pointer-events: none !important; -moz-window-opacity: 0 !important;"
    " -moz-window-shadow: none !important; appearance: none !important;"
    " background: transparent !important; }"
)

# Whether the panel is concealed, from its computed style.
CONCEALED = """
const s = win.getComputedStyle(win.PopupNotifications.panel);
return s.opacity == "0" && s.pointerEvents == "none";
"""

CONCEAL = """
const style = win.document.createElementNS("http://www.w3.org/1999/xhtml", "style");
style.setAttribute("data-zen-share-picker-conceal", "");
style.textContent = args[0];
win.document.documentElement.append(style);
await new Promise(r => win.setTimeout(r, 300));
"""

PANEL_STATE = """
const n = shareNotification();
const el = win.document.getElementById("webRTC-shareDevices-notification");
const s = win.getComputedStyle(win.PopupNotifications.panel);
return {
  same: !!n && n === win.__spikeNotification,
  timeShown: n ? n.timeShown : null,
  inactive: el.matches(":-moz-window-inactive"),
  panel: win.PopupNotifications.panel.state,
  opacity: s.opacity,
  pointerEvents: s.pointerEvents,
  window: [win.screenX, win.screenY, win.outerWidth, win.outerHeight],
};
"""


def test_concealed_panel_keeps_allow_working(zen, site):
    """S6a. With the hiding rule applied, Zen's share panel stays open with
    the same notification, its enable delay does not restart, the window
    stays active, and its real Allow button still shares."""
    if zen.screen_capture_denied():
        pytest.skip("macOS denies Zen screen capture; Allow would raise a macOS dialog")
    background = "http://docs.test/s6"
    zen.visit(background)
    target = zen.browser_id(background)
    zen.settle()
    zen.request_share()
    zen.settle()
    before = zen.chrome("win.__spikeNotification = shareNotification();" + PANEL_STATE)
    zen.chrome(CONCEAL, CONCEAL_RULE)
    after = zen.chrome(PANEL_STATE)
    hidden = zen.chrome(CONCEALED)
    shared = zen.chrome(
        """
        const n = shareNotification();
        const list = win.document.getElementById("webRTC-selectWindow-menulist");
        const el = win.document.getElementById("webRTC-shareDevices-notification");
        const item = Array.from(list.menupopup.children).find(i => String(i.deviceId) == args[0]);
        if (!item) throw new Error("no entry for the tab");
        list.selectedItem = item;
        item.doCommand();
        if (el.hasAttribute("invalidselection")) {
          item.dispatchEvent(new win.Event("command", { bubbles: true }));
        }
        await waitFor(() => ChromeUtils.now() - n.timeShown >= 500, "the enable delay", 5000);
        el.button.click();
        let gone = false;
        try {
          await waitFor(() => !shareNotification(), "the notification to go", 1000);
          gone = true;
        } catch (e) {}
        return { gone, activeWindow: Services.focus.activeWindow == win };
        """,
        target,
    )
    spike(
        "S6a",
        {
            "before": before,
            "after": after,
            "concealed": hidden,
            "shared": shared,
        },
    )
    assert after["panel"] == "open", after
    assert after["same"], after
    assert after["timeShown"] == before["timeShown"], (before, after)
    assert after["inactive"] == before["inactive"], (before, after)
    assert hidden, after
    assert shared["gone"], shared
    deadline = time.monotonic() + 5
    while zen.page_title("http://meet.test/share") != "shared":
        assert time.monotonic() < deadline, zen.page_title("http://meet.test/share")
        time.sleep(0.1)
    assert target in zen.sharing_device_ids()


# Records each mousedown in the window as {inPanel, target, onUnder} and
# stops it, so the click does nothing beneath. `composedPath()` crosses
# shadow roots, so a hit on the panel's own shadow content counts as in
# the panel. A synthetic mousedown on that shadow content is the spy's own
# control; it is recorded and then dropped.
HIT_SPY = """
const panel = win.PopupNotifications.panel;
win.__hits = [];
win.addEventListener("mousedown", e => {
  const path = e.composedPath();
  const t = e.originalTarget;
  win.__hits.push({
    inPanel: path.includes(panel),
    target: t.localName ?? t.nodeName,
    onUnder: !!win.__under && path.includes(win.__under),
  });
  e.preventDefault();
  e.stopPropagation();
}, true);
const inner = panel.shadowRoot?.querySelector("*:not(style, link)");
if (!inner) throw new Error("the panel has no shadow content");
inner.dispatchEvent(new win.MouseEvent("mousedown", { bubbles: true, composed: true }));
return { shadow: inner.localName, spy: win.__hits.splice(0) };
"""


def test_concealed_panel_lets_clicks_through(zen, site):
    """S6b. A click where the concealed panel sits does not land in the
    panel. A click at the same point before concealing is the control: it
    must land in the panel, or this setup cannot observe click-through."""
    zen.settle()
    zen.request_share()
    zen.settle()
    spy = zen.chrome(HIT_SPY)
    left, top, right, bottom = zen.panel_rect()
    x, y = (left + right) / 2, (top + bottom) / 2
    zen._click(x, y)
    control = zen.chrome("return win.__hits.slice();")
    zen.chrome(CONCEAL, CONCEAL_RULE)
    # What lies under the panel at the click point, from the chrome
    # document's own hit test (asserted below not to be the panel). The
    # second click must reach it: the page, or Zen's sidebar headful.
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
    open_after = zen.stock_prompt_open()
    spike(
        "S6b",
        {
            "spy": spy,
            "rect": [left, top, right, bottom],
            "control": control,
            "hits": hits,
            "under": under,
            "open_after": open_after,
        },
    )
    assert [h["inPanel"] for h in spy["spy"]] == [True], spy
    if [h["inPanel"] for h in control] != [True]:
        pytest.skip("pointer actions do not reach the panel here")
    assert len(hits) == 2, hits
    assert not hits[1]["inPanel"], hits
    assert under["name"] and not under["inPanel"], under
    assert hits[1]["onUnder"], (hits, under)
    assert open_after


@pytest.mark.parametrize("camera", [True, False], ids=["camera", "no-camera"])
def test_abandon_denies_without_a_permission(launch_zen, site, camera):
    """S7. Removing the share notification without a user response
    (`PopupNotifications.remove(n, true)`) denies the page's request and
    sets no "screen" permission, whether the secondary button reads
    "Not now" (camera allowed) or "Block"."""
    zen = launch_zen()
    if camera:
        zen.allow_camera()
    zen.request_share()
    result = zen.chrome(
        """
        const n = shareNotification();
        const el = win.document.getElementById("webRTC-shareDevices-notification");
        const label = el.getAttribute("secondarybuttonlabel");
        win.PopupNotifications.remove(n, true);
        let gone = false;
        try {
          await waitFor(() => shareNotification() !== n &&
                              win.PopupNotifications.panel.state == "closed",
                        "the notification to go", 1000);
          gone = true;
        } catch (e) {}
        return { label, gone, panel: win.PopupNotifications.panel.state };
        """
    )
    deadline = time.monotonic() + 1
    title = zen.page_title("http://meet.test/share")
    while title != "share failed NotAllowedError" and time.monotonic() < deadline:
        time.sleep(0.05)
        title = zen.page_title("http://meet.test/share")
    permission = zen.screen_permission()
    spike(
        "S7",
        {"camera": camera, **result, "title": title, "screen_permission": permission},
    )
    # The camera grant took effect: the case the test names is the one Zen built.
    assert result["label"] == SECONDARY_LABEL[camera], result
    assert result["gone"], result
    assert result["panel"] == "closed", result
    assert title == "share failed NotAllowedError", title
    assert permission == 0, permission
    # Control: the helper reads a "screen" state once one is set, here a
    # temporary block on the selected tab, as Zen's Block button sets.
    block = zen.chrome(
        """
        const { SitePermissions } = ChromeUtils.importESModule(
          "resource:///modules/SitePermissions.sys.mjs");
        const principal =
          Services.scriptSecurityManager.createContentPrincipalFromOrigin("http://meet.test");
        SitePermissions.setForPrincipal(principal, "screen", SitePermissions.BLOCK,
          SitePermissions.SCOPE_TEMPORARY, win.gBrowser.selectedBrowser);
        return SitePermissions.BLOCK;
        """
    )
    assert block != 0
    assert zen.screen_permission() == block
