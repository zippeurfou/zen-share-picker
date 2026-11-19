"""Zen's add-on manager updates the add-on from its update manifest.

The real channel is https: the manifest's `update_url` is the latest GitHub
release's `updates.json`, whose `update_link` is the versioned release asset,
with its sha256 in `update_hash` (scripts/make_updates_json.py).

Here the update manifest and the XPI come from the local test server over
plain HTTP (the harness proxy refuses HTTPS tunnels, and a local certificate
would not chain to a built-in root, which `extensions.update.requireBuiltInCerts`
demands by default: AddonSettings.sys.mjs:62-68, AddonUpdateChecker.sys.mjs:264-301).
That takes one test-only pref, set only in these temporary profiles:
`extensions.checkUpdateSecurity=false`. With its default (true) Zen disables an
add-on whose `update_url` is not https (XPIDatabase.sys.mjs:2711-2718,
providesUpdatesSecurely :439-441). The hash is still checked on download
(XPIInstall.sys.mjs:2800-2805), which the wrong-hash test proves.
`test_release_manifest_parses_in_zen` covers the https shape with the default
security settings.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import subprocess
import time
import zipfile
from pathlib import Path

from test_picker import (
    assert_no_picker_for,
    assert_prompt_concealed,
    assert_prompt_untouched,
    setup,
    wait_picker,
)
from zen import REPO_ROOT, ZenScriptError

ADDON_ID = "zen-share-picker@zippeurfou.github.io"
MAKE_UPDATES = REPO_ROOT / "scripts" / "make_updates_json.py"
UPDATE_URL = "http://updates.test/updates.json"
REAL_UPDATE_URL = "https://github.com/zippeurfou/zen-share-picker/releases/latest/download/updates.json"

UPDATE_PREFS = {
    # The harness turns update checks off everywhere else.
    "extensions.update.enabled": True,
    # Test-only, see the module docstring: the local server is plain HTTP.
    "extensions.checkUpdateSecurity": False,
    # No add-on metadata fetch from addons.mozilla.org during the check
    # (AddonRepository.sys.mjs:663).
    "extensions.getAddons.cache.enabled": False,
}

# Runs the periodic update check Zen runs once a day (components.manifest:17,
# AddonManager.sys.mjs:1368-1430), which installs an update on its own when
# auto-update is on (the default), and reports how that install ends.
UPDATE_CHECK = """
const [id] = args;
const { AddonManager, AddonManagerPrivate } = ChromeUtils.importESModule(
  "resource://gre/modules/AddonManager.sys.mjs");
const names = Object.fromEntries(
  Object.keys(AddonManager).filter(k => k.startsWith("ERROR_"))
    .map(k => [AddonManager[k], k]));
let done;
const ended = new Promise(r => (done = r));
const mine = install => install.existingAddon?.id == id || install.addon?.id == id;
const listener = {
  onDownloadFailed(i) { if (mine(i)) done({ failed: "download", error: names[i.error] ?? i.error }); },
  onInstallFailed(i) { if (mine(i)) done({ failed: "install", error: names[i.error] ?? i.error }); },
  onInstallCancelled(i) { if (mine(i)) done({ failed: "cancelled" }); },
  onInstallEnded(i, addon) { if (mine(i)) done({ version: addon.version }); },
};
AddonManager.addInstallListener(listener);
try {
  await AddonManagerPrivate.backgroundUpdateCheck();
  const timeout = new Promise(r => win.setTimeout(() => r({ failed: "timeout" }), 30000));
  return await Promise.race([ended, timeout]);
} finally {
  AddonManager.removeInstallListener(listener);
}
"""

ADDON_INFO = """
const { AddonManager } = ChromeUtils.importESModule(
  "resource://gre/modules/AddonManager.sys.mjs");
const a = await AddonManager.getAddonByID(args[0]);
return a && { version: a.version, active: a.isActive,
              temporary: a.temporarilyInstalled, updateURL: a.updateURL ?? null };
"""

# Whether each resource host in args[0] is registered.
HOST_CHECK = """
const resProto = Cc["@mozilla.org/network/protocol;1?name=resource"].getService(
  Ci.nsISubstitutingProtocolHandler);
return Object.fromEntries(args[0].map(h => [h, resProto.hasSubstitution(h)]));
"""


def host_for(version: str) -> str:
    return "zen-share-picker-" + re.sub(r"[^A-Za-z0-9]", "-", version)


def installed_prefs() -> dict[str, object]:
    """The prefs of the block `scripts/install.py` writes to user.js, so the
    updated profile is set up as a user's."""
    spec = importlib.util.spec_from_file_location(
        "zsp_install", REPO_ROOT / "scripts" / "install.py"
    )
    assert spec and spec.loader
    install = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(install)
    prefs: dict[str, object] = {}
    for line in install.build_block().splitlines():
        m = re.fullmatch(r"user_pref\((.+), (.+)\);", line)
        if m:
            prefs[json.loads(m.group(1))] = json.loads(m.group(2))
    assert "extensions.experiments.enabled" in prefs, prefs
    return prefs


