"""Stress the window: many page switches, theme flips and two real runs.

Run from the repository root (exits non-zero on a crash)::

    python tests/stress_ui.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
os.environ["UAD_DISABLE_MICA"] = "1"

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import droidprune.core.controller as controller_module  # noqa: E402
from droidprune.core.controller import Controller  # noqa: E402
from droidprune.core.models import Level, Profile, State  # noqa: E402
from droidprune.paths import PROFILES_DIR  # noqa: E402
from droidprune.ui import theme  # noqa: E402
from droidprune.ui.main_window import MainWindow  # noqa: E402
from tests.fake_adb import FakeAdb  # noqa: E402


def wait(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_until(predicate, timeout_ms: int = 8000, step: int = 50) -> bool:
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        if predicate():
            return True
        wait(step)
    return predicate()


def main() -> int:
    temp = Path(tempfile.mkdtemp(prefix="uad-stress-"))
    controller_module.JOURNAL_PATH = temp / "journal.jsonl"
    controller_module.LOG_DIR = temp / "logs"
    controller_module.SELECTION_DIR = temp / "selection"

    profile = Profile.load(PROFILES_DIR / "oneplus15_oos16.json")
    fake = FakeAdb(profile)

    app = QApplication(sys.argv)
    theme.apply(False)
    controller = Controller(adb=fake)
    window = MainWindow(controller)
    window.resize(1400, 900)
    window.show()
    controller.start()
    assert wait_until(lambda: controller.inventory is not None), "no inventory"

    pages = ["home", "packages", "profiles", "activity", "settings"]
    for cycle in range(3):
        for name in pages:
            window.switch_to(name)
            wait(120)
        for mode in ("light", "dark", "system"):
            window.apply_theme_mode(mode)
            wait(120)
        for name in reversed(pages):
            window.switch_to(name)
            wait(120)
        print(f"cycle {cycle + 1} ok", flush=True)

    # Select a handful and run a real (fake) apply + revert.
    targets = [p for p in profile.packages if p.level is Level.SAFE][:5]
    for package in targets:
        controller.set_selected(package.package, True)
    controller.apply_selected(dry_run=False)
    assert wait_until(lambda: not controller.running), "apply did not finish"
    wait(600)
    states = [controller.state_for(p.package) for p in targets]
    print("after apply:", states, flush=True)
    if any(state is not State.UNINSTALLED for state in states):
        print("unexpected state after apply", flush=True)
        return 1

    controller.revert_selected(dry_run=False)
    assert wait_until(lambda: not controller.running), "revert did not finish"
    wait(600)
    states = [controller.state_for(p.package) for p in targets]
    print("after revert:", states, flush=True)
    if any(state is not State.ACTIVE for state in states):
        print("unexpected state after revert", flush=True)
        return 1

    runs = controller.journal.runs(limit=4)
    print("runs:", [(r.kind, r.ok_count, r.total) for r in runs], flush=True)

    window.switch_to("activity")
    wait(400)
    window.grab().save(str(ROOT / "shots" / "stress-activity.png"))
    window.close()
    controller.shutdown()
    print("stress ok", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
