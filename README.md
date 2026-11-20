# zen-share-picker

A Zen Browser add-on that puts a large, keyboard-first picker for tabs, windows and screens on top of Zen's screen-share prompt.

When a video-call site asks to share your screen, Zen shows Firefox's standard prompt: a small panel at the top left with a dropdown that lists tabs by title, one line each. You see one entry at a time, and a preview only of the entry you already picked. Telling two similar tabs apart is hard, and it all happens while people are watching. This add-on opens a picker with a search box, a list of your tabs with their icons and hosts, and a big preview of the highlighted tab. Tabs from your other spaces stay hidden until you ask for them. The picker's Windows tab lists your screens and windows, with a live preview of the one you highlight. On macOS it lists them only when you install with `--list-windows`. While you share on macOS, it also restyles Firefox's sharing bar: bigger, rounded, at the bottom center, with a Hide button.

It is a privileged, unsigned add-on, so please read the start of "Install" before you run anything.

## What it does

When a site asks to share your screen and Zen's prompt lists tabs, screens or windows, a picker opens in the middle of the window. Its header names the site that asks, as Zen's prompt does: "call.example wants to see your screen". Zen's own prompt is hidden while the picker is open. It comes back whenever the picker closes without a decision. On macOS it then comes back as a plain panel rather than Zen's usual rounded bubble, until it closes. In compact mode, the sidebar stays as it was while the picker is open; if Zen's prompt comes back, the sidebar slides out for it as usual.

The picker has two tabs at the top, Tabs and Windows. Cmd+1 and Cmd+2 switch between them on macOS, Ctrl+1 and Ctrl+2 elsewhere, and so does a click on a tab's name. Switching clears the search. The picker opens on the Tabs tab, or on the Windows tab when Zen's prompt lists no tab you can share.

The Tabs list:

* Tabs of the current space come first, most recently used first. The tab you used last, other than the one asking to share, starts highlighted. That is usually the one you mean to show.
* The tab asking to share (the call itself) comes after the current space's other tabs and is never highlighted at the start.
* A footer reminds you that tabs that are asleep can't be shared.
* When Zen's prompt lists no tab, the list says so.

The Windows list follows Zen's prompt:

* The screens Zen lists, then its windows, each under the name Zen gives it, in Zen's order. On macOS, Zen lists them only when you installed with `--list-windows` (see "Listing windows").
* Then, when Zen's prompt has a "Use operating system settings" entry, a row that hands over to your system's own picker: "Open the macOS picker (apps, windows or a screen)" on macOS, "Open the system picker (apps, windows or a screen)" elsewhere. Without `--list-windows`, this row is all the Windows tab holds on macOS.
* When there is nothing to list, there is no Windows tab.
* Nothing is highlighted when you switch to it.
* When a screen is highlighted, a line under the list says "Careful: everything on this screen will be visible." It stands in for the warning Zen's hidden prompt would show.

Zen's own windows never appear in the Windows list. A Zen window's title is the title of its active tab, and that tab can belong to another space, so listing it would show another space's title before you press Tab. To share something in Zen, share its tab. If the add-on can't tell which windows are Zen's, it hides every window of that prompt and keeps the screens. Windows of another Zen profile or Zen process are listed like any other app's windows, titles included. Only the windows of the Zen you share from are hidden.

The keys:

* Type to filter the list you see: tabs by title and host, windows by title. The system picker row always stays.
* The arrow keys, Home and End move the highlight.
* Enter shares the highlighted tab, window or screen, and on the system picker row it hands over to your system's picker. You can also click a row, then click Share.
* Esc, or Cancel, declines the request. The site is told no, and no permission is saved for it, whatever Zen's prompt offered, so it can ask again. If the decline doesn't go through, the picker closes, Zen's prompt shows, and you decide there. The repeats of a held-down Esc do nothing, so an Esc you were already holding when the picker opened doesn't decline.
* Tab shows the tabs from your other spaces (see below). In the Windows tab it does nothing. Shift+Tab does nothing.
* Cmd+1 and Cmd+2 (Ctrl elsewhere) switch to the Tabs tab and to the Windows tab, wherever the focus is. They do nothing else while the picker is open, even when there is no Windows tab.

