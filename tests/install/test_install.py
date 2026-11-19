"""Tests for scripts/install.py against fake profile trees.

Nothing here touches a real Zen profile: every test builds a Zen data
directory under tmp_path and passes it with --zen-dir (or a profile with
--profile), and HOME points at an empty temporary directory, so even a
missed flag finds no Zen. Run with `uv run --with pytest pytest tests/install`.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import stat
import subprocess
import sys
import time
import urllib.error
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "install.py"
ADDON_ID = "zen-share-picker@zippeurfou.github.io"
BEGIN = "// zen-share-picker: begin"
END = "// zen-share-picker: end"
RELEASES_ENV = "ZEN_SHARE_PICKER_RELEASES_URL"

BLOCK_LINES = [
    'user_pref("xpinstall.signatures.required", false);',
    'user_pref("extensions.experiments.enabled", true);',
    'user_pref("extensions.autoDisableScopes", 14);',
    'user_pref("extensions.startupScanScopes", 1);',
]
EXPECTED_BLOCK = "\n".join([BEGIN, *BLOCK_LINES, END]) + "\n"
BLOCK_NAMES = [line.split('"')[1] for line in BLOCK_LINES]

# --list-windows adds this line, last (P54).
PICKER = "media.getdisplaymedia.screencapturekit.picker.enabled"
PICKER_LINE = f'user_pref("{PICKER}", false);'
WINDOWS_BLOCK = "\n".join([BEGIN, *BLOCK_LINES, PICKER_LINE, END]) + "\n"
ALL_NAMES = [*BLOCK_NAMES, PICKER]


def _uv_dir(what: str) -> str:
    out = subprocess.run(["uv", what, "dir"], capture_output=True, text=True)
    return out.stdout.strip()


# uv keeps finding its cache and Pythons while HOME is a temporary directory.
UV_ENV = {
    "UV_CACHE_DIR": _uv_dir("cache"),
    "UV_PYTHON_INSTALL_DIR": _uv_dir("python"),
}


@pytest.fixture(autouse=True)
def fake_home(tmp_path_factory, monkeypatch):
    """Every test, and every installer it runs, sees an empty HOME: profile
    auto-detection can never reach a real Zen data directory."""
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    for name, value in UV_ENV.items():
        if value:
            monkeypatch.setenv(name, value)
    return home


def _require_temp_target(args: tuple[str, ...]) -> None:
    assert "--profile" in args or "--zen-dir" in args, (
        f"installer run without --profile or --zen-dir: {args}"
    )


def run(*args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    _require_temp_target(args)
    full_env = {**os.environ, **(env or {})}
    return subprocess.run(
        ["uv", "run", "--no-project", str(SCRIPT), *args],
        check=False,
        capture_output=True,
        text=True,
        env=full_env,
        cwd=REPO,
    )


def make_xpi(path: Path, addon_id: str | None = ADDON_ID) -> Path:
    manifest = {"manifest_version": 2, "name": "x", "version": "9.9.9"}
    if addon_id is not None:
        manifest["browser_specific_settings"] = {"gecko": {"id": addon_id}}
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("manifest.json", json.dumps(manifest))
    return path


@pytest.fixture
def xpi(tmp_path: Path) -> Path:
    return make_xpi(tmp_path / "zen-share-picker-9.9.9.xpi")


def load_installer():
    spec = importlib.util.spec_from_file_location("zsp_install", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_profile(root: Path, rel: str = "Profiles/abc.Default") -> Path:
    p = root / rel
    p.mkdir(parents=True)
    return p


def mac_tree(tmp_path: Path) -> tuple[Path, Path]:
    """macOS layout: installs.ini names the default profile."""
    root = tmp_path / "Library" / "Application Support" / "zen"
    profile = make_profile(root, "Profiles/abc.Default (release)")
    other = make_profile(root, "Profiles/xyz.Other")
    (root / "profiles.ini").write_text(
        "[Profile1]\nName=Other\nIsRelative=1\nPath=Profiles/xyz.Other\n\n"
        "[Profile0]\nName=Default (release)\nIsRelative=1\n"
        "Path=Profiles/abc.Default (release)\nDefault=1\n\n"
        "[General]\nStartWithLastProfile=1\nVersion=2\n"
    )
    (root / "installs.ini").write_text(
        "[ABCDEF0123456789]\nDefault=Profiles/abc.Default (release)\nLocked=1\n"
    )
    assert other.is_dir()
    return root, profile


def linux_tree(tmp_path: Path) -> tuple[Path, Path]:
    """Linux layout: no installs.ini, the Default=1 profile of profiles.ini,
    and an absolute path."""
    root = tmp_path / ".zen"
    profile = tmp_path / "elsewhere" / "p1.default"
    profile.mkdir(parents=True)
    other = make_profile(root, "q2.second")
    (root / "profiles.ini").write_text(
        f"[Profile1]\nName=second\nIsRelative=1\nPath={other.name}\n\n"
        f"[Profile0]\nName=default\nIsRelative=0\nPath={profile}\nDefault=1\n\n"
        "[General]\nStartWithLastProfile=1\nVersion=2\n"
    )
    return root, profile


# -- profile discovery ------------------------------------------------------


def test_discovers_default_profile_from_installs_ini(tmp_path, xpi):
    root, profile = mac_tree(tmp_path)
    r = run("--zen-dir", str(root), "--xpi", str(xpi))
    assert r.returncode == 0, r.stderr
    assert (profile / "extensions" / f"{ADDON_ID}.xpi").exists()
    assert str(profile) in r.stdout


def test_discovers_default_profile_from_profiles_ini_on_linux(tmp_path, xpi):
    root, profile = linux_tree(tmp_path)
    r = run("--zen-dir", str(root), "--xpi", str(xpi))
    assert r.returncode == 0, r.stderr
    assert (profile / "extensions" / f"{ADDON_ID}.xpi").exists()


def test_installs_ini_wins_over_default_flag(tmp_path, xpi):
    root, _ = mac_tree(tmp_path)
    other = root / "Profiles" / "xyz.Other"
    (root / "installs.ini").write_text(f"[AAAA]\nDefault={'Profiles/xyz.Other'}\n")
    r = run("--zen-dir", str(root), "--xpi", str(xpi))
    assert r.returncode == 0, r.stderr
    assert (other / "extensions" / f"{ADDON_ID}.xpi").exists()


def test_install_section_in_profiles_ini(tmp_path, xpi):
    root, _ = mac_tree(tmp_path)
    (root / "installs.ini").unlink()
    other = root / "Profiles" / "xyz.Other"
    with open(root / "profiles.ini", "a") as f:
        f.write("\n[InstallABC]\nDefault=Profiles/xyz.Other\nLocked=1\n")
    r = run("--zen-dir", str(root), "--xpi", str(xpi))
    assert r.returncode == 0, r.stderr
    assert (other / "extensions" / f"{ADDON_ID}.xpi").exists()


def test_ambiguous_installs_asks_for_profile(tmp_path, xpi):
    root, profile = mac_tree(tmp_path)
    (root / "installs.ini").write_text(
        "[AAAA]\nDefault=Profiles/xyz.Other\n[BBBB]\nDefault=Profiles/other2\n"
    )
    (root / "profiles.ini").write_text("[General]\nVersion=2\n")
    r = run("--zen-dir", str(root), "--xpi", str(xpi))
    assert r.returncode != 0
    assert "--profile" in r.stderr
    assert not (profile / "extensions").exists()


def test_no_zen_dir_is_a_clear_error(tmp_path, xpi):
    r = run("--zen-dir", str(tmp_path / "nothing"), "--xpi", str(xpi))
    assert r.returncode != 0
    assert "--profile" in r.stderr


def test_explicit_profile_skips_discovery(tmp_path, xpi):
    profile = make_profile(tmp_path, "p")
    r = run("--profile", str(profile), "--xpi", str(xpi))
    assert r.returncode == 0, r.stderr
    assert (profile / "user.js").exists()


def test_profile_must_exist(tmp_path, xpi):
    r = run("--profile", str(tmp_path / "missing"), "--xpi", str(xpi))
    assert r.returncode != 0
    assert not (tmp_path / "missing").exists()


# -- the block -----------------------------------------------------------------


def print_block(tmp_path: Path) -> str:
    """--print-block, with a temporary --profile as every run here has."""
    r = run("--print-block", "--profile", str(tmp_path))
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_block_is_exactly_the_four_prefs(tmp_path):
    assert print_block(tmp_path) == EXPECTED_BLOCK
    assert sorted(p.name for p in tmp_path.iterdir()) == []


def test_block_inserted_once_and_rerun_does_not_duplicate(tmp_path, xpi):
    profile = make_profile(tmp_path, "p")
    for _ in range(3):
        r = run("--profile", str(profile), "--xpi", str(xpi))
        assert r.returncode == 0, r.stderr
    text = (profile / "user.js").read_text()
    assert text.count(BEGIN) == 1
    assert text.count(END) == 1
    assert text == EXPECTED_BLOCK


def test_unrelated_lines_kept_and_stale_block_replaced(tmp_path, xpi):
    profile = make_profile(tmp_path, "p")
    (profile / "user.js").write_text(
        'user_pref("a.b", 1);\n'
        f'{BEGIN}\nuser_pref("old", true);\n{END}\n'
        '// mine\nuser_pref("c.d", "x");\n'
    )
    r = run("--profile", str(profile), "--xpi", str(xpi))
    assert r.returncode == 0, r.stderr
    text = (profile / "user.js").read_text()
    assert text.startswith('user_pref("a.b", 1);\n')
    assert text.endswith('// mine\nuser_pref("c.d", "x");\n')
    assert '"old"' not in text
    assert text.count(BEGIN) == 1


def test_begin_without_end_is_refused(tmp_path, xpi):
    profile = make_profile(tmp_path, "p")
    original = f'{BEGIN}\nuser_pref("x", 1);\n'
    (profile / "user.js").write_text(original)
    r = run("--profile", str(profile), "--xpi", str(xpi))
    assert r.returncode != 0
    assert (profile / "user.js").read_text() == original
    assert not (profile / "extensions").exists()


def test_symlinked_user_js_is_written_through(tmp_path, xpi):
    profile = make_profile(tmp_path, "p")
    target = tmp_path / "dotfiles" / "user.js"
    target.parent.mkdir()
    target.write_text('user_pref("keep", true);\n')
    (profile / "user.js").symlink_to(target)
    r = run("--profile", str(profile), "--xpi", str(xpi))
    assert r.returncode == 0, r.stderr
    assert (profile / "user.js").is_symlink()
    assert BEGIN in target.read_text()
    assert target.read_text().startswith('user_pref("keep", true);\n')
    assert "symlink" in r.stdout and str(target) in r.stdout
    r = run("--profile", str(profile), "--uninstall")
    assert r.returncode == 0, r.stderr
    assert (profile / "user.js").is_symlink()
    assert target.read_text() == 'user_pref("keep", true);\n'


@pytest.mark.parametrize(
    "extra", [(), ("--dry-run",), ("--uninstall",), ("--uninstall", "--dry-run")]
)
def test_dangling_user_js_symlink_is_refused(tmp_path, xpi, extra):
    """A user.js symlink whose target does not exist is
    refused before any write, and no directory is created outside the
    profile."""
    profile = make_profile(tmp_path, "p")
    target = tmp_path / "dotfiles" / "zen" / "user.js"
    (profile / "user.js").symlink_to(target)
    (profile / "extensions").mkdir()
    (profile / "extensions" / f"{ADDON_ID}.xpi").write_bytes(b"old")
    write_prefs_js(profile)
    before = snapshot(profile)
    r = run("--profile", str(profile), "--xpi", str(xpi), *extra)
    assert r.returncode != 0 and "Traceback" not in r.stderr
    assert "symlink" in r.stderr and str(target) in r.stderr
    assert "does not exist" in r.stderr and "nothing was changed" in r.stderr
    assert not (tmp_path / "dotfiles").exists()
    assert snapshot(profile) == before
    assert os.readlink(profile / "user.js") == str(target)


def test_uninstall_restores_file_byte_for_byte(tmp_path, xpi):
    profile = make_profile(tmp_path, "p")
    original = (
        b'user_pref("a", 1);\r\n\n// odd \xc3\xa9 spacing  \nuser_pref("b", 2);\n'
    )
    (profile / "user.js").write_bytes(original)
    run("--profile", str(profile), "--xpi", str(xpi))
    assert (profile / "user.js").read_bytes() != original
    r = run("--profile", str(profile), "--uninstall")
    assert r.returncode == 0, r.stderr
    assert (profile / "user.js").read_bytes() == original
    assert not (profile / "extensions" / f"{ADDON_ID}.xpi").exists()


def test_uninstall_removes_a_user_js_the_installer_created(tmp_path, xpi):
    profile = make_profile(tmp_path, "p")
    run("--profile", str(profile), "--xpi", str(xpi))
    r = run("--profile", str(profile), "--uninstall")
    assert r.returncode == 0, r.stderr
    assert not (profile / "user.js").exists()


def test_uninstall_when_nothing_installed_is_a_noop(tmp_path):
    profile = make_profile(tmp_path, "p")
    (profile / "user.js").write_text("x\n")
    r = run("--profile", str(profile), "--uninstall")
    assert r.returncode == 0, r.stderr
    assert (profile / "user.js").read_text() == "x\n"


def test_uninstall_leaves_other_extensions(tmp_path, xpi):
    profile = make_profile(tmp_path, "p")
    run("--profile", str(profile), "--xpi", str(xpi))
    (profile / "extensions" / "other@x.xpi").write_bytes(b"x")
    run("--profile", str(profile), "--uninstall")
    assert (profile / "extensions" / "other@x.xpi").exists()


# -- dry run, running Zen, XPI sources ---------------------------------------------


def snapshot(root: Path) -> dict[str, bytes | None]:
    return {
        str(p.relative_to(root)): (p.read_bytes() if p.is_file() else None)
        for p in sorted(root.rglob("*"))
    }


def test_dry_run_writes_nothing_and_prints_changes(tmp_path, xpi):
    profile = make_profile(tmp_path, "p")
    (profile / "user.js").write_text('user_pref("a", 1);\n')
    before = snapshot(profile)
    r = run("--profile", str(profile), "--xpi", str(xpi), "--dry-run")
    assert r.returncode == 0, r.stderr
    assert snapshot(profile) == before
    assert "user.js" in r.stdout and ADDON_ID in r.stdout
    assert "dry run" in r.stdout.lower()


def test_dry_run_uninstall_writes_nothing(tmp_path, xpi):
    profile = make_profile(tmp_path, "p")
    run("--profile", str(profile), "--xpi", str(xpi))
    before = snapshot(profile)
    r = run("--profile", str(profile), "--uninstall", "--dry-run")
    assert r.returncode == 0, r.stderr
    assert snapshot(profile) == before


def test_refuses_while_zen_runs_on_the_profile(tmp_path, xpi):
    profile = make_profile(tmp_path, "p")
    # Zen's lock: a dangling symlink "<ip>:+<pid>". Our parent is alive.
    (profile / "lock").symlink_to(f"127.0.0.1:+{os.getpid()}")
    r = run("--profile", str(profile), "--xpi", str(xpi))
    assert r.returncode != 0
    assert "running" in r.stderr.lower()
    assert not (profile / "user.js").exists()
    assert not (profile / "extensions").exists()


def test_stale_lock_does_not_block(tmp_path, xpi):
    profile = make_profile(tmp_path, "p")
    (profile / "lock").symlink_to("127.0.0.1:+999999999")
    r = run("--profile", str(profile), "--xpi", str(xpi))
    assert r.returncode == 0, r.stderr


def test_default_builds_xpi_from_checkout(tmp_path):
    profile = make_profile(tmp_path, "p")
    r = run("--profile", str(profile))
    assert r.returncode == 0, r.stderr
    xpi = profile / "extensions" / f"{ADDON_ID}.xpi"
    assert xpi.stat().st_size > 1000


def test_missing_xpi_file_is_an_error_and_writes_nothing(tmp_path):
    profile = make_profile(tmp_path, "p")
    r = run("--profile", str(profile), "--xpi", str(tmp_path / "nope.xpi"))
    assert r.returncode != 0
    assert not (profile / "user.js").exists()


def test_latest_fails_gracefully_without_release(tmp_path):
    profile = make_profile(tmp_path, "p")
    # An unreachable API base makes this deterministic and offline.
    r = run(
        "--profile",
        str(profile),
        "--latest",
        env={"ZEN_SHARE_PICKER_RELEASES_URL": "https://127.0.0.1:9/none"},
    )
    assert r.returncode != 0
    assert "Traceback" not in r.stderr
    assert "--xpi" in r.stderr
    assert not (profile / "user.js").exists()
    assert not (profile / "extensions").exists()


def test_xpi_and_latest_are_exclusive(tmp_path, xpi):
    profile = make_profile(tmp_path, "p")
    r = run("--profile", str(profile), "--xpi", str(xpi), "--latest")
    assert r.returncode != 0


# -- what the user is told ----------------------------------------------------------


def test_output_explains_start_defaults_and_uninstall(tmp_path, xpi):
    profile = make_profile(tmp_path, "p")
    r = run("--profile", str(profile), "--xpi", str(xpi))
    out = r.stdout.lower()
    assert "default" in out
    assert "--uninstall" in out
    assert "start zen" in out


def test_module_imports_without_side_effects():
    r = subprocess.run(
        [
            "uv",
            "run",
            "--no-project",
            "python",
            "-c",
            (
                f"import importlib.util as u;s=u.spec_from_file_location('i','{SCRIPT}');"
                "m=u.module_from_spec(s);s.loader.exec_module(m);print(callable(m.main))"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert r.stdout.strip() == "True", r.stderr


if __name__ == "__main__":
    sys.exit(pytest.main([__file__]))


# -- uninstall resets the block's prefs in prefs.js (R32) ----------------------------

PREFS_JS_HEAD = (
    "// Mozilla User Preferences\n"
    'user_pref("browser.startup.homepage", "about:blank");\r\n'
    'user_pref("browser.urlbar.suggest.history.custom", 1);\n'
)
PREFS_JS_TAIL = 'user_pref("zzz.last", "caf\xc3\xa9 x");'


def block_names() -> list[str]:
    # test_block_is_exactly_the_four_prefs ties these to --print-block.
    return list(BLOCK_NAMES)


def write_prefs_js(profile: Path, with_block_prefs: bool = True) -> bytes:
    lines = PREFS_JS_HEAD
    if with_block_prefs:
        for i, name in enumerate(block_names()):
            lines += f'user_pref("{name}", {"true" if i % 2 else "false"});\n'
    lines += PREFS_JS_TAIL  # no trailing newline on purpose
    data = lines.encode("utf-8")
    (profile / "prefs.js").write_bytes(data)
    return data


def test_uninstall_deletes_exactly_the_block_prefs_from_prefs_js(tmp_path, xpi):
    profile = make_profile(tmp_path, "p")
    run("--profile", str(profile), "--xpi", str(xpi))
    write_prefs_js(profile)
    r = run("--profile", str(profile), "--uninstall")
    assert r.returncode == 0, r.stderr
    assert (profile / "prefs.js").read_bytes() == (
        PREFS_JS_HEAD + PREFS_JS_TAIL
    ).encode("utf-8")
    for name in block_names():
        assert name in r.stdout
    assert "reset" in r.stdout.lower()


def test_uninstall_prefs_js_only_removes_whole_exact_names(tmp_path, xpi):
    profile = make_profile(tmp_path, "p")
    run("--profile", str(profile), "--xpi", str(xpi))
    keep = (
        'user_pref("extensions.experiments.enabled.later", true);\n'
        'user_pref("extensions.startupScanScopesX", 3);\n'
    )
    (profile / "prefs.js").write_text(
        keep + 'user_pref("extensions.experiments.enabled", true);\n'
    )
    run("--profile", str(profile), "--uninstall")
    assert (profile / "prefs.js").read_text() == keep


def test_uninstall_dry_run_leaves_prefs_js(tmp_path, xpi):
    profile = make_profile(tmp_path, "p")
    run("--profile", str(profile), "--xpi", str(xpi))
    data = write_prefs_js(profile)
    r = run("--profile", str(profile), "--uninstall", "--dry-run")
    assert r.returncode == 0, r.stderr
    assert (profile / "prefs.js").read_bytes() == data
    assert "extensions.startupScanScopes" in r.stdout


def test_uninstall_without_prefs_js_is_fine(tmp_path, xpi):
    profile = make_profile(tmp_path, "p")
    run("--profile", str(profile), "--xpi", str(xpi))
    r = run("--profile", str(profile), "--uninstall")
    assert r.returncode == 0, r.stderr
    assert not (profile / "prefs.js").exists()


def test_uninstall_prefs_js_without_block_prefs_untouched(tmp_path, xpi):
    profile = make_profile(tmp_path, "p")
    run("--profile", str(profile), "--xpi", str(xpi))
    data = write_prefs_js(profile, with_block_prefs=False)
    run("--profile", str(profile), "--uninstall")
    assert (profile / "prefs.js").read_bytes() == data


def test_uninstall_symlinked_prefs_js_written_through(tmp_path, xpi):
    profile = make_profile(tmp_path, "p")
    run("--profile", str(profile), "--xpi", str(xpi))
    real = tmp_path / "dotfiles" / "prefs.js"
    real.parent.mkdir()
    (profile / "prefs.js").symlink_to(real)
    write_prefs_js(profile)
    r = run("--profile", str(profile), "--uninstall")
    assert r.returncode == 0, r.stderr
    assert (profile / "prefs.js").is_symlink()
    assert real.read_bytes() == (PREFS_JS_HEAD + PREFS_JS_TAIL).encode("utf-8")


def test_uninstall_resets_prefs_even_if_user_js_block_is_gone(tmp_path, xpi):
    profile = make_profile(tmp_path, "p")
    write_prefs_js(profile)
    r = run("--profile", str(profile), "--uninstall")
    assert r.returncode == 0, r.stderr
    assert (profile / "prefs.js").read_bytes() == (
        PREFS_JS_HEAD + PREFS_JS_TAIL
    ).encode("utf-8")


TAB_SHARING = 'user_pref("media.getusermedia.browser.enabled", true);\n'


def test_uninstall_leaves_tab_sharing_alone(tmp_path, xpi):
    """The block does not set the tab-sharing pref, so uninstall keeps it."""
    profile = make_profile(tmp_path, "p")
    run("--profile", str(profile), "--xpi", str(xpi))
    block_prefs = "".join(f'user_pref("{n}", true);\n' for n in block_names())
    (profile / "prefs.js").write_bytes(
        (PREFS_JS_HEAD + TAB_SHARING + block_prefs + PREFS_JS_TAIL).encode("utf-8")
    )
    r = run("--profile", str(profile), "--uninstall")
    assert r.returncode == 0, r.stderr
    assert (profile / "prefs.js").read_bytes() == (
        PREFS_JS_HEAD + TAB_SHARING + PREFS_JS_TAIL
    ).encode("utf-8")
    assert "media.getusermedia" not in r.stdout


OTHER_BLOCK = (
    "// zen-space-scope: begin\n"
    'user_pref("xpinstall.signatures.required", false);\n'
    'user_pref("extensions.experiments.enabled", true);\n'
    'user_pref("extensions.autoDisableScopes", 14);\n'
    'user_pref("extensions.startupScanScopes", 1);\n'
    'user_pref("browser.urlbar.suggest.history", false);\n'
    "// zen-space-scope: end\n"
)


def test_other_addon_block_is_left_alone(tmp_path, xpi):
    profile = make_profile(tmp_path, "p")
    original = 'user_pref("a", 1);\n' + OTHER_BLOCK + 'user_pref("b", 2);\n'
    (profile / "user.js").write_text(original)
    r = run("--profile", str(profile), "--xpi", str(xpi))
    assert r.returncode == 0, r.stderr
    text = (profile / "user.js").read_text()
    assert text == original + EXPECTED_BLOCK
    r = run("--profile", str(profile), "--xpi", str(xpi))
    assert r.returncode == 0, r.stderr
    assert (profile / "user.js").read_text() == original + EXPECTED_BLOCK
    r = run("--profile", str(profile), "--uninstall")
    assert r.returncode == 0, r.stderr
    assert (profile / "user.js").read_text() == original


def test_uninstall_says_another_block_sets_the_prefs_again(tmp_path, xpi):
    """With zen-space-scope's block still setting the same
    prefs, uninstall does not claim they are back at Zen's defaults."""
    profile = make_profile(tmp_path, "p")
    (profile / "user.js").write_text(OTHER_BLOCK)
    run("--profile", str(profile), "--xpi", str(xpi))
    write_prefs_js(profile)
    r = run("--profile", str(profile), "--uninstall")
    assert r.returncode == 0, r.stderr
    assert "back at Zen's defaults" not in r.stdout
    last = r.stdout.strip().splitlines()[-1]
    assert "Zen applies them again at the next start" in last, last
    for name in block_names():
        assert name in last, (name, last)
    # Dry run: the same caveat.
    run("--profile", str(profile), "--xpi", str(xpi))
    r = run("--profile", str(profile), "--uninstall", "--dry-run")
    assert "Zen applies them again at the next start" in r.stdout


