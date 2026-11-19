"""An in-place update loads the new version's code without a Zen restart."""

import json
import re
import subprocess
from pathlib import Path

from test_picker import (
    DOCS,
    WIKI,
    assert_prompt_concealed,
    assert_prompt_untouched,
    key_of,
    setup,
    wait_gone,
    wait_picker,
)
from zen import REPO_ROOT

HOST_CHECK = """
const resProto = Cc["@mozilla.org/network/protocol;1?name=resource"].getService(
  Ci.nsISubstitutingProtocolHandler);
return Object.fromEntries(args[0].map(h => [h, resProto.hasSubstitution(h)]));
"""

# The row key (P9) of the selected tab.
SELECTED_KEY = """
const t = win.gBrowser.selectedTab;
return t.id || "browser:" + t.linkedBrowser.browserId;
"""


def host_for(version: str) -> str:
    return "zen-share-picker-" + re.sub(r"[^A-Za-z0-9]", "-", version)


def test_update_in_place(zen, site, addon):
    assert addon is not None, "the add-on is not built"
    old = json.loads((REPO_ROOT / "manifest.json").read_text())["version"]
    new = old + ".1"
    out = subprocess.run(
        ["sh", str(REPO_ROOT / "scripts" / "build.sh"), new],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    new_xpi = Path(out.stdout.strip().splitlines()[-1])
    assert new_xpi.name == f"zen-share-picker-{new}.xpi"

    assert zen.addon_call(addon, "getStatus")["version"] == old
    # A picker open on a concealed panel when the update lands.
    setup(zen)
    wait_picker(zen)
    assert_prompt_concealed(zen)
    assert zen.chrome(HOST_CHECK, [host_for(old), host_for(new)]) == {
        host_for(old): True,
        host_for(new): False,
    }

    assert zen.install_addon(str(new_xpi)) == addon
    status = zen.wait_addon_active(addon)
    assert status["version"] == new, f"still the old code: {status}"
    assert status["state"] == "active", status
    assert zen.chrome(HOST_CHECK, [host_for(old), host_for(new)]) == {
        host_for(old): False,
        host_for(new): True,
    }
    # The old version's picker is gone and Zen's prompt is visible again.
    wait_gone(zen)
    assert_prompt_untouched(zen)

    # Positive control: the updated add-on opens its picker on a fresh share
    # request, from a second Meet tab, and hides the panel.
    first_meet = zen.chrome(SELECTED_KEY)
    zen.request_share()
    p = wait_picker(zen)
    expected = [first_meet, key_of(zen, WIKI), key_of(zen, DOCS)]
    assert p["keys"] == expected, p
    assert_prompt_concealed(zen)
    status = zen.addon_call(addon, "getStatus")
    assert status["version"] == new, status
    assert status["promptProblems"] == [], status
