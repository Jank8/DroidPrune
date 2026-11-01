"""Headless-ish visual check: builds the real window with a fake phone and
writes PNG screenshots of every page.  Run from the repository root:

    python tests/preview_ui.py
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

from debloater.core.controller import Controller  # noqa: E402
import debloater.core.controller as controller_module  # noqa: E402
from debloater.core.models import Level, Profile  # noqa: E402
from debloater.paths import PROFILES_DIR  # noqa: E402
from debloater.ui import theme  # noqa: E402
from debloater.ui.main_window import MainWindow  # noqa: E402
from tests.fake_adb import FakeAdb  # noqa: E402

SHOTS = ROOT / "shots"


def wait(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_until(predicate, timeout_ms: int = 8000, step: int = 100) -> bool:
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        if predicate():
            return True
        wait(step)
    return predicate()


def main() -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix="uad-preview-"))
    controller_module.JOURNAL_PATH = temp / "journal.jsonl"
    controller_module.LOG_DIR = temp / "logs"
    controller_module.SELECTION_DIR = temp / "selection"

    profile = Profile.load(PROFILES_DIR / "oneplus15_oos16.json")
    fake = FakeAdb(profile)

    app = QApplication(sys.argv)
    app.setApplicationName("Universal Android Debloater")
    theme.apply(False)

    controller = Controller(adb=fake)
    window = MainWindow(controller)
    window.resize(1400, 900)
    window.show()
    controller.start()

    wait_until(lambda: controller.inventory is not None, 9000)
    wait(400)

    print("device      :", controller.device)
    print("inventory   :", controller.inventory.total if controller.inventory else None)
    print("profile     :", controller.profile.name if controller.profile else None)

    # A believable selection: a handful of safe apps plus two caution ones.
    safe = [p for p in profile.packages if p.level is Level.SAFE][:7]
    caution = [p for p in profile.packages if p.level is Level.CAUTION][:2]
    for package in safe + caution:
        controller.set_selected(package.package, True)

    pages = [
        ("home", window.home),
        ("packages", window.packages),
        ("profiles", window.profiles),
        ("activity", window.activity),
        ("settings", window.settings),
    ]
    for name, page in pages:
        if name == "packages":
            window.packages.category_list.setCurrentRow(0)
        if name == "activity" and not controller.journal.runs(limit=1):
            pass
        window.switchTo(page)
        wait(600)
        path = SHOTS / f"{name}.png"
        window.grab().save(str(path))
        print("saved", path.relative_to(ROOT))

    # Simulate a real run so Activity has content and the table states change.
    window.switchTo(window.home)
    wait(300)
    controller.apply_selected(dry_run=False)
    wait_until(lambda: not controller.running, 10000)
    wait(1200)

    window.switchTo(window.activity)
    wait(700)
    window.grab().save(str(SHOTS / "activity-run.png"))
    print("saved shots/activity-run.png")

    window.switchTo(window.packages)
    wait(700)
    window.grab().save(str(SHOTS / "packages-after.png"))
    print("saved shots/packages-after.png")

    runs = controller.journal.runs(limit=3)
    if runs:
        print("run         :", runs[0].kind, runs[0].ok_count, "/", runs[0].total)

    # Light theme snapshot of the home page.
    theme.apply(True)
    window.apply_theme_mode("light")
    window.switchTo(window.home)
    wait(700)
    window.grab().save(str(SHOTS / "home-light.png"))
    print("saved shots/home-light.png")

    fake.calls.clear()
    controller.shutdown()
    window.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
