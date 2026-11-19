# Design

This is how zen-share-picker works and why it is built this way. The README covers install and use. This page is for people who want to check the reasoning or change the code.

Line numbers in code comments point at the Zen 1.24.2b sources. Comments and tests also cite decisions as "P13" or "R32". Those numbers are resolved in the decision log at the end.

## Problem

When a site asks to share the screen, Zen shows Firefox's standard permission prompt. It is a small panel at the top left, next to the address bar. Its dropdown lists the shareable sources, tabs included, by title, one line each. You see one entry at a time, and a preview only of the entry you already picked. With a dozen tabs, finding the right one is slow, and on a video call everyone waits while you do it.

Spaces add a second problem. Many people keep work and personal tabs in separate spaces so that they never mix on screen. Zen's prompt lists the tabs of each window's active space. With a second window on another space, the dropdown shows that space's titles too, in the middle of a presentation.

## Goals

* When a site asks to share the screen and Zen's prompt lists tabs, a picker opens in the window: a search box, a list of tabs with icon, title and host, and a large preview of the highlighted tab.
* The current space's tabs come first, most recently used first. The tab used just before the one asking to share starts highlighted.
* Other spaces' tabs are hidden until the user presses Tab. Once shown, they sit under their space's name with a "careful" mark, and sharing one takes a second Enter.
* Keyboard first: type to filter, arrows to move, Enter to share, Esc to decline.
* A last row hands over to the operating system's own picker for apps, windows and screens.
* Nothing is ever shared without an explicit Enter or a click on Share.
* It never breaks sharing. If Zen's prompt is not what the add-on expects, the picker stays away and the prompt works as if the add-on were not installed.

## Non-goals

* A grid of thumbnails.
* Capture types Zen doesn't offer. If the prompt lists no tabs, the add-on has nothing to show.
* Picking individual windows of other apps. The operating system's picker already does that.
* Changing how sites request sharing, or any site's own interface.
* Regular Firefox and other Firefox-based browsers.
* A listing on addons.mozilla.org. The add-on is privileged and unsigned.

It must also never touch the address bar, never write a pref at runtime, never store a title, URL or image, and never press anything in the prompt other than its real Allow button, and never set a permission.

## How it works

### Entries and mapping

Zen opens the prompt as the `webRTC-shareDevices` notification. Its dropdown (`#webRTC-selectWindow-menupopup`) holds one item per source, each with a label, a `mediaSource` and a `deviceId` (`WebRTCParent.sys.mjs`, `listScreenShareDevices`). A tab entry has `mediaSource` "browser", and its `deviceId` is the tab's browser id as a string. Firefox builds the tab entries from `BrowserWindowTracker.getAllVisibleTabs()`, which in Zen means each window's `gBrowser.visibleTabs`: the tabs of that window's active space, plus the Essentials Zen shows there (P13).

Every time Zen shows the prompt, the add-on reads it (`src/glue/prompt.sys.mjs`). It skips the separator and the "Select a window or screen" placeholder, and checks every other item. Entries are told apart by kind and id, since a tab's browser id can equal a screen's or a window's id. A camera or microphone request, a screen request that also asks for a microphone or a tab's audio (P34), or a prompt without tab entries, is left alone with no record. Anything else unexpected is a problem code for that prompt.

The add-on then maps each tab entry back to its tab, in any window and any space, through `browser.browserId` (`src/glue/tabs.sys.mjs`). From the tab it reads the title, the host, the favicon, the last-accessed time, the Zen space and the container. If one entry doesn't map to a tab, the picker stays away: it could not tell which space that tab belongs to, so it could not keep it hidden.

### Which tabs count as here

"Here" is the requesting window's active space and that space's container (`hereOf`).

* A regular or pinned tab belongs to its Zen space.
* An Essential belongs to every space whose container matches the Essential's container, which is where Zen shows it. An Essential from another container counts as another space.
* A tab whose space or container can't be read counts as another space. So does every tab when the requesting window has no space, as in a private window.

Other-space tabs are grouped by space, with Essentials of other containers in their own group, and the groups are ordered by their most recent tab.

### Mirrored tabs

