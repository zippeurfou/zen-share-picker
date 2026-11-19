# Contributing

Small, focused changes with a test are the easiest to review. The add-on is privileged and can press Allow on a share prompt, so a change that could share something the user did not pick, or show another space's tab before Tab, needs a test that proves it can't.

[docs/design.md](docs/design.md) explains how the add-on works and resolves the "P13" and "R32" style references in code comments and tests.

## Tooling

Python runs through [uv](https://docs.astral.sh/uv/) only. Don't call `python` or `pip` directly. Scripts use the standard library only. Unit tests need Node 24. Don't commit `uv.lock` files: uv writes the URL of whatever package index your machine uses into them, and CI resolves test dependencies from PyPI instead.

## Running the tests

From the repository root:

```sh
node --test tests/unit/*.test.mjs
uv run --with pytest pytest tests/install
uv run --with pytest --with pyyaml pytest tests/release
HEADLESS=1 MOZ_REMOTE_ALLOW_SYSTEM_ACCESS=1 uv run --project tests/acceptance pytest tests/acceptance
```

The unit tests cover the row model, the screen and window rows, the picker's state machine with its two tabs, the live preview's one-capture rule, the share and decline sequences, the picker's header text and the startup checks, with stubbed Firefox internals. The install tests run the installer against fake profile trees and never touch a real profile. The release tests check the update manifest script and the workflows.

The installer reads one environment variable, `ZEN_SHARE_PICKER_RELEASES_URL`. It is a test hook. It replaces the GitHub API URL that `--latest` asks for the latest release, so the install tests can point it at a fake. It has to be an HTTPS URL, like every URL the installer follows, and anything else is refused before a byte is written. Don't set it for a real install.

The acceptance tests drive a real Zen through Marionette, in a fresh temporary profile each, so a Zen you are using is not touched. They request a screen share from a local page and use the picker the way a user does, real Allow button included. They need Zen 1.24.2b or later. `ZEN_BINARY` points at the executable (it defaults to the macOS app path, or `zen` on Linux), and leaving `HEADLESS` unset lets you watch. `MOZ_REMOTE_ALLOW_SYSTEM_ACCESS=1` is required by Zen for chrome-context scripts; the harness sets it too. Details are in [tests/acceptance/README.md](tests/acceptance/README.md).

On macOS, pressing Allow makes Zen check its screen-recording permission. If macOS denies it, that check would raise a system dialog in the middle of the run. So every test that presses Allow first reads the permission state, and skips with "macOS denies Zen screen capture" when it is denied. Grant Zen screen recording in System Settings to run them.

The default runs never capture a real window or the screen. Tests of the Windows tab use fake windows (tab entries turned into window entries, previews off), and tests that list your real windows read only keys, ids and counts, never a title. The capture tests in `tests/acceptance/test_capture.py` are opt-in. They preview and share a real window and the screen, check that the live preview follows the highlight and that only one capture runs, and check that Enter shares the window or the screen. On macOS 15 and later, the first such capture can raise an alert asking whether Zen may bypass the system private window picker, and macOS can ask again later. So they skip unless you set `ZSP_CAPTURE_TESTS=1`, and they also skip headless and off macOS. Run them headful, at the machine, ready to answer the alert:

```sh
ZSP_CAPTURE_TESTS=1 MOZ_REMOTE_ALLOW_SYSTEM_ACCESS=1 uv run --project tests/acceptance pytest tests/acceptance/test_capture.py -rP
```

To run what CI runs, set `UV_NO_CONFIG=1` first so uv ignores any machine-level config.

## CI

CI runs on every push and once a day. The unit tests run on Linux, the install and release tests on Linux and macOS, and the acceptance tests on Linux, headless, against the latest Zen release. So a Zen update that breaks the add-on shows up without a push. GitHub disables scheduled workflows after 60 days without repository activity. A daily run that has stopped is not a green one, so check that it is still running.

On headless Linux, Zen's prompt has no screen, window or operating-system entry. The tests that need a real one skip, with a reason that says so; the Windows tab runs there on fake windows.

## Releasing

Tag `v<version>`, where the version matches `manifest.json`. The release workflow runs the tests first. Then its release job builds the XPI, fails if the tag and the version differ, hashes the XPI and publishes it with `updates.json`. Never upload release assets by hand: the self-update channel trusts the hash that workflow writes.

If a release changes the installer's `user.js` block, say so in the release notes. Self-updates don't touch `user.js`, so users have to re-run the installer to get the new block.

## Commits

Conventional commits (`feat`, `fix`, `docs`, `refactor`, `test`, `chore`), one logical change each.
