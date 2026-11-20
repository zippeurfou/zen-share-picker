"""Tests for scripts/build.sh, the XPI a release ships. Run with
`uv run --with pytest --with pyyaml pytest tests/release`.
"""

from __future__ import annotations

import json
import re
import subprocess
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ICONS = ["icons/icon.svg", "icons/icon-16.svg"]
VIEWBOXES = {"icons/icon.svg": "0 0 32 32", "icons/icon-16.svg": "0 0 16 16"}
ALLOWED_TOP = {"manifest.json", "LICENSE"}
ALLOWED_DIRS = ("src/", "options/", "icons/")
SVG_NAMESPACE = 'xmlns="http://www.w3.org/2000/svg"'


def build() -> Path:
    out = subprocess.run(
        ["sh", str(REPO / "scripts" / "build.sh")],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(out.stdout.strip().splitlines()[-1])


def test_xpi_holds_the_icons():
    xpi = build()
    with zipfile.ZipFile(xpi) as z:
        names = set(z.namelist())
        files = {n: z.read(n) for n in names}

    for icon in ICONS:
        assert icon in names, icon
        assert files[icon] == (REPO / icon).read_bytes(), icon

    manifest = json.loads(files["manifest.json"])
    for size, path in manifest["icons"].items():
        assert path in names, (size, path)

    for icon in ICONS:
        svg = files[icon].decode("utf-8")
        assert "<text" not in svg, icon
        # The SVG namespace is a name, not a fetch; any other URL is.
        assert "http" not in svg.replace(SVG_NAMESPACE, "", 1), icon
        assert "href" not in svg, icon
        assert all(u.startswith("#") for u in re.findall(r"url\(([^)]*)\)", svg)), icon
        match = re.search(r'viewBox="([^"]*)"', svg)
        assert match and match.group(1) == VIEWBOXES[icon], icon

    stray = [
        n for n in names if n not in ALLOWED_TOP and not n.startswith(ALLOWED_DIRS)
    ]
    assert stray == []
