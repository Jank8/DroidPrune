"""Filesystem layout for the application.

The tool is portable: profiles and user data live next to the launcher, so the
folder can be copied to a USB stick.  When running frozen (PyInstaller) the
bundled read-only resources sit in ``sys._MEIPASS`` while writable files stay
next to the executable.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def _installation_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _resource_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", _installation_root()))
    return Path(__file__).resolve().parent.parent


BASE_DIR = _installation_root()
RESOURCE_DIR = _resource_root()

PROFILES_DIR = BASE_DIR / "profiles"
SEED_PROFILES_DIR = RESOURCE_DIR / "profiles"
DATA_DIR = BASE_DIR / "data"
SELECTION_DIR = DATA_DIR / "selection"
LOG_DIR = DATA_DIR / "logs"
JOURNAL_PATH = DATA_DIR / "journal.jsonl"


def ensure_directories() -> None:
    """Create the writable folders and seed the bundled profiles once."""
    for directory in (PROFILES_DIR, DATA_DIR, SELECTION_DIR, LOG_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    if SEED_PROFILES_DIR.exists() and SEED_PROFILES_DIR != PROFILES_DIR:
        for source in SEED_PROFILES_DIR.glob("*.json"):
            target = PROFILES_DIR / source.name
            if not target.exists():
                target.write_bytes(source.read_bytes())


def is_writable(path: Path) -> bool:
    try:
        with tempfile.NamedTemporaryFile(dir=path, prefix=".write-test-", delete=True):
            return True
    except OSError:
        return False


def open_in_explorer(path: Path) -> None:
    """Reveal a file or folder in Explorer (no-op elsewhere)."""
    if os.name != "nt":
        return
    import subprocess

    if path.is_file():
        subprocess.Popen(["explorer", "/select,", str(path)])
    else:
        os.startfile(str(path))  # type: ignore[attr-defined]