def variant(
    src: Path,
    dest: Path,
    version: str,
    update_url: str,
    patch: dict[str, tuple[str, str]] | None = None,
) -> Path:
    """A copy of the built XPI whose manifest has another version and
    update_url. `patch` maps a file to one (old, new) text replacement; every
    other file is kept byte for byte."""
    patch = dict(patch or {})
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dest, "w") as zout:
        for info in zin.infolist():
            data = zin.read(info)
            if info.filename in patch:
                old, new = patch.pop(info.filename)
                text = data.decode()
                assert text.count(old) == 1, f"{old!r} not once in {info.filename}"
                data = text.replace(old, new).encode()
            if info.filename == "manifest.json":
                manifest = json.loads(data)
                manifest["version"] = version
                manifest["browser_specific_settings"]["gecko"]["update_url"] = (
                    update_url
                )
                data = json.dumps(manifest, indent=2).encode()
            zout.writestr(info, data)
    assert not patch, f"files not in the XPI: {list(patch)}"
    return dest


def make_updates_json(xpi: Path, out: Path, *args: str) -> dict:
    subprocess.run(
        [
            "uv",
            "run",
            "--no-project",
            str(MAKE_UPDATES),
            str(xpi),
            "-o",
            str(out),
            *args,
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(out.read_text())


def wait_version(zen, addon_id: str, version: str) -> dict:
    """The add-on's status once it runs `version` and is past start-up."""
    deadline = time.monotonic() + 30
    last: object = None
    while True:
        try:
            last = zen.addon_call(addon_id, "getStatus")
            if last.get("version") == version:
                return last
        except ZenScriptError as e:  # restarting: briefly not running
            last = e
        if time.monotonic() > deadline:
            raise AssertionError(f"the add-on does not run {version}: {last}")
        time.sleep(0.2)


def published_pair(
    site,
    tmp_path: Path,
    addon_xpi: Path,
    *,
    tamper: bool = False,
    patch: dict[str, tuple[str, str]] | None = None,
) -> tuple[Path, list[str]]:
    """Builds 0.0.1 and 0.0.2 (with `patch`) with update_url at the test
    server, publishes 0.0.2 and its updates.json there, and returns the 0.0.1
    XPI and the served URLs. `tamper` publishes a wrong update_hash."""
    old = variant(
        addon_xpi, tmp_path / "zen-share-picker-0.0.1.xpi", "0.0.1", UPDATE_URL
    )
    rel = tmp_path / "v0.0.2"
    rel.mkdir()
    new = variant(
        addon_xpi, rel / "zen-share-picker-0.0.2.xpi", "0.0.2", UPDATE_URL, patch
    )
    base = "http://updates.test/releases/download/v0.0.2"
    manifest = make_updates_json(
        new, tmp_path / "updates.json", "--base-url", base, "--allow-http"
    )
    if tamper:
        entry = manifest["addons"][ADDON_ID]["updates"][0]
        entry["update_hash"] = "sha256:" + hashlib.sha256(b"not the file").hexdigest()
    link = f"{base}/{new.name}"
    site.serve(UPDATE_URL, json.dumps(manifest).encode(), "application/json")
    site.serve(link, new.read_bytes(), "application/x-xpinstall")
    return old, [UPDATE_URL, link]


def unserve(site, served: list[str]) -> None:
    for url in served:
        site.unserve(url)


def test_self_update(launch_zen, site, addon_xpi, tmp_path):
    """An installed 0.0.1 finds 0.0.2 through its update_url, Zen installs it
    in place, and 0.0.2 comes back active on its own resource host, and a
    share prompt then opens its picker (R16, R35 g)."""
    assert addon_xpi is not None, "the add-on is not built"
    old_xpi, served = published_pair(site, tmp_path, addon_xpi)
    try:
        zen = launch_zen({**installed_prefs(), **UPDATE_PREFS})
        addon = zen.install_addon(str(old_xpi), temp=False)
        assert addon == ADDON_ID
        status = wait_version(zen, addon, "0.0.1")
        assert status["state"] == "active", status
        assert zen.chrome(ADDON_INFO, addon) == {
            "version": "0.0.1",
            "active": True,
            "temporary": False,
            "updateURL": UPDATE_URL,
        }
        hosts = [host_for("0.0.1"), host_for("0.0.2")]
        assert zen.chrome(HOST_CHECK, hosts) == {hosts[0]: True, hosts[1]: False}

        outcome = zen.chrome(UPDATE_CHECK, addon, timeout=60)
        assert outcome == {"version": "0.0.2"}, f"no update: {outcome}"

        status = wait_version(zen, addon, "0.0.2")
        assert status["state"] == "active", f"0.0.2 is not active: {status}"
        info = zen.chrome(ADDON_INFO, addon)
        assert info["version"] == "0.0.2" and info["active"], info
        assert not info["temporary"], info
        assert zen.chrome(HOST_CHECK, hosts) == {hosts[0]: False, hosts[1]: True}

        # Positive control: the updated add-on does its job.
        setup(zen)
        p = wait_picker(zen)
        assert p["groups"][-1] == "os", p
        assert p["focused"] == "zen-share-picker-search", p
        assert_prompt_concealed(zen)
        status = zen.addon_call(addon, "getStatus")
        assert status["version"] == "0.0.2", status
        assert status["promptProblems"] == [], status
    finally:
        unserve(site, served)


def test_self_update_stays_inert_when_the_new_check_fails(
    launch_zen, site, addon_xpi, tmp_path
):
    """Negative control for R16: a 0.0.2 whose start-up check fails installs,
    but stays inert and opens no picker; 0.0.1's "active" is not carried."""
    assert addon_xpi is not None, "the add-on is not built"
    forced = ("  return failed;", "  failed.push(CHECKS[0]);\n  return failed;")
    old_xpi, served = published_pair(
        site, tmp_path, addon_xpi, patch={"src/glue/selfcheck.sys.mjs": forced}
    )
    try:
        zen = launch_zen({**installed_prefs(), **UPDATE_PREFS})
        addon = zen.install_addon(str(old_xpi), temp=False)
        assert wait_version(zen, addon, "0.0.1")["state"] == "active"
        outcome = zen.chrome(UPDATE_CHECK, addon, timeout=60)
        assert outcome == {"version": "0.0.2"}, f"no update: {outcome}"
        status = wait_version(zen, addon, "0.0.2")
        assert status["state"] == "inert", status
        assert status["failedChecks"] == ["popup-notifications"], status
        setup(zen)
        assert_no_picker_for(zen, 2)
        assert_prompt_untouched(zen)
    finally:
        unserve(site, served)


def test_self_update_refuses_a_wrong_hash(launch_zen, site, addon_xpi, tmp_path):
    """An XPI whose sha256 differs from update_hash is not installed, and the
    running version stays active."""
    assert addon_xpi is not None, "the add-on is not built"
    old_xpi, served = published_pair(site, tmp_path, addon_xpi, tamper=True)
    try:
        zen = launch_zen({**installed_prefs(), **UPDATE_PREFS})
        addon = zen.install_addon(str(old_xpi), temp=False)
        wait_version(zen, addon, "0.0.1")
        outcome = zen.chrome(UPDATE_CHECK, addon, timeout=60)
        assert outcome == {"failed": "download", "error": "ERROR_INCORRECT_HASH"}, (
            outcome
        )
        status = wait_version(zen, addon, "0.0.1")
        assert status["state"] == "active", status
        assert zen.chrome(ADDON_INFO, addon)["version"] == "0.0.1"
    finally:
        unserve(site, served)


def test_release_manifest_parses_in_zen(zen, site, addon_xpi, tmp_path):
    """The updates.json a release publishes passes Zen's own parser with the
    default security settings: the https update_link, its sha256 and
    strict_min_version survive (AddonUpdateChecker.sys.mjs:93-241)."""
    assert addon_xpi is not None, "the add-on is not built"
    manifest_json = json.loads((REPO_ROOT / "manifest.json").read_text())
    gecko = manifest_json["browser_specific_settings"]["gecko"]
    assert gecko["update_url"] == REAL_UPDATE_URL
    version = manifest_json["version"]
    published = make_updates_json(addon_xpi, tmp_path / "updates.json")
    url = "http://updates.test/release/updates.json"
    site.serve(url, json.dumps(published).encode(), "application/json")
    try:
        results = zen.chrome(
            """
            const [id, url] = args;
            const { AddonUpdateChecker } = ChromeUtils.importESModule(
              "resource://gre/modules/addons/AddonUpdateChecker.sys.mjs");
            const { AddonManager } = ChromeUtils.importESModule(
              "resource://gre/modules/AddonManager.sys.mjs");
            if (!AddonManager.checkUpdateSecurity) throw new Error("security is off");
            return await new Promise((resolve, reject) => {
              AddonUpdateChecker.checkForUpdates(id, url, {
                onUpdateCheckComplete: r => resolve(r.map(u => ({
                  version: u.version, updateURL: u.updateURL ?? null,
                  updateHash: u.updateHash ?? null,
                  minVersion: u.targetApplications[0].minVersion }))),
                onUpdateCheckError: e => reject(new Error("update check error " + e)),
              });
            });
            """,
            ADDON_ID,
            url,
        )
    finally:
        site.unserve(url)
    digest = hashlib.sha256(addon_xpi.read_bytes()).hexdigest()
    assert results == [
        {
            "version": version,
            "updateURL": "https://github.com/zippeurfou/zen-share-picker/releases/"
            f"download/v{version}/{addon_xpi.name}",
            "updateHash": f"sha256:{digest}",
            "minVersion": "160.0",
        }
    ]
