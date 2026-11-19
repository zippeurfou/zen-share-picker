"""Self-tests for the harness: the profile, the test pages and the add-on
are set up the way the other tests assume, and its guards around the
installed Zen hold."""

import subprocess
import sys
import time
from pathlib import Path

import pytest
import zen


def test_zen_starts_with_a_user_input_on_record(zen):
    since = zen.chrome("return win.windowUtils.millisSinceLastUserInput;")
    assert 0 <= since < 5000


def test_profile_prefs(zen):
    prefs = zen.chrome(
        """
        return [Services.prefs.prefHasUserValue("media.getusermedia.browser.enabled"),
                Services.prefs.getIntPref("security.notification_enable_delay")];
        """
    )
    # The prompt lists tabs without media.getusermedia.browser.enabled in
    # Zen 1.24.2b, so the profile leaves it at its default.
    assert prefs == [False, 500]


def test_meet_page_is_a_secure_context(zen, site):
    zen.visit("http://meet.test/share")
    assert zen.content("return window.isSecureContext;") is True


def test_request_share_shows_the_stock_prompt(zen, site):
    zen.request_share()
    assert zen.stock_prompt_open()
    entries = zen.stock_entries()
    assert any(e["mediaSource"] == "browser" for e in entries), entries


def test_addon_reports_its_version(zen, addon):
    assert zen.addon_call(addon, "getStatus")["version"] == "0.1.0"


# -- the harness's own guards, without a Zen ---------------------------------

# Never run: the guard must stop before any launch. Only a path for the
# update directory name.
MAC_BINARY = "/Applications/Zen.app/Contents/MacOS/zen"


def fake_status(root: Path, text: str | None) -> Path:
    """An update status file for MAC_BINARY under the temporary `root`."""
    status = root / "Applications" / "Zen" / "updates" / "0" / "update.status"
    if text is not None:
        status.parent.mkdir(parents=True, exist_ok=True)
        status.write_text(text)
    return status


@pytest.mark.parametrize(
    "text, staged",
    [
        ("pending\n", True),
        ("pending-service\n", True),
        ("applied\n", True),
        ("applied-service\n", True),
        ("succeeded\n", False),
        ("failed: 7\n", False),
        (None, False),
    ],
)
def test_staged_update_reads_the_install_status(tmp_path, text, staged):
    status = fake_status(tmp_path, text)
    assert zen.update_status_file(MAC_BINARY, tmp_path) == status
    assert zen.staged_update(MAC_BINARY, tmp_path, "darwin") is staged
    assert zen.staged_update(MAC_BINARY, tmp_path, "linux") is False


def test_a_staged_update_stops_the_session_before_any_launch(tmp_path, monkeypatch):
    fake_status(tmp_path, "applied\n")
    monkeypatch.setattr(zen, "UPDATE_ROOT", tmp_path)
    monkeypatch.setattr(zen, "PLATFORM", "darwin")

    def no_launch(*a, **k):
        raise AssertionError("Zen was launched")

    monkeypatch.setattr(zen.subprocess, "Popen", no_launch)
    z = zen.Zen(binary=MAC_BINARY, headless=True)
    with pytest.raises(pytest.exit.Exception, match=zen.STAGED_MESSAGE):
        z.start()
    assert z.profile is None and z.process is None


def sleeper(profile: Path) -> subprocess.Popen:
    """A process whose command line holds `-profile <profile>`."""
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)", "-profile", str(profile)],
        start_new_session=True,
    )


def test_close_kills_every_process_on_the_exact_profile_path(tmp_path):
    profile = tmp_path / "zen-share-picker-profile-abc"
    profile.mkdir()
    other = tmp_path / "zen-share-picker-profile-abcd"
    other.mkdir()
    target = sleeper(profile)
    control = sleeper(other)
    try:
        time.sleep(0.5)
        z = zen.Zen(binary=MAC_BINARY, headless=True)
        z.profile = profile
        z.close()
        assert target.wait(timeout=10) is not None
        assert control.poll() is None
        assert not profile.exists()
    finally:
        for p in (target, control):
            p.kill()
            p.wait()


def test_zen_version_reads_application_ini(tmp_path):
    app = tmp_path / "Zen.app"
    ini = app / "Contents" / "Resources" / "application.ini"
    ini.parent.mkdir(parents=True)
    ini.write_text("[App]\nVendor=Zen\nVersion=9.9.9b\nBuildID=1\n")
    assert zen.zen_version(str(app / "Contents" / "MacOS" / "zen")) == "9.9.9b"
    linux = tmp_path / "opt" / "zen"
    linux.mkdir(parents=True)
    (linux / "application.ini").write_text("[App]\nVersion=8.8.8b\n")
    assert zen.zen_version(str(linux / "zen")) == "8.8.8b"
    assert zen.zen_version(str(tmp_path / "nowhere" / "zen")) is None