Zen's window sync can show one logical tab in several windows. Firefox then lists it once per window. The picker shows one row per logical tab, keyed by the synced tab's DOM id (P9). It keeps the copy that holds the live content, otherwise the requesting window's copy, otherwise the most recently used one (P8). Sharing a copy without content would show a blank page.

### The picker

The picker (`src/glue/overlay.sys.mjs`, with its rules in `src/lib/state.mjs` and `src/lib/rows.mjs`) is an HTML overlay in the window's `#zen-main-app-wrapper`. It sits in the middle of the window: Zen's prompt is hidden while the picker is open (P35), so nothing covers it. Its header names the site asking, as Zen's prompt did, set as text only: "call.example wants to see your screen", with the delegation and local-file wordings of Zen's own prompt (P37). Share takes Zen's accent color, `--zen-primary-color`, and looks disabled until the picker is armed; Cancel is neutral. One picker per window at a time.

Rows are built only from what is visible. Before Tab, other spaces' rows are not in the DOM at all: no title, host, icon, device id or preview. The hint "Tab: show tabs from your other spaces" appears only when another window shows another space, and has no count. Search filters by title and host and never reveals. The requesting tab comes after the current space's other tabs and is never highlighted at the start. The last row, "Apps, windows or a screen...", maps to the prompt's operating-system entry, the one Zen pre-selects (P6, P17).

The picker owns a few keys: the arrows, Home, End, Enter, Esc and Tab. Shift+Tab is swallowed and does nothing (P10). Any key with Alt, Ctrl or Cmd passes through to Zen. Other keys go to the search box. A press on a row only highlights it, and a press on Share or Cancel keeps focus in the search box (P22).

Enter and Share commit a choice only once the picker is armed: `security.notification_enable_delay` must have passed since it opened or since its window was last activated, as for Zen's own Allow button. Until then they change nothing and Share is disabled. A held-down Enter (an auto-repeat) and an untrusted event never commit. `api.js` checks the same delay on its own before it acts on a share (P33).

