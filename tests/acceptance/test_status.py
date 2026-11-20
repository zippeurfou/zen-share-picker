"""The options page, the off switch and the debug log.

The off switch and the debug switch last until Zen restarts (P27). The
debug log is off by default, holds at most 2000 lines, never a title or an
image, and holds another space's host only once Tab revealed it (P12).
"""

import re
import time

from test_picker import (
    DOCS,
    MAIL,
    WIKI,
    allow_clicks,
    assert_no_picker_for,
    assert_no_stream,
    assert_prompt_concealed,
    assert_prompt_untouched,
    block_allow,
    prompt,
    setup,
    status,
    wait_concealed,
    wait_gone,
    wait_picker,
)
from zen import CONFIG

ENABLED_LABEL = (
    "Show the tab, window and screen picker on share prompts (resets when Zen restarts)"
)
DEBUG_LABEL = "Log picker decisions (resets when Zen restarts)"
LOG_LIMIT = 2000
SECRET = "Secret Title 123"
PROMPT_LINE = re.compile(
    r"prompt (\d+) entries, (\d+) tabs, (\d+) here, "
    r"(\d+) screens, (\d+) windows, (\d+) hidden"
)


def share_mode() -> str:
    m = re.search(
        r'^export const SHARE_MODE = "(\w+)";', CONFIG.read_text(), re.MULTILINE
    )
    assert m, CONFIG
    return m.group(1)


def log(zen, addon):
    return zen.addon_call(addon, "getLog")


def wait_log(zen, addon, pred, what, timeout=5.0):
    end = time.monotonic() + timeout
    while True:
        lines = log(zen, addon)
        if pred(lines):
            return lines
        if time.monotonic() > end:
            raise AssertionError(f"timed out waiting for {what}: {lines}")
        time.sleep(0.1)


def hosts(lines):
    return [line.removeprefix("host ") for line in lines if line.startswith("host ")]


def test_options_page_shows_status(zen, addon):
    with zen.options_page(addon) as page:
        page.wait(
            "return document.getElementById('state').textContent == 'active';", "active"
        )
        assert page.text("#version") == "0.3.0"
        assert page.text("#share-mode") == share_mode()
        assert page.text("#preview-mode") != ""
        assert page.text("#bar-problems") == "none"
        assert page.eval("return document.getElementById('failed-box').hidden;") is True
        labels = page.eval(
            """
            const label = id => document.getElementById(id).closest("label").textContent;
            return [label("enabled"), label("debug")].map(t => t.trim().replace(/\\s+/g, " "));
            """
        )
        assert labels == [ENABLED_LABEL, DEBUG_LABEL]
        assert page.eval("return document.getElementById('enabled').checked;") is True
        assert page.eval("return document.getElementById('debug').checked;") is False
        assert page.eval("return document.getElementById('log').localName;") == "pre"
        page.click("#debug")
    s = status(zen, addon)
    assert s["debug"] is True, s
    assert s["barProblems"] == [], s
    with zen.options_page(addon) as page:
        page.wait("return document.getElementById('debug').checked;", "debug checked")
        page.click("#enabled")
    s = status(zen, addon)
    assert s["state"] == "disabled", s
    with zen.options_page(addon) as page:
        page.wait(
            "return document.getElementById('state').textContent == 'disabled';",
            "disabled",
        )
        assert page.eval("return document.getElementById('enabled').checked;") is False


def test_disable_stops_the_picker(zen, site, addon):
    s = zen.addon_call(addon, "setEnabled", False)
    assert s["state"] == "disabled", s
    setup(zen)
    assert_no_picker_for(zen)
    assert_prompt_untouched(zen)
    s = zen.addon_call(addon, "setEnabled", True)
    assert s["state"] == "active", s
    assert s["failedChecks"] == [], s
    zen.request_share()
    wait_picker(zen)
    assert_prompt_concealed(zen)


def test_disable_closes_an_open_picker(zen, site, addon):
    setup(zen)
    wait_picker(zen)
    s = zen.addon_call(addon, "setEnabled", False)
    assert s["state"] == "disabled", s
    wait_gone(zen)
    assert_prompt_untouched(zen)
    assert s["lastOutcome"] is None, s


def test_disable_during_a_share_shows_the_prompt(zen, site, addon):
    """P35: the off switch shows Zen's panel again at once, even while a
    share waits on the hidden panel's Allow, and nothing is shared."""
    setup(zen)
    block_allow(zen)
    wait_picker(zen)
    assert_prompt_concealed(zen)
    zen.wait_picker_armed()
    zen.press("Enter")
    wait_gone(zen)
    # The share still waits on the hidden panel: the off switch shows it.
    got = prompt(zen)
    assert (got["exists"], got["concealed"], got["markers"]) == (True, True, 1), got
    assert status(zen, addon)["lastOutcome"] is None
    s = zen.addon_call(addon, "setEnabled", False)
    assert s["state"] == "disabled", s
    end = time.monotonic() + 1
    while True:
        try:
            assert_prompt_untouched(zen)
            break
        except AssertionError:
            if time.monotonic() > end:
                raise
            time.sleep(0.05)
    assert allow_clicks(zen) <= 1
    assert_no_stream(zen)


# Hides the panel of the selected window through the add-on's own module,
# with no session behind it.
CONCEAL_HERE = """
const { concealPanel } = ChromeUtils.importESModule(args[0]);
concealPanel(win);
"""


