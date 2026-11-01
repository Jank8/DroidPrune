"""Tests for the application core (no Qt event loop required)."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from droidprune.core.adb import Adb  # noqa: E402
from droidprune.core.engine import Engine, WorkItem  # noqa: E402
from droidprune.core.journal import Journal  # noqa: E402
from droidprune.core.models import (Action, Category, Level, MatchRules,  # noqa: E402
                                   Package, Profile, ProfileError, State)
from droidprune.core.profiles import ProfileStore  # noqa: E402
from droidprune.core.selection import SelectionStore  # noqa: E402
from droidprune.paths import PROFILES_DIR  # noqa: E402
from tests.fake_adb import FakeAdb  # noqa: E402

PROFILE_PATH = PROFILES_DIR / "oneplus15_oos16.json"


class ProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.profile = Profile.load(PROFILE_PATH)

    def test_all_shipped_profiles_are_valid(self) -> None:
        store = ProfileStore(PROFILES_DIR)
        profiles = store.reload()
        self.assertTrue(profiles)
        self.assertEqual(store.errors, [])

    def test_catalogue_shape(self) -> None:
        profile = self.profile
        self.assertEqual(profile.id, "oneplus15_oos16")
        self.assertEqual(profile.package_count, 232)
        self.assertEqual(profile.category_count, 6)
        counts = profile.counts()
        self.assertEqual(counts[Level.SAFE], 82)
        self.assertEqual(counts[Level.CAUTION], 107)
        self.assertEqual(counts[Level.RISKY], 43)
        self.assertEqual(len({p.package for p in profile.packages}), 232)

    def test_every_package_has_a_category_and_title(self) -> None:
        for package in self.profile.packages:
            self.assertTrue(package.title)
            self.assertIsNotNone(self.profile.category(package.category))

    def test_round_trip(self) -> None:
        restored = Profile.from_dict(json.loads(self.profile.to_json()))
        self.assertEqual(restored.to_dict(), self.profile.to_dict())

    def test_match_oneplus(self) -> None:
        props = {
            "brand": "OnePlus",
            "model": "OnePlus 15",
            "android": "16",
            "os": "OxygenOS 16.0.1",
        }
        result = self.profile.match_device(props)
        self.assertGreaterEqual(result.score, 0.99)
        self.assertTrue(result.is_match)

    def test_match_other_phone(self) -> None:
        props = {"brand": "Samsung", "model": "SM-S931B", "android": "15", "os": ""}
        result = self.profile.match_device(props)
        self.assertFalse(result.is_match)

    def test_unknown_category_rejected(self) -> None:
        data = {
            "id": "broken",
            "name": "Broken",
            "categories": [{"id": "one", "name": "One"}],
            "packages": [{
                "package": "com.example.app",
                "category": "missing",
                "level": "safe",
                "action": "disable",
            }],
        }
        with self.assertRaises(ProfileError):
            Profile.from_dict(data)

    def test_invalid_level_rejected(self) -> None:
        with self.assertRaises(ProfileError):
            Package.from_dict({"package": "com.example.app", "level": "maybe"})

    def test_invalid_package_name_rejected(self) -> None:
        with self.assertRaises(ProfileError):
            Package.from_dict({"package": "not a package"})

    def test_snapshot_state_round_trip(self) -> None:
        package = Package.from_dict({
            "package": "com.example.app",
            "category": "general",
            "level": "caution",
            "action": "disable",
            "state": "disabled",
        })
        self.assertIs(package.state, State.DISABLED)
        restored = Package.from_dict(json.loads(json.dumps(package.to_dict())))
        self.assertEqual(restored, package)
        self.assertIn("snapshot", restored.search_blob)

    def test_invalid_snapshot_state_rejected(self) -> None:
        for value in ("absent", "unknown", "gone"):
            with self.subTest(value=value):
                with self.assertRaises(ProfileError):
                    Package.from_dict({
                        "package": "com.example.app",
                        "category": "general",
                        "state": value,
                    })


class MatchRuleTests(unittest.TestCase):
    def test_partial_score(self) -> None:
        profile = Profile(
            id="test",
            name="Test",
            categories=[Category("general", "General")],
            packages=[Package("com.example.app", category="general")],
            match=MatchRules(brand="oneplus", model="oneplus 15", android="^16"),
        )
        result = profile.match_device({
            "brand": "OnePlus", "model": "OnePlus 15", "android": "15", "os": "",
        })
        self.assertAlmostEqual(result.score, 2 / 3)
        self.assertTrue(result.is_match)


class ProfileStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="uad-test-")
        self.directory = Path(self.temp.name)
        self.store = ProfileStore(self.directory / "profiles")
        self.profile = Profile.load(PROFILE_PATH)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_create_duplicate_export_delete(self) -> None:
        store = self.store
        blank = store.create_blank("My phone")
        self.assertTrue(store.path_for(blank.id).exists())
        store.reload()
        self.assertIsNotNone(store.get(blank.id))

        copy = store.duplicate(self.profile)
        self.assertNotEqual(copy.id, self.profile.id)
        self.assertIn("copy", copy.name)

        export = store.export_file(copy, self.directory / "export.json")
        self.assertTrue(export.exists())
        imported = store.import_file(export)
        self.assertNotEqual(imported.id, copy.id)

        store.delete(imported)
        self.assertIsNone(store.get(imported.id))

    def test_broken_file_is_reported_not_raised(self) -> None:
        (self.store.directory / "bad.json").write_text("{ nope", encoding="utf-8")
        store = ProfileStore(self.store.directory)
        profiles = store.reload()
        self.assertEqual(profiles, [])
        self.assertEqual(len(store.errors), 1)

    def test_profile_requires_packages_or_categories(self) -> None:
        empty = Profile(id="empty", name="Empty")
        with self.assertRaises(ProfileError):
            self.store.save(empty)


class SelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="uad-sel-")
        self.directory = Path(self.temp.name) / "selection"
        self.store = SelectionStore(self.directory)
        self.profile = Profile.load(PROFILE_PATH)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_round_trip_and_overrides(self) -> None:
        selection = self.store.load(self.profile)
        first = self.profile.packages[0]
        second = self.profile.packages[1]
        selection.set_selected(first.package, True)
        selection.set_selected(second.package, True)
        selection.set_action(first, Action.DISABLE)
        self.store.save(self.profile, selection)

        restored = self.store.load(self.profile)
        self.assertTrue(restored.is_selected(first.package))
        self.assertEqual(restored.action_for(first), Action.DISABLE)
        self.assertEqual(restored.action_for(second), second.action)

    def test_unknown_packages_are_dropped(self) -> None:
        path = self.store.path_for(self.profile.id)
        path.write_text(json.dumps({
            "schema": 1,
            "packages": [
                {"package": "com.example.gone", "selected": True},
                {"package": self.profile.packages[0].package, "selected": True},
            ],
        }), encoding="utf-8")
        selection = self.store.load(self.profile)
        self.assertFalse(selection.is_selected("com.example.gone"))
        self.assertTrue(selection.is_selected(self.profile.packages[0].package))


class _ShellAdb(Adb):
    """Adb with canned shell responses, so parsing can be tested offline."""

    def __init__(self, outputs: dict[str, str]) -> None:
        super().__init__("adb")
        self.outputs = outputs

    def _run(self, args, *, serial=None, timeout=None):
        command = " ".join(args)
        for key, value in self.outputs.items():
            if key in command:
                return subprocess.CompletedProcess(args, 0, value, "")
        return subprocess.CompletedProcess(args, 0, "", "")


class AdbParsingTests(unittest.TestCase):
    def test_devices_list(self) -> None:
        adb = _ShellAdb({
            "devices -l": (
                "List of devices attached\n"
                "R5CT123ABCD   device product:CPH2745 model:OnePlus_15 "
                "device:OP5D3BL1 transport_id:1\n"
                "emulator-5554 offline transport_id:2\n"
            )
        })
        devices = adb.devices()
        self.assertEqual(len(devices), 2)
        self.assertEqual(devices[0].serial, "R5CT123ABCD")
        self.assertEqual(devices[0].model, "OnePlus 15")
        self.assertTrue(devices[0].ready)
        self.assertFalse(devices[1].ready)

    def test_inventory_states(self) -> None:
        adb = _ShellAdb({
            "pm list packages --user 0 -f -u": (
                "package:/system/app/A/A.apk=com.example.active\n"
                "package:/system/app/B/B.apk=com.example.disabled\n"
                "package:/system/app/C/C.apk=com.example.removed\n"
            ),
            "pm list packages --user 0 -f -d": (
                "package:/system/app/B/B.apk=com.example.disabled\n"
            ),
            "pm list packages --user 0 -f": (
                "package:/system/app/A/A.apk=com.example.active\n"
                "package:/system/app/B/B.apk=com.example.disabled\n"
            ),
        })
        inventory = adb.inventory("SERIAL")
        self.assertEqual(inventory.state("com.example.active"), State.ACTIVE)
        self.assertEqual(inventory.state("com.example.disabled"), State.DISABLED)
        self.assertEqual(inventory.state("com.example.removed"), State.UNINSTALLED)
        self.assertEqual(inventory.state("com.example.missing"), State.ABSENT)

    def test_getprop(self) -> None:
        adb = _ShellAdb({
            "getprop": (
                "[ro.product.brand]: [OnePlus]\n"
                "[ro.product.model]: [CPH2745]\n"
                "[ro.vendor.oplus.market.name]: [OnePlus 15]\n"
                "[ro.build.version.release]: [16]\n"
                "[ro.build.version.sdk]: [36]\n"
                "[ro.build.version.oplusrom]: [V16.0.1]\n"
            )
        })
        info = adb.device_info("SERIAL")
        self.assertEqual(info.model, "OnePlus 15")
        self.assertEqual(info.brand, "OnePlus")
        self.assertEqual(info.android, "16")
        self.assertEqual(info.os_version, "V16.0.1")

    def test_success_detection(self) -> None:
        self.assertTrue(Adb._success(
            "disable", "Package com.foo new state: disabled-user"
        ))
        self.assertFalse(Adb._success(
            "disable", "Error: java.lang.IllegalArgumentException: Unknown package"
        ))
        self.assertTrue(Adb._success("uninstall", "Success"))
        self.assertFalse(Adb._success("uninstall", "Failure [DELETE_FAILED_USER_RESTRICTED]"))
        self.assertTrue(Adb._success(
            "install-existing", "Package com.foo installed for user: 0"
        ))
        self.assertFalse(Adb._success("enable", ""))


class EngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="uad-engine-")
        self.directory = Path(self.temp.name)
        self.profile = Profile.load(PROFILE_PATH)
        self.fake = FakeAdb(self.profile)
        self.journal = Journal(self.directory / "journal.jsonl")
        self.engine = Engine(self.fake, self.journal, self.directory / "logs")
        self.device = self.fake.device_info(self.fake.serial)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _items(self, count: int, action: Action) -> list[WorkItem]:
        return [WorkItem(package, action)
                for package in self.profile.packages[:count]]

    def test_apply_then_revert(self) -> None:
        items = self._items(3, Action.UNINSTALL)
        progress: list[tuple[int, str]] = []
        result = self.engine.run(
            profile=self.profile,
            device=self.device,
            items=items,
            revert=False,
            dry_run=False,
            states={item.package.package: self.fake.state_of(item.package.package)
                    for item in items},
            on_progress=lambda done, total, package, ok: progress.append(
                (done, package.package)
            ),
        )
        self.assertEqual(result.ok, 3)
        self.assertEqual(result.failed, 0)
        self.assertFalse(result.dry_run)
        self.assertEqual(len(progress), 3)
        self.assertTrue(result.log_path and result.log_path.exists())
        for item in items:
            self.assertEqual(self.fake.state_of(item.package.package),
                             State.UNINSTALLED)

        states = {item.package.package: self.fake.state_of(item.package.package)
                  for item in items}
        revert = self.engine.run(
            profile=self.profile,
            device=self.device,
            items=items,
            revert=True,
            dry_run=False,
            states=states,
        )
        self.assertEqual(revert.ok, 3)
        for item in items:
            self.assertEqual(self.fake.state_of(item.package.package), State.ACTIVE)
        actions = [call[2] for call in self.fake.calls if call[0] == "revert"]
        self.assertEqual(actions, ["install-existing"] * 3)

        runs = self.journal.runs()
        self.assertEqual(len(runs), 2)
        self.assertEqual(runs[0].kind, "revert")
        self.assertEqual(runs[1].kind, "apply")
        self.assertIn("com.", self.journal.export_text(runs[1]))

    def test_dry_run_does_not_touch_device(self) -> None:
        items = self._items(2, Action.DISABLE)
        before = len(self.fake.calls)
        result = self.engine.run(
            profile=self.profile,
            device=self.device,
            items=items,
            revert=False,
            dry_run=True,
        )
        self.assertTrue(result.dry_run)
        self.assertEqual(result.ok, 2)
        self.assertEqual(len(self.fake.calls), before)
        for item in items:
            self.assertEqual(self.fake.state_of(item.package.package), State.ACTIVE)
        run = self.journal.runs()[0]
        self.assertTrue(run.dry_run)
        self.assertIsNone(
            self.journal.last_run("apply", include_dry=False)
        )

    def test_stop_event_aborts(self) -> None:
        event = threading.Event()
        event.set()
        result = self.engine.run(
            profile=self.profile,
            device=self.device,
            items=self._items(4, Action.DISABLE),
            revert=False,
            dry_run=False,
            stop_event=event,
        )
        self.assertTrue(result.stopped)
        self.assertEqual(result.total, 4)
        self.assertEqual(result.entries, [])
        self.assertEqual(self.fake.calls, [])


class JournalTests(unittest.TestCase):
    def test_grouping_and_limits(self) -> None:
        temp = tempfile.TemporaryDirectory(prefix="uad-journal-")
        self.addCleanup(temp.cleanup)
        profile = Profile.load(PROFILE_PATH)
        fake = FakeAdb(profile)
        journal = Journal(Path(temp.name) / "journal.jsonl")
        engine = Engine(fake, journal, Path(temp.name) / "logs")
        device = fake.device_info(fake.serial)
        for count in (2, 3):
            engine.run(
                profile=profile,
                device=device,
                items=[WorkItem(p, Action.DISABLE) for p in profile.packages[:count]],
                revert=False,
                dry_run=False,
            )
        runs = journal.runs(limit=1)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].total, 3)
        self.assertEqual(runs[0].ok_count, 3)
        self.assertIsNotNone(journal.last_run("apply"))
        self.assertGreaterEqual(len(journal.entries()), 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
