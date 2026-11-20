# Acceptance tests

These tests drive a real Zen through Marionette, request a screen share from
a local page, and read Zen's share prompt the way a user sees it.

## Run

From the repository root:

```sh
HEADLESS=1 MOZ_REMOTE_ALLOW_SYSTEM_ACCESS=1 uv run --project tests/acceptance pytest tests/acceptance
```

- `HEADLESS=1` runs Zen without windows. Spaces, containers, the share
  prompt and its Allow button all work headless: a headless Zen window is
  the active window. Leave it unset to watch the run.
- `ZEN_BINARY` points at the Zen executable. It defaults to
  `/Applications/Zen.app/Contents/MacOS/zen` on macOS and `zen` on Linux.
- Requires Zen 1.24.2b or later, and Python 3.12 through `uv` (no other setup).
- `-k stock_share -x` runs one test and stops at the first failure.
- `-rP` prints the `SPIKE` lines of the platform tests (what each one saw).

Each test starts its own Zen in a fresh temporary profile, with `-no-remote
-new-instance` and a Marionette port picked at random, so a Zen you are
already using is never touched. The profile and every process of the test
Zen are removed after the test, pass or fail: the harness kills every
process whose command line holds that profile's exact path, so a test Zen
relaunched outside the harness goes too.

The test Zen runs from your installed Zen. On macOS, a Zen started from an
install where your own Zen has staged an update applies that update before
it opens a window. So before each launch the harness reads the install's
update status (`~/Library/Caches/Mozilla/updates/<install path>/updates/0/update.status`),
and when an update is staged it stops the run with "a Zen update is
staged; restart your Zen first". The run also prints the installed Zen's
version at its start and end, and fails if it changed.

Once its window is ready, each test Zen gets one click in the middle of the
page (`user_input()`), so it runs with a user input on record like a user's
Zen. The click is a WebDriver action that Marionette synthesizes inside that
Zen: it never moves your pointer or reaches another window.

Tests that press Allow run headless too: a headless Zen window becomes the
active window, which Allow needs. Headful runs (`HEADLESS` unset) work as
well. Each test then opens a Zen window on your screen for a few seconds;
leave it alone until it closes. If Zen's first-run sweep animation keeps
covering the page, unlock the screen, since a locked screen gives Zen no
animation frames. A tiling window manager can move a new test window just
as Zen's panel opens, which leaves the panel misplaced for a moment, so the
tests that measure the panel or the picker call `settle()` first.

Skips, and why:

- On macOS, pressing Allow makes Zen check its screen-recording permission,
  and a denied permission raises a system dialog. Every test that presses
  Allow reads `screen_capture_denied()` first and skips with "macOS denies
  Zen screen capture; Allow would raise a macOS dialog" when it is denied.
  Grant Zen screen recording in System Settings to run them.
- `test_stock_share_flow` skips with "window could not become active" when
  the test window never becomes the active window.
- `test_zen_windows_match_window_entries` runs only headful on macOS, where
  Zen lists windows (`zen.LIST_WINDOWS_PREFS`). It skips headless, off macOS,
  and with "the window could not become active (screen locked?)". It lists
  your open windows but returns only counts and ids, and never previews one.
- `test_real_window_rows_are_listed_without_capture` and
  `test_zen_windows_are_never_listed` run only on macOS with
  `zen.LIST_WINDOWS_PREFS`. They read the picker through `picker_keys()`
  (keys, ids and counts, never a title), never press an arrow, and keep
  previews off. The first skips with "Zen listed no screen here"; the
  second runs only headful (Zen's own window ids can't be read headless)
  and skips with "the window could not become active (screen locked?)".
- The fake-window tests (`wrap_append_item` with "tabs-as-windows" or
  "only-windows") turn tab items into window items, keep previews off, and
  give Zen's window a readable fake id where reading it throws
  (`READABLE_WINDOW_IDS`). `test_unreadable_zen_window_ids_hide_every_window`
  skips where the real ids read fine (headful), and so does
  `test_a_zen_window_entry_is_hidden_and_never_selected`, which makes one
  fake window's id read as Zen's own. `test_debug_log_holds_no_window_title`
  checks that every listed window is a fake one, by id, before it reads a
  label.