def test_disable_sweeps_every_concealed_panel(zen, site, addon):
    """P35: the off switch removes every hiding element in every window,
    whether a session owns it or not."""
    url = zen.glue("glue/conceal.sys.mjs")
    first = zen.window
    second = zen.open_window()
    for handle in (first, second):
        zen.use_window(handle)
        zen.chrome(CONCEAL_HERE, url)
        got = wait_concealed(zen)
        assert (got["markers"], got["concealed"]) == (1, True), got
    s = zen.addon_call(addon, "setEnabled", False)
    assert s["state"] == "disabled", s
    for handle in (first, second):
        zen.use_window(handle)
        got = prompt(zen)
        assert (got["markers"], got["concealed"]) == (0, False), got


def test_debug_log_off_by_default_and_cleared(zen, site, addon):
    assert status(zen, addon)["debug"] is False
    setup(zen)
    wait_picker(zen)
    assert log(zen, addon) == []
    zen.press("Escape")
    wait_gone(zen)
    zen.addon_call(addon, "setDebug", True)
    assert status(zen, addon)["debug"] is True
    zen.request_share()
    wait_picker(zen)
    lines = wait_log(
        zen, addon, lambda ls: any(x.startswith("prompt ") for x in ls), "a prompt line"
    )
    prompts = [x for x in lines if x.startswith("prompt ")]
    assert all(PROMPT_LINE.fullmatch(x) for x in prompts), lines
    zen.press("Escape")
    wait_log(zen, addon, lambda ls: "share declined device -" in ls, "the decline line")
    zen.addon_call(addon, "setDebug", False)
    assert log(zen, addon) == []
    assert status(zen, addon)["debug"] is False


def test_log_never_holds_titles(zen, site, addon):
    secret = "http://docs.test/secret"
    site.serve(
        secret,
        f"<!doctype html><title>{SECRET}</title><h1>{SECRET}</h1>".encode(),
        "text/html; charset=utf-8",
    )
    try:
        zen.addon_call(addon, "setDebug", True)
        zen.visit(secret)
        assert zen.page_title(secret) == SECRET
        zen.request_share()
        p = wait_picker(zen)
        assert SECRET in p["text"], p
        zen.type_text("secret")
        zen.press("ArrowDown", "ArrowUp", "Escape")
        wait_gone(zen)
        lines = wait_log(
            zen, addon, lambda ls: "share declined device -" in ls, "the decline line"
        )
        assert any(x.startswith("prompt ") for x in lines), lines
        assert "docs.test" in hosts(lines), lines
        joined = "\n".join(lines)
        assert SECRET not in joined, lines
        assert "secret" not in joined.lower(), lines
        assert "data:" not in joined and "blob:" not in joined, lines
    finally:
        site.unserve(secret)


def test_other_space_hosts_wait_for_tab(zen, site, addon):
    """P12: hosts of current-space rows at once, another space's host only
    after Tab. The Perso tab comes from a second window on Perso (P14)."""
    zen.addon_call(addon, "setDebug", True)
    setup(zen, other_window=True)
    p = wait_picker(zen)
    assert "mail.test" not in p["text"], p
    lines = wait_log(
        zen, addon, lambda ls: any(x.startswith("prompt ") for x in ls), "a prompt line"
    )
    m = PROMPT_LINE.fullmatch(next(x for x in lines if x.startswith("prompt ")))
    assert m and m.group(2, 3) == ("4", "3"), lines
    seen = hosts(lines)
    for url in (DOCS, WIKI):
        assert url.split("/")[2] in seen, lines
    assert "mail.test" not in "\n".join(lines), lines
    zen.press("Tab")
    wait_picker(zen, lambda p: p["headers"], "the reveal")
    lines = wait_log(
        zen, addon, lambda ls: "mail.test" in hosts(ls), "the revealed host"
    )
    assert MAIL.split("/")[2] in hosts(lines)
    # A second Tab reveals nothing new and logs nothing new.
    count = len(lines)
    zen.press("Tab")
    time.sleep(0.3)
    assert len(log(zen, addon)) == count


def test_log_is_capped(zen, site, addon):
    """The log keeps the newest 2000 lines. A real prompt logs first; then
    PanelUpdated events for the share prompt on a tab without one each log
    `problem no-notification` until the prompt line falls off."""
    zen.addon_call(addon, "setDebug", True)
    setup(zen)
    wait_picker(zen)
    wait_log(
        zen, addon, lambda ls: any(x.startswith("prompt ") for x in ls), "a prompt line"
    )
    # A tab switch closes the picker without declining the prompt, so the
    # prompt is read again on each PanelUpdated, and fails: it is not open.
    zen.chrome("win.gBrowser.selectedTab = findTab(args[0]);", DOCS)
    wait_gone(zen)
    zen.chrome(
        """
        const panel = win.PopupNotifications.panel;
        for (let i = 0; i < args[0]; i++) {
          panel.dispatchEvent(new win.CustomEvent("PanelUpdated",
                                                  { detail: ["webRTC-shareDevices"] }));
        }
        """,
        LOG_LIMIT + 100,
    )
    lines = wait_log(
        zen,
        addon,
        lambda ls: not any(x.startswith("prompt ") for x in ls),
        "the prompt line to fall off",
        timeout=15,
    )
    assert len(lines) == LOG_LIMIT, len(lines)
    assert set(lines) == {"problem no-notification"}, set(lines)
    s = status(zen, addon)
    assert len(s["promptProblems"]) == 10, s
