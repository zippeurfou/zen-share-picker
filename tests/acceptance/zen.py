"""Drive a real Zen through Marionette for the acceptance tests.

Every `Zen` runs in a fresh temporary profile with its own Marionette port, so
it never touches, or attaches to, a Zen the user is already running. All
helpers run chrome-context scripts in the browser window that Marionette has
selected (the first window, unless a test switches windows).

Fixtures (registered through conftest.py):

- `zen`: a started `Zen` with the default prefs, closed after the test.
- `launch_zen`: a factory, `launch_zen(prefs=None) -> Zen`, for tests that
  need extra prefs at startup. Every Zen it starts is closed after the test.
- `addon`: when the repository root has a `manifest.json`, builds the add-on
  with `scripts/build.sh` (once per session), installs the XPI as a temporary
  add-on, waits until it reports `active`, and yields its id. Yields None and
  installs nothing otherwise.
"""

from __future__ import annotations

import configparser
import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import pytest
from marionette_driver.addons import Addons
from marionette_driver.keys import Keys
from marionette_driver.marionette import Marionette
from pages import Site

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG = REPO_ROOT / "src" / "lib" / "config.mjs"

DEFAULT_BINARY = {
    "darwin": "/Applications/Zen.app/Contents/MacOS/zen",
    "linux": "zen",
}

ADDON_ID = "zen-share-picker@zippeurfou.github.io"
NAMESPACE = "sharePicker"

# The two prefs the add-on needs.
ADDON_PREFS: dict[str, Any] = {
    "xpinstall.signatures.required": False,
    "extensions.experiments.enabled": True,
}

# Zen's prompt lists the screens and windows itself, as with the installer's
# --list-windows. The pref takes effect at startup only. Previews off, so
# listing never starts a capture.
LIST_WINDOWS_PREFS: dict[str, Any] = {
    "media.getdisplaymedia.screencapturekit.picker.enabled": False,
    "media.getdisplaymedia.previews.enabled": False,
}

# Quiet, deterministic startup in a throwaway profile.
BASE_PREFS: dict[str, Any] = {
    "marionette.port": 0,  # pick a free port, written to MarionetteActivePort
    "zen.welcome-screen.seen": True,
    "browser.shell.checkDefaultBrowser": False,
    "browser.startup.page": 0,
    "browser.startup.homepage": "about:blank",
    "startup.homepage_welcome_url": "about:blank",
    "browser.aboutwelcome.enabled": False,
    "browser.sessionstore.resume_from_crash": False,
    "app.update.disabledForTesting": True,
    "app.update.auto": False,
    "datareporting.policy.dataSubmissionEnabled": False,
    "datareporting.healthreport.uploadEnabled": False,
    "toolkit.telemetry.reportingpolicy.firstRun": False,
    "network.captive-portal-service.enabled": False,
    "network.connectivity-service.enabled": False,
    "network.trr.mode": 5,
    "privacy.userContext.enabled": True,
    "extensions.autoDisableScopes": 0,
    "extensions.enabledScopes": 5,
    "extensions.update.enabled": False,
    # Marionette's recommended prefs set this to 0 on the default branch
    # (RecommendedPreferences.sys.mjs:403-404); a user pref wins, so the
    # prompt keeps a real enable delay, as in a user's Zen.
    "security.notification_enable_delay": 500,
    # http://meet.test pages are secure contexts, so they can call
    # getDisplayMedia over the plain-HTTP test proxy.
    "dom.securecontext.allowlist": "meet.test",
}

# On macOS, Gecko keeps an install's downloaded update under this root, in a
# directory named after the install's path without ".app"
# (/Applications/Zen.app -> Applications/Zen). Any Zen started from that
# install, a test Zen included, applies an update staged there before it
# opens a window, and then relaunches outside the harness.
UPDATE_ROOT = Path.home() / "Library" / "Caches" / "Mozilla" / "updates"
STAGED = ("pending", "applied")
STAGED_MESSAGE = "a Zen update is staged; restart your Zen first"
PLATFORM = sys.platform

STARTUP_TIMEOUT = 60  # seconds, Zen startup plus Marionette handshake
SCRIPT_TIMEOUT = 30  # seconds, one chrome script

# How far the picker's centre may be from the window's, in CSS pixels (P37).
# Measured over 3 headless and 3 headful runs of both centring tests: at most
# 1.5e-5 px off. The measured maximum rounded up, plus 1.
CENTER_TOL_PX = 2

# The share prompt's secondary button labels, by whether the site has a
# camera or microphone allowed (en-US, as the test Zen runs).
SECONDARY_LABEL = {True: "Not now", False: "Block"}

# WebDriver key values for the key names the tests use.
KEY_NAMES: dict[str, str] = {
    "Escape": Keys.ESCAPE,
    "Enter": Keys.ENTER,
    "Tab": Keys.TAB,
    "Backspace": Keys.BACK_SPACE,
    "Shift": Keys.SHIFT,
    "ArrowDown": Keys.ARROW_DOWN,
    "ArrowUp": Keys.ARROW_UP,
    "ArrowLeft": Keys.ARROW_LEFT,
    "ArrowRight": Keys.ARROW_RIGHT,
    "Home": Keys.HOME,
    "End": Keys.END,
    "F6": Keys.F6,
}


# The `ui.key.chromeAccess` bits and the WebDriver keys that hold them.
ACCESS_MODIFIERS = (
    (1, Keys.SHIFT),
    (2, Keys.CONTROL),
    (4, Keys.ALT),
    (8, Keys.META),
)


class ZenScriptError(RuntimeError):
    """A chrome-context script threw. The message carries the JS stack."""


def zen_binary() -> str:
    env = os.environ.get("ZEN_BINARY")
    if env:
        return env
    default = DEFAULT_BINARY.get(sys.platform)
    if default is None:
        raise RuntimeError(f"set ZEN_BINARY: no default Zen path on {sys.platform}")
    return default


def app_bundle(binary: str) -> Path | None:
    """The `.app` bundle that holds `binary`, or None."""
    for parent in Path(binary).parents:
        if parent.suffix == ".app":
            return parent
    return None