def test_uninstall_names_only_the_prefs_another_block_sets(tmp_path, xpi):
    profile = make_profile(tmp_path, "p")
    other = (
        "// mine\n"
        'user_pref("extensions.experiments.enabled", true);\n'
        '// user_pref("xpinstall.signatures.required", false);\n'
    )
    (profile / "user.js").write_text(other)
    run("--profile", str(profile), "--xpi", str(xpi))
    last = run("--profile", str(profile), "--uninstall").stdout.strip().splitlines()[-1]
    assert "extensions.experiments.enabled" in last, last
    assert "xpinstall.signatures.required" not in last, last
    assert "Zen applies them again at the next start" in last, last


def test_uninstall_without_another_block_says_defaults(tmp_path, xpi):
    profile = make_profile(tmp_path, "p")
    (profile / "user.js").write_text('user_pref("a", 1);\n')
    run("--profile", str(profile), "--xpi", str(xpi))
    last = run("--profile", str(profile), "--uninstall").stdout.strip().splitlines()[-1]
    assert "back at Zen's defaults" in last, last
    assert "again at the next start" not in last, last


def test_notes_do_not_call_leftovers_harmless(tmp_path, xpi):
    profile = make_profile(tmp_path, "p")
    out = run("--profile", str(profile), "--xpi", str(xpi)).stdout.lower()
    assert "harmless" not in out
    assert "leaves them off" not in out
    assert "unsigned" in out
    assert "without a prompt" in out
    assert "not restored" in out
    assert "about:config" in out
    assert "\u2014" not in out and "\u2013" not in out


