# zen-share-picker

A Zen Browser add-on that puts a large, keyboard-first tab picker on top of Zen's screen-share prompt.

When a video-call site asks to share your screen, Zen shows Firefox's standard prompt: a small panel at the top left with a dropdown that lists tabs by title, one line each. You see one entry at a time, and a preview only of the entry you already picked. Telling two similar tabs apart is hard, and it all happens while people are watching. This add-on opens a picker with a search box, a list of your tabs with their icons and hosts, and a big preview of the highlighted tab. Tabs from your other spaces stay hidden until you ask for them.

It is a privileged, unsigned add-on, so please read the start of "Install" before you run anything.

## What it does

When a site asks to share your screen and Zen's prompt lists tabs, a picker opens in the middle of the window. Its header names the site that asks, as Zen's prompt does: "call.example wants to see your screen". Zen's own prompt is hidden while the picker is open. It comes back whenever the picker closes without a decision. On macOS it then comes back as a plain panel rather than Zen's usual rounded bubble, until it closes. In compact mode, the sidebar stays as it was while the picker is open; if Zen's prompt comes back, the sidebar slides out for it as usual.

The list:

* Tabs of the current space come first, most recently used first. The tab you used last, other than the one asking to share, starts highlighted. That is usually the one you mean to show.
* The tab asking to share (the call itself) comes after the current space's other tabs and is never highlighted at the start.
* The last row, "Apps, windows or a screen...", hands over to your system's own picker, like choosing "Use operating system settings" in Zen's prompt.
* A footer reminds you that tabs that are asleep can't be shared.

The keys:

* Type to filter by title and host.
* The arrow keys, Home and End move the highlight.
* Enter shares the highlighted tab. You can also click a row, then click Share.
* Esc, or Cancel, declines the request. The site is told no, and no permission is saved for it, whatever Zen's prompt offered, so it can ask again. If the decline doesn't go through, the picker closes, Zen's prompt shows, and you decide there. The repeats of a held-down Esc do nothing, so an Esc you were already holding when the picker opened doesn't decline.
* Tab shows the tabs from your other spaces (see below). Shift+Tab does nothing.

The preview on the right is a still image of the highlighted tab, refreshed about once a second. Nothing is captured for a tab until you highlight it.

**Other spaces.** Zen's prompt lists only the tabs of each window's active space. With one window, that is the space you are in, and there is usually nothing to hide. When another window shows another space, its tabs are in Zen's list too. The picker keeps them out of sight. You see a hint, "Tab: show tabs from your other spaces", with no count and no names. It appears only when such tabs exist. Press Tab and they show up under their space's name, marked "careful". Sharing one of them takes a second Enter. Typing a search never reveals them: if nothing in the current space matches, the hint says "No match here. Tab to search other spaces."

**Nothing is shared without you.** The only way to share is Enter, or a click on Share. Both do nothing until Zen's own Allow delay (half a second by default) has passed since the picker opened or its window came back to the front, and a held-down Enter never shares. No timer, focus change or closed picker leads to a share. If you switch to another app while the picker is open, it stays open and shares nothing.

**How it shares.** The picker doesn't grant anything itself. On Enter it selects your tab in Zen's own dropdown, closes, waits for the short delay Zen puts on the Allow button, and presses Zen's real Allow button. Zen's prompt stays hidden during that wait. Then the add-on checks that the tab is really being shared. If Zen doesn't take the click, Zen's prompt shows with your tab selected, and you press Allow yourself.

**How it declines.** Esc and Cancel don't press anything in Zen's prompt. They withdraw the prompt the way Firefox does when a request ends without an answer, and Firefox then tells the site no and saves nothing. Zen's "Block" button, which the prompt shows when the site has no camera or microphone allowed, would set a temporary block on the site instead. While Zen's prompt is hidden, Esc belongs to the picker even when you clicked the page first, and keyboard focus can't move into the hidden prompt, so no key ever acts on a prompt you can't see. While the add-on waits to press Allow for you, Esc does nothing. While the picker is open, Ctrl plus a letter that matches a shortcut of Zen's prompt, such as Ctrl+A or Ctrl+B, does nothing on macOS; elsewhere the same goes for Alt plus that letter.

**The fail-safe.** If anything about Zen's prompt is not what the add-on expects, the picker doesn't open, and Zen's prompt is left exactly as Zen built it, in view. See "How the fail-safe works".

The picker closes without sharing or declining when you switch tabs or spaces, when Zen's prompt goes away, when a listed tab is closed or put to sleep, and when you turn the picker off. None of these declines the request: it stays with Zen's prompt. Only Esc and Cancel decline.

## Requirements