- `test_port_select_checks_the_target_kind` skips its operating-system half
  where the prompt has no screen or window entry (headless Linux).
- `test_focus_never_rests_in_the_hidden_panel` and
  `test_the_key_and_focus_guards_go_with_the_hiding` skip their focus part
  with "the panel's Allow button takes no focus here, even shown (control)"
  where a script cannot focus Zen's Allow button even in the shown panel
  (headless Linux). Their Esc and F6 checks run first, everywhere.
- `test_headful_panel_is_a_plain_hidden_window` runs only headful, since
  headless Gecko shows every anchored popup as a plain window, and skips with
  "the screen is locked" when its window cannot become active.
- `test_preview_follows_highlight` and `test_stop_preview_ends_the_loop`
  skip when `PREVIEW_MODE` in `src/lib/config.mjs` is not "snapshot".
- `test_concealed_panel_lets_clicks_through`, in `test_platform.py` (with
  the hiding rule alone) and in `test_picker.py` (with the add-on's own
  hiding), first clicks the visible panel as a control. If that click does
  not land in the panel, pointer actions can't test click-through here, and the
  test skips with "pointer actions do not reach the panel here". It has
  not skipped on macOS, headless or headful, or on headless Linux.
- No test skips on Linux for the hiding itself: in the headless Linux
  container the hidden panel has a computed opacity of 0, as on macOS. Off
  macOS, Zen fades its panel's opacity, so the hiding checks wait up to a
  second for it.

## Sharing bar tests

`test_bar.py` checks Firefox's sharing bar as the add-on restyles it. Each
test shares a tab through Zen's stock prompt and presses the real Allow,
so it needs what the other Allow tests need: on macOS, Zen granted screen
recording, otherwise the test skips with "macOS denies Zen screen
capture; Allow would raise a macOS dialog". A tab share raises no macOS
alert.

- Firefox opens, moves and hides the bar headless, so these tests run
  headless (`BAR_HEADLESS = True` in `test_bar.py`) and headful alike.
  Headful, a test whose window can't become active skips with "the window
  could not become active (screen locked?)".
