"""The stock-prompt glue (`src/glue/prompt.sys.mjs`, `src/glue/tabs.sys.mjs`)
and the share sequence (`src/lib/share.mjs`) against a real Zen, imported
from the installed add-on through `zen.glue(...)`."""

import sys
import time

import pytest
from test_picker import assert_rejected_without_permission

SHARE_PAGE = "http://meet.test/share"

# Imports the glue into the chrome script: P (prompt), T (tabs), R (rows),
# S (share), C (config). args[0] is the map of their URLs.
IMPORTS = """
const urls = args[0];
const P = ChromeUtils.importESModule(urls.prompt);
const T = ChromeUtils.importESModule(urls.tabs);
const R = ChromeUtils.importESModule(urls.rows);
const S = ChromeUtils.importESModule(urls.share);
const C = ChromeUtils.importESModule(urls.config);
"""


def glue_urls(zen):
    return {
        "prompt": zen.glue("glue/prompt.sys.mjs"),
        "tabs": zen.glue("glue/tabs.sys.mjs"),
        "rows": zen.glue("lib/rows.mjs"),
        "share": zen.glue("lib/share.mjs"),
        "config": zen.glue("lib/config.mjs"),
    }


def run(zen, body, *args):
    return zen.chrome(IMPORTS + body, glue_urls(zen), *args)


def two_spaces(zen):
    """Spaces Work (no container) and Perso (container "Perso"), one tab in
    each, Work active. Returns the space uuids and the tab URLs."""
    work = zen.make_space("Work", None)
    perso = zen.make_space("Perso", "Perso")
    urls = {"work": "http://docs.test/w1", "perso": "http://mail.test/p1"}
    zen.switch_space(perso)
    zen.visit(urls["perso"])
    zen.switch_space(work)
    zen.visit(urls["work"])
    return work, perso, urls


def test_read_prompt_maps_every_tab_entry(zen, site, addon):
    """readPrompt lists the tab entries, tabFacts maps each to its tab with
    the right space, and hereOf is the requesting window's space. Zen lists
    only each window's active space (P13), so Perso's tab is listed through
    a second window on Perso (P14)."""
    work, perso, urls = two_spaces(zen)
    first = zen.window
    zen.open_window()
    zen.switch_space(perso)
    zen.chrome(
        """
        const tab = tabsOf(win).find(t => t.linkedBrowser?.currentURI?.spec == args[0]);
        win.gBrowser.selectedTab = tab;
        await waitFor(() => tab.linkedPanel, "the Perso tab to have a browser");
        """,
        urls["perso"],
    )
    zen.use_window(first)
    zen.request_share()
    got = run(
        zen,
        """
        const r = P.readPrompt(win);
        if (!r.ok) return { reason: r.reason };
        const t = T.tabFacts(r.info.entries, win, r.info.browser, Services);
        return {
          entries: r.info.entries.map(e => ({ deviceId: e.deviceId, mediaSource: e.mediaSource })),
          osEntry: r.info.osEntry ? r.info.osEntry.deviceId : null,
          initial: r.info.initialItem?.deviceId == undefined ? null
                                                             : String(r.info.initialItem.deviceId),
          requesting: String(r.info.browser.browserId),
          site: r.info.site,
          facts: t.ok ? t.facts.map(f => ({ deviceId: f.deviceId, spaceId: f.spaceId,
                                            host: f.host, requesting: f.requesting,
                                            inPromptWindow: f.inPromptWindow })) : t.reason,
          here: T.hereOf(win),
          names: Object.fromEntries(T.spaceNamesOf(win)),
        };
        """,
    )
    assert "reason" not in got, got
    browser_entries = [e for e in got["entries"] if e["mediaSource"] == "browser"]
    assert browser_entries, got
    assert isinstance(got["facts"], list), got
    assert [f["deviceId"] for f in got["facts"]] == [
        e["deviceId"] for e in browser_entries
    ]
    # P6: the OS row is only ever the pre-selected, non-tab item.
    assert got["osEntry"] is None or got["osEntry"] == got["initial"], got
    assert got["osEntry"] not in {e["deviceId"] for e in browser_entries}, got
    by_host = {}
    for f in got["facts"]:
        by_host.setdefault(f["host"], []).append(f)
    # The Perso tab is listed once, from the second window.
    assert [(f["spaceId"], f["inPromptWindow"]) for f in by_host["mail.test"]] == [
        (perso, False)
    ], got
    assert [(f["spaceId"], f["inPromptWindow"]) for f in by_host["docs.test"]] == [
        (work, True)
    ], got
    requesting = [f for f in got["facts"] if f["requesting"]]
    assert [f["deviceId"] for f in requesting] == [got["requesting"]], got
    assert requesting[0]["host"] == "meet.test", got
    # P37: the asking site, for the picker's header.
    assert got["site"] == {"name": "meet.test", "secondName": None}, got
    assert got["here"] == {"spaceId": work, "ucid": 0}
    assert got["names"][work] == "Work"
    assert got["names"][perso] == "Perso"


