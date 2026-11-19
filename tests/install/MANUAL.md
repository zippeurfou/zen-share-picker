# Installer: manual real run

`tests/install/test_install.py` covers the installer against fake profile
trees. These scripts are the checks against a real Zen. They never use
`-CreateProfile` and never touch a registered profile or `profiles.ini` /
`installs.ini`: each one makes a temporary directory, passes it to
`scripts/install.py --profile <dir>`, and launches Zen on it through the
acceptance harness (unregistered `-no-remote -new-instance -profile <dir>`).
Every Zen they start is quit and its processes killed; the directory is
deleted at the end.

```sh
HEADLESS=1 uv run --project tests/acceptance python tests/install/real_run.py
HEADLESS=1 uv run --project tests/acceptance python tests/install/real_run.py --existing
HEADLESS=1 uv run --project tests/acceptance python tests/install/real_run.py --existing --no-sideload-prefs
HEADLESS=1 uv run --project tests/acceptance python tests/install/real_running.py
HEADLESS=1 uv run --project tests/acceptance python tests/install/real_uninstall.py
```

The harness sets `MOZ_REMOTE_ALLOW_SYSTEM_ACCESS=1` for the Zen it starts, so
the commands need nothing more.

`real_run.py` runs the installer, starts Zen and asks it for the add-on's
state and `getStatus()`. `--existing` lets Zen run once on the profile before
the install. `--no-sideload-prefs` is a control: it pins Zen's shipped values
(`autoDisableScopes=15`, `startupScanScopes=0`) in place of the installer's.

## Results (Zen 1.24.2b, macOS, 2026-11-18)

| Check | What was seen | Outcome |
| --- | --- | --- |
| `real_run.py` (fresh profile) | `isActive: true`, `userDisabled: false`, `scope: 1` (profile), `foreignInstall: true`, `getStatus().state: "active"` | PASS |
| `real_run.py --existing` (Zen ran once before the install) | same | PASS |
| `real_run.py --existing --no-sideload-prefs` (control) | `isActive: false`, `userDisabled: true` | FAIL, as expected |
| `real_running.py` | while the harness Zen holds `.parentlock`: install exit 1 and `--uninstall` exit 1 ("Zen is running on ..."), `--dry-run` exit 0 with "note: Zen may be running on this profile", nothing written; after Zen quit, install exit 0 | PASS |
| `real_uninstall.py` | every step below ok | PASS |
| `install.py --profile <dir> --latest` | exit 1, "no release has been published yet; pass --xpi PATH ...", nothing written | as expected while no release exists |

No test Zen process and no temporary profile was left after the runs.

Reading: with `extensions.autoDisableScopes=14` the sideloaded add-on starts
enabled with no prompt; with Zen's shipped 15 it is added disabled.
Marionette sets `extensions.autoDisableScopes=0` as a default
(`RecommendedPreferences.sys.mjs`), so a user value is needed to see the
effect; the installer's block is a user value, so it wins.

## Running-Zen check (R33)

The profile of a running Zen holds `.parentlock` (macOS has no `lock`
symlink). The installer takes a non-blocking exclusive `fcntl` lock on it:
when another process holds it, install and uninstall refuse and a dry run
warns. Outside dry runs the installer keeps holding that lock until its last
write (a missing `.parentlock` is created for the hold and removed again), so
a Zen started during a build or download finds the profile in use. The unit
tests check the hold from a separate process, and that the lock is free again
after a success, a failure and an interrupt.

## Why `startupScanScopes=1` stays (R34)

`XPIProvider.sys.mjs` runs the startup scan with `ignoreSideloads =
(appChanged === false)` and skips scopes missing from the pref, so on an
already-run profile a new XPI is only found by the later `getNewSideloads`
scan, which lists it as a disabled sideload. That matches the control.

## Install, run, uninstall, run (R32)

`real_uninstall.py`, temp profile, headless:

1. Install, start Zen: add-on `active`. After quitting, `prefs.js` holds the
   four prefs of the block (Zen copies them there) and `extensions.json` lists
   the add-on. This is the leftover state `--uninstall` has to clean.
2. `--uninstall` exits 0.
3. Start Zen: `AddonManager.getAddonByID` is null at once,
   `AddonManagerPrivate.getNewSideloads()` is empty, `ExtensionsUI.sideloaded`
   is empty (no sideload notification), no block pref has a user value, and no
   console message mentions the add-on.
4. After quitting: `prefs.js` has none of the block's names, `extensions.json`
   has no entry, the XPI is gone, `user.js` has no markers.
5. A second start and quit is still clean.

The unit tests add what a real run cannot show cheaply: `--uninstall` deletes
the `user_pref` lines of exactly the four names, keeps every other byte
(including `media.getusermedia.browser.enabled`, which the block does not
set), writes through a symlinked `prefs.js` or `user.js`, and leaves a
zen-space-scope block in `user.js` byte for byte.