The preview on the right follows the highlight. For a tab it is a still image, refreshed about once a second. For a window or a screen it is live, like the preview in Zen's own prompt. Nothing is captured until a row is highlighted. In the Windows tab, a live preview starts only when you highlight a row with an arrow key, Home, End or a click, and the highlight stays there for a moment, so rows you only pass over are never captured. Opening the picker, switching to the Windows tab and typing never start one. Only one live preview runs at a time, and it stops when the highlight moves, when you switch to the Tabs tab, when the picker closes and when a share starts. The preview says "No preview" when no picture arrives: when Zen's previews are off (`media.getdisplaymedia.previews.enabled` set to false), when macOS denies Zen screen recording, or when macOS refuses the capture. The preview never asks macOS for screen recording, and the add-on sets no permission of its own for it. When you share "Entire screen", the add-on picks it in Zen's prompt, and Zen itself may then ask macOS for screen recording if it is denied.

**Other spaces.** Zen's prompt lists only the tabs of each window's active space. With one window, that is the space you are in, and there is usually nothing to hide. When another window shows another space, its tabs are in Zen's list too. The picker keeps them out of sight. You see a hint, "Tab: show tabs from your other spaces", with no count and no names. It appears only when such tabs exist. Press Tab and they show up under their space's name, marked "careful". Sharing one of them takes a second Enter. Typing a search never reveals them: if nothing in the current space matches, the hint says "No match here. Tab to search other spaces."

**Nothing is shared without you.** The only way to share a tab, a window or a screen is Enter, or a click on Share. Both do nothing until Zen's own Allow delay (half a second by default) has passed since the picker opened or its window came back to the front, and a held-down Enter never shares. No timer, focus change or closed picker leads to a share. If you switch to another app while the picker is open, it stays open and shares nothing.

**How it shares.** The picker doesn't grant anything itself. On Enter it selects your tab, window or screen in Zen's own dropdown, closes, waits for the short delay Zen puts on the Allow button, and presses Zen's real Allow button. Zen's prompt stays hidden during that wait. Then the add-on checks Zen's list of active shares: the site must be sharing that tab, window or screen. If Zen doesn't take the click, Zen's prompt shows with your choice selected, and you press Allow yourself.

**How it declines.** Esc and Cancel don't press anything in Zen's prompt. They withdraw the prompt the way Firefox does when a request ends without an answer, and Firefox then tells the site no and saves nothing. Zen's "Block" button, which the prompt shows when the site has no camera or microphone allowed, would set a temporary block on the site instead. While Zen's prompt is hidden, Esc belongs to the picker even when you clicked the page first, and keyboard focus can't move into the hidden prompt, so no key ever acts on a prompt you can't see. While the add-on waits to press Allow for you, Esc does nothing. While the picker is open, Ctrl plus a letter that matches a shortcut of Zen's prompt, such as Ctrl+A or Ctrl+B, does nothing on macOS; elsewhere the same goes for Alt plus that letter.

**The fail-safe.** If anything about Zen's prompt is not what the add-on expects, the picker doesn't open, and Zen's prompt is left exactly as Zen built it, in view. See "How the fail-safe works".

The picker closes without sharing or declining when you switch to another tab or space in Zen, when Zen's prompt goes away, when a listed tab is closed or put to sleep, and when you turn the picker off. None of these declines the request: it stays with Zen's prompt. Only Esc and Cancel decline.

## The sharing bar

While you share a tab, a window or your screen, Firefox shows a small floating bar that says what you share and has a Stop Sharing button. The add-on restyles that bar in place. In 0.3.0 it does so on macOS only; on Linux and Windows you keep Firefox's stock bar. It is still Firefox's bar: Firefox decides when it shows, and Stop sharing does what it always did.