def test_notes_say_the_zen_space_scope_block_is_left_alone(tmp_path, xpi):
    profile = make_profile(tmp_path, "p")
    out = run("--profile", str(profile), "--xpi", str(xpi)).stdout
    notes = out[out.index("Next steps") :]
    assert "zen-space-scope" in notes and "left alone" in notes
    assert "tab sharing" not in notes.lower()
    assert "media.getusermedia" not in out


# -- running check by .parentlock (R33) ------------------------------------------------

HOLDER = (
    "import fcntl, sys\n"
    "f = open(sys.argv[1], 'a+')\n"
    "fcntl.lockf(f, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
    "print('locked', flush=True)\n"
    "sys.stdin.read()\n"
)


@pytest.fixture
def parentlock_held(tmp_path):
    """Returns hold(profile): another process locks <profile>/.parentlock the
    way Gecko does (POSIX fcntl). POSIX locks never conflict inside one
    process, so the holder must be a separate process."""
    procs = []

    def hold(profile: Path) -> None:
        p = subprocess.Popen(
            [sys.executable, "-c", HOLDER, str(profile / ".parentlock")],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        procs.append(p)
        assert p.stdout.readline().strip() == "locked"

    yield hold
    for p in procs:
        p.stdin.close()
        p.wait(timeout=10)


@pytest.mark.parametrize("mode", [[], ["--uninstall"]])
def test_refuses_while_parentlock_is_held_by_another_process(
    tmp_path, xpi, parentlock_held, mode
):
    profile = make_profile(tmp_path, "p")
    parentlock_held(profile)
    user_js = 'user_pref("a", 1);\n'
    (profile / "user.js").write_text(user_js)
    write_prefs_js(profile)
    before = snapshot(profile)
    r = run("--profile", str(profile), "--xpi", str(xpi), *mode)
    assert r.returncode != 0
    assert "running" in r.stderr.lower()
    assert snapshot(profile) == before


def test_dry_run_warns_while_parentlock_is_held(tmp_path, xpi, parentlock_held):
    profile = make_profile(tmp_path, "p")
    parentlock_held(profile)
    before = snapshot(profile)
    r = run("--profile", str(profile), "--xpi", str(xpi), "--dry-run")
    assert r.returncode == 0, r.stderr
    assert "running" in r.stdout.lower()
    assert snapshot(profile) == before


PROBE = (
    "import fcntl, os, sys\n"
    "fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o644)\n"
    "try:\n"
    "    fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
    "    print('free')\n"
    "except OSError:\n"
    "    print('held')\n"
)


def probe_parentlock(profile: Path) -> str:
    """'held' or 'free': whether another process can take the same POSIX
    lock Zen takes on <profile>/.parentlock. Run in a separate process, as
    Zen would be. A missing file is created, as Zen does."""
    r = subprocess.run(
        [sys.executable, "-c", PROBE, str(profile / ".parentlock")],
        capture_output=True,
        text=True,
        check=True,
    )
    return r.stdout.strip()


def popen(*args: str, env: dict | None = None) -> subprocess.Popen:
    _require_temp_target(args)
    return subprocess.Popen(
        ["uv", "run", "--no-project", str(SCRIPT), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, **(env or {})},
        cwd=REPO,
    )


@pytest.fixture
def stalled_https():
    """A local https:// URL whose server accepts the connection and never
    answers, so `--latest` stalls in its download step. Yields (url,
    wait_connected, close)."""
    import socket

    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    conns = []

    def wait_connected(timeout: float = 60) -> None:
        server.settimeout(timeout)
        conn, _ = server.accept()
        conns.append(conn)

    def close() -> None:
        for c in conns:
            c.close()
        server.close()

    yield f"https://127.0.0.1:{server.getsockname()[1]}/latest", wait_connected, close
    close()


@pytest.mark.parametrize("existing_lock", [True, False])
def test_install_holds_the_parentlock_through_the_slow_step(
    tmp_path, stalled_https, existing_lock
):
    """A Zen started while the installer downloads (or builds) must find
    the profile locked. Then the lock is released on the failure path."""
    url, wait_connected, close = stalled_https
    profile = make_profile(tmp_path, "p")
    if existing_lock:
        (profile / ".parentlock").write_text("")  # left behind by a quit Zen
    p = popen("--profile", str(profile), "--latest", env={RELEASES_ENV: url})
    try:
        wait_connected()
        assert probe_parentlock(profile) == "held"
    finally:
        close()
        _, err = p.communicate(timeout=60)
    assert p.returncode == 1 and "Traceback" not in err, err
    assert not (profile / "user.js").exists()
    # A .parentlock the installer created only to hold is removed again.
    assert (profile / ".parentlock").exists() == existing_lock
    assert probe_parentlock(profile) == "free"


def test_parentlock_released_after_interrupt(tmp_path, stalled_https):
    import signal

    url, wait_connected, close = stalled_https
    profile = make_profile(tmp_path, "p")
    p = popen("--profile", str(profile), "--latest", env={RELEASES_ENV: url})
    try:
        wait_connected()
        assert probe_parentlock(profile) == "held"
        p.send_signal(signal.SIGINT)  # uv forwards it to the script
        _, err = p.communicate(timeout=60)
        # Still before close(): the stalled download did not end the run.
        assert probe_parentlock(profile) == "free"
    finally:
        close()
    assert p.returncode != 0
    assert "KeyboardInterrupt" in err, err
    assert not (profile / "user.js").exists()


def test_uninstall_holds_the_parentlock_through_the_prefs_js_reset(tmp_path, xpi):
    """prefs.js is a FIFO here, so uninstall stalls while reading it, after
    the running check and before its first write."""
    profile = make_profile(tmp_path, "p")
    assert run("--profile", str(profile), "--xpi", str(xpi)).returncode == 0
    os.mkfifo(profile / "prefs.js")
    p = popen("--profile", str(profile), "--uninstall")
    try:
        writer = None
        deadline = time.monotonic() + 60
        while writer is None:  # ENXIO until the installer opens it to read
            assert p.poll() is None, p.communicate()
            assert time.monotonic() < deadline, "uninstall never read prefs.js"
            try:
                writer = os.open(profile / "prefs.js", os.O_WRONLY | os.O_NONBLOCK)
            except OSError:
                time.sleep(0.05)
        assert probe_parentlock(profile) == "held"
        os.write(writer, f'{BLOCK_LINES[0]}\nuser_pref("keep", 1);\n'.encode())
        os.close(writer)
        out, err = p.communicate(timeout=60)
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()
    assert p.returncode == 0, err
    assert (profile / "prefs.js").read_text() == 'user_pref("keep", 1);\n'
    assert probe_parentlock(profile) == "free"


def test_parentlock_released_after_success_and_profile_unchanged(tmp_path, xpi):
    profile = make_profile(tmp_path, "p")
    assert run("--profile", str(profile), "--xpi", str(xpi)).returncode == 0
    # A .parentlock the installer created only to hold is removed again.
    assert sorted(p.name for p in profile.iterdir()) == ["extensions", "user.js"]
    assert probe_parentlock(profile) == "free"
    # The probe left a .parentlock, as a quit Zen does: uninstall keeps it.
    assert run("--profile", str(profile), "--uninstall").returncode == 0
    assert probe_parentlock(profile) == "free"
    assert (profile / ".parentlock").read_bytes() == b""


def test_unheld_parentlock_does_not_block(tmp_path, xpi):
    profile = make_profile(tmp_path, "p")
    (profile / ".parentlock").write_text("")  # left behind by a quit Zen
    r = run("--profile", str(profile), "--xpi", str(xpi))
    assert r.returncode == 0, r.stderr
    r = run("--profile", str(profile), "--uninstall")
    assert r.returncode == 0, r.stderr


# -- profile discovery -------------------------------------------------------


def test_install_section_beats_legacy_default_flag(tmp_path, xpi):
    """The real shape: installs.ini and an [Install<hash>] section both name
    profile B, the legacy Default=1 flag sits on profile A."""
    root = tmp_path / "zen"
    a = make_profile(root, "Profiles/a.Default")
    b = make_profile(root, "Profiles/b.Used")
    (root / "profiles.ini").write_text(
        "[Profile1]\nName=B\nIsRelative=1\nPath=Profiles/b.Used\n\n"
        "[Profile0]\nName=A\nIsRelative=1\nPath=Profiles/a.Default\nDefault=1\n\n"
        "[InstallH1]\nDefault=Profiles/b.Used\nLocked=1\n\n[General]\nVersion=2\n"
    )
    (root / "installs.ini").write_text("[H1]\nDefault=Profiles/b.Used\nLocked=1\n")
    r = run("--zen-dir", str(root), "--xpi", str(xpi))
    assert r.returncode == 0, r.stderr
    assert (b / "extensions" / f"{ADDON_ID}.xpi").exists()
    assert not (a / "extensions").exists()


def test_duplicate_entries_for_one_profile_are_one_install(tmp_path, xpi):
    root = tmp_path / "zen"
    b = make_profile(root, "Profiles/b.Used")
    (root / "profiles.ini").write_text(
        f"[InstallH1]\nDefault={b}\n\n[General]\nVersion=2\n"
    )
    (root / "installs.ini").write_text("[H1]\nDefault=Profiles/b.Used\n")
    r = run("--zen-dir", str(root), "--xpi", str(xpi))
    assert r.returncode == 0, r.stderr
    assert (b / "extensions" / f"{ADDON_ID}.xpi").exists()


def test_several_installs_refuse_and_list_paths_even_with_default_flag(tmp_path, xpi):
    root = tmp_path / "zen"
    a = make_profile(root, "Profiles/a.Default")
    b = make_profile(root, "Profiles/b.Two")
    (root / "profiles.ini").write_text(
        "[Profile0]\nName=A\nIsRelative=1\nPath=Profiles/a.Default\nDefault=1\n\n"
        "[InstallH2]\nDefault=Profiles/b.Two\n\n[General]\nVersion=2\n"
    )
    (root / "installs.ini").write_text("[H1]\nDefault=Profiles/a.Default\n")
    r = run("--zen-dir", str(root), "--xpi", str(xpi))
    assert r.returncode != 0
    assert "--profile" in r.stderr
    assert str(a) in r.stderr and str(b) in r.stderr
    assert not (a / "extensions").exists() and not (b / "extensions").exists()


def test_bad_ini_files_are_clear_errors(tmp_path, xpi):
    for content in (b"\xff\xfe\x00garbage", b"no section header\n"):
        root = tmp_path / f"zen{len(content)}"
        root.mkdir()
        (root / "profiles.ini").write_bytes(content)
        r = run("--zen-dir", str(root), "--xpi", str(xpi))
        assert r.returncode != 0
        assert "Traceback" not in r.stderr
        assert "profiles.ini" in r.stderr


# -- lock errors fail closed --------------------------------------------------


def test_unreadable_parentlock_refuses_and_dry_run_warns(tmp_path, xpi):
    profile = make_profile(tmp_path, "p")
    lock = profile / ".parentlock"
    lock.write_text("")
    lock.chmod(0)
    try:
        r = run("--profile", str(profile), "--xpi", str(xpi))
        assert r.returncode != 0
        assert "quit zen" in r.stderr.lower() and "Traceback" not in r.stderr
        assert not (profile / "user.js").exists()
        d = run("--profile", str(profile), "--xpi", str(xpi), "--dry-run")
        assert d.returncode == 0
        assert "running" in d.stdout.lower()
    finally:
        lock.chmod(0o644)


# -- the XPI is validated before any write --------------------------------------


def _assert_nothing_written(profile: Path):
    assert not (profile / "user.js").exists()
    assert not (profile / "extensions").exists()


def test_xpi_that_is_not_a_zip_is_rejected(tmp_path):
    profile = make_profile(tmp_path, "p")
    bad = tmp_path / "bad.xpi"
    bad.write_bytes(b"PK fake xpi")
    r = run("--profile", str(profile), "--xpi", str(bad))
    assert r.returncode != 0 and "Traceback" not in r.stderr
    assert "zip" in r.stderr.lower()
    _assert_nothing_written(profile)


def test_xpi_with_wrong_id_or_no_manifest_is_rejected(tmp_path):
    profile = make_profile(tmp_path, "p")
    wrong = make_xpi(tmp_path / "wrong.xpi", "other@example.org")
    noid = make_xpi(tmp_path / "noid.xpi", None)
    nomanifest = tmp_path / "nomanifest.xpi"
    with zipfile.ZipFile(nomanifest, "w") as z:
        z.writestr("readme.txt", "x")
    for bad in (wrong, noid, nomanifest):
        r = run("--profile", str(profile), "--xpi", str(bad))
        assert r.returncode != 0 and "Traceback" not in r.stderr, bad
        _assert_nothing_written(profile)


# -- --latest, in-process with a stubbed opener -----------------------------------


class FakeResponse(io.BytesIO):
    def __init__(self, data: bytes, url: str):
        super().__init__(data)
        self._url = url

    def geturl(self):
        return self._url


def fake_opener(routes: dict):
    """routes: url -> bytes, or (bytes, final_url)."""
    seen = []

    def opener(req, timeout=None):
        url = req if isinstance(req, str) else req.full_url
        seen.append(url)
        value = routes[url]
        data, final = value if isinstance(value, tuple) else (value, url)
        return FakeResponse(data, final)

    opener.seen = seen
    return opener


def release_json(mod, assets):
    return json.dumps({"assets": assets}).encode()


def xpi_bytes(tmp_path, addon_id=ADDON_ID) -> bytes:
    return make_xpi(tmp_path / "src.xpi", addon_id).read_bytes()


ASSET_URL = "https://github.com/x/y/releases/download/v1/zsp.xpi"


def test_latest_downloads_and_validates(tmp_path):
    mod = load_installer()
    dest = tmp_path / "dl"
    dest.mkdir()
    opener = fake_opener(
        {
            mod.RELEASES_URL: release_json(
                mod, [{"name": "zsp.xpi", "browser_download_url": ASSET_URL}]
            ),
            ASSET_URL: xpi_bytes(tmp_path),
        }
    )
    path = mod.download_latest(dest, opener=opener)
    assert path == dest / "latest.xpi"
    mod.validate_xpi(path)
    assert opener.seen == [mod.RELEASES_URL, ASSET_URL]


@pytest.mark.parametrize("name", ["../../evil.xpi", "/tmp/evil.xpi", "a/b.xpi"])
def test_latest_hostile_asset_name_cannot_pick_the_path(tmp_path, name):
    mod = load_installer()
    dest = tmp_path / "a" / "b" / "dl"
    dest.mkdir(parents=True)
    opener = fake_opener(
        {
            mod.RELEASES_URL: release_json(
                mod, [{"name": name, "browser_download_url": ASSET_URL}]
            ),
            ASSET_URL: xpi_bytes(tmp_path),
        }
    )
    path = mod.download_latest(dest, opener=opener)
    assert path == dest / "latest.xpi"
    assert sorted(p.name for p in dest.parent.iterdir()) == ["dl"]
    assert sorted(p.name for p in dest.iterdir()) == ["latest.xpi"]


def test_latest_rejects_http_everywhere(tmp_path):
    mod = load_installer()
    dest = tmp_path
    good_release = release_json(
        mod, [{"name": "z.xpi", "browser_download_url": ASSET_URL}]
    )
    http_asset = "http://example.invalid/z.xpi"
    cases = {
        "http asset": {
            mod.RELEASES_URL: release_json(
                mod, [{"name": "z.xpi", "browser_download_url": http_asset}]
            ),
        },
        "file asset": {
            mod.RELEASES_URL: release_json(
                mod, [{"name": "z.xpi", "browser_download_url": "file:///etc/passwd"}]
            ),
        },
        "release redirected to http": {
            mod.RELEASES_URL: (good_release, "http://example.invalid/r"),
        },
        "asset redirected to http": {
            mod.RELEASES_URL: good_release,
            ASSET_URL: (xpi_bytes(tmp_path), "http://example.invalid/z.xpi"),
        },
    }
    for label, routes in cases.items():
        with pytest.raises(mod.InstallError, match="https"):
            mod.download_latest(dest, opener=fake_opener(routes))
        assert list(dest.glob("latest.xpi")) == [], label


def test_latest_rejects_an_http_releases_url(tmp_path, monkeypatch):
    mod = load_installer()
    monkeypatch.setattr(mod, "RELEASES_URL", "http://example.invalid/latest")
    opener = fake_opener({})
    with pytest.raises(mod.InstallError, match="https"):
        mod.download_latest(tmp_path, opener=opener)
    assert opener.seen == []


def test_latest_wrong_id_and_not_a_zip_fail_validation(tmp_path):
    mod = load_installer()
    for data in (xpi_bytes(tmp_path, "other@example.org"), b"not a zip"):
        opener = fake_opener(
            {
                mod.RELEASES_URL: release_json(
                    mod, [{"name": "z.xpi", "browser_download_url": ASSET_URL}]
                ),
                ASSET_URL: data,
            }
        )
        path = mod.download_latest(tmp_path, opener=opener)
        with pytest.raises(mod.InstallError):
            mod.validate_xpi(path)


def test_latest_http_override_via_cli_is_rejected_and_writes_nothing(tmp_path):
    profile = make_profile(tmp_path, "p")
    r = run(
        "--profile",
        str(profile),
        "--latest",
        env={"ZEN_SHARE_PICKER_RELEASES_URL": "http://127.0.0.1:9/none"},
    )
    assert r.returncode != 0 and "Traceback" not in r.stderr
    assert "https" in r.stderr
    _assert_nothing_written(profile)


def test_latest_default_url_is_this_repository(monkeypatch):
    monkeypatch.delenv(RELEASES_ENV, raising=False)
    mod = load_installer()
    assert mod.RELEASES_URL == (
        "https://api.github.com/repos/zippeurfou/zen-share-picker/releases/latest"
    )


def test_latest_without_a_release_says_so(tmp_path):
    """GitHub answers 404 for releases/latest while nothing is published."""
    mod = load_installer()

    def opener(req, timeout=None):
        raise urllib.error.HTTPError(mod.RELEASES_URL, 404, "Not Found", {}, None)

    with pytest.raises(mod.InstallError) as e:
        mod.download_latest(tmp_path, opener=opener)
    assert "no release has been published yet" in str(e.value)
    assert "--xpi" in str(e.value)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("count", [0, 2])
def test_latest_needs_exactly_one_xpi_asset(tmp_path, count):
    mod = load_installer()
    assets = [
        {"name": f"z{i}.xpi", "browser_download_url": f"{ASSET_URL}{i}"}
        for i in range(count)
    ] + [{"name": "updates.json", "browser_download_url": ASSET_URL + ".json"}]
    opener = fake_opener({mod.RELEASES_URL: release_json(mod, assets)})
    with pytest.raises(mod.InstallError, match=r"\.xpi"):
        mod.download_latest(tmp_path, opener=opener)
    assert opener.seen == [mod.RELEASES_URL]
    assert list(tmp_path.iterdir()) == []


# -- write order and failures ----------------------------------------------------


def readonly_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(stat.S_IRUSR | stat.S_IXUSR)
    return path


def test_install_failure_on_the_xpi_step_changes_no_pref(tmp_path, xpi):
    profile = make_profile(tmp_path, "p")
    (profile / "extensions").write_text("a file where the folder belongs")
    r = run("--profile", str(profile), "--xpi", str(xpi))
    assert r.returncode != 0 and "Traceback" not in r.stderr
    assert "re-run" in r.stderr.lower()
    assert not (profile / "user.js").exists()


def test_install_failure_on_user_js_leaves_xpi_only_then_rerun_finishes(tmp_path, xpi):
    profile = make_profile(tmp_path, "p")
    # The target exists (a dangling link is refused before any write) but
    # its directory is read-only, so the atomic replace fails.
    (tmp_path / "dotfiles").mkdir()
    (tmp_path / "dotfiles" / "user.js").write_text("x\n")
    ro = readonly_dir(tmp_path / "dotfiles")
    try:
        (profile / "user.js").symlink_to(ro / "user.js")
        r = run("--profile", str(profile), "--xpi", str(xpi))
        assert r.returncode != 0 and "Traceback" not in r.stderr
        assert "re-run" in r.stderr.lower()
        assert (profile / "extensions" / f"{ADDON_ID}.xpi").exists()
        assert (ro / "user.js").read_text() == "x\n"
    finally:
        ro.chmod(0o755)
    r = run("--profile", str(profile), "--xpi", str(xpi))
    assert r.returncode == 0, r.stderr
    assert BEGIN in (ro / "user.js").read_text()


def test_install_leaves_no_temp_files(tmp_path, xpi):
    profile = make_profile(tmp_path, "p")
    run("--profile", str(profile), "--xpi", str(xpi))
    run("--profile", str(profile), "--xpi", str(xpi))
    assert sorted(p.name for p in (profile / "extensions").iterdir()) == [
        f"{ADDON_ID}.xpi"
    ]
    assert sorted(p.name for p in profile.iterdir()) == ["extensions", "user.js"]


def test_uninstall_unreadable_prefs_js_changes_nothing(tmp_path, xpi):
    profile = make_profile(tmp_path, "p")
    run("--profile", str(profile), "--xpi", str(xpi))
    (profile / "prefs.js").mkdir()  # a directory where the file belongs
    before = (profile / "user.js").read_bytes()
    r = run("--profile", str(profile), "--uninstall")
    assert r.returncode != 0 and "Traceback" not in r.stderr
    assert "nothing was changed" in r.stderr.lower()
    assert (profile / "user.js").read_bytes() == before
    assert (profile / "extensions" / f"{ADDON_ID}.xpi").exists()


def test_uninstall_resets_prefs_first_and_rerun_finishes(tmp_path, xpi):
    profile = make_profile(tmp_path, "p")
    ro = readonly_dir(tmp_path / "x")
    ro.chmod(0o755)
    real_user_js = ro / "user.js"
    real_user_js.write_text("")
    (profile / "user.js").symlink_to(real_user_js)
    run("--profile", str(profile), "--xpi", str(xpi))
    write_prefs_js(profile)
    ro.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        r = run("--profile", str(profile), "--uninstall")
        assert r.returncode != 0 and "Traceback" not in r.stderr
        assert "re-run" in r.stderr.lower()
        prefs = (profile / "prefs.js").read_text()
        assert not any(f'"{n}"' in prefs for n in block_names())
        assert BEGIN in real_user_js.read_text()
        assert (profile / "extensions" / f"{ADDON_ID}.xpi").exists()
    finally:
        ro.chmod(0o755)
    r = run("--profile", str(profile), "--uninstall")
    assert r.returncode == 0, r.stderr
    assert BEGIN not in real_user_js.read_text()
    assert not (profile / "extensions" / f"{ADDON_ID}.xpi").exists()


def test_uninstall_says_start_zen_not_restart(tmp_path, xpi):
    profile = make_profile(tmp_path, "p")
    run("--profile", str(profile), "--xpi", str(xpi))
    out = run("--profile", str(profile), "--uninstall").stdout
    assert "Start Zen" in out and "Restart" not in out


# -- empty ini values and several data directories ------------------------------------


def _empty_value_trees(tmp_path: Path):
    """(name, data directory) for each place an empty Default= or Path= can
    name a profile."""
    for name, profiles_ini, installs_ini in (
        (
            "installs.ini Default",
            "[General]\nVersion=2\n",
            "[H1]\nDefault=\nLocked=1\n",
        ),
        ("[Install] Default", "[InstallH1]\nDefault=\n\n[General]\nVersion=2\n", None),
        (
            "[Profile] Path",
            "[Profile0]\nName=A\nIsRelative=1\nPath=\nDefault=1\n\n[General]\nVersion=2\n",
            None,
        ),
        ("installs.ini Default dot", "[General]\nVersion=2\n", "[H1]\nDefault=.\n"),
        (
            "[Profile] Path dot",
            "[Profile0]\nName=A\nIsRelative=1\nPath=.\nDefault=1\n\n[General]\nVersion=2\n",
            None,
        ),
    ):
        root = tmp_path / name.replace(" ", "-").replace("[", "").replace("]", "")
        root.mkdir()
        (root / "profiles.ini").write_text(profiles_ini)
        if installs_ini is not None:
            (root / "installs.ini").write_text(installs_ini)
        yield name, root


def test_empty_default_or_path_never_installs_into_the_data_directory(tmp_path, xpi):
    """An empty Default= or Path= resolves to the Zen data directory itself.
    That is not a profile: refuse, and write nothing."""
    for name, root in _empty_value_trees(tmp_path):
        before = snapshot(root)
        for mode in ([], ["--dry-run"], ["--uninstall"]):
            r = run("--zen-dir", str(root), "--xpi", str(xpi), *mode)
            assert r.returncode != 0, f"{name} {mode}: {r.stdout}"
            assert "Traceback" not in r.stderr, r.stderr
            assert "--profile" in r.stderr, f"{name} {mode}: {r.stderr}"
        assert snapshot(root) == before, f"{name}: the data directory was written to"
        assert not (root / "user.js").exists() and not (root / "extensions").exists()


def test_empty_values_are_named_in_the_error(tmp_path, xpi):
    root = tmp_path / "zen"
    root.mkdir()
    (root / "profiles.ini").write_text("[General]\nVersion=2\n")
    (root / "installs.ini").write_text("[H1]\nDefault=\n")
    r = run("--zen-dir", str(root), "--xpi", str(xpi))
    assert r.returncode != 0
    assert "installs.ini" in r.stderr and "Default" in r.stderr and "H1" in r.stderr


def test_positive_control_a_filled_default_still_installs(tmp_path, xpi):
    """The same trees with the value filled in install into that profile."""
    root = tmp_path / "zen"
    profile = make_profile(root, "Profiles/abc.Default")
    (root / "profiles.ini").write_text(
        "[Profile0]\nName=A\nIsRelative=1\nPath=Profiles/abc.Default\nDefault=1\n\n"
        "[General]\nVersion=2\n"
    )
    (root / "installs.ini").write_text("[H1]\nDefault=Profiles/abc.Default\n")
    r = run("--zen-dir", str(root), "--xpi", str(xpi))
    assert r.returncode == 0, r.stderr
    assert (profile / "extensions" / f"{ADDON_ID}.xpi").exists()
    assert not (root / "user.js").exists()


def test_explicit_profile_that_is_a_data_directory_is_refused(tmp_path, xpi):
    root, profile = mac_tree(tmp_path)
    before = snapshot(root)
    r = run("--profile", str(root), "--xpi", str(xpi))
    assert r.returncode != 0
    assert "data directory" in r.stderr and "Traceback" not in r.stderr
    assert snapshot(root) == before
    # Positive control: the profile inside it is accepted.
    r = run("--profile", str(profile), "--xpi", str(xpi))
    assert r.returncode == 0, r.stderr


def _linux_data_dirs(mod, tmp_path, monkeypatch) -> list[Path]:
    monkeypatch.setenv("HOME", str(tmp_path))
    dirs = mod.default_zen_dirs("linux")
    assert dirs[0] == tmp_path / ".zen" and len(dirs) == 3, dirs
    monkeypatch.setattr(mod, "default_zen_dirs", lambda: dirs)
    return dirs


def _data_dir_with_profile(root: Path, name: str) -> Path:
    profile = make_profile(root, name)
    (root / "profiles.ini").write_text(
        f"[Profile0]\nName=p\nIsRelative=1\nPath={name}\nDefault=1\n\n"
        "[General]\nVersion=2\n"
    )
    return profile


def test_several_zen_data_directories_refuse_and_list_them(tmp_path, monkeypatch):
    """On Linux a native install (~/.zen) and a flatpak one can both exist.
    The first one found must not win silently."""
    mod = load_installer()
    native, _, flatpak = _linux_data_dirs(mod, tmp_path, monkeypatch)
    native_profile = _data_dir_with_profile(native, "n1.default")
    flatpak_profile = _data_dir_with_profile(flatpak, "f1.default")

    with pytest.raises(mod.InstallError) as e:
        mod.locate_profile(None, None)
    message = str(e.value)
    assert str(native) in message and str(flatpak) in message, message
    assert "--zen-dir" in message and "--profile" in message, message

    # Positive controls: naming one data directory, or the profile, works.
    assert mod.locate_profile(None, str(native)) == native_profile
    assert mod.locate_profile(None, str(flatpak)) == flatpak_profile
    assert mod.locate_profile(str(flatpak_profile), None) == flatpak_profile


def test_one_zen_data_directory_is_used_without_asking(tmp_path, monkeypatch):
    mod = load_installer()
    native, config, flatpak = _linux_data_dirs(mod, tmp_path, monkeypatch)
    flatpak_profile = _data_dir_with_profile(flatpak, "f1.default")
    assert mod.locate_profile(None, None) == flatpak_profile

    # The same directory reached through a symlink is still one directory.
    config.parent.mkdir(parents=True)
    config.symlink_to(flatpak, target_is_directory=True)
    assert mod.locate_profile(None, None) == flatpak_profile
    assert not native.exists()


def _block_names(block: str) -> list[str]:
    return re.findall(r'^user_pref\("([^"]+)",', block, flags=re.MULTILINE)


def test_readme_lists_exactly_the_prefs_the_block_sets(tmp_path):
    """The README's manual uninstall names the 5 prefs uninstall resets, in
    the order of `--print-block --list-windows`, the first 4 being the
    default block. Every "<N> prefs" says 4 (the default block) or 5 (with
    --list-windows, and what uninstall resets)."""
    default = _block_names(print_block(tmp_path))
    r = run("--print-block", "--list-windows", "--profile", str(tmp_path))
    assert r.returncode == 0, r.stderr
    names = _block_names(r.stdout)
    assert len(default) == 4 and len(names) == 5, (default, names)
    readme = (REPO / "README.md").read_text()
    m = re.search(
        r"uninstall resets these (\d+) prefs.*?\n```\n(.*?)\n```", readme, re.DOTALL
    )
    assert m, "the README has no list of the prefs uninstall resets"
    assert m.group(1) == "5"
    listed = m.group(2).split("\n")
    assert listed == names
    assert listed[:4] == default
    counts = set(re.findall(r"\b(\d+) prefs\b", readme))
    assert counts == {"4", "5"}, f"README pref counts: {counts}"


# -- --list-windows (P54) -------------------------------------------------------------


def test_list_windows_block_adds_the_picker_pref_last(tmp_path):
    r = run("--print-block", "--list-windows", "--profile", str(tmp_path))
    assert r.returncode == 0, r.stderr
    assert r.stdout == EXPECTED_BLOCK.replace(END, PICKER_LINE + "\n" + END)
    assert r.stdout == WINDOWS_BLOCK
    assert sorted(p.name for p in tmp_path.iterdir()) == []


def test_install_with_list_windows_writes_five_prefs(tmp_path, xpi):
    profile = make_profile(tmp_path, "p")
    r = run("--profile", str(profile), "--xpi", str(xpi), "--list-windows")
    assert r.returncode == 0, r.stderr
    assert (profile / "user.js").read_text() == WINDOWS_BLOCK
    assert PICKER_LINE in r.stdout
    assert (profile / "extensions" / f"{ADDON_ID}.xpi").exists()


def test_rerun_with_the_same_flag_keeps_one_block(tmp_path, xpi):
    profile = make_profile(tmp_path, "p")
    (profile / "user.js").write_text('user_pref("a", 1);\n')
    for _ in range(3):
        r = run("--profile", str(profile), "--xpi", str(xpi), "--list-windows")
        assert r.returncode == 0, r.stderr
    assert (profile / "user.js").read_text() == 'user_pref("a", 1);\n' + WINDOWS_BLOCK


def install_with_flag(profile: Path, xpi: Path) -> None:
    r = run("--profile", str(profile), "--xpi", str(xpi), "--list-windows")
    assert r.returncode == 0, r.stderr
    assert (profile / "user.js").read_text().endswith(PICKER_LINE + "\n" + END + "\n")


def write_all_prefs_js(profile: Path) -> None:
    """prefs.js as Zen leaves it after a run with --list-windows: the five
    prefs among unrelated lines."""
    lines = PREFS_JS_HEAD
    for name in ALL_NAMES:
        value = "false" if name in (PICKER, BLOCK_NAMES[0]) else "true"
        lines += f'user_pref("{name}", {value});\n'
    (profile / "prefs.js").write_bytes((lines + PREFS_JS_TAIL).encode("utf-8"))


def test_rerun_without_the_flag_turns_apple_picker_back_on(tmp_path, xpi):
    profile = make_profile(tmp_path, "p")
    r = run("--profile", str(profile), "--xpi", str(xpi), "--list-windows")
    assert r.returncode == 0, r.stderr
    write_all_prefs_js(profile)
    before = (profile / "prefs.js").read_bytes()
    r = run("--profile", str(profile), "--xpi", str(xpi))
    assert r.returncode == 0, r.stderr
    assert (profile / "user.js").read_text() == EXPECTED_BLOCK
    assert (profile / "prefs.js").read_bytes() == before.replace(
        (PICKER_LINE + "\n").encode(), b""
    )
    assert f"reset {PICKER} in prefs.js" in r.stdout
    # The other four prefs are the new block's: they stay in prefs.js.
    for name in BLOCK_NAMES:
        assert f"reset {name} " not in r.stdout


def test_rerun_without_the_flag_dry_run_writes_nothing(tmp_path, xpi):
    profile = make_profile(tmp_path, "p")
    install_with_flag(profile, xpi)
    write_all_prefs_js(profile)
    before = snapshot(profile)
    r = run("--profile", str(profile), "--xpi", str(xpi), "--dry-run")
    assert r.returncode == 0, r.stderr
    assert snapshot(profile) == before
    assert f"[dry run] would reset {PICKER} in prefs.js" in r.stdout


def test_rerun_without_the_flag_and_without_prefs_js_is_fine(tmp_path, xpi):
    profile = make_profile(tmp_path, "p")
    install_with_flag(profile, xpi)
    r = run("--profile", str(profile), "--xpi", str(xpi))
    assert r.returncode == 0, r.stderr
    assert (profile / "user.js").read_text() == EXPECTED_BLOCK
    assert not (profile / "prefs.js").exists()


def test_rerun_without_the_flag_writes_through_a_symlinked_prefs_js(tmp_path, xpi):
    profile = make_profile(tmp_path, "p")
    install_with_flag(profile, xpi)
    real = tmp_path / "dotfiles" / "prefs.js"
    real.parent.mkdir()
    (profile / "prefs.js").symlink_to(real)
    write_all_prefs_js(profile)
    r = run("--profile", str(profile), "--xpi", str(xpi))
    assert r.returncode == 0, r.stderr
    assert (profile / "prefs.js").is_symlink()
    assert PICKER not in real.read_text()
    assert BLOCK_NAMES[0] in real.read_text()


def test_rerun_without_the_flag_with_unreadable_prefs_js_changes_nothing(tmp_path, xpi):
    profile = make_profile(tmp_path, "p")
    install_with_flag(profile, xpi)
    (profile / "prefs.js").mkdir()  # a directory where the file belongs
    before = snapshot(profile)
    r = run("--profile", str(profile), "--xpi", str(xpi))
    assert r.returncode != 0 and "Traceback" not in r.stderr
    assert "nothing was changed" in r.stderr.lower()
    assert snapshot(profile) == before


def test_rerun_without_the_flag_finishes_after_a_prefs_js_failure(tmp_path, xpi):
    """A failed prefs.js write must leave a state the same command finishes:
    the old block, still setting the picker pref, is kept until prefs.js is
    reset."""
    profile = make_profile(tmp_path, "p")
    install_with_flag(profile, xpi)
    ro = tmp_path / "dotfiles"
    ro.mkdir()
    (ro / "prefs.js").write_text(PICKER_LINE + '\nuser_pref("keep", 1);\n')
    (profile / "prefs.js").symlink_to(ro / "prefs.js")
    readonly_dir(ro)
    try:
        r = run("--profile", str(profile), "--xpi", str(xpi))
        assert r.returncode != 0 and "Traceback" not in r.stderr
        assert "re-run" in r.stderr.lower()
        assert (profile / "user.js").read_text() == WINDOWS_BLOCK
    finally:
        ro.chmod(0o755)
    r = run("--profile", str(profile), "--xpi", str(xpi))
    assert r.returncode == 0, r.stderr
    assert (profile / "user.js").read_text() == EXPECTED_BLOCK
    assert (ro / "prefs.js").read_text() == 'user_pref("keep", 1);\n'


def test_rerun_without_the_flag_leaves_a_hand_set_picker_pref(tmp_path, xpi):
    profile = make_profile(tmp_path, "p")
    run("--profile", str(profile), "--xpi", str(xpi))
    write_all_prefs_js(profile)
    before = (profile / "prefs.js").read_bytes()
    r = run("--profile", str(profile), "--xpi", str(xpi))
    assert r.returncode == 0, r.stderr
    assert (profile / "prefs.js").read_bytes() == before
    assert PICKER not in r.stdout


def test_uninstall_resets_the_picker_pref_even_when_set_by_hand(tmp_path, xpi):
    profile = make_profile(tmp_path, "p")
    run("--profile", str(profile), "--xpi", str(xpi))
    write_all_prefs_js(profile)
    r = run("--profile", str(profile), "--uninstall")
    assert r.returncode == 0, r.stderr
    assert (profile / "prefs.js").read_bytes() == (
        PREFS_JS_HEAD + PREFS_JS_TAIL
    ).encode("utf-8")
    for name in ALL_NAMES:
        assert f"reset {name} in prefs.js" in r.stdout


def test_uninstall_accepts_and_ignores_list_windows(tmp_path, xpi):
    profile = make_profile(tmp_path, "p")
    install_with_flag(profile, xpi)
    write_all_prefs_js(profile)
    r = run("--profile", str(profile), "--uninstall", "--list-windows")
    assert r.returncode == 0, r.stderr
    assert not (profile / "user.js").exists()
    assert (profile / "prefs.js").read_bytes() == (
        PREFS_JS_HEAD + PREFS_JS_TAIL
    ).encode("utf-8")


def test_uninstall_says_another_block_sets_the_picker_pref_again(tmp_path, xpi):
    profile = make_profile(tmp_path, "p")
    other = f'// mine\n{PICKER_LINE}\nuser_pref("a", 1);\n'
    (profile / "user.js").write_text(other)
    run("--profile", str(profile), "--xpi", str(xpi))
    write_all_prefs_js(profile)
    r = run("--profile", str(profile), "--uninstall")
    assert r.returncode == 0, r.stderr
    assert (profile / "user.js").read_text() == other
    last = r.stdout.strip().splitlines()[-1]
    assert "Zen applies them again at the next start" in last, last
    assert PICKER in last, last
    assert BLOCK_NAMES[0] not in last, last


NOTE_WINDOWS = (
    "Apple's screen picker is off in this profile: Zen lists your screens and "
    "windows itself. macOS may ask you to allow that at the first window "
    "preview or share, and maybe again later. "
    "Run this script again without --list-windows to turn Apple's picker back on."
)


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_notes_explain_the_alert_only_with_list_windows(tmp_path, xpi):
    a = make_profile(tmp_path, "a")
    b = make_profile(tmp_path, "b")
    with_flag = run("--profile", str(a), "--xpi", str(xpi), "--list-windows")
    without = run("--profile", str(b), "--xpi", str(xpi))
    assert with_flag.returncode == 0 and without.returncode == 0
    assert NOTE_WINDOWS in _flat(with_flag.stdout)
    assert "Apple" not in without.stdout
    notes = without.stdout[without.stdout.index("Next steps") :]
    flagged = with_flag.stdout[with_flag.stdout.index("Next steps") :]
    assert _flat(flagged).replace("- " + NOTE_WINDOWS + " ", "") == _flat(notes)


# -- Windows -----------------------------------------------------------------------

# Runs the script as on Windows, where Python has no fcntl module.
AS_ON_WINDOWS = (
    "import runpy, sys; sys.modules['fcntl'] = None; "
    "sys.argv = sys.argv[1:]; runpy.run_path(sys.argv[0], run_name='__main__')"
)


def run_without_fcntl(*args: str) -> subprocess.CompletedProcess:
    _require_temp_target(args)
    return subprocess.run(
        [
            "uv",
            "run",
            "--no-project",
            "python",
            "-c",
            AS_ON_WINDOWS,
            str(SCRIPT),
            *args,
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=REPO,
    )


@pytest.mark.parametrize("mode", [[], ["--dry-run"], ["--uninstall"]])
def test_windows_gets_a_clear_message_not_a_traceback(tmp_path, xpi, mode):
    profile = make_profile(tmp_path, "p")
    before = snapshot(profile)
    r = run_without_fcntl("--profile", str(profile), "--xpi", str(xpi), *mode)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "Traceback" not in r.stderr and "fcntl" not in r.stderr, r.stderr
    assert "macOS and Linux only" in r.stderr, r.stderr
    assert "by hand" in r.stderr, r.stderr
    assert snapshot(profile) == before


def test_print_block_needs_no_profile_lock_support(tmp_path):
    """Positive control: the one mode that touches no profile still works, so
    a Windows user can install by hand."""
    r = run_without_fcntl("--print-block", "--profile", str(tmp_path))
    assert r.returncode == 0, r.stderr
    assert r.stdout == EXPECTED_BLOCK


def test_the_test_runner_refuses_an_installer_run_without_a_temp_target():
    """The guard behind every run above: no flag, no run."""
    with pytest.raises(AssertionError, match="--profile"):
        run("--print-block")
    with pytest.raises(AssertionError, match="--profile"):
        run_without_fcntl("--dry-run")
