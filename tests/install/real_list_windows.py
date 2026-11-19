"""Real check of --list-windows (P54) against Zen (see MANUAL.md).

Temp profile directory, unregistered `-profile` through the acceptance harness,
HEADLESS=1; never `-CreateProfile`, never a real profile. Nothing here opens a
share prompt or lists a window: it only reads prefs.

  1. install.py --profile <dir> --list-windows; start Zen: the add-on is
     active and the picker pref is false with a user value; quit. prefs.js
     holds the pref's line (Zen copies user.js values there).
  2. install.py --profile <dir> (no flag): it prints the reset, the block has
     the 4 default prefs, and prefs.js has no picker line.
  3. start Zen: the picker pref has no user value; quit. prefs.js still has
     no picker line, and the 4 block prefs are back in it.
  4. install with --list-windows again, start, quit, then --uninstall:
     prefs.js has none of the 5 names.

    HEADLESS=1 uv run --project tests/acceptance python tests/install/real_list_windows.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests" / "acceptance"))
sys.path.insert(0, str(REPO / "scripts"))

from install import ADDON_ID, WINDOWS_PREFS, block_pref_names, build_block
from zen import BASE_PREFS, Zen

INSTALL = ["uv", "run", "--no-project", str(REPO / "scripts" / "install.py")]
PICKER = WINDOWS_PREFS[0][0]
PICKER_LINE = f"user_pref({json.dumps(PICKER)}, false);"
failures: list[str] = []


def check(label: str, ok: bool, detail: object = "") -> None:
    print(
        f"  [{'ok' if ok else 'FAIL'}] {label}"
        + (f": {detail}" if detail != "" else "")
    )
    if not ok:
        failures.append(label)


def installer(profile: Path, *extra: str) -> subprocess.CompletedProcess:
    r = subprocess.run(
        [*INSTALL, "--profile", str(profile), *extra],
        capture_output=True,
        text=True,
        check=False,
    )
    print(f"$ install.py --profile <dir> {' '.join(extra)} -> exit {r.returncode}")
    if r.returncode:
        print(r.stdout, r.stderr)
    return r


PREF_STATE = """
const [name] = args;
return {
  userValue: Services.prefs.prefHasUserValue(name),
  value: Services.prefs.getBoolPref(name, null),
};
"""


def start(profile: Path) -> Zen:
    zen = Zen(prefs={})
    zen.profile = profile  # an existing directory: the harness starts on it as is
    return zen.start()


def quit_keeping_profile(zen: Zen) -> None:
    """Quit Zen and clean up its processes, but keep the profile directory
    (the harness's close() deletes it)."""
    profile, zen.profile = zen.profile, None
    zen.close()
    zen.profile = profile


def run_once(profile: Path) -> dict:
    zen = start(profile)
    try:
        status = zen.wait_addon_active(ADDON_ID)
        state = zen.chrome(PREF_STATE, PICKER)
    finally:
        quit_keeping_profile(zen)
    state["addon"] = status["state"]
    return state


def prefs_lines(profile: Path) -> list[str]:
    path = profile / "prefs.js"
    return path.read_text().splitlines() if path.exists() else []


def block_lines(profile: Path) -> list[str]:
    return [
        line
        for line in prefs_lines(profile)
        if any(f'"{n}"' in line for n in block_pref_names(True))
    ]


def main() -> int:
    profile = Path(tempfile.mkdtemp(prefix="zen-share-picker-list-windows-"))
    try:
        quiet = {k: v for k, v in BASE_PREFS.items() if not k.startswith("extensions.")}
        quiet_js = "".join(
            f"user_pref({json.dumps(k)}, {json.dumps(v)});\n" for k, v in quiet.items()
        )
        (profile / "user.js").write_text(quiet_js)

        print("1. install with --list-windows, start, quit")
        r = installer(profile, "--list-windows")
        check("install exit 0", r.returncode == 0)
        check(
            "user.js holds the 5-pref block",
            (profile / "user.js").read_text() == quiet_js + build_block(True),
        )
        state = run_once(profile)
        print("   in session:", json.dumps(state))
        check("add-on active", state["addon"] == "active", state["addon"])
        check(
            "picker pref is false, as a user value",
            state["value"] is False and state["userValue"],
            state,
        )
        check(
            "prefs.js holds the picker line after the quit",
            PICKER_LINE in prefs_lines(profile),
            block_lines(profile),
        )

        print("2. install again without the flag")
        r = installer(profile)
        check("install exit 0", r.returncode == 0)
        check(
            "it printed the reset",
            f"reset {PICKER} in prefs.js" in r.stdout,
        )
        check(
            "user.js holds the 4-pref block",
            (profile / "user.js").read_text() == quiet_js + build_block(False),
        )
        check(
            "prefs.js has no picker line",
            not any(f'"{PICKER}"' in line for line in prefs_lines(profile)),
            block_lines(profile),
        )
        check(
            "prefs.js keeps the 4 block prefs",
            len(block_lines(profile)) == 4,
            block_lines(profile),
        )

        print("3. start without the flag, quit")
        state = run_once(profile)
        print("   in session:", json.dumps(state))
        check("add-on active", state["addon"] == "active", state["addon"])
        check("picker pref has no user value", not state["userValue"], state)
        check(
            "prefs.js still has no picker line",
            not any(f'"{PICKER}"' in line for line in prefs_lines(profile)),
            block_lines(profile),
        )

        print("4. install with the flag, start, quit, uninstall")
        check("install exit 0", installer(profile, "--list-windows").returncode == 0)
        state = run_once(profile)
        check("picker pref is false again", state["value"] is False, state)
        check("prefs.js holds the picker line", PICKER_LINE in prefs_lines(profile))
        r = installer(profile, "--uninstall")
        check("uninstall exit 0", r.returncode == 0)
        check(
            "it printed the reset of all 5",
            all(f"reset {n} in prefs.js" in r.stdout for n in block_pref_names(True)),
        )
        check(
            "prefs.js has none of the 5 names",
            block_lines(profile) == [],
            block_lines(profile),
        )
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    print("RESULT:", "PASS" if not failures else f"FAIL ({', '.join(failures)})")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