The picker closes without sharing when the stock panel hides, when the user switches tabs or spaces (also when the switch keeps the same tab selected, through Zen's space-switch listeners), when the prompt is replaced, when a listed tab is closed or put to sleep (P11), and when the picker is turned off. Each of these ends the hiding of Zen's panel and declines nothing. Focus loss closes nothing and shares nothing.

### Preview

The preview is a still snapshot of the highlighted row's tab, taken with `PageThumbs.captureTabPreviewThumbnail`, the helper behind Firefox's tab hover preview. It refreshes about once a second while the row stays highlighted. One capture runs at a time, and a result for a tab that is no longer highlighted is dropped. Nothing is captured until a row is highlighted, and an other-space tab only after Tab revealed it. A live capture through Firefox's `webrtc-preview` exists in the code as a fallback mode, but the snapshot mode is the one in use.

### The share sequence and its verification

The add-on never grants a share. It drives Zen's prompt the way a user would, and Firefox keeps every permission check. `runShare` (`src/lib/share.mjs`) is the only code that presses Allow, and only after an Enter or a click on Share:

1. It stops the picker's preview, so that only one capture ever runs (P19).
2. It selects the chosen item in the stock dropdown and dispatches the item's `command` event, as a real pick does. Zen then runs its own checks and starts its own preview. The add-on reads the selection back. A tab target must be a tab entry and the operating-system target must be the recorded entry (P19). On any mismatch it puts the old selection back and stops, with nothing pressed.
3. It closes the picker. Zen's panel stays hidden (P35) and keeps working, because Zen's Allow check looks at whether the window is active and at the delay, not at visibility (platform test S6a).
4. It waits until the window is active, Allow is enabled, and `security.notification_enable_delay` has passed since the panel was shown. Firefox ignores an earlier click on purpose, as a guard against tricked clicks, and that delay restarts when the window activates.
5. It presses the real Allow button (`button.click()`), right after checking in the same step that the prompt and the selection are unchanged. A click Firefox ignores gets one retry.
6. It verifies: the notification is gone, and Firefox's list of active shares holds the chosen tab. As soon as the prompt is no longer current (gone after the click, replaced or hidden), Zen's panel shows again, before this check starts (P43).

The outcomes are `shared`, `handed-off` (the operating-system picker took over), `assist`, `aborted` and `unverified`. If Allow doesn't take within about 5 seconds, the outcome is `assist`: the chosen tab stays selected in Zen's prompt, with Zen's preview showing, and the user presses Allow. Nothing ever runs a share again for that prompt, and a throw after a click is `unverified`, never `assist`, so the add-on never asks for a second Allow (P18). Whatever the outcome, the hiding ends when the sequence settles, at the latest.

The add-on never calls `mainAction.callback`, `_onButtonEvent` or the `webrtc:Allow` message, never presses the prompt's secondary button or its menu, and never touches the prompt's checkbox. It calls `PopupNotifications.remove` only to decline.

### Declining

Esc and Cancel decline the request (P36). `runDecline` (`src/lib/decline.mjs`) checks that the prompt is still the session's own and, in the same step, abandons it once with `PopupNotifications.remove(notification, true)`, Zen's path for a request removed without a user response: WebRTC denies the request and sets no permission (P38). It checks at once that the notification went, shows Zen's panel again, and waits up to a second for the notification to go. The outcome is `declined`. If the call throws or the notification stays, Zen's prompt shows again, the problem code is `decline-failed`, the outcome is `cancelled`, and the user decides in Zen's prompt. A held-down Esc and an untrusted Esc or Cancel do nothing; arming does not gate a decline, which is not a commit. No other close declines: a tab or space switch, a closed or sleeping tab, a navigation, the off switch and shutdown leave the request pending.

Why not press Zen's secondary button, as a user would? Its label and its effect depend on the site. It reads "Not now" only when the site already has a camera or microphone allowed or active. Otherwise it reads "Block", which sets a temporary block on the site. A ticked checkbox in the prompt turns either into a remembered decision. The button also needs the window to be active. Abandoning the request avoids all of that: it presses no button, reads no checkbox, needs no active window, and sets no permission on any site (platform test S7, and acceptance tests with and without a camera grant).

While Zen's panel is hidden, the add-on owns Esc and keyboard focus in that window (P44), since the user cannot see what a key would act on there. Zen has its own Esc handler on the window: with focus on the page or in the panel, it presses the top notification's secondary button, which on a site without a camera grant is "Block". So the hiding element comes with two guards, added and removed with it (`src/glue/conceal.sys.mjs`). A capturing `keydown` listener on the window cancels every Escape, which also stops the keypress Zen listens to. While the picker is open, the Escape goes to the picker as its own Esc, wherever focus is, and declines as above; during the Allow wait or a decline it does nothing. A capturing `focusin` listener on the panel sends focus that enters it to the picker's search box, or to the page once the picker closed, so F6, Tab, Space or Enter never reach the unseen Allow or Block. The same `keydown` listener also cancels every chord of the chrome access-key modifiers (`ui.key.chromeAccess`: Ctrl on macOS, Alt elsewhere) with a key that is an access key in the panel, wherever focus is, since such a chord would press Allow or Block (P47). Gecko handles access keys on the keypress, and sends no keypress for a cancelled keydown.

A prompt the add-on handed back, after a failed decline, the stock path of the operating-system row or a share, gets no picker again when Zen shows it again.

### Fail-safe

At start, in the first browser window, the add-on checks Zen's notification panel, the prompt's elements, Firefox's list of active shares, the Zen space API and the thumbnail helper (`src/glue/selfcheck.sys.mjs`). If one fails, or a module doesn't load, the add-on is `inert`: it opens no picker and listens to no prompt, tab or space. It still adds one `unload` listener per window, to forget the window when it closes (`src/glue/watch.sys.mjs`).

Each prompt is checked again when it shows. Any failure there, including a reason code the wiring doesn't know and a throw, means that prompt gets no picker. The code goes to the status (the last 10) and to the browser console. The stock prompt is left exactly as Zen built it, and in view: a prompt with no picker is never hidden, and a failure to hide it is the code `conceal-failed` with no picker (P35). The hiding starts as the panel starts to show, for a prompt the picker will take (P48), and ends at once if the picker then does not open, or after 3 seconds at the latest with the problem code `hide-timeout` (P64). A prompt whose panel opened without the add-on's `nonnative` gets no picker and no hiding; the debug log says `prompt shown-native` (P64). While the panel is hidden, Zen's sidebar and toolbar stay as they were; a prompt shown again opens them as stock Zen does (P67).

The hiding is one style element per window, carrying the add-on's marker and owned by the picker's session. Every way a session ends removes it, except a share, which removes it once its prompt is no longer current or its sequence settles. A sweep runs on top of that, independent of any session: turning the picker off, shutdown (so uninstall and the old version in an update in place) and each window's own cleanup remove every marked element, and a window the add-on starts watching is swept first. The marker is the same in every version, so the sweep also removes an older version's leftovers.

The options page shows the state, the failed checks, the problem codes, the last outcome, an off switch and the debug log. The off switch and the debug switch last until Zen restarts, because the add-on stores nothing (P27). Each version loads its modules from its own resource host, so an update in place runs the new code (R16).

### Privacy

* Titles, hosts, icons and snapshots live only in memory, while the picker is open, except that the opt-in debug log keeps hosts until it is turned off.
* The add-on writes no prefs and stores nothing.
* Console lines carry reason codes only, never a title, URL, host or image.
* The debug log is off by default, in memory, capped at 2000 lines, and emptied when turned off. It holds entry and tab counts, the hosts of current-space rows and of rows revealed with Tab, device ids, and outcome and problem codes. It never holds a title or an image, and another space's host only after Tab (P12).

## Approaches considered

**How to share.** Three options:

1. Drive Zen's own prompt: read its entries, show the picker, then select the same entry in the stock dropdown and press the stock Allow button. Chosen. Firefox keeps every check and grants the share itself.
2. Replace the prompt and grant the share directly. Rejected. It means copying Firefox's permission code from `WebRTCParent.sys.mjs`, which is security-sensitive and can change in any release, and the module does not export the function that builds the prompt.
3. Restyle the prompt with CSS only. Rejected. CSS can make the panel wider, but it can't add search, a preview that follows the highlight, or hidden spaces.

**Pressing Allow, or leaving it to the user.** The add-on could stop after selecting the tab (an assist mode) and let the user press Allow. Tests showed that Zen accepts a click on the real Allow button once its delay has passed and the window is active, also in a headless window. So the add-on presses it, and falls back to assist when the click doesn't take.

**Layout.** A grid of thumbnails, or a search list with one large preview. The list won: it is faster from the keyboard and fits many tabs.

**Other spaces.** Always listed but dimmed, hidden until asked, or listed with a confirm step. Hidden until asked won, with a second Enter for a revealed tab on top. A dimmed row still shows its title on screen.

**Preview.** A live capture of the highlighted tab, as Zen's own prompt does for the selected entry, or a still snapshot. Snapshots won. They need no capture permission, they are cheap enough to refresh once a second, and they never leave a second capture running next to the real share.

**Packaging.** A feature inside zen-space-scope, or its own add-on. Its own add-on won: a picker that breaks after a Zen update can't affect anything else, and anyone can install it alone. It reuses zen-space-scope's installer, update channel and test harness.

## Testing

* Unit tests in Node cover the row model (space rules, mirrored tabs, order), the state machine (keys, search, reveal, the second Enter), the share sequence and the decline sequence with a fake prompt and clock, the picker's header copy for a site, a delegated request and a local file, the arming gate and the startup checks.
* Install tests run the installer against fake profile trees, never a real one.
* Release tests check the update manifest script and the workflows.
* Acceptance tests drive a real Zen through Marionette, each in a fresh temporary profile, with local test pages and no internet. They request a share from a page on a placeholder host (`meet.test`), use the picker by keyboard and mouse, press the real Allow button, and check the stream the page receives. Tests that need another space's tabs in the prompt open a second window on that space (P14). The checks that another space stays hidden come with a positive control on the same setup: after Tab, the same tab shows. Other acceptance tests check that Zen's panel is hidden while the picker is open and shows again on every exit, that a click where the hidden panel sits misses it, that the picker is centered, and that Esc and Cancel reject the page's request with no "screen" permission set, both for a site with a camera grant ("Not now") and without one ("Block").
* CI runs all of it on every push and once a day against the latest Zen release, the acceptance tests on headless Linux (P29).

## Decision log

R numbers come from zen-space-scope, the sibling add-on whose installer, update channel and harness this one reuses. They keep their numbers so the code comments match in both projects. P numbers are this project's own. Numbers that are missing were process decisions with no trace in the code.

| Ruling | Decision |
|---|---|
| P6 | The operating-system row maps only to the prompt's pre-selected operating-system entry. Zen adds that entry on macOS and on Linux with PipeWire. Where there is none (X11 without PipeWire, or headless Linux), the row closes the picker and puts the focus on Zen's dropdown. The row never shares a screen entry directly. Cost if wrong: that row only hands over to the dropdown on such systems. |
| P8 | A tab listed once per window is shown once. The kept copy is the one holding the live content, otherwise the requesting window's, otherwise the most recently used. Sharing a copy without content would show a blank page. |
| P9 | A tab row's key is the synced tab's DOM id, the same in every window. The operating-system row's key is `os`. |
| P10 | Shift+Tab is swallowed and does nothing. Tab after the reveal changes nothing. Every action other than Enter cancels a pending second Enter. Cost if wrong: one extra Enter. |
| P11 | The picker closes without sharing when a listed tab is closed, discarded or put to sleep. Tests cover closing the highlighted tab and then pressing Enter, and every mouse path: a row, Share and Cancel. The Cancel test now checks that the request is declined (P36). |
| P12 | The debug log holds the hosts of current-space rows at once, and another space's hosts only once Tab revealed them. It keeps at most 2000 lines, oldest dropped first. |
| P13 | Zen's prompt lists only the tabs of each window's active space. Other spaces' tabs reach it only through other windows. So the reveal hint appears only when such tabs exist, and it never shows a count. Cost if wrong: the hint itself tells an onlooker that another window shows another space. |
| P14 | A test that needs another space's tabs in the prompt opens a second window on that space. |
| P17 | Zen rebuilds the dropdown and pre-selects the operating-system entry each time the prompt shows, so the add-on reads the prompt on every show. The operating-system entry is pinned by its device id at the first read of a notification, and never taken from a later selection by the user. |
| P18 | Nothing ever runs a share again for the same prompt. A throw after a click is reported as `unverified`, never `assist`, so the user is never told to press Allow a second time. |
| P19 | `runShare` needs a way to stop the picker's preview and aborts before selecting anything without one. The dropdown selection checks the target kind: a tab target needs a tab entry, the operating-system target needs the recorded entry. A mismatch aborts with no click. |
| P22 | Esc and Cancel decline (P36); every other click in the picker keeps the stock notification open and not dismissed. Share and Cancel keep focus in the search box. A window holds at most one picker. A test closes and reopens the picker in one window and checks that no capture keeps running after a close. |
| P23 | Superseded by P37: the picker was placed below or beside Zen's panel, which was drawn above it. The panel is now hidden while the picker is open (P35), so the picker is centered and the placement code and its tests are gone. |
| P27 | The off switch and the debug switch last until Zen restarts. Nothing is stored and no pref is written. The labels say so, and the README says to disable the add-on in `about:addons` to turn it off for good. |
| P29 | CI runs the acceptance tests on headless Linux, where the prompt has no screen, window or operating-system entry. Each test was made platform-neutral, or skips only the part that has no data there, with a reason. |
| P33 | An explicit choice is input received once the picker is armed, never an auto-repeat. The picker arms when `security.notification_enable_delay` (read at open, 500 when unreadable, a user-set 0 respected) has passed since it opened, and the delay restarts when its window is activated, as for Zen's own buttons. Until then Enter, a click on Share and the operating-system row change nothing, and Share is disabled. Commits need trusted events. `api.js` refuses a share that reaches it unarmed, with its own open and activate times. The gate is a pure function in `src/lib/arming.mjs`. Cost if wrong: Enter is ignored for half a second after the picker opens or the window comes back, and the user presses it again. |
| P34 | The picker opens only for a screen request that asks for no audio input. A prompt that also asks for a microphone (its section is shown) or a tab's audio (the prompt's message says so) is skipped with the silent code `mixed-request`, and the stock prompt is untouched. One Enter must not also grant audio the picker never showed. Cost if wrong: the rare site that asks for both gets Zen's own prompt. |
| P35 | While a picker is open on a prompt that Zen's panel shows alone, the panel is hidden: opacity 0, no pointer events and a window opacity of 0 (`-moz-window-opacity`), so it stays open and its Allow button keeps working (platform tests S6a and S6b). The rule lives in one style element with the add-on's marker, owned by the picker's session. Closing the session shows the panel again. A share shows it as soon as its prompt is no longer current (gone after the Allow click, replaced or hidden), and at the latest when its sequence settles; a decline shows it right after its first check that the notification went. Another notification joining the panel, or the session's own notification leaving it, shows it for the rest of the session (P43). While it is hidden, the session also owns Esc and keyboard focus in that window (P44). A prompt with no picker is never hidden, and a failure to hide is the problem code `conceal-failed`, with no picker. Turning the picker off, and removing or updating the add-on, remove every marked element in every window, with or without a session behind it; the add-on also clears a window's marked elements when it starts watching that window. Cost if wrong: a prompt briefly invisible until the picker's session ends. |
| P36 | Esc and Cancel decline the request: one trusted, non-repeat Esc or click on Cancel abandons the session's own notification once, through `PopupNotifications.remove(notification, true)` (P38), right after checking that it is still current. Arming does not gate it. The panel shows again right after the first check that the notification went. If the call throws or the notification is still there after `goneWaitMs` (1 s), Zen's prompt shows again, the problem code is `decline-failed`, and the user decides there. No other close path declines. Cost if wrong: the user presses "Not now" in Zen's prompt, as before. |
| P37 | The picker is centered in the window, its header names the asking site, and Share uses Zen's accent. The header reads "<site> wants to see your screen", "<site> wants to give <other> permission to see your screen" for a delegated request, "This local file wants to see your screen" when Zen names no site, and "Choose what to share" without a prompt. The name is Zen's own `options.name` and `options.secondName` from the notification, set with `textContent` only. Share's background is `var(--zen-primary-color, AccentColor)` with `contrast-color()` text, Cancel a neutral tint, and a disabled Share is at half opacity. Cost if wrong: the header names a site in different words than Zen's prompt would. When Zen's panel stays in view because another notification shares it, it can cover the top left of the centered picker, and mouse clicks there land in Zen's panel; the keyboard still works. |
| P38 | Declining abandons the request rather than pressing Zen's secondary button. The button reads "Not now" only when the site already has a camera or microphone allowed or active, and "Block" otherwise, which sets a temporary block; it also depends on the prompt's checkbox. Removing the notification without a user response makes WebRTC deny the request and set no permission, on every site, needs no active window and presses no button (platform test S7). Nothing else calls `remove`, and nothing sets or changes a permission. Cost if wrong: if a future Zen stopped denying on removal, the page's request would hang until the site gives up; the rejection tests catch that. |
| P43 | The hiding never outlives the session's own notification. A share shows Zen's panel again as soon as its prompt is no longer current (gone after the Allow click, replaced or hidden), before it checks that the stream started. While the panel is hidden, for an open picker or a running share, another notification joining the panel, or the session's own notification leaving it, shows the panel at once. Cost if wrong: none; it narrows the hidden time to the add-on's own prompt. |
| P44 | While the add-on hides Zen's panel (a picker open, an Allow wait or a decline), it owns Esc and keyboard focus in that window, so neither Zen's Esc handler nor a key acts on the hidden prompt. A capturing `keydown` listener on the window cancels every Escape: with the picker open, a trusted, non-repeat Esc declines as the picker's own (P36), wherever focus is; otherwise it does nothing. A capturing `focusin` listener on the panel moves focus out, to the search box while the picker is open and to the page after. Both come and go with the hiding element: its restore and every sweep remove them. Cost if wrong: while Zen's prompt is hidden, Esc always means "decline" in that window. |
| P47 | While the add-on hides Zen's panel, the window's `keydown` guard (P44) also cancels every keydown that holds the chrome access-key modifiers (`ui.key.chromeAccess`, read when hiding) and whose key matches, in any case, an access key in the panel, read at that moment (Allow "A", Block "B", Not now "N" in English). This holds wherever focus is, the search box included. Cancelling the keydown stops Gecko's access-key handling, which runs on the keypress. Cost if wrong: those chords (Ctrl+A and Ctrl+B on macOS) don't edit the search box while the picker is open. |
| P48 | On macOS Zen shows its notification panel as a native popover (`widget.macos.native-popovers`), whose bubble, tail and shadow AppKit draws out of reach of any style, so the hidden prompt left an empty bubble on screen. For a prompt the picker will take, the add-on acts in `popupshowing`, before the first frame: it sets `nonnative` on the panel, so Gecko shows a plain popup window, and hides it at once with the marker and the guards of P44 and P47. It records whether it set `nonnative` or found Gecko's own (headless Gecko sets it on every anchored popup), and takes off only its own, on `popuphidden` and in every sweep. The hiding rule has a doubled id, to outrank Zen's `!important` menu look for plain-window panels, and also drops the window shadow, the native appearance and the background. When the picker then does not open, the panel shows again at once. Cost if wrong: an empty bubble where Zen's prompt was; a prompt the picker gave back looks like a plain panel rather than a native popover until it closes. |
| P64 | Three limits on P48's hiding. (a) A share prompt whose panel is already open without the add-on's record of `nonnative` (the picker was off or still starting when it opened, or Zen replaced a prompt in place) may be a native popover, which no style hides: the picker does not take it, nothing is hidden, and the debug log says `prompt shown-native`. (b) A headful test shows the panel natively first (a camera prompt) and checks, through the macOS window server, that the share prompt's panel then opens as one window at alpha 0 with no popover window. (c) A hiding taken in `popupshowing` that no picker adopts or ends within 3 seconds ends by itself, with the problem code `hide-timeout`. Cost if wrong: in the rare case (a), the user answers Zen's normal prompt without the picker. |
| P67 | Hiding the panel leaves Zen's sidebar and toolbar as they were. As a panel shows, Zen's `panel.js` marks its anchor `open`, which in compact mode slides the sidebar out (`zen-compact-mode-active` on the toolbox), and gives the URL bar `has-popup-open`, unless the panel has `no-open-on-anchor`. With the early hide (P48), the add-on sets that attribute, recording whether it added it, before `panel.js` acts (a test checks the order). When it shows a still-open prompt again (an assist, a failed decline, a per-prompt failure, the 3 s fallback, the off switch, another notification joining), it takes off its own attribute and does what `panel.js` would have done, so the prompt looks like stock Zen's, with the sidebar out. `popuphidden` and every sweep take off its own attribute. Cost if wrong: in compact mode, a prompt shown again might not slide the sidebar out; the panel itself still shows. |
| R13 | `uv.lock` files are not committed. uv writes the URL of the machine's package index into them, and CI resolves test dependencies from PyPI. |
| R16 | Each version of the add-on loads its modules from its own resource host, so an update in place runs the new code. The status reports the version. |
| R32 | Uninstall also deletes from `prefs.js` the lines of exactly the prefs the block set, because Zen copies `user.js` values there. Custom values from before the install are not restored. |
| R33 | The installer tells a running Zen by the lock Zen holds on the profile's `.parentlock` (and the `lock` symlink on Linux). It refuses when Zen runs and when it can't tell. In this project it also holds that lock from the check through its last write. |
| R34 | The block keeps `extensions.startupScanScopes=1` and `extensions.autoDisableScopes=14`, so an add-on file in the profile is found at startup and starts without a prompt. The README states what that enables. |
| R35 | Release rules: (a) the tag must match the manifest version; (b) a release holds exactly one add-on file plus the update manifest; (c) the manifest links the versioned file with its sha256 and minimum Zen version; (d) workflows get the least permissions they need, with actions pinned to a commit and no secret beyond the default token; (e) CI runs the acceptance tests headless and depends on no private package index; (g) a test proves a self-updated add-on comes back active and opens its picker. Item (f) concerned zen-space-scope only. |