The look:

* A rounded pill, 44px tall, light or dark like Zen's own windows.
* From left to right: a grip, an icon, the label, then two buttons, Hide and Stop sharing. Both take Zen's accent color, or your system's.
* When you share your whole screen, the icon and the edge turn amber.

Where it sits:

* At the bottom center of the call's window. When the call's tab is the one in front in its window, the bar sits 88px above the bottom of the page, clear of the toolbars of most call sites. When another tab is in front, it sits 16px above the bottom.
* It follows tab switches and resizes of that window.
* You can drag it anywhere. After you drag it, it stays where you dropped it until the share ends.

Hide hides the bar until a new share starts, or until every share ends. A share you already had running doesn't bring it back. While it is hidden, you can still stop a share from the sharing icon in the macOS menu bar, which keeps the bar hidden, from Zen's site panel, or from the site itself.

The label names the share type and the site that asked, in English: "Sharing a tab with call.example", "Sharing a Zen window with call.example", "Sharing a window with call.example" or "Sharing your entire screen with call.example". When several sites share, or a sharing page has no `http:` or `https:` host, the site is dropped. The label never holds the title of a tab or a window.

Other rules:

* It applies to every share in Zen, also the ones not started from the picker.
* It stays on when you switch the picker off. To get Firefox's own bar back, disable the add-on.
* With `privacy.webrtc.globalMuteToggles` on (the bar's microphone and camera toggles), the bar stays as Firefox builds it.
* The add-on never shows a bar that `privacy.webrtc.hideGlobalIndicator` hides.
* Disabling or removing the add-on, even in the middle of a share, puts back Firefox's stock bar.

## Requirements

* Zen 1.24.2b or later (Firefox 160).
* A profile that allows unsigned add-ons and experiment add-ons. The installer sets that up.
* For the install script: [uv](https://docs.astral.sh/uv/), on macOS or Linux. The script uses only the Python standard library. Building the add-on from a checkout (the default) also needs `zip`.

## Install

First, what the install enables in your profile. The add-on is unsigned and uses an experiment API, so the installer writes a block of 4 prefs into your profile's `user.js` that turns on:

* unsigned add-ons (`xpinstall.signatures.required=false`);
* experiment add-ons (`extensions.experiments.enabled=true`);
* any add-on file in the profile's `extensions` folder starting without a prompt (`extensions.autoDisableScopes=14`);
* a startup scan of that folder (`extensions.startupScanScopes=1`).

The add-on itself runs with full browser privileges: it can read everything you do in the browser. That is how it reads the share prompt and your tabs, and it is why it should come only from this repository's releases. Only drop add-on files you trust into that folder.

If you use zen-space-scope, its own block sets some of the same prefs. This installer leaves that block alone, on install and on uninstall.

With the script:

1. Quit Zen (Cmd+Q). The script refuses to touch a profile while Zen runs.
2. Get the code:

   ```sh
   git clone https://github.com/zippeurfou/zen-share-picker.git
   cd zen-share-picker
   ```

3. See what it would do, without writing anything:

   ```sh
   uv run scripts/install.py --dry-run
   ```

4. Run it:

   ```sh
   uv run scripts/install.py
   ```

5. Start Zen. The add-on enables itself without a prompt and checks its own setup. Open `about:addons`, pick Zen Share Picker, and check that the options page says `active`. The picker opens the next time a site asks to share your screen.

On macOS, to list your screens and windows in the picker, add `--list-windows`. Read "Listing windows" first: it turns Apple's screen picker off in Zen.

By default the script builds the add-on from your checkout. To install the latest GitHub release instead, add `--latest`. That only works once a release has been published.

The script prints each change it makes. It keeps everything else in your `user.js`, and writes through it if it is a symlink. A symlink whose target doesn't exist is refused before anything is written. Running it again updates the block in place.

Flags:

| Flag | What it does |
|---|---|
| `--profile PATH` | Use this profile directory. Needed when `--zen-dir` and auto-detection can't pick one. Find yours at `about:profiles`. |
| `--zen-dir PATH` | Zen's data directory (the one holding `profiles.ini`), when it isn't in the default place, or when the script finds several. |
| `--xpi PATH` | Install this XPI instead of building from the checkout. |
| `--latest` | Download the latest GitHub release and install that. Over HTTPS only, and it checks the add-on id before writing anything. |
| `--list-windows` | Also turn Apple's screen picker off, so Zen lists your windows and screens itself (see "Listing windows"). Not remembered: pass it on every run. `--uninstall` ignores it. |
| `--dry-run` | Print every change and write nothing. |
| `--uninstall` | Remove the add-on, the block, and the prefs it set (see "Uninstall"). |
| `--print-block` | Print the `user.js` block and exit (with `--list-windows`, the 5-pref block). Touches no profile. |

`--xpi` and `--latest` can't be combined. With several Zen installs in the data directory, the script lists the default profile of each and asks for `--profile`. With several data directories (on Linux, a native install next to a Flatpak one), it lists them and asks for `--zen-dir` or `--profile`. On Windows only `--print-block` works, so install by hand.

By hand, without the script: quit Zen, copy the XPI to `<profile>/extensions/zen-share-picker@zippeurfou.github.io.xpi` (make the `extensions` folder if it is missing), and add the output of `uv run scripts/install.py --print-block` to `<profile>/user.js`.

## Listing windows (`--list-windows`)

On macOS, Zen hands window and screen sharing to Apple's own picker. Its prompt then lists no screen or window, and the picker's Windows tab holds only the "Open the macOS picker" row. To have Zen list them itself, install with the flag:

```sh
uv run scripts/install.py --list-windows
```

The block then has 5 prefs. The fifth, `media.getdisplaymedia.screencapturekit.picker.enabled=false`, turns Apple's picker off. Zen reads it only at startup. Zen's prompt then lists "Entire screen" and your on-screen windows, and the Windows tab shows them, with a live preview of the one you highlight.

What you give up:

* Apple's picker, in Zen, for every share. Zen's prompt no longer offers "Use operating system settings". That stays true when the picker is switched off or the add-on is disabled, since the pref is in your profile, not in the add-on.
* Sharing a whole app. Zen lists screens and single windows, not apps.
* App names and icons. A window row shows the window's title only, as Zen gives it.
* Zen's own windows. They are never listed (see "What it does"). Share a tab instead.

On macOS 15 and later, the first time Zen previews or captures a window, and maybe a screen, macOS can show an alert asking whether Zen may bypass the system private window picker. Allow it to use the Windows tab. macOS can ask again later; for other apps it comes back about every 30 to 90 days. So right after installing with the flag, do one test share: open a site that asks to share your screen, highlight a window, wait for its preview and share it. The first alert then doesn't come in the middle of a meeting.

The flag is not remembered. Each run writes the block for the flags it was given, so run the installer with the same flags every time, `--list-windows` included. A run without it turns Apple's picker back on: it takes the pref out of the block and deletes that pref's line from `prefs.js`, and prints it. Uninstall turns Apple's picker back on too.

## Update

Zen checks for a new version of the add-on once a day and installs it in place, from the GitHub release. The update file carries the sha256 of the release file, and the update URL is HTTPS. That hash protects against a corrupted or swapped download. It does not protect against a compromised release, because the same release workflow writes the hash. Updates trust this GitHub repository and its workflow.

A self-update does not touch your `user.js`, so it keeps your `--list-windows` choice. If a release ever changes the block, its release notes say so, and you re-run the installer. Run the installer again with the same flags: a run without `--list-windows` turns Apple's picker back on. Once a release exists, `uv run scripts/install.py --latest` updates by hand. Pull the checkout first (`git pull`), since the installer builds the block from the checkout's own script.

## Uninstall

Quit Zen, then:

```sh
uv run scripts/install.py --uninstall
```

This removes the add-on file and the block from `user.js`. Zen also copies the `user.js` values into `prefs.js`, so removing the block alone resets nothing. The script therefore also deletes from `prefs.js` the lines of the 5 prefs listed below, and prints each one. They go back to Zen's defaults: unsigned add-ons off, experiments off, sideloaded add-ons prompting again, and Apple's screen picker on. A custom value you had for one of those prefs before installing is not restored. If zen-space-scope is installed, its own block sets its prefs again at the next start, and the script says so when another block in `user.js` still sets any of them. Add `--dry-run` to see what it would do first.

The script is the simpler path. It also deletes `user.js` when the block was its only content. The script's uninstall resets these 5 prefs, whether or not your block set the fifth one, and even if you had set it by hand before installing (`uv run scripts/install.py --print-block --list-windows` prints them with their values, and is the source of truth; without `--list-windows` the block has only the first 4):

```
xpinstall.signatures.required
extensions.experiments.enabled
extensions.autoDisableScopes
extensions.startupScanScopes
media.getdisplaymedia.screencapturekit.picker.enabled
```

If you would rather do it by hand, the order matters, because Zen re-applies `user.js` at every start and rewrites `prefs.js` when it quits:

1. Quit Zen.
2. Delete `<profile>/extensions/zen-share-picker@zippeurfou.github.io.xpi`.
3. Remove the block from `user.js`, from the `// zen-share-picker: begin` line to the `// zen-share-picker: end` line.
4. Still with Zen quit, delete the `user_pref(...)` line of each of the 5 prefs from `prefs.js`. Then start Zen.

If you prefer `about:config`, do steps 1 to 3, start Zen, click Reset on each of the 5 prefs, then quit and start Zen again so the change is saved. Skip step 4 in that case. Editing `prefs.js` while Zen runs doesn't work: Zen overwrites it when it quits.

## How the fail-safe works

The goal is that a broken add-on never breaks sharing. Zen's prompt must always work as if the add-on weren't there.

At start, the add-on checks the Zen and Firefox parts it relies on, in the first browser window:

| Check | What it looks for |
|---|---|
| `popup-notifications` | Zen's notification panel, which holds the share prompt. |
| `prompt-elements` | The share prompt's elements and its dropdown. |
| `webrtc-ui` | Firefox's list of active shares, used to verify a share. |
| `zen-spaces` | The Zen space API the picker reads, and its space-switch listeners. |
| `page-thumbs` | Firefox's tab thumbnail helper, used for the preview. |

If a module fails to load, the check is `modules`. An unexpected error at start is `start`. Any failed check leaves the add-on `inert`: it never opens a picker, and every share prompt stays exactly as Zen shows it.

Each prompt is checked again when it opens. If the prompt is missing a part, if a tab entry can't be mapped to a tab, or if anything throws, that prompt gets no picker. The add-on records a reason code and leaves the prompt as Zen built it. The next prompt gets a fresh try. If the add-on can't tell which window entries are Zen's own, it lists none of that prompt's windows, and the screens and tabs still show.

Zen's prompt is hidden only while a picker is open for it, or while the add-on is pressing Allow or declining for you, and only when Zen's panel holds that prompt alone. If hiding it fails, the picker stays away (`conceal-failed`). If Zen's prompt was already open before the add-on could prepare it, for example because you turned the picker on while it was showing, the picker stays away too and you answer Zen's prompt as usual. Every way the picker closes ends the hiding. Turning the picker off, and removing or updating the add-on, also clear the hiding in every window, and a window the add-on starts watching is cleared first.

The status page shows both. Open `about:addons`, pick Zen Share Picker and open its options page.

## Troubleshooting

The options page shows the state (`active`, `inert`, `disabled` or `starting`), the version, the failed checks, the last outcome, the codes of the last 10 prompts that got no picker, the sharing bar's problems, the on/off switch and the debug log.

The on/off switch lasts until Zen restarts. The add-on starts switched on every time, so to turn the picker off for good, disable the add-on in `about:addons`.

**No picker opens.** Check the state on the options page.

* `inert`: look at the failed checks. Switch the picker on to run the checks again. If `modules` failed, nothing can retry until you restart Zen, and a `start` failure may need a restart too.
* `active`, with a code under "Prompts without a picker": that prompt didn't look as expected. The table below says what each code means.
* `active`, with no code: open Zen's dropdown. The picker opens when it lists a tab, a screen or a window other than Zen's own. If it shows only "Use operating system settings", or only Zen's own windows, there is nothing for the picker to offer. The picker also stays away from camera and microphone requests, and from screen requests that also ask for audio.
* The add-on isn't listed at all: you probably started Zen on a different profile than the one the installer used (it prints the profile path), or Zen wasn't restarted after the install.

| Code | Meaning |
|---|---|
| `no-notification` | The share prompt was gone by the time the picker looked. |
| `no-menulist`, `no-mic-section`, `no-allow-button` | The prompt is missing its dropdown, its microphone section or its Allow button. Usually a Zen update. |
| `bad-entry` | A dropdown entry doesn't look like a tab, screen or window. Usually a Zen update. |
| `unmapped-entry` | A tab entry doesn't match any open tab. The picker can't tell which space it belongs to, so it stays away. |
| `read-error`, `tab-error`, `internal` | Something threw while reading the prompt or the tabs. |
| `no-mount` | The window has no place to show the picker. |
| `already-open` | A picker was already open in that window. |
| `conceal-failed` | The picker couldn't hide Zen's prompt, so it stayed away and left the prompt as Zen built it. |
| `decline-failed` | Esc or Cancel couldn't decline the request, so Zen's prompt came back for you to decide. |
| `hide-timeout` | Zen's prompt was hidden as it opened, but no picker took it within 3 seconds, so it came back as Zen built it. |
| `zen-ids-unknown` | The add-on couldn't tell which windows in the prompt are Zen's own, so it listed none of them. The picker still opens when the prompt has a tab or a screen. Recorded once per prompt. |

After a Zen update, a failed check or a repeated code usually means Zen changed code the add-on relies on. Open an issue with the code, and attach the debug log.

**The last outcome.** `shared` means the tab, window or screen is being shared and the add-on saw it. `handed-off` means your system's picker took over. `declined` means you pressed Esc or Cancel and the request was declined. `cancelled` means you pressed Esc or Cancel but nothing was declined: the prompt was already gone, or the decline failed and Zen's prompt is yours to answer. `aborted` means nothing was clicked, for example because the prompt went away first. `unverified` means Allow was pressed, but the add-on never saw the share start.

**The sharing bar looks like Firefox's stock bar.** On Linux and Windows, or with `privacy.webrtc.globalMuteToggles` on, that is on purpose (see "The sharing bar"). Otherwise look under "Sharing bar problems" on the options page. Each code means the restyle didn't apply or was undone, and you get the stock bar back, so sharing and Stop Sharing work as usual:

| Code | Meaning |
|---|---|
| `bar-unknown-markup` | The bar is missing an element or a function the restyle relies on. Usually a Zen update. |
| `bar-style-failed` | Something threw while restyling the bar, and the restyle was undone. |
| `bar-internal` | Something threw on a later update of the bar, or the add-on couldn't start watching for bars. |

The add-on keeps the last 10 codes.

**The outcome is `assist`.** Zen didn't take the add-on's click on Allow in time, for example because the window wasn't active. Your tab, window or screen is already selected in Zen's prompt, with its preview. Press Allow yourself. The add-on never presses it again for that prompt.

**The installer says Zen is running.** Quit Zen with Cmd+Q and run the same command again. The script also refuses when it can't tell whether the profile is locked, and the message says why.

**The installer lists several Zen installs or data directories.** Pass `--profile` with the path from `about:profiles`.

**The debug log.** Turn it on in the options page to log what the picker decides. It is off by default, lives in memory only, keeps at most 2000 lines, and is emptied when you turn it off. It holds:

* the number of entries in each prompt, and the number of tabs, in the current space and in total;
* the number of screens and windows the picker lists, and of windows it hid (Zen's own, or every window when it can't tell);
* the hosts of current-space rows, and of other spaces' rows once you press Tab;
* device ids (Firefox's numbers for the tabs, screens and windows in the prompt);
* outcome and problem codes, including the steps of each share, any failed check, and the switch going off or on;
* the sharing bar's lines: `bar placed 88` and `bar placed 16` (the gap it sits at), `bar hidden N shares` (N is a count), `bar dragged`, `bar shown new-share`, `bar stock mute-toggles`, `bar stock platform` and `bar hide refused`.

It never holds an image, or the title of a tab or a window. The total tab count includes tabs from other spaces that other windows show, so the log tells how many there are, but not what they are. Check the hosts before pasting it into an issue.

## Known limitations

* Tab capture in Firefox can run at a lower frame rate than a window share (bug 1717868, unconfirmed).
* Tabs that are asleep, and tabs in a collapsed group, can't be shared from Zen's prompt. Firefox leaves them out of the list, so the picker can't show them. Open the tab first.
* Share prompts shown in Zen's sidebar are not handled.
* A site that asks for your screen and your microphone (or a tab's audio) in one request gets Zen's own prompt, so one Enter never grants audio the picker didn't show.
* An Essential from another container counts as another space, even when Zen shows Essentials in every space. It stays hidden until Tab.
* A tab whose space or container can't be read counts as another space. When the call runs in a private window, every tab does.
* A prompt the picker handed back to you doesn't get the picker again: after a decline that failed, or after a share Zen didn't take. Use Zen's prompt, or ask the site to share again.
* If another notification is already in Zen's panel when the picker opens, or joins it while the picker is open, Zen's prompt stays in view. It can cover the top left of the picker, and a click there lands in Zen's prompt instead of the picker. The keyboard still works. Zen's dropdown lists every tab Zen offers, other spaces included, and Zen's own windows, so don't open it while presenting.
* The system picker row is on the Windows tab wherever Zen's prompt has a "Use operating system settings" entry: on macOS without `--list-windows`, and on Linux with PipeWire. Without that entry there is no such row.
* On Linux, there is a Windows tab only where Zen's prompt lists screens, windows or a "Use operating system settings" entry. Headless Linux lists none of them.
* With `--list-windows`, on macOS 15 and later, macOS can show an alert about Zen bypassing the system private window picker at the first window preview or share, maybe at the first screen one too, and again later (see "Listing windows").
* Windows are listed in Zen's order, not most recently used first.
* Switching the picker back on while a share prompt is open doesn't open a picker on that prompt until Zen shows it again.
* The sharing bar's label and buttons are in English only.
* The sharing bar doesn't know about Zen's split view. It centers on the selected pane. When the call's tab shows in a split but isn't the selected tab, the bar sits 16px above the bottom, and may cover the call's own controls. Drag it away.
* If you disable or remove the add-on in the middle of a share, Firefox's stock bar goes back to the top center (unless you dragged it), but it no longer re-centers itself on later changes during that share.
* The sharing bar is still Firefox's window, so its corners and shadow are drawn by the system.

Not supported:

* regular Firefox;
* addons.mozilla.org. The add-on is unsigned, so it ships as a GitHub release file.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). How it works, and why, is in [docs/design.md](docs/design.md). The license is MPL-2.0.