def test_read_prompt_rejects_a_camera_request(launch_zen, site, addon_xpi):
    zen = launch_zen({"media.navigator.streams.fake": True})
    zen.wait_addon_active(zen.install_addon(str(addon_xpi)))
    zen.request_share("camera")
    got = run(zen, "return P.readPrompt(win);")
    assert got == {"ok": False, "reason": "not-screen-request"}


def test_read_prompt_without_a_prompt(zen, site, addon):
    got = run(zen, "return P.readPrompt(win);")
    assert got == {"ok": False, "reason": "no-notification"}


def test_port_shares_a_background_tab(zen, site, addon):
    if zen.screen_capture_denied():
        pytest.skip("macOS denies Zen screen capture; Allow would raise a macOS dialog")
    background = "http://docs.test/bg"
    zen.visit(background)
    target = zen.browser_id(background)
    zen.request_share()
    got = run(
        zen,
        """
        const { webrtcUI } = ChromeUtils.importESModule("resource:///modules/webrtcUI.sys.mjs");
        const r = P.readPrompt(win);
        if (!r.ok) return { reason: r.reason };
        const port = P.makePort(win, r.info, { Services, ChromeUtils, webrtcUI });
        const clock = {
          now: () => ChromeUtils.now(),
          sleep: ms => new Promise(res => win.setTimeout(res, ms)),
        };
        const lines = [];
        const n = r.info.notification;
        const t0 = ChromeUtils.now();
        let clickedAt = null;
        const button = r.info.element.button;
        const onClick = () => { clickedAt ??= ChromeUtils.now() - n.timeShown; };
        button.addEventListener("click", onClick);
        const outcome = await S.runShare({
          port, clock, mode: "click",
          target: { kind: "tab", deviceId: args[1] },
          closePicker() {}, stopPreview() {},
          timing: C.TIMING, log: l => lines.push(l),
        });
        button.removeEventListener("click", onClick);
        return { outcome, lines, clickedAt, ms: Math.round(ChromeUtils.now() - t0) };
        """,
        target,
    )
    assert got.get("outcome") == "shared", got
    assert got["clickedAt"] is not None and got["clickedAt"] >= 500, got
    deadline = time.monotonic() + 5
    while zen.page_title(SHARE_PAGE) != "shared":
        assert time.monotonic() < deadline, zen.page_title(SHARE_PAGE)
        time.sleep(0.1)
    assert target in zen.sharing_device_ids()


def test_same_id_of_another_kind_is_not_a_duplicate(zen, site, addon):
    """Entries are unique by mediaSource and deviceId, so a window whose
    id equals a tab's browserId still gets a picker, and select picks the
    entry of the asked kind. The same id twice for one kind stays a
    bad-entry. The collision is made by turning one tab item into a window
    item, so it holds where the prompt lists no screen or window (P29)."""
    zen.visit("http://docs.test/one")
    zen.visit("http://wiki.test/two")
    zen.request_share()
    got = run(
        zen,
        """
        const { webrtcUI } = ChromeUtils.importESModule("resource:///modules/webrtcUI.sys.mjs");
        const popup = win.document.getElementById("webRTC-selectWindow-menupopup");
        const tabs = Array.from(popup.children).filter(i => i.mediaSource == "browser");
        if (tabs.length < 3) throw new Error("want 3 tab items, got " + tabs.length);
        const [first, second, last] = [tabs[0], tabs[1], tabs[tabs.length - 1]];
        // The first tab item becomes a window with the last tab's id.
        first.mediaSource = "window";
        first.deviceId = last.deviceId;
        const r = P.readPrompt(win);
        if (!r.ok) return { reason: r.reason };
        const id = String(last.deviceId);
        const same = r.info.entries.filter(e => e.deviceId == id)
          .map(e => e.mediaSource).sort();
        const port = P.makePort(win, r.info, { Services, ChromeUtils, webrtcUI });
        const picked = port.select(id, "tab");
        const list = win.document.getElementById("webRTC-selectWindow-menulist");
        const selectedLast = list.selectedItem === last;
        // One kind, one id twice: still refused.
        second.deviceId = last.deviceId;
        const dup = P.readPrompt(win);
        return { same, picked, selectedLast, dup: dup.ok ? "ok" : dup.reason };
        """,
    )
    assert got == {
        "same": ["browser", "window"],
        "picked": True,
        "selectedLast": True,
        "dup": "bad-entry",
    }, got


def test_port_select_of_a_missing_device_keeps_the_selection(zen, site, addon):
    zen.visit("http://docs.test/keep")
    zen.request_share()
    before = zen.stock_selected()
    got = run(
        zen,
        """
        const { webrtcUI } = ChromeUtils.importESModule("resource:///modules/webrtcUI.sys.mjs");
        const r = P.readPrompt(win);
        if (!r.ok) return { reason: r.reason };
        const port = P.makePort(win, r.info, { Services, ChromeUtils, webrtcUI });
        return { selected: port.select("999999"), current: port.isCurrent() };
        """,
    )
    assert got == {"selected": False, "current": True}
    assert zen.stock_selected() == before
    assert zen.stock_prompt_open()


