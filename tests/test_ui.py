"""Qt-level tests: controller wiring, page models and a fake debloat run.

Run with::

    python -m unittest tests.test_ui -v
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import droidprune.core.controller as controller_module  # noqa: E402
from droidprune.core.controller import Controller  # noqa: E402
from droidprune.core.models import Action, Level, Profile, State  # noqa: E402
from droidprune.paths import PROFILES_DIR  # noqa: E402
from droidprune.ui import theme  # noqa: E402
from droidprune.ui.pages.home import HomePage  # noqa: E402
from droidprune.ui.pages.packages import PackagesPage  # noqa: E402
from tests.fake_adb import FakeAdb  # noqa: E402

APP = QApplication.instance() or QApplication(sys.argv)
theme.apply(False)


def wait(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_until(predicate, timeout_ms: int = 6000, step: int = 50) -> bool:
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        if predicate():
            return True
        wait(step)
    return predicate()


class ControllerPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.profile = Profile.load(PROFILES_DIR / "oneplus15_oos16.json")

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="uad-ui-")
        self.directory = Path(self.temp.name)
        self._saved_paths = (
            controller_module.JOURNAL_PATH,
            controller_module.LOG_DIR,
            controller_module.SELECTION_DIR,
        )
        controller_module.JOURNAL_PATH = self.directory / "journal.jsonl"
        controller_module.LOG_DIR = self.directory / "logs"
        controller_module.SELECTION_DIR = self.directory / "selection"

        self.fake = FakeAdb(self.profile)
        self.controller = Controller(adb=self.fake)
        self.controller.set_setting("profile", self.profile.id)
        self.controller.start()
        self.assertTrue(wait_until(lambda: self.controller.inventory is not None))

    def tearDown(self) -> None:
        self.controller.shutdown()
        (controller_module.JOURNAL_PATH,
         controller_module.LOG_DIR,
         controller_module.SELECTION_DIR) = self._saved_paths
        self.temp.cleanup()

    # ------------------------------------------------------------------
    def test_device_and_inventory(self) -> None:
        self.assertIsNotNone(self.controller.device)
        self.assertEqual(self.controller.device.model, "OnePlus 15")
        self.assertEqual(self.controller.profile.id, "oneplus15_oos16")
        self.assertEqual(
            self.controller.state_for("com.amazon.appmanager"), State.ACTIVE
        )

    def test_selection_persists(self) -> None:
        package = self.profile.packages[0]
        self.controller.set_selected(package.package, True)
        self.controller.set_action(package, Action.DISABLE)
        self.assertTrue(wait_until(
            lambda: (self.directory / "selection" / "oneplus15_oos16.json").exists()
        ))
        symbol = self.directory / "selection" / "oneplus15_oos16.json"
        self.assertIn(package.package, symbol.read_text(encoding="utf-8"))
        self.assertEqual(
            self.controller.selection.action_for(package), Action.DISABLE
        )

    def test_packages_page_filters(self) -> None:
        page = PackagesPage(self.controller)
        wait(50)
        model = page.table.model()
        self.assertEqual(model.rowCount(), 232)

        page.search.setText("facebook")
        wait(50)
        visible = page.table.visible_packages()
        self.assertTrue(visible)
        self.assertTrue(all("facebook" in p.search_blob for p in visible))

        page.search.setText("")
        page.level_combo.setCurrentIndex(1)  # Safe
        wait(50)
        self.assertTrue(page.table.visible_packages())
        self.assertTrue(all(p.level is Level.SAFE
                            for p in page.table.visible_packages()))

        page.level_combo.setCurrentIndex(0)
        page.category_list.setCurrentRow(2)  # Google Bloat
        wait(50)
        visible = page.table.visible_packages()
        self.assertEqual(len(visible), 46)
        self.assertTrue(all(p.category == "google" for p in visible))

        page.category_list.setCurrentRow(0)
        page.search.setText("")
        wait(50)
        self.assertEqual(model.rowCount(), 232)
        page.deleteLater()

    def test_action_toggle_and_footer(self) -> None:
        page = PackagesPage(self.controller)
        wait(50)
        package = self.controller.profile.get("com.amazon.appmanager")
        self.assertEqual(self.controller.action_for(package), Action.UNINSTALL)
        page._toggle_action(package.package)
        self.assertEqual(self.controller.action_for(package), Action.DISABLE)
        page._toggle_action(package.package)
        self.assertEqual(self.controller.action_for(package), Action.UNINSTALL)

        self.controller.set_selected(package.package, True)
        wait(30)
        self.assertIn("1", page.selection_label.text())
        self.assertTrue(page.apply_button.isEnabled())
        page.deleteLater()

    def test_home_page_reads_controller(self) -> None:
        home = HomePage(self.controller)
        wait(50)
        self.assertEqual(
            home.profile_combo.currentText(), "OnePlus 15 - OxygenOS 16"
        )
        self.assertIn("232", home.profile_stats.text())
        self.assertEqual(home.stat_present.value.text(), "186")

        package = self.profile.packages[0]
        self.controller.set_selected(package.package, True)
        wait(30)
        self.assertEqual(home.stat_selected.value.text(), "1")
        self.assertTrue(home.apply_button.isEnabled())
        home.deleteLater()

    def test_apply_run_updates_states_and_journal(self) -> None:
        package = next(
            p for p in self.profile.packages
            if self.controller.state_for(p.package) is State.ACTIVE
        )
        self.controller.set_selected(package.package, True)
        default_action = self.controller.action_for(package)
        self.controller.apply_selected(dry_run=False)
        self.assertTrue(wait_until(lambda: not self.controller.running, 8000))
        wait(700)

        expected = State.UNINSTALLED if default_action is Action.UNINSTALL \
            else State.DISABLED
        self.assertEqual(self.controller.state_for(package.package), expected)
        runs = self.controller.journal.runs(limit=1)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].kind, "apply")
        self.assertEqual(runs[0].ok_count, 1)
        self.assertTrue((self.directory / "logs").exists())

    def test_theme_palette_switch_does_not_raise(self) -> None:
        page = PackagesPage(self.controller)
        wait(30)
        for light in (True, False, True):
            theme.apply(light)
            page.apply_palette()
            wait(20)
        self.assertTrue(theme.palette().light)
        page.deleteLater()


class SnapshotProfileTests(unittest.TestCase):
    """Creating a profile from the packages installed on a fake device."""

    def test_snapshot_creates_a_usable_profile(self) -> None:
        profile = Profile.load(PROFILES_DIR / "oneplus15_oos16.json")
        fake = FakeAdb(profile)
        temp = tempfile.TemporaryDirectory(prefix="uad-snapshot-")
        self.addCleanup(temp.cleanup)
        directory = Path(temp.name)

        saved = (
            controller_module.PROFILES_DIR,
            controller_module.JOURNAL_PATH,
            controller_module.LOG_DIR,
            controller_module.SELECTION_DIR,
        )
        controller_module.PROFILES_DIR = directory / "profiles"
        controller_module.JOURNAL_PATH = directory / "journal.jsonl"
        controller_module.LOG_DIR = directory / "logs"
        controller_module.SELECTION_DIR = directory / "selection"
        try:
            controller = Controller(adb=fake)
            controller.start()
            self.assertTrue(wait_until(lambda: controller.inventory is not None))
            controller.create_profile_from_device(
                "Snapshot test",
                include_system=False,
                level=Level.CAUTION,
            )
            self.assertTrue(wait_until(
                lambda: bool(controller.profiles_list), 8000
            ))
            wait(200)
            created = controller.profile
            self.assertIsNotNone(created)
            self.assertEqual(created.name, "Snapshot test")
            self.assertEqual(len(created.packages), 10)
            states = {package.state for package in created.packages}
            self.assertIn(State.ACTIVE, states)
            self.assertIn(State.DISABLED, states)
            self.assertIn(State.UNINSTALLED, states)
            for package in created.packages:
                self.assertEqual(package.state, fake.state_of(package.package))
                if package.state is State.ACTIVE:
                    self.assertEqual(package.note, "")
                else:
                    self.assertIn("Snapshot", package.note)
                if package.state is State.DISABLED:
                    self.assertIs(package.action, Action.DISABLE)
                else:
                    self.assertIs(package.action, Action.UNINSTALL)
            self.assertIn("disabled", created.description)
            self.assertIn("removed for user 0", created.description)
            self.assertTrue(all(package.level is Level.CAUTION
                                for package in created.packages))
            self.assertTrue((directory / "profiles" / f"{created.id}.json").exists())
            controller.shutdown()
        finally:
            (controller_module.PROFILES_DIR,
             controller_module.JOURNAL_PATH,
             controller_module.LOG_DIR,
             controller_module.SELECTION_DIR) = saved


if __name__ == "__main__":
    unittest.main(verbosity=2)