* Zen 1.24.2b or later (Firefox 160).
* A profile that allows unsigned add-ons and experiment add-ons. The installer sets that up.
* For the install script: [uv](https://docs.astral.sh/uv/), on macOS or Linux. The script uses only the Python standard library. Building the add-on from a checkout (the default) also needs `zip`.

## Install

First, what the install enables in your profile. The add-on is unsigned and uses an experiment API, so the installer writes a block into your profile's `user.js` that turns on:

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

By default the script builds the add-on from your checkout. To install the latest GitHub release instead, add `--latest`. That only works once a release has been published.

The script prints each change it makes. It keeps everything else in your `user.js`, and writes through it if it is a symlink. A symlink whose target doesn't exist is refused before anything is written. Running it again updates the block in place.

Flags:

| Flag | What it does |
|---|---|
| `--profile PATH` | Use this profile directory. Needed when `--zen-dir` and auto-detection can't pick one. Find yours at `about:profiles`. |
| `--zen-dir PATH` | Zen's data directory (the one holding `profiles.ini`), when it isn't in the default place, or when the script finds several. |
| `--xpi PATH` | Install this XPI instead of building from the checkout. |
| `--latest` | Download the latest GitHub release and install that. Over HTTPS only, and it checks the add-on id before writing anything. |
| `--dry-run` | Print every change and write nothing. |
| `--uninstall` | Remove the add-on, the block, and the prefs it set (see "Uninstall"). |
| `--print-block` | Print the `user.js` block and exit. Touches no profile. |

`--xpi` and `--latest` can't be combined. With several Zen installs in the data directory, the script lists the default profile of each and asks for `--profile`. With several data directories (on Linux, a native install next to a Flatpak one), it lists them and asks for `--zen-dir` or `--profile`. On Windows only `--print-block` works, so install by hand.

By hand, without the script: quit Zen, copy the XPI to `<profile>/extensions/zen-share-picker@zippeurfou.github.io.xpi` (make the `extensions` folder if it is missing), and add the output of `uv run scripts/install.py --print-block` to `<profile>/user.js`.

## Update

Zen checks for a new version of the add-on once a day and installs it in place, from the GitHub release. The update file carries the sha256 of the release file, and the update URL is HTTPS. That hash protects against a corrupted or swapped download. It does not protect against a compromised release, because the same release workflow writes the hash. Updates trust this GitHub repository and its workflow.

A self-update does not touch your `user.js`. If a release ever changes the block, its release notes say so, and you re-run the installer. Once a release exists, `uv run scripts/install.py --latest` updates by hand. Pull the checkout first (`git pull`), since the installer builds the block from the checkout's own script.

## Uninstall

Quit Zen, then:

```sh
uv run scripts/install.py --uninstall
```

This removes the add-on file and the block from `user.js`. Zen also copies the `user.js` values into `prefs.js`, so removing the block alone resets nothing. The script therefore deletes the lines for exactly the prefs the block set from `prefs.js` too, and prints each one. They go back to Zen's defaults: unsigned add-ons off, experiments off, and sideloaded add-ons prompting again. A custom value you had for one of those prefs before installing is not restored. If zen-space-scope is installed, its own block sets its prefs again at the next start, and the script says so when another block in `user.js` still sets any of the 4. Add `--dry-run` to see what it would do first.

The script is the simpler path. It also deletes `user.js` when the block was its only content. If you would rather do it by hand, the block sets these 4 prefs (`uv run scripts/install.py --print-block` prints them with their values, and is the source of truth):

```
xpinstall.signatures.required
extensions.experiments.enabled
extensions.autoDisableScopes
extensions.startupScanScopes
```

The order matters, because Zen re-applies `user.js` at every start and rewrites `prefs.js` when it quits:

1. Quit Zen.
2. Delete `<profile>/extensions/zen-share-picker@zippeurfou.github.io.xpi`.
3. Remove the block from `user.js`, from the `// zen-share-picker: begin` line to the `// zen-share-picker: end` line.
4. Still with Zen quit, delete the `user_pref(...)` line of each of the 4 prefs from `prefs.js`. Then start Zen.

If you prefer `about:config`, do steps 1 to 3, start Zen, click Reset on each of the 4 prefs, then quit and start Zen again so the change is saved. Skip step 4 in that case. Editing `prefs.js` while Zen runs doesn't work: Zen overwrites it when it quits.

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

Each prompt is checked again when it opens. If the prompt is missing a part, if an entry can't be mapped to a tab, or if anything throws, that prompt gets no picker. The add-on records a reason code and leaves the prompt as Zen built it. The next prompt gets a fresh try.

Zen's prompt is hidden only while a picker is open for it, or while the add-on is pressing Allow or declining for you, and only when Zen's panel holds that prompt alone. If hiding it fails, the picker stays away (`conceal-failed`). If Zen's prompt was already open before the add-on could prepare it, for example because you turned the picker on while it was showing, the picker stays away too and you answer Zen's prompt as usual. Every way the picker closes ends the hiding. Turning the picker off, and removing or updating the add-on, also clear the hiding in every window, and a window the add-on starts watching is cleared first.

The status page shows both. Open `about:addons`, pick Zen Share Picker and open its options page.

## Troubleshooting

The options page shows the state (`active`, `inert`, `disabled` or `starting`), the version, the failed checks, the last outcome, the codes of the last 10 prompts that got no picker, the on/off switch and the debug log.

The on/off switch lasts until Zen restarts. The add-on starts switched on every time, so to turn the picker off for good, disable the add-on in `about:addons`.

**No picker opens.** Check the state on the options page.

* `inert`: look at the failed checks. Switch the picker on to run the checks again. If `modules` failed, nothing can retry until you restart Zen, and a `start` failure may need a restart too.
* `active`, with a code under "Prompts without a picker": that prompt didn't look as expected. The table below says what each code means.
* `active`, with no code: check that Zen's prompt lists tabs. Open its dropdown. If it shows only screens, windows or "Use operating system settings", there is nothing for the picker to offer. The picker also stays away from camera and microphone requests, and from screen requests that also ask for audio.
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

After a Zen update, a failed check or a repeated code usually means Zen changed code the add-on relies on. Open an issue with the code, and attach the debug log.

**The last outcome.** `shared` means the tab is being shared and the add-on saw it. `handed-off` means your system's picker took over. `declined` means you pressed Esc or Cancel and the request was declined. `cancelled` means you pressed Esc or Cancel but nothing was declined: the prompt was already gone, or the decline failed and Zen's prompt is yours to answer. `stock` means the "Apps, windows or a screen..." row handed you Zen's own dropdown. `aborted` means nothing was clicked, for example because the prompt went away first. `unverified` means Allow was pressed, but the add-on never saw the share start.

**The outcome is `assist`.** Zen didn't take the add-on's click on Allow in time, for example because the window wasn't active. Your tab is already selected in Zen's prompt, with its preview. Press Allow yourself. The add-on never presses it again for that prompt.

**The installer says Zen is running.** Quit Zen with Cmd+Q and run the same command again. The script also refuses when it can't tell whether the profile is locked, and the message says why.

**The installer lists several Zen installs or data directories.** Pass `--profile` with the path from `about:profiles`.

**The debug log.** Turn it on in the options page to log what the picker decides. It is off by default, lives in memory only, keeps at most 2000 lines, and is emptied when you turn it off. It holds:

* the number of entries in each prompt, and the number of tabs, in the current space and in total;
* the hosts of current-space rows, and of other spaces' rows once you press Tab;
* device ids (Firefox's numbers for the tabs in the prompt);
* outcome and problem codes, including the steps of each share, any failed check, and the switch going off or on.

It never holds a title or an image. The total tab count includes tabs from other spaces that other windows show, so the log tells how many there are, but not what they are. Check the hosts before pasting it into an issue.

## Known limitations

* Tab capture in Firefox can run at a lower frame rate than a window share (bug 1717868, unconfirmed).
* Tabs that are asleep, and tabs in a collapsed group, can't be shared from Zen's prompt. Firefox leaves them out of the list, so the picker can't show them. Open the tab first.
* Share prompts shown in Zen's sidebar are not handled.
* A site that asks for your screen and your microphone (or a tab's audio) in one request gets Zen's own prompt, so one Enter never grants audio the picker didn't show.
* An Essential from another container counts as another space, even when Zen shows Essentials in every space. It stays hidden until Tab.
* A tab whose space or container can't be read counts as another space. When the call runs in a private window, every tab does.
* A prompt the picker handed back to you doesn't get the picker again: after a decline that failed, after the "Apps, windows or a screen..." row left you in Zen's dropdown, or after a share Zen didn't take. Use Zen's prompt, or ask the site to share again.
* If another notification is already in Zen's panel when the picker opens, or joins it while the picker is open, Zen's prompt stays in view. It can cover the top left of the picker, and a click there lands in Zen's prompt instead of the picker. The keyboard still works. Zen's dropdown lists every tab Zen offers, other spaces included, so don't open it while presenting.
* The "Apps, windows or a screen..." row hands over to your system's picker wherever Zen's prompt has a "Use operating system settings" entry: on macOS, and on Linux with PipeWire. Without that entry (Linux on X11 without PipeWire, or headless), the row closes the picker and puts the focus on Zen's dropdown, where you pick a screen or window yourself.
* Switching the picker back on while a share prompt is open doesn't open a picker on that prompt until Zen shows it again.

Not supported:

* regular Firefox;
* addons.mozilla.org. The add-on is unsigned, so it ships as a GitHub release file.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). How it works, and why, is in [docs/design.md](docs/design.md). The license is MPL-2.0.