def test_synced_tab_in_two_windows_dedupes_to_one(zen, site, addon):
    """A synced tab whose content moved to a second window is listed once
    per window. dedupe keeps each tab once: the copy holding the content
    (P8), and for a tab only the requesting window shows, that window's."""
    moved = "http://docs.test/a"
    zen.visit(moved)
    zen.visit("http://wiki.test/b")
    first = zen.window
    zen.open_window()
    # Selecting the tab in the second window moves its content there; the
    # first window's copy keeps a browser without content.
    zen.chrome(
        """
        const tab = tabsOf(win).find(t => t.linkedBrowser?.currentURI?.spec == args[0]);
        win.gBrowser.selectedTab = tab;
        await waitFor(() => tab.linkedPanel && tab._zenContentsVisible,
                      "the tab to show its content in the second window");
        """,
        moved,
    )
    zen.use_window(first)
    zen.request_share()
    got = run(
        zen,
        """
        const r = P.readPrompt(win);
        if (!r.ok) return { reason: r.reason };
        const t = T.tabFacts(r.info.entries, win, r.info.browser, Services);
        if (!t.ok) return { reason: t.reason };
        const kept = R.dedupe(t.facts);
        return {
          facts: t.facts.map(f => ({ syncKey: f.syncKey, inPromptWindow: f.inPromptWindow,
                                     host: f.host, contentsVisible: f.contentsVisible })),
          kept: kept.map(f => ({ syncKey: f.syncKey, inPromptWindow: f.inPromptWindow,
                                 host: f.host, contentsVisible: f.contentsVisible })),
        };
        """,
    )
    assert "reason" not in got, got
    keys = [f["syncKey"] for f in got["facts"]]
    doubled = {k for k in keys if keys.count(k) > 1}
    if sys.platform == "darwin":
        assert {f["host"] for f in got["facts"] if f["syncKey"] in doubled} == {
            "docs.test"
        }, got
    else:
        # By sync key, not host: on Linux the copy without content reports
        # an empty host (P29).
        assert doubled == {
            f["syncKey"] for f in got["facts"] if f["host"] == "docs.test"
        }, got
    assert len(doubled) == 1, got
    kept_keys = [f["syncKey"] for f in got["kept"]]
    assert sorted(kept_keys) == sorted(set(keys)), got
    kept = {f["host"]: f for f in got["kept"]}
    assert kept["docs.test"]["contentsVisible"] is True, got
    assert kept["docs.test"]["inPromptWindow"] is False, got
    assert kept["wiki.test"]["inPromptWindow"] is True, got
    assert kept["meet.test"]["inPromptWindow"] is True, got


def test_port_abandons_the_notification(zen, site, addon):
    """P38: abandon() removes the session's own notification without a user
    response, so Zen denies the request and sets no permission; isGone()
    sees it go."""
    zen.visit("http://docs.test/abandon")
    zen.request_share()
    got = run(
        zen,
        """
        const { webrtcUI } = ChromeUtils.importESModule("resource:///modules/webrtcUI.sys.mjs");
        const r = P.readPrompt(win);
        if (!r.ok) return { reason: r.reason };
        const port = P.makePort(win, r.info, { Services, ChromeUtils, webrtcUI });
        const before = { gone: port.isGone(), current: port.isCurrent() };
        port.abandon();
        return { before, gone: port.isGone(), current: port.isCurrent() };
        """,
    )
    assert got == {
        "before": {"gone": False, "current": True},
        "gone": True,
        "current": False,
    }, got
    assert_rejected_without_permission(zen)


def test_port_select_checks_the_target_kind(zen, site, addon):
    """P19: a "tab" target must be a tab entry and an "os" target the
    recorded OS entry; a mismatch selects nothing."""
    zen.visit("http://docs.test/kind")
    tab = zen.browser_id("http://docs.test/kind")
    zen.request_share()
    before = zen.stock_selected()
    got = run(
        zen,
        """
        const { webrtcUI } = ChromeUtils.importESModule("resource:///modules/webrtcUI.sys.mjs");
        const r = P.readPrompt(win);
        if (!r.ok) return { reason: r.reason };
        const port = P.makePort(win, r.info, { Services, ChromeUtils, webrtcUI });
        const other = r.info.entries.find(e => e.mediaSource != "browser");
        const noOs = P.makePort(win, { ...r.info, osEntry: null },
                                { Services, ChromeUtils, webrtcUI });
        return {
          tabAsOs: port.select(args[0], "os"),
          osAsTab: other ? port.select(other.deviceId, "tab") : false,
          osWithoutRecord: other ? noOs.select(other.deviceId, "os") : false,
          noKind: port.select(args[0]),
          hasOther: !!other,
        };
        """,
        tab,
    )
    assert got["tabAsOs"] is False and got["noKind"] is False, got
    assert zen.stock_selected() == before
    assert zen.stock_prompt_open()
    if not got["hasOther"]:
        # P29: headless Linux lists no screen or window, only tabs.
        pytest.skip("the prompt has no screen or window entry to check as 'os'")
    assert got == {
        "tabAsOs": False,
        "osAsTab": False,
        "osWithoutRecord": False,
        "noKind": False,
        "hasOther": True,
    }