def update_status_file(binary: str, root: Path | None = None) -> Path | None:
    """The update status file of the macOS install that holds `binary`, under
    `root` (UPDATE_ROOT by default); None outside an `.app` bundle."""
    app = app_bundle(binary)
    if app is None:
        return None
    root = UPDATE_ROOT if root is None else root
    install = app.with_suffix("").relative_to(app.anchor)
    return root / install / "updates" / "0" / "update.status"


def staged_update(
    binary: str, root: Path | None = None, platform: str | None = None
) -> bool:
    """Whether the install that holds `binary` has an update staged, which
    the next launch from it would apply. Only macOS is checked."""
    if (PLATFORM if platform is None else platform) != "darwin":
        return False
    status = update_status_file(binary, root)
    if status is None:
        return False
    try:
        text = status.read_text(errors="replace").strip()
    except OSError:
        return False
    return text.startswith(STAGED)


def zen_version(binary: str) -> str | None:
    """`Version` from the install's application.ini, or None if unreadable."""
    app = app_bundle(binary)
    if app is not None:
        ini = app / "Contents" / "Resources" / "application.ini"
    else:
        found = shutil.which(binary) or binary
        ini = Path(found).resolve().parent / "application.ini"
    parser = configparser.ConfigParser(interpolation=None)
    try:
        if not parser.read(ini):
            return None
    except configparser.Error:
        return None
    return parser.get("App", "Version", fallback=None)


# Characters a POSIX extended regular expression treats as special.
_ERE_SPECIAL = re.compile(r"([.\[\](){}*+?|^$\\])")