- `test_hide_removes_the_bar_from_the_screen` reads the macOS window
  server's list (sizes and alpha, no pixels) to check that Hide takes the
  bar off the screen. It skips headless ("needs the window server, run
  headful") and off macOS.
- The restyle runs on macOS only, so off macOS every test skips with "the
  sharing bar restyle is macOS only", before Zen starts, except
  `test_bar_stays_stock_off_macos`. That one shares a tab and checks the
  bar has no marker, no added element and no wrapper; it skips with
  "Firefox opened no sharing bar here" when no bar opens within 10 s.
- On macOS each test waits up to 10 s for the bar after the share, and a
  bar that never opens fails the test.
- The tests read computed sizes, colors, positions and the window's
  visibility in the bar's window, and never print a page title. The
  whole-screen look is checked by setting Firefox's sharing attribute on a
  live bar during a tab share, not by sharing the screen.
- `test_bar.py` never shares a real window or the screen. A bar check that
  needs one belongs in `test_capture.py` and is opt-in like the rest of it
  (below).

## Capture tests (opt-in)

`test_capture.py` previews and shares a real window and the screen: the
picker's live preview follows the highlight, and Enter shares a window or
the screen. On macOS any such capture makes the system raise an alert on
your screen, so these tests are off by default. Every test there skips
with "captures a window or the screen, which raises a macOS alert: set
ZSP_CAPTURE_TESTS=1 with the owner present" unless that variable is set,
skips headless ("needs real windows, run headful") and off macOS, and skips
when macOS denies Zen screen capture or the window can't become active
(screen locked?). No Zen starts for the first three skips; the last two
come from a running test Zen, before any capture.

Run them only with the machine's owner present, to answer the alert:

```sh
ZSP_CAPTURE_TESTS=1 MOZ_REMOTE_ALLOW_SYSTEM_ACCESS=1 uv run --project tests/acceptance pytest tests/acceptance/test_capture.py -rP
```

- The window tests start a second test Zen on `http://docs.test/a` and
  share or preview that window only. They reach it by clicking its row's
  key, and the screen with Home; nothing arrows across your other windows.
- They read the picker through `picker_keys()` (keys, never a title) and
  print `CAPTURE` lines with times, counts and booleans only. No frame is
  saved or copied.
- Each first-frame wait is 60 s, time enough to answer the alert.

`uv.lock` is not committed: uv writes the URL of whatever package index the
machine is configured with into it. Set `UV_NO_CONFIG=1` to resolve from
PyPI regardless of a machine-level `uv.toml`.

## Continuous integration

`.github/workflows/ci.yml` runs on every push and once a day:

- `node --test tests/unit/*.test.mjs` (Node 24);
- `uv run --with pytest --with pyyaml pytest tests/install tests/release`, on
  Linux and macOS;
- this suite on Linux, headless, against the latest Zen release
  (`zen.linux-x86_64.tar.xz` from `zen-browser/desktop`, extracted so that
  `ZEN_BINARY` is `<dir>/zen/zen`). The daily run catches a Zen release that
  breaks the add-on.

Every job sets `UV_NO_CONFIG=1`, so uv ignores any machine-level `uv.toml`
and resolves test dependencies from PyPI. To run what CI runs, from the
repository root:

```sh
export UV_NO_CONFIG=1
node --test tests/unit/*.test.mjs
uv run --with pytest --with pyyaml pytest tests/install tests/release
HEADLESS=1 uv run --project tests/acceptance pytest tests/acceptance
```

`.github/workflows/release.yml` runs on a `v<version>` tag. It fails unless
the tag matches `manifest.json`'s version, runs the unit, install and release
tests, then publishes exactly one XPI plus `updates.json`
(`scripts/make_updates_json.py`) as the latest release.

On headless Linux the share prompt lists only tabs, after its "Select window
or screen" placeholder: no screen, no window, and no pre-selected
operating-system entry. The picker then has no Windows tab, the real-window
tests skip with "only macOS lists windows here", the fake-window tests run,
and `test_port_select_checks_the_target_kind` skips its half that needs a
screen or window entry. Pressing Allow needs no screen-capture permission
there, so the share tests run.

## Self-update

The manifest's `update_url` is the latest release's `updates.json`. Its
`update_link` is the versioned asset URL, with the file's sha256 as
`update_hash` and `strict_min_version` 160.0. Zen checks it once a day and
installs a newer version in place. `test_self_update.py` serves both files
from the local test server over plain HTTP, which needs
`extensions.checkUpdateSecurity=false` in those temporary profiles only (Zen
otherwise disables an add-on whose `update_url` is not https); the real
channel is https and needs no pref change.

## How it works

- **Pages** (`pages.py`). The `site` fixture runs one HTTP server on
  `127.0.0.1` and Zen uses it as its HTTP and HTTPS proxy. Pages keep plain
  URLs such as `http://docs.test/a` (no port, no DNS). The served hosts are in
  `pages.HOSTS`. Any other host gets a 404 and HTTPS tunnels are refused, so
  nothing reaches the internet. Each page is titled `"<host> <name>"`, except
  two pages on `meet.test`:
  - `http://meet.test/share`: one full-viewport button whose click calls
    `getDisplayMedia({video: true})`. The title starts as `"meet.test share"`
    and becomes `"shared"` on success or `"share failed <error name>"`.
  - `http://meet.test/camera`: the same with `getUserMedia({video: true})`.
- **Profile prefs** (`zen.BASE_PREFS`). Besides a quiet startup:
  - `security.notification_enable_delay=500`: Marionette sets it to 0 on the
    default branch, and a user pref wins, so the prompt keeps a real delay;
  - `dom.securecontext.allowlist="meet.test"`: the plain-HTTP meet pages are
    secure contexts, which `getDisplayMedia` needs.
  - `xpinstall.signatures.required=false` and
    `extensions.experiments.enabled=true` (`zen.ADDON_PREFS`).

  No pref turns tab sharing on: Zen 1.24.2b lists tabs in the share prompt
  without one, as a user's Zen does. A tab is listed once it is in a window's
  visible tabs. Zen's initial empty tab is not, which is why `visit()` opens
  each page in a new tab.
- **Zen** (`zen.py`). Zen allows chrome-context scripts only when the
  environment variable `MOZ_REMOTE_ALLOW_SYSTEM_ACCESS=1` is set
  (`remote/content/components/RemoteAgent.sys.mjs`). It has no command-line
  flag for this, so the harness sets the variable.
- **The add-on**. When `manifest.json` exists at the repository root, the
  `addon` fixture builds the add-on with `scripts/build.sh` (once per
  session), installs the XPI as a temporary add-on, and waits until it
  reports `active`. Without `manifest.json` it installs nothing.

## Fixtures

| Fixture | What it gives |
|---|---|
| `site` | `Site` (session scope). `site.url(host, name) -> "http://host/name"`. `site.serve(url, body, content_type)` serves a file at any plain-HTTP URL until `site.unserve(url)`. |
| `zen` | A started `Zen` with the default prefs. |
| `launch_zen` | `launch_zen(prefs: dict \| None = None) -> Zen`, for extra startup prefs. Can start several. |
| `addon_xpi` | The XPI built by `scripts/build.sh` (session scope), or `None` without `manifest.json`. |
| `addon` | The add-on id after a temporary install of `addon_xpi`, once it is `active`, or `None` without `manifest.json`. |

`Zen` methods. They act on the browser window Marionette has selected.

| Method | Does |
|---|---|
| `chrome(body, *args, timeout=30)` | Runs `body` as an async function in the window. `win`, `args`, `waitFor(fn, what, ms)`, `tabsOf(w)` (every tab of window `w`, in every space), `findTab(url)` and `shareNotification(browser)` are in scope; `return` a JSON value. A throw raises `ZenScriptError` with the JS stack. |
| `content(js, *args)` | Runs `js` as a function body in the selected tab's page and returns its value. |
| `user_input()` | Clicks the middle of the window through WebDriver actions and checks Firefox recorded it as a user input. |
| `press(*keys)`, `type_text(text)` | Key presses into the focused chrome element. A key is one character or a name such as `"Escape"`, `"Enter"`, `"Tab"`, `"ArrowDown"`, `"F6"` (`zen.KEY_NAMES`). WebDriver key actions, or untrusted `KeyboardEvent`s when `src/lib/config.mjs` has `KEY_INPUT = "synthetic"`. |
| `press_access_chord(key)` | Holds the chrome access-key modifiers from `ui.key.chromeAccess` (Ctrl on macOS, Alt elsewhere) and presses `key`, as WebDriver key actions. |
| `make_space(name, container: str \| None) -> str` | Returns the uuid of a space called `name`. `container` is a container label, created if missing; `None` means no container. The first call with `None` renames and reuses the profile's default space. The active space does not change. |
| `switch_space(uuid)`, `active_space() -> dict` | Makes that space active; `{uuid, name, container}` of the active space. |
| `container_id(name) -> int` | The container's userContextId. |
| `visit(url, container: int \| None = None)` | Opens `url` in a new selected tab of the active space and waits until it has loaded and has its title. `None` uses the active space's container, as Zen does. |
| `make_essential(url, container: str)` | Opens `url` in that container (from a space with that container) and makes it an Essential. The active space is the same after. |
| `request_share(path="share")` | Opens `http://meet.test/<path>`, makes the window active, clicks the page centre (a trusted click), and waits until the share prompt is open. |
| `stock_prompt_open() -> bool` | Whether the selected tab's share prompt is open. |
| `stock_entries() -> list[dict]` | The prompt's dropdown items as `{label, mediaSource, deviceId}`; the placeholder has `None` for both. |
| `stock_selected() -> str \| None` | The selected item's `deviceId`; `None` for the placeholder. |
| `stock_counts() -> dict[str, int]` | How many of the prompt's items have each `mediaSource`; the placeholder counts as `"placeholder"`. No labels. |
| `stock_ids(source) -> list[str]` | The `deviceId`s of the prompt's items with that `mediaSource`, in order. No labels. |
| `zen_window_ids() -> list[str]` | `String(windowUtils.webrtcRawDeviceId)` of every top-level Zen window, the id the prompt's window entries carry. Raises if a read throws. |
| `browser_id(url) -> str`, `page_title(url) -> str` | The browser id and page title of the first tab on `url`, this window first. |
| `sharing_device_ids() -> list[str]` | The rawIds of the `browser` devices of every active stream. |
| `screen_capture_denied() -> bool` | Whether macOS denies Zen screen capture (pressing Allow would raise a macOS dialog). Always `False` off macOS. |
| `panel_rect() -> list[float]` | `[left, top, right, bottom]` of Zen's notification panel, in the coordinates pointer actions use. |
| `settle()` | Waits until the window and Zen's panel have been still for 1 s (10 s cap). Headful tests call it before a share request and before measuring. |
| `allow_camera(origin="http://meet.test")` | Gives `origin` a permanent camera permission, so Zen's prompt offers "Not now" instead of "Block". |
| `secondary_label() -> str \| None` | The label of the open share prompt's secondary button: "Not now" once the site has a camera or microphone allowed, "Block" otherwise (`zen.SECONDARY_LABEL`). Tests that call `allow_camera()` check it, so the case they name is the one Zen built. |
| `screen_permission(origin="http://meet.test") -> int` | The "screen" `SitePermissions` state of `origin` in the selected tab, temporary ones included. `0` is `SitePermissions.UNKNOWN`. |
| `install_addon(path) -> str` | Temporary install of a directory or `.xpi`. |
| `addon_call(addon_id, method, *args)` | Calls `browser.sharePicker.<method>` of the add-on from chrome and returns the result. |
| `wait_addon_active(addon_id) -> dict` | The add-on's status; raises unless it is `active`. |
| `glue(name) -> str` | The `resource://zen-share-picker-<version>/src/<name>` URL of a module of the installed add-on. |
| `options_page(addon_id)` | Context manager: opens the options page in a new tab and yields an `ExtensionPage` (`eval`, `wait`, `text`, `click`) running in the page. |
| `open_window(*, private=False, synced=True) -> str` | Opens a browser window, selects it for the helpers without focusing it, and returns its handle. |
| `wait_new_window(opener) -> str`, `use_window(handle, *, focus=False)`, `window` | Waits for a window `opener()` opens; selects another window; the selected window's handle. |

Things worth knowing:

- In Zen, `gBrowser.tabs` and `gBrowser.visibleTabs` hold only the window's
  active space (plus the Essentials of its container). Use `tabsOf(win)`
  (`gZenWorkspaces.allStoredTabs`) for every tab.
- Firefox lists a tab in the share prompt when it is in some window's
  `gBrowser.visibleTabs` and has a `linkedPanel`. So another space's tab is
  listed only when another window shows that space, and a synced tab can be
  listed once per window that shows its space (`test_platform.py`).
- A fresh profile starts with one space named "Space" that has no container.
- Zen's prompt has a secondary button whose label depends on the site:
  "Not now" when the site already has a camera or microphone allowed or
  active, "Block" otherwise (which sets a temporary block). The add-on never
  presses it. The decline tests run both ways, with `allow_camera()` and
  without, and each checks that the page's request was rejected ("share
  failed NotAllowedError") and that `screen_permission()` is still `0`.