def _profile_pids(profile: Path) -> set[int]:
    """Every process whose command line holds `profile`, exactly: the path
    as given or resolved, followed by a space, a slash or the end."""
    paths = sorted({str(profile), os.path.realpath(profile)})
    try:
        out = subprocess.run(
            [
                "pgrep",
                "-f",
                "("
                + "|".join(_ERE_SPECIAL.sub(r"\\\1", p) for p in paths)
                + ")($| |/)",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        pids = {int(p) for p in out.stdout.split()}
    except FileNotFoundError:
        # No pgrep (a minimal Linux image): the same match over /proc.
        pids = set()
        for cmdline in Path("/proc").glob("[0-9]*/cmdline"):
            try:
                args = cmdline.read_bytes().split(b"\0")
            except OSError:
                continue
            text = b" ".join(args).decode(errors="replace") + " "
            if any(re.search(re.escape(p) + "( |/)", text) for p in paths):
                pids.add(int(cmdline.parent.name))
    pids.discard(os.getpid())
    return pids


def kill_profile_processes(profile: Path, timeout: float = 5.0) -> set[int]:
    """Kill every process running on `profile`, for example a Zen that an
    update relaunched outside the harness, and wait until none is left."""
    found = _profile_pids(profile)
    deadline = time.monotonic() + timeout
    left = found
    while left:
        for pid in left:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(pid, signal.SIGKILL)
        if time.monotonic() > deadline:
            break
        time.sleep(0.1)
        left = _profile_pids(profile)
    return found


def key_input() -> str:
    """`KEY_INPUT` from `src/lib/config.mjs`: how `press` sends keys."""
    m = re.search(
        r'^export const KEY_INPUT = "(\w+)";', CONFIG.read_text(), re.MULTILINE
    )
    if not m:
        raise RuntimeError(f"no KEY_INPUT in {CONFIG}")
    return m.group(1)


def _pref_line(name: str, value: Any) -> str:
    return f"user_pref({json.dumps(name)}, {json.dumps(value)});\n"


# Wraps an async function body. `win` is the chrome window Marionette has
# selected. The result is JSON: {"ok": value} or {"error": "message + stack"}.
_PRELUDE = """
const __resolve = arguments[arguments.length - 1];
const args = Array.from(arguments).slice(0, -1);
const win = window;
(async () => {
/*BODY*/
})().then(
  value => __resolve({ ok: value === undefined ? null : value }),
  e => __resolve({ error: String(e) + "\\n" + (e && e.stack || "") })
);
"""

# Helpers available to every script:
# - waitFor(fn, what, ms) polls until fn() is truthy;
# - tabsOf(w) every tab of window w, in every space;
# - findTab(url) the first tab on `url`, this window first;
# - shareNotification(browser) the open webRTC-shareDevices notification.
_HELPERS = """
async function waitFor(fn, what, ms = 15000) {
  const end = Date.now() + ms;
  for (;;) {
    const v = await fn();
    if (v) return v;
    if (Date.now() > end) throw new Error("timed out waiting for " + what);
    await new Promise(r => win.setTimeout(r, 50));
  }
}
function browserWindows() {
  const all = Array.from(Services.wm.getEnumerator("navigator:browser"));
  return [win, ...all.filter(w => w != win)];
}
function tabsOf(w) {
  // gBrowser.tabs holds only the active space's tabs in Zen.
  return Array.from(w.gZenWorkspaces.allStoredTabs);
}
function findTab(url) {
  const spec = Services.io.newURI(url).spec;
  for (const w of browserWindows()) {
    const tab = tabsOf(w).find(t => t.linkedBrowser?.currentURI?.spec == spec);
    if (tab) return tab;
  }
  throw new Error("no tab on " + url);
}
function shareNotification(browser = win.gBrowser.selectedBrowser) {
  return win.PopupNotifications.getNotification("webRTC-shareDevices", browser);
}
"""


# Waits until a browser window has its spaces ready.
_WINDOW_READY = """
await waitFor(() => win.gZenWorkspaces && win.gBrowser, "browser window");
await win.delayedStartupPromise;
await win.gZenWorkspaces.promiseInitialized;
await waitFor(() => win.gZenWorkspaces.getActiveWorkspaceFromCache(), "an active space");
"""


# See Zen.os_windows(). JXA: argv[0] is the process id.
_OS_WINDOWS = """
ObjC.import("CoreGraphics");
function run(argv) {
  const pid = parseInt(argv[0]);
  const ref = $.CGWindowListCopyWindowInfo($.kCGWindowListOptionOnScreenOnly, 0);
  const all = ObjC.deepUnwrap(ObjC.castRefToObject(ref));
  return JSON.stringify(all.filter(w => w.kCGWindowOwnerPID === pid).map(w => ({
    layer: w.kCGWindowLayer,
    alpha: w.kCGWindowAlpha,
    bounds: [w.kCGWindowBounds.X, w.kCGWindowBounds.Y,
             w.kCGWindowBounds.Width, w.kCGWindowBounds.Height],
  })));
}
"""


# See Zen.settle().
_SETTLE = """
const p = win.PopupNotifications.panel;
const flush = win.document.createElementNS("http://www.w3.org/1999/xhtml", "style");
win.document.documentElement.append(flush);
let last = ChromeUtils.now();
const moved = () => { last = ChromeUtils.now(); };
const where = () => {
  const r = p.getOuterScreenRect();
  return [win.screenX, win.screenY, win.outerWidth, win.outerHeight,
          r.left, r.top, r.width, r.height].join(",");
};
let seen = where();
p.addEventListener("popuppositioned", moved);
win.addEventListener("activate", moved, true);
try {
  await waitFor(() => {
    const now = where();
    if (now != seen) {
      seen = now;
      moved();
    }
    return ChromeUtils.now() - last >= 1000;
  }, "the window and the panel to settle", 10000);
} finally {
  p.removeEventListener("popuppositioned", moved);
  win.removeEventListener("activate", moved, true);
}
"""


class Zen:
    """One running Zen in a fresh temporary profile."""

    def __init__(
        self,
        site: Site | None = None,
        prefs: dict[str, Any] | None = None,
        *,
        binary: str | None = None,
        headless: bool | None = None,
    ) -> None:
        self.binary = binary or zen_binary()
        self.headless = (
            os.environ.get("HEADLESS") == "1" if headless is None else headless
        )
        self.prefs: dict[str, Any] = {**BASE_PREFS, **ADDON_PREFS}
        if site is not None:
            self.prefs.update(site.prefs)
        self.prefs.update(prefs or {})
        self.profile: Path | None = None
        self.process: subprocess.Popen[bytes] | None = None
        self.client: Marionette | None = None
        self._log = None
        self._default_space_claimed = False

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> Zen:
        if staged_update(self.binary):
            pytest.exit(STAGED_MESSAGE, returncode=3)
        if self.profile is None:
            self.profile = Path(tempfile.mkdtemp(prefix="zen-share-picker-profile-"))
            with open(self.profile / "user.js", "w") as f:
                f.writelines(
                    _pref_line(name, value) for name, value in self.prefs.items()
                )
        (self.profile / "MarionetteActivePort").unlink(missing_ok=True)

        args = [
            self.binary,
            "-marionette",
            "-no-remote",
            "-new-instance",
            "-profile",
            str(self.profile),
        ]
        if self.headless:
            args.append("-headless")
        env = {
            **os.environ,
            # Lets Marionette run chrome-context scripts. Zen 1.24.2b reads
            # this env var (RemoteAgent.sys.mjs:28,60); it has no CLI flag.
            "MOZ_REMOTE_ALLOW_SYSTEM_ACCESS": "1",
            "MOZ_CRASHREPORTER_DISABLE": "1",
            "MOZ_CRASHREPORTER_SHUTDOWN": "1",
        }
        if self.headless:
            env["MOZ_HEADLESS"] = "1"
        self._log = open(self.profile / "zen-stdout.log", "ab")  # noqa: SIM115 (lives as long as Zen)
        self.process = subprocess.Popen(
            args,
            env=env,
            stdout=self._log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            port = self._wait_for_port()
            self.client = Marionette(host="127.0.0.1", port=port)
            self.client.start_session(timeout=STARTUP_TIMEOUT)
            self.client.set_context(Marionette.CONTEXT_CHROME)
            self.client.timeout.script = SCRIPT_TIMEOUT
            self.chrome(_WINDOW_READY, timeout=STARTUP_TIMEOUT)
            # A real user has clicked or typed by now.
            self.user_input()
        except BaseException as e:
            log = self.profile / "zen-stdout.log"
            if log.exists():
                tail = log.read_text(errors="replace").splitlines()[-30:]
                e.add_note("Zen output (last 30 lines):\n" + "\n".join(tail))
            self.close()
            raise
        return self

    def _wait_for_port(self) -> int:
        assert self.profile is not None and self.process is not None
        port_file = self.profile / "MarionetteActivePort"
        deadline = time.monotonic() + STARTUP_TIMEOUT
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(
                    f"Zen exited with {self.process.returncode} during startup"
                )
            if port_file.exists():
                text = port_file.read_text().strip()
                if text:
                    return int(text)
            time.sleep(0.1)
        raise TimeoutError(f"Marionette did not start within {STARTUP_TIMEOUT}s")

    def close(self) -> None:
        """Quit Zen, kill anything left of it, and delete the profile.

        Anything left includes every process whose command line holds the
        profile's exact path: a Zen relaunched outside the harness, as after
        applying an update, is in no process group the harness knows."""
        if self.client is not None:
            # Best effort: the process is killed below whatever happens here.
            with contextlib.suppress(Exception):
                self.client._send_message("Marionette:Quit", {"flags": ["eForceQuit"]})
            with contextlib.suppress(Exception):
                self.client.delete_session(send_request=False)
            self.client = None
        if self.process is not None:
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                pass
            # Zen's child processes share its process group.
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
            self.process = None
        if self._log is not None:
            self._log.close()
            self._log = None
        if self.profile is not None:
            kill_profile_processes(self.profile)
            shutil.rmtree(self.profile, ignore_errors=True)
            self.profile = None

    # -- generic chrome access --------------------------------------------

    def chrome(self, body: str, *args: Any, timeout: float = SCRIPT_TIMEOUT) -> Any:
        """Run `body` as an async function in the selected browser window.

        Inside `body`: `win` is the chrome window, `args` the positional
        arguments, and the helpers `waitFor(fn, what, ms)`, `tabsOf(w)`,
        `findTab(url)` and `shareNotification(browser)` are in scope.
        `return` sends a JSON-serializable value back. A throw raises
        `ZenScriptError` with the JS stack.
        """
        assert self.client is not None, "Zen is not started"
        script = _PRELUDE.replace("/*BODY*/", _HELPERS + body)
        result = self.client.execute_async_script(
            script,
            script_args=list(args),
            script_timeout=int((timeout + 5) * 1000),
        )
        if result is None or "error" in result:
            raise ZenScriptError((result or {}).get("error", "script returned nothing"))
        return result["ok"]

    def content(self, js: str, *args: Any) -> Any:
        """Run `js` as a function body in the page of the selected tab
        (Marionette's content context) and return its value."""
        assert self.client is not None
        tab = self.chrome(
            """
            const { NavigableManager } = ChromeUtils.importESModule(
              "chrome://remote/content/shared/NavigableManager.sys.mjs");
            return NavigableManager.getIdForBrowser(win.gBrowser.selectedBrowser);
            """
        )
        chrome_handle = self.window
        self.client.set_context(Marionette.CONTEXT_CONTENT)
        try:
            self.client.switch_to_window(tab, focus=False)
            return self.client.execute_script(js, script_args=list(args))
        finally:
            self.client.set_context(Marionette.CONTEXT_CHROME)
            self.client.switch_to_window(chrome_handle, focus=False)

    # -- user input ---------------------------------------------------------

    def user_input(self) -> None:
        """Click the middle of the selected window, as a user clicking the
        page, and check that Firefox took it as a user input.

        The click goes through WebDriver actions: Marionette synthesizes it
        inside this Zen, so it never reaches the screen or another
        application.
        """
        width, height = self.chrome("return [win.innerWidth, win.innerHeight];")
        self._click(width // 2, height // 2)
        since = self.chrome("return win.windowUtils.millisSinceLastUserInput;")
        if not 0 <= since < 5000:
            raise RuntimeError(
                f"Firefox did not record the click as a user input: {since}"
            )

    def _click(self, x: int, y: int) -> None:
        assert self.client is not None
        mouse = self.client.actions.sequence(
            "pointer", "mouse", {"pointerType": "mouse"}
        )
        mouse.pointer_move(int(x), int(y)).pointer_down().pointer_up().perform()
        self.client.actions.release()

    def press(self, *keys: str) -> None:
        """Press each key in turn into the focused chrome element.

        A key is one character or a name from `KEY_NAMES` ("Escape",
        "Enter", "ArrowDown"...). With `KEY_INPUT = "webdriver"` the keys are
        WebDriver key actions, which Marionette synthesizes as trusted key
        events inside this Zen. With `"synthetic"` they are untrusted
        `KeyboardEvent`s dispatched on the focused element; a printable key
        then also inserts its character into a focused text field.
        """
        values = [KEY_NAMES.get(k, k) for k in keys]
        for k, v in zip(keys, values, strict=True):
            if len(v) != 1:
                raise ValueError(f"not a single key: {k!r}")
        if key_input() == "synthetic":
            self.chrome(
                """
                for (const key of args[0]) {
                  const target = Services.focus.focusedElement ?? win.document.activeElement;
                  const init = { key, bubbles: true, cancelable: true, composed: true };
                  const go = target.dispatchEvent(new win.KeyboardEvent("keydown", init));
                  if (go && key.length == 1 && "value" in target) {
                    target.value += key;
                    target.dispatchEvent(new win.Event("input", { bubbles: true }));
                  }
                  target.dispatchEvent(new win.KeyboardEvent("keyup", init));
                }
                """,
                list(keys),
            )
            return
        assert self.client is not None
        seq = self.client.actions.sequence("key", "keyboard")
        for v in values:
            seq.key_down(v).key_up(v)
        seq.perform()
        self.client.actions.release()

    def press_access_chord(self, key: str) -> None:
        """Hold the chrome access-key modifiers (`ui.key.chromeAccess`: 1
        Shift, 2 Ctrl, 4 Alt, 8 Meta; Ctrl on macOS, Alt elsewhere) and
        press `key`, as WebDriver key actions."""
        assert self.client is not None
        mask = self.chrome(
            'return Services.prefs.getIntPref("ui.key.chromeAccess", -1);'
        )
        mods = [k for bit, k in ACCESS_MODIFIERS if mask > 0 and mask & bit]
        if not mods:
            raise RuntimeError(f"no chrome access-key modifier: {mask}")
        seq = self.client.actions.sequence("key", "keyboard")
        for m in mods:
            seq.key_down(m)
        seq.key_down(key).key_up(key)
        for m in reversed(mods):
            seq.key_up(m)
        seq.perform()
        self.client.actions.release()

    def chord(self, key: str) -> None:
        """Press Accel+`key` as WebDriver key actions: Meta on macOS,
        Control elsewhere (`Services.appinfo.OS`)."""
        assert self.client is not None
        darwin = self.chrome('return Services.appinfo.OS == "Darwin";')
        mod = Keys.META if darwin else Keys.CONTROL
        seq = self.client.actions.sequence("key", "keyboard")
        seq.key_down(mod).key_down(key).key_up(key).key_up(mod).perform()
        self.client.actions.release()

    def type_text(self, text: str) -> None:
        """Type `text` into the focused chrome element, one key per character."""
        self.press(*text)

    # -- add-ons ------------------------------------------------------------

    def install_addon(self, path: str, *, temp: bool = True) -> str:
        """Install the add-on at `path` (a directory or an .xpi), temporarily
        unless `temp` is False, and return its id."""
        assert self.client is not None
        return Addons(self.client).install(str(Path(path).resolve()), temp=temp)

    def addon_call(self, addon_id: str, method: str, *args: Any) -> Any:
        """Call `browser.sharePicker.<method>(*args)` of the installed add-on
        from chrome, through the same API object its background page uses,
        and return the result."""
        return self.chrome(
            """
            const [id, method, callArgs, ns] = args;
            const { ExtensionParent } = ChromeUtils.importESModule(
              "resource://gre/modules/ExtensionParent.sys.mjs");
            const extension = ExtensionParent.GlobalManager.getExtension(id);
            if (!extension) throw new Error("add-on not running: " + id);
            const api = extension.apiManager.getAPI(ns, extension, "addon_parent");
            if (!api) throw new Error(`no ${ns} experiment in ` + id);
            const value = await api.getAPI({ extension })[ns][method](...callArgs);
            return value === undefined ? null : value;
            """,
            addon_id,
            method,
            list(args),
            NAMESPACE,
        )

    def wait_addon_active(self, addon_id: str) -> dict:
        """Wait until the add-on has started and return its status. Raises if
        the state is not `active`. `getStatus` resolves once start-up is
        over, so one call is enough."""
        status = self.addon_call(addon_id, "getStatus")
        if status["state"] != "active":
            raise RuntimeError(f"add-on is not active: {status}")
        return status

    def glue(self, name: str) -> str:
        """The `resource://zen-share-picker-<v>/src/...` URL of module `name`
        (a path under `src/`, for example `"glue/prompt.sys.mjs"`), from the
        installed add-on's version, for chrome scripts that import glue
        directly. The add-on must be installed and started."""
        version = self.chrome(
            """
            const { AddonManager } = ChromeUtils.importESModule(
              "resource://gre/modules/AddonManager.sys.mjs");
            const addon = await AddonManager.getAddonByID(args[0]);
            if (!addon) throw new Error("add-on not installed: " + args[0]);
            return addon.version;
            """,
            ADDON_ID,
        )
        host = "zen-share-picker-" + re.sub(r"[^A-Za-z0-9]", "-", version)
        return f"resource://{host}/src/{name}"

    @contextlib.contextmanager
    def options_page(self, addon_id: str):
        """Open the add-on's options page in a new tab and yield an
        `ExtensionPage` that runs scripts in it (Marionette's content
        context). The tab is closed and the chrome context restored after.
        Leave the `with` block before calling the other helpers: they run
        chrome scripts, which need the chrome context."""
        assert self.client is not None
        chrome_handle = self.window
        before = set(self.client.window_handles)
        self.chrome(
            """
            const policy = WebExtensionPolicy.getByID(args[0]);
            const tab = win.gBrowser.addTab(
              `moz-extension://${policy.mozExtensionHostname}/options/options.html`,
              { triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal() });
            win.gBrowser.selectedTab = tab;
            win.optionsTab = tab;
            """,
            addon_id,
        )
        deadline = time.monotonic() + SCRIPT_TIMEOUT
        while not (new := set(self.client.window_handles) - before):
            if time.monotonic() > deadline:
                self.chrome("win.gBrowser.removeTab(win.optionsTab);")
                raise TimeoutError("the options tab did not open")
            time.sleep(0.1)
        tab = new.pop()
        try:
            self.client.set_context(Marionette.CONTEXT_CONTENT)
            self.client.switch_to_window(tab)
            yield ExtensionPage(self.client)
        finally:
            self.client.set_context(Marionette.CONTEXT_CHROME)
            self.client.switch_to_window(chrome_handle)
            self.chrome("win.gBrowser.removeTab(win.optionsTab);")

    # -- containers and spaces ----------------------------------------------

    def container_id(self, name: str) -> int:
        """The userContextId of the container labelled `name`."""
        ucid = self.chrome(
            """
            const { ContextualIdentityService } = ChromeUtils.importESModule(
              "moz-src:///toolkit/components/contextualidentity/ContextualIdentityService.sys.mjs");
            const hit = ContextualIdentityService.getPublicIdentities().find(
              i => ContextualIdentityService.getUserContextLabel(i.userContextId) == args[0]);
            return hit ? hit.userContextId : null;
            """,
            name,
        )
        if ucid is None:
            raise LookupError(f"no container named {name!r}")
        return ucid

    def make_space(self, name: str, container: str | None) -> str:
        """Create a space called `name` and return its uuid.

        `container` is a container label, created if missing, or None for a
        space without a container (container 0). The active space does not
        change. A fresh profile already has one space without a container:
        the first `make_space(name, None)` renames and reuses it rather than
        leave two spaces without a container. Later calls with None create a
        new space.
        """
        claim_default = container is None and not self._default_space_claimed
        uuid = self.chrome(
            """
            const [name, containerName, claimDefault] = args;
            const { ContextualIdentityService } = ChromeUtils.importESModule(
              "moz-src:///toolkit/components/contextualidentity/ContextualIdentityService.sys.mjs");
            let ucid = 0;
            if (containerName !== null) {
              let hit = ContextualIdentityService.getPublicIdentities().find(
                i => ContextualIdentityService.getUserContextLabel(i.userContextId)
                     == containerName);
              hit ??= ContextualIdentityService.create(containerName, "fingerprint", "blue");
              ucid = hit.userContextId;
            }
            const zw = win.gZenWorkspaces;
            const noContainer = s => typeof s.containerTabId != "number" || s.containerTabId == 0;
            if (claimDefault) {
              const spaces = zw.getWorkspaces().filter(noContainer);
              if (spaces.length > 1) {
                throw new Error(`${spaces.length} spaces already have no container`);
              }
              if (spaces.length == 1) {
                zw.saveWorkspace({ ...spaces[0], name });
                await waitFor(() => zw.getWorkspaceFromId(spaces[0].uuid)?.name == name,
                              "the default space to be renamed");
                return spaces[0].uuid;
              }
            }
            const previous = zw.getActiveWorkspaceFromCache().uuid;
            const space = await zw.createAndSaveWorkspace(name, undefined, false, ucid);
            if (!space) throw new Error("createAndSaveWorkspace returned nothing");
            if (space.name !== name || space.containerTabId !== ucid) {
              throw new Error(`space came out as ${space.name}/${space.containerTabId}`);
            }
            await zw.changeWorkspaceWithID(previous);
            await waitFor(() => zw.getActiveWorkspaceFromCache().uuid == previous,
                          "switch back to the previous space");
            return space.uuid;
            """,
            name,
            container,
            claim_default,
        )
        if claim_default:
            self._default_space_claimed = True
        return uuid

    def switch_space(self, uuid: str) -> None:
        """Make space `uuid` the active space of the window."""
        self.chrome(
            """
            const zw = win.gZenWorkspaces;
            await zw.changeWorkspaceWithID(args[0]);
            await waitFor(() => zw.getActiveWorkspaceFromCache().uuid == args[0],
                          "space " + args[0]);
            """,
            uuid,
        )

    def active_space(self) -> dict[str, Any]:
        """`{uuid, name, container}` of the window's active space."""
        return self.chrome(
            """
            const zw = win.gZenWorkspaces;
            const s = zw.getActiveWorkspaceFromCache();
            return { uuid: s.uuid, name: s.name, container: zw.getCurrentSpaceContainerId() };
            """
        )

    # -- windows --------------------------------------------------------------

    def open_window(self, *, private: bool = False, synced: bool = True) -> str:
        """Open a new browser window, select it, and return its handle.

        `private` opens a private window. `synced=False` opens an unsynced
        window, as Zen's "New Unsynced Window" command does. Marionette
        selects the window without focusing it.
        """
        return self.wait_new_window(
            lambda: self.chrome(
                "win.OpenBrowserWindow({ private: args[0], zenSyncedWindow: args[1] });",
                private,
                synced,
            )
        )

    def wait_new_window(self, opener, *, ready: str = _WINDOW_READY) -> str:
        """Call `opener()`, wait for the chrome window it opens, select it,
        run the `ready` script in it, and return its handle."""
        assert self.client is not None
        before = set(self.client.chrome_window_handles)
        opener()
        deadline = time.monotonic() + STARTUP_TIMEOUT
        while True:
            new = set(self.client.chrome_window_handles) - before
            if new:
                break
            if time.monotonic() > deadline:
                raise TimeoutError("the new browser window did not open")
            time.sleep(0.1)
        handle = new.pop()
        self.use_window(handle)
        self.chrome(ready, timeout=STARTUP_TIMEOUT)
        return handle

    def use_window(self, handle: str, *, focus: bool = False) -> None:
        """Direct every later helper at window `handle`. By default the window
        is not focused, so which window is the most recent does not change."""
        assert self.client is not None
        self.client.switch_to_window(handle, focus=focus)

    @property
    def window(self) -> str:
        """The handle of the window the helpers act on."""
        assert self.client is not None
        return self.client.current_chrome_window_handle

    # -- browsing -----------------------------------------------------------

    def visit(self, url: str, container: int | None = None) -> None:
        """Open `url` in a new, selected tab of the active space and wait
        until it has loaded and has its title.

        `container` is a userContextId; None means the active space's
        container, which is what Zen gives a new tab.
        """
        self.chrome(
            """
            const url = Services.io.newURI(args[0]).spec;
            const ucid = args[1] ?? win.gZenWorkspaces.getCurrentSpaceContainerId();
            const tab = win.gBrowser.addTab(url, {
              triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal(),
              userContextId: ucid,
            });
            win.gBrowser.selectedTab = tab;
            const b = tab.linkedBrowser;
            await waitFor(() => b.currentURI.spec == url && !b.webProgress?.isLoadingDocument &&
                                b.contentTitle, "the tab to load " + url);
            const got = Number(tab.getAttribute("usercontextid") || 0);
            if (got != ucid) throw new Error(`tab opened in container ${got}, not ${ucid}`);
            """,
            url,
            container,
        )

    def make_essential(self, url: str, container: str) -> None:
        """Open `url` in container `container` (a label) and make it an
        Essential, as a user does from a space with that container. The
        active space is the same after."""
        self.chrome(
            """
            const [url, containerName] = args;
            const { ContextualIdentityService } = ChromeUtils.importESModule(
              "moz-src:///toolkit/components/contextualidentity/ContextualIdentityService.sys.mjs");
            const hit = ContextualIdentityService.getPublicIdentities().find(
              i => ContextualIdentityService.getUserContextLabel(i.userContextId) == containerName);
            if (!hit) throw new Error("no container named " + containerName);
            const ucid = hit.userContextId;
            const zw = win.gZenWorkspaces;
            const previous = zw.getActiveWorkspaceFromCache().uuid;
            const home = zw.getWorkspaces().find(s => (s.containerTabId || 0) == ucid);
            if (!home) throw new Error("no space with container " + containerName);
            if (home.uuid != previous) {
              await zw.changeWorkspaceWithID(home.uuid);
              await waitFor(() => zw.getActiveWorkspaceFromCache().uuid == home.uuid,
                            "space " + home.uuid);
            }
            const spec = Services.io.newURI(url).spec;
            const tab = win.gBrowser.addTab(spec, {
              triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal(),
              userContextId: ucid,
            });
            win.gBrowser.selectedTab = tab;
            await waitFor(() => tab.linkedBrowser.currentURI.spec == spec &&
                                tab.linkedBrowser.contentTitle, "the tab to load " + url);
            if (!win.gZenPinnedTabManager.addToEssentials(tab)) {
              throw new Error("Zen refused to make the tab an Essential");
            }
            await waitFor(() => tab.hasAttribute("zen-essential"), "the Essential");
            if (home.uuid != previous) {
              await zw.changeWorkspaceWithID(previous);
              await waitFor(() => zw.getActiveWorkspaceFromCache().uuid == previous,
                            "space " + previous);
            }
            """,
            url,
            container,
        )

    def browser_id(self, url: str) -> str:
        """`String(browserId)` of the first tab on `url`, this window first."""
        return self.chrome(
            "return String(findTab(args[0]).linkedBrowser.browserId);", url
        )

    def page_title(self, url: str) -> str:
        """The page title of the first tab on `url`, this window first."""
        return self.chrome("return findTab(args[0]).linkedBrowser.contentTitle;", url)

    # -- the stock share prompt ---------------------------------------------

    def request_share(self, path: str = "share") -> None:
        """Open `http://meet.test/<path>`, click the page centre with
        WebDriver pointer actions (a trusted click, so the page has user
        activation), and wait until Zen's share prompt is open for it.
        Like a user's click, it first makes the window the active one: Zen
        shows the prompt's panel only in the active window."""
        self.visit(f"http://meet.test/{path}")
        x, y = self.chrome(
            """
            if (Services.focus.activeWindow != win) {
              win.focus();
              await waitFor(() => Services.focus.activeWindow == win,
                            "the window to become active", 10000);
            }
            // Zen's first-run sweep animation covers the page for 0.35 s and
            // takes clicks meanwhile. It never ends while the screen is
            // locked (no animation frames), so say so rather than time out
            // on the prompt.
            await waitFor(() => !win.document.getElementById("zen-update-animation-border"),
                          "Zen's update animation to end (is the screen locked?)", 5000);
            const r = win.gBrowser.selectedBrowser.getBoundingClientRect();
            return [r.left + r.width / 2, r.top + r.height / 2];
            """
        )
        self._click(x, y)
        self.chrome(
            """
            await waitFor(() => shareNotification() &&
                                win.PopupNotifications.panel.state == "open",
                          "the share prompt to open");
            """
        )

    def stock_prompt_open(self) -> bool:
        """Whether the share prompt of the selected tab is open."""
        return self.chrome(
            "return !!shareNotification() && win.PopupNotifications.panel.state == 'open';"
        )

    def stock_entries(self) -> list[dict[str, Any]]:
        """The share prompt's dropdown items as `{label, mediaSource,
        deviceId}`, in order, without the separator. The placeholder has
        `deviceId` and `mediaSource` None."""
        return self.chrome(
            """
            const popup = win.document.getElementById("webRTC-selectWindow-menupopup");
            return Array.from(popup.children)
              .filter(i => i.localName == "menuitem")
              .map(i => ({
                label: i.getAttribute("label"),
                mediaSource: i.mediaSource ?? null,
                deviceId: i.deviceId == undefined ? null : String(i.deviceId),
              }));
            """
        )

    def stock_counts(self) -> dict[str, int]:
        """How many of the prompt's dropdown items have each `mediaSource`;
        the "-1" item counts as `"placeholder"`. No labels."""
        return self.chrome(
            """
            const popup = win.document.getElementById("webRTC-selectWindow-menupopup");
            const counts = {};
            for (const i of popup.children) {
              if (i.localName != "menuitem") continue;
              const key = i.value == "-1" ? "placeholder" : String(i.mediaSource);
              counts[key] = (counts[key] ?? 0) + 1;
            }
            return counts;
            """
        )

    def stock_ids(self, source: str) -> list[str]:
        """The `deviceId`s of the prompt's items whose `mediaSource` is
        `source`, in order. No labels."""
        return self.chrome(
            """
            const popup = win.document.getElementById("webRTC-selectWindow-menupopup");
            return Array.from(popup.children)
              .filter(i => i.localName == "menuitem" && i.mediaSource == args[0])
              .map(i => String(i.deviceId));
            """,
            source,
        )

    def zen_window_ids(self) -> list[str]:
        """`String(windowUtils.webrtcRawDeviceId)` of every top-level Zen
        window, as the prompt's window entries carry them. Raises
        `ZenScriptError` if any read throws."""
        return self.chrome(
            """
            return Array.from(Services.wm.getEnumerator(null),
                              w => String(w.windowUtils.webrtcRawDeviceId));
            """
        )

    def picker_keys(self) -> dict[str, Any] | None:
        """The open picker as `{keys, groups, selected, view, count}`, or
        None when none is open. Never any text: a test that lists real
        windows reads the picker only through this, so no window title
        reaches its output."""
        return self.chrome(
            """
            const root = win.document.getElementById("zen-share-picker");
            if (!root) return null;
            const rows = Array.from(root.querySelectorAll(".zsp-row"));
            const sel = rows.find(r => r.getAttribute("aria-selected") == "true");
            return {
              keys: rows.map(r => r.dataset.key),
              groups: rows.map(r => r.dataset.group),
              selected: sel ? sel.dataset.key : null,
              view: root.dataset.view ?? null,
              count: rows.length,
            };
            """
        )

    def live_tracks(self) -> int:
        """Live video tracks across every `<webrtc-preview>` in the selected
        window, the picker's and Zen's own. Reads track states only: no
        frame is copied."""
        return self.chrome(
            """
            return Array.from(win.document.querySelectorAll("webrtc-preview"))
              .flatMap(el => el.videoEl?.srcObject?.getVideoTracks() ?? [])
              .filter(t => t.readyState == "live").length;
            """
        )

    def click_row(self, key: str) -> None:
        """A WebDriver click on the centre of the picker's row whose
        `data-key` is `key`. The row is found by key alone, so a test reaches
        a real window without arrowing across the others. Raises
        `ZenScriptError`, before any click, when the element at that point is
        not in the row."""
        x, y = self.chrome(
            """
            const root = win.document.getElementById("zen-share-picker");
            const row = Array.from(root?.querySelectorAll(".zsp-row") ?? [])
              .find(r => r.dataset.key == args[0]);
            if (!row) throw new Error("no picker row with that key");
            row.scrollIntoView({ block: "nearest" });
            const r = row.getBoundingClientRect();
            const x = r.left + r.width / 2;
            const y = r.top + r.height / 2;
            const hit = win.document.elementFromPoint(x, y);
            if (!hit || !row.contains(hit)) {
              throw new Error("the click point is not on that row");
            }
            return [x, y];
            """,
            key,
        )
        self._click(x, y)

    def stock_selected(self) -> str | None:
        """The `deviceId` of the prompt's selected item; None for the
        placeholder or no selection."""
        return self.chrome(
            """
            const item = win.document.getElementById("webRTC-selectWindow-menulist").selectedItem;
            return item?.deviceId == undefined ? null : String(item.deviceId);
            """
        )

    def panel_rect(self) -> list[float]:
        """`[left, top, right, bottom]` of Zen's notification panel, in the
        selected window's coordinates (the ones pointer actions use)."""
        return self.chrome(
            """
            const r = win.PopupNotifications.panel.getOuterScreenRect();
            const x = win.mozInnerScreenX;
            const y = win.mozInnerScreenY;
            return [r.left - x, r.top - y, r.right - x, r.bottom - y];
            """
        )

    def settle(self) -> None:
        """Wait until the selected window and Zen's notification panel have
        been still for 1 s (10 s cap).

        Headful, a tiling window manager can move a new window around the
        time the panel opens. The panel can then open where the window was,
        and the next style change anywhere in the window may move it, with a
        `popuppositioned` that bumps `timeShown` (PopupNotifications.sys.mjs:
        887-901). Run this before a share request, so the window has stopped
        moving, and again after it before measuring the panel: an empty
        style element gets any such move done first."""
        self.chrome(_SETTLE)

    def allow_camera(self, origin: str = "http://meet.test") -> None:
        """Give `origin` a permanent camera permission, so Zen's share prompt
        offers "Not now" rather than "Block" (WebRTCParent.sys.mjs:612-613,
        1525-1537)."""
        self.chrome(
            """
            const principal =
              Services.scriptSecurityManager.createContentPrincipalFromOrigin(args[0]);
            Services.perms.addFromPrincipal(principal, "camera", Services.perms.ALLOW_ACTION);
            """,
            origin,
        )

    def os_windows(self) -> list[dict[str, Any]] | None:
        """The on-screen windows of this test Zen as macOS's window server
        sees them (`CGWindowListCopyWindowInfo`, only this Zen's process),
        as `{layer, alpha, bounds: [x, y, w, h]}`. None off macOS or when
        the list cannot be read. Reads window metadata only: no capture."""
        if sys.platform != "darwin" or self.process is None:
            return None
        out = subprocess.run(
            ["osascript", "-l", "JavaScript", "-e", _OS_WINDOWS, str(self.process.pid)],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if out.returncode != 0:
            return None
        return json.loads(out.stdout)

    def secondary_label(self) -> str | None:
        """The label of the open share prompt's secondary button: "Not now"
        once the site has a camera or microphone allowed, "Block" otherwise
        (WebRTCParent.sys.mjs:612-627)."""
        return self.chrome(
            """
            return win.document.getElementById("webRTC-shareDevices-notification")
              ?.getAttribute("secondarybuttonlabel") ?? null;
            """
        )

    def screen_permission(self, origin: str = "http://meet.test") -> int:
        """The "screen" `SitePermissions` state of `origin` in the selected
        tab, temporary ones included. `SitePermissions.UNKNOWN` is 0."""
        return self.chrome(
            """
            const { SitePermissions } = ChromeUtils.importESModule(
              "resource:///modules/SitePermissions.sys.mjs");
            const principal =
              Services.scriptSecurityManager.createContentPrincipalFromOrigin(args[0]);
            return SitePermissions.getForPrincipal(
              principal, "screen", win.gBrowser.selectedBrowser).state;
            """,
            origin,
        )

    def sharing_device_ids(self) -> list[str]:
        """The rawIds of the `browser` devices of every active stream."""
        return self.chrome(
            """
            const { webrtcUI } = ChromeUtils.importESModule("resource:///modules/webrtcUI.sys.mjs");
            return webrtcUI.getActiveStreams(true, true, true, true, true)
              .flatMap(s => s.devices ?? [])
              .filter(d => d.mediaSource == "browser")
              .map(d => String(d.rawId));
            """
        )

    def wait_picker_armed(self, timeout: float = 10) -> None:
        """Wait until the open picker takes Enter and Share (P33): its Share
        button is enabled once `security.notification_enable_delay` has
        passed since the picker opened or its window was last activated."""
        self.chrome(
            """
            await waitFor(() => {
              const b = win.document.getElementById("zen-share-picker-share");
              return b && !b.disabled;
            }, "the picker to be armed", args[0]);
            """,
            int(timeout * 1000),
            timeout=timeout + 5,
        )

    def screen_capture_denied(self) -> bool:
        """Whether macOS denies Zen screen capture. Pressing Allow would then
        raise a macOS dialog (WebRTCParent.sys.mjs:195-238). Always False
        off macOS."""
        if sys.platform != "darwin":
            return False
        return self.chrome(
            """
            const os = Cc["@mozilla.org/ospermissionrequest;1"]
              .getService(Ci.nsIOSPermissionRequest);
            const out = {};
            os.getScreenCapturePermissionState(out);
            return out.value == os.PERMISSION_STATE_DENIED;
            """
        )


class ExtensionPage:
    """An extension page open in the selected tab, driven in the content
    context. Get one from `Zen.options_page`."""

    def __init__(self, client: Marionette) -> None:
        self.client = client

    def eval(self, js: str, *args: Any) -> Any:
        """Run `js` as a function body in the page and return its value."""
        return self.client.execute_script(js, script_args=list(args))

    def wait(self, js: str, what: str, timeout: float = 15) -> Any:
        """Poll `js` (a function body) until it returns something truthy."""
        end = time.monotonic() + timeout
        while True:
            value = self.eval(js)
            if value:
                return value
            if time.monotonic() > end:
                raise AssertionError(f"timed out waiting for {what}")
            time.sleep(0.1)

    def text(self, selector: str) -> str:
        return self.eval(
            "return document.querySelector(arguments[0])?.textContent ?? null;",
            selector,
        )

    def click(self, selector: str) -> None:
        self.eval("document.querySelector(arguments[0]).click();", selector)


def pytest_report_header() -> str:
    binary = zen_binary()
    return f"zen: {binary} {zen_version(binary)} (at session start)"


@pytest.fixture(scope="session", autouse=True)
def zen_install_unchanged():
    """Fails the session when the installed Zen's version changed while it
    ran: a test launch must never update the install."""
    binary = zen_binary()
    before = zen_version(binary)
    yield before
    after = zen_version(binary)
    print(f"\nzen: {binary} {after} (at session end)")
    if after != before:
        pytest.fail(
            f"the installed Zen changed from {before} to {after} during the run"
        )


@pytest.fixture
def launch_zen(site: Site):
    started: list[Zen] = []

    def launch(prefs: dict[str, Any] | None = None) -> Zen:
        z = Zen(site, prefs)
        started.append(z)
        return z.start()

    try:
        yield launch
    finally:
        for z in started:
            z.close()


@pytest.fixture
def zen(launch_zen) -> Zen:
    return launch_zen()


@pytest.fixture(scope="session")
def addon_xpi() -> Path | None:
    """The add-on built from the repository by `scripts/build.sh`, once per
    session, or None when the repository has no `manifest.json` yet."""
    if not (REPO_ROOT / "manifest.json").exists():
        return None
    out = subprocess.run(
        ["sh", str(REPO_ROOT / "scripts" / "build.sh")],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(out.stdout.strip().splitlines()[-1])


@pytest.fixture
def addon(zen: Zen, addon_xpi: Path | None) -> str | None:
    if addon_xpi is None:
        return None
    addon_id = zen.install_addon(str(addon_xpi))
    zen.wait_addon_active(addon_id)
    return addon_id
