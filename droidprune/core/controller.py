"""Application state and background tasks.

The controller owns ADB, the profile catalogue, the current selection and all
long-running work.  Pages only talk to it and react to its Qt signals; no page
runs subprocesses or touches files directly.
"""

from __future__ import annotations

import shutil
import threading
from collections import Counter
from pathlib import Path
from typing import Iterable

from PySide6.QtCore import QObject, QSettings, QTimer, Signal

from .. import APP_ID, ORG_NAME
from ..paths import (JOURNAL_PATH, LOG_DIR, PROFILES_DIR, SELECTION_DIR,
                     ensure_directories)
from .adb import Adb, AdbError, PackageInventory, find_adb, install_platform_tools
from .engine import Engine, RunResult, WorkItem
from .journal import Journal, RunSummary
from .models import (Action, Category, Device, DeviceInfo, Level, MatchResult,
                     Package, Profile, ProfileError, State, now_iso)
from .profiles import ProfileStore, slugify
from .selection import Selection, SelectionStore


class Controller(QObject):
    devicesChanged = Signal()
    deviceChanged = Signal()
    inventoryChanged = Signal()
    profilesChanged = Signal()
    profileChanged = Signal()
    selectionChanged = Signal()
    busyChanged = Signal(bool)
    journalChanged = Signal()
    progress = Signal(int, int, str, bool)
    logLine = Signal(str)
    runFinished = Signal(object)
    notice = Signal(str, str)          # kind ("info"/"warning"/"error"), text
    adbChanged = Signal()

    _devicesLoaded = Signal(object)
    _devicesFailed = Signal(object)
    _deviceInfoLoaded = Signal(object)
    _deviceInfoFailed = Signal(str)
    _inventoryLoaded = Signal(object)
    _inventoryFailed = Signal(str)
    _runDone = Signal(object)
    _profileCreated = Signal(object)
    _profileFailed = Signal(str)
    _snapshotBuilt = Signal(object)
    _adbInstallFinished = Signal(object)
    _errorMessage = Signal(str)
    _busyRelease = Signal()

    def __init__(self, parent: QObject | None = None, *, adb: Adb | None = None) -> None:
        super().__init__(parent)
        ensure_directories()
        self.settings = QSettings(ORG_NAME, APP_ID)
        stored_adb = str(self.settings.value("adb_path", "") or "")
        self.adb = adb or Adb(stored_adb or None)
        self.profiles = ProfileStore(PROFILES_DIR)
        self.selection_store = SelectionStore(SELECTION_DIR)
        self.journal = Journal(JOURNAL_PATH)
        self.engine = Engine(self.adb, self.journal, LOG_DIR)

        self.devices: list[Device] = []
        self.device: DeviceInfo | None = None
        self.inventory: PackageInventory | None = None
        self.states: dict[str, State] = {}
        self.profile: Profile | None = None
        self.selection = Selection("")

        self._busy_depth = 0
        self._busy_text = ""
        self._scanning = False
        self._fetching_info = False
        self._loading_inventory = False
        self._running = False
        self._inventory_serial = ""
        self._stop_event = threading.Event()
        self._auto_timer = QTimer(self)
        self._auto_timer.setInterval(6000)
        self._auto_timer.timeout.connect(lambda: self.refresh_devices(quiet=True))

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(350)
        self._save_timer.timeout.connect(self._flush_selection)

        self._devicesLoaded.connect(self._on_devices_loaded)
        self._devicesFailed.connect(self._on_devices_failed)
        self._deviceInfoLoaded.connect(self._on_device_info_loaded)
        self._deviceInfoFailed.connect(self._on_device_info_failed)
        self._inventoryLoaded.connect(self._on_inventory_loaded)
        self._inventoryFailed.connect(self._on_inventory_failed)
        self._runDone.connect(self._on_run_done)
        self._profileCreated.connect(self._on_profile_created)
        self._profileFailed.connect(lambda message: self.notice.emit("error", message))
        self._snapshotBuilt.connect(self._on_snapshot_built)
        self._adbInstallFinished.connect(self._on_adb_install_finished)
        self._errorMessage.connect(lambda message: self.notice.emit("warning", message))
        self._busyRelease.connect(self._end_busy)

    # ------------------------------------------------------------------ setup
    def start(self) -> None:
        self.profiles.reload()
        last_id = str(self.settings.value("profile", "") or "")
        chosen = self.profiles.get(last_id) if last_id else None
        if chosen is None and self.profiles.profiles:
            chosen = self.profiles.profiles[0]
        if chosen is not None:
            self.profile = chosen
            self.selection = self.selection_store.load(chosen)
        self._recompute_states()
        self.profilesChanged.emit()
        self.profileChanged.emit()
        self.selectionChanged.emit()
        self.refresh_devices()
        seconds = self._auto_refresh_seconds()
        if seconds > 0:
            self._auto_timer.setInterval(seconds * 1000)
            self._auto_timer.start()

    # -------------------------------------------------------------- devices
    @property
    def ready_device(self) -> DeviceInfo | None:
        if self.device and self.device.ready:
            return self.device
        return None

    def refresh_devices(self, quiet: bool = False) -> None:
        if self._scanning:
            return
        self._scanning = True

        def work() -> None:
            try:
                devices = self.adb.devices()
            except AdbError as error:
                self._devicesFailed.emit((str(error), quiet))
                return
            finally:
                self._scanning = False
            self._devicesLoaded.emit(devices)

        threading.Thread(target=work, daemon=True, name="adb-devices").start()

    def _on_devices_loaded(self, devices: list[Device]) -> None:
        self.devices = list(devices)
        ready = [device for device in self.devices if device.ready]
        serials = {device.serial for device in ready}

        selected = self.device.serial if self.device else ""
        if selected not in serials:
            selected = ready[0].serial if ready else ""

        self._scanning = False
        self.devicesChanged.emit()

        if not selected:
            if self.device is not None:
                self.device = None
                self.inventory = None
                self.states = {}
                self._inventory_serial = ""
                self.deviceChanged.emit()
                self.inventoryChanged.emit()
            return

        if self.device is None or self.device.serial != selected:
            if self.device is not None and self.device.serial != selected:
                self.device = None
                self.inventory = None
                self.states = {}
                self._inventory_serial = ""
                self.deviceChanged.emit()
                self.inventoryChanged.emit()
            self._fetch_device_info(selected)
        else:
            self.deviceChanged.emit()

    def _on_devices_failed(self, payload: tuple[str, bool]) -> None:
        message, quiet = payload
        self._scanning = False
        had_device = self.device is not None
        self.devices = []
        self.device = None
        self.inventory = None
        self.states = {}
        self._inventory_serial = ""
        if had_device:
            self.deviceChanged.emit()
            self.inventoryChanged.emit()
        self.devicesChanged.emit()
        if not quiet:
            self.notice.emit("warning", message)

    def select_device(self, serial: str) -> None:
        if self.device and self.device.serial == serial:
            return
        self.device = None
        self.inventory = None
        self.states = {}
        self._inventory_serial = ""
        self.inventoryChanged.emit()
        self._fetch_device_info(serial)

    def _fetch_device_info(self, serial: str) -> None:
        if self._fetching_info:
            return
        self._fetching_info = True

        def work() -> None:
            try:
                info = self.adb.device_info(serial)
            except AdbError as error:
                self._deviceInfoFailed.emit(str(error))
                return
            finally:
                self._fetching_info = False
            self._deviceInfoLoaded.emit(info)

        threading.Thread(target=work, daemon=True, name="adb-info").start()

    def _on_device_info_loaded(self, info: DeviceInfo) -> None:
        self.device = info
        self.deviceChanged.emit()
        if self._inventory_serial != info.serial:
            self.refresh_inventory()

    def _on_device_info_failed(self, message: str) -> None:
        self.notice.emit("warning", message)
        if self.device is None:
            self.deviceChanged.emit()

    # ------------------------------------------------------------ inventory
    def refresh_inventory(self) -> None:
        if self._loading_inventory:
            return
        device = self.ready_device
        if device is None:
            return
        serial = device.serial
        self._loading_inventory = True

        def work() -> None:
            try:
                inventory = self.adb.inventory(serial)
            except AdbError as error:
                self._inventoryFailed.emit(str(error))
                return
            finally:
                self._loading_inventory = False
            self._inventoryLoaded.emit((serial, inventory))

        threading.Thread(target=work, daemon=True, name="adb-inventory").start()

    def _on_inventory_loaded(self, payload: tuple[str, PackageInventory]) -> None:
        serial, inventory = payload
        if not self.device or self.device.serial != serial:
            return
        self._inventory_serial = serial
        self.inventory = inventory
        self._recompute_states()
        self.inventoryChanged.emit()

    def _on_inventory_failed(self, message: str) -> None:
        self.notice.emit("warning", f"Could not read the package list: {message}")

    def _recompute_states(self) -> None:
        if not self.profile or self.inventory is None:
            self.states = {}
            return
        self.states = {
            package.package: self.inventory.state(package.package)
            for package in self.profile.packages
        }

    def state_for(self, package: str) -> State:
        if self.inventory is None:
            return State.UNKNOWN
        return self.states.get(package, State.UNKNOWN)

    # -------------------------------------------------------------- profiles
    @property
    def profiles_list(self) -> list[Profile]:
        return self.profiles.profiles

    @property
    def profile_errors(self) -> list[tuple[Path, str]]:
        return self.profiles.errors

    def reload_profiles(self) -> None:
        self.profiles.reload()
        current = self.profiles.get(self.profile.id) if self.profile else None
        if self.profile and current is None:
            self.profile = None
            self.selection = Selection("")
        elif current is not None:
            self.profile = current
        self.profilesChanged.emit()
        if self.profile is None and self.profiles.profiles:
            self.set_profile(self.profiles.profiles[0].id)
        elif self.profile:
            self._recompute_states()
            self.profileChanged.emit()
            self.selectionChanged.emit()

    def set_profile(self, profile_id: str) -> None:
        profile = self.profiles.get(profile_id)
        if profile is None or (self.profile and self.profile.id == profile.id):
            return
        self._flush_selection()
        self.profile = profile
        self.selection = self.selection_store.load(profile)
        self.settings.setValue("profile", profile.id)
        self._recompute_states()
        self.profileChanged.emit()
        self.selectionChanged.emit()
        if self.inventory is not None:
            self.inventoryChanged.emit()

    def import_profile(self, path: str | Path) -> Profile:
        profile = self.profiles.import_file(Path(path))
        self.profilesChanged.emit()
        self.notice.emit("info", f"Imported profile \u201c{profile.name}\u201d")
        return profile

    def export_profile(self, profile: Profile, destination: str | Path) -> Path:
        return self.profiles.export_file(profile, Path(destination))

    def duplicate_profile(self, profile: Profile) -> Profile:
        copy = self.profiles.duplicate(profile)
        self.profilesChanged.emit()
        return copy

    def delete_profile(self, profile: Profile) -> None:
        was_active = bool(self.profile and self.profile.id == profile.id)
        self.profiles.delete(profile)
        self.selection_store.delete(profile.id)
        if was_active:
            self.profile = None
            self.selection = Selection("")
            if self.profiles.profiles:
                self.set_profile(self.profiles.profiles[0].id)
            else:
                self.profileChanged.emit()
                self.selectionChanged.emit()
        self.profilesChanged.emit()

    def create_blank_profile(self, name: str) -> Profile:
        profile = self.profiles.create_blank(name)
        self.profilesChanged.emit()
        self.notice.emit("info", f"Created profile \u201c{profile.name}\u201d")
        return profile

    def create_profile_from_device(
        self,
        name: str,
        *,
        include_system: bool,
        level: Level,
        category_name: str = "Device snapshot",
    ) -> None:
        device = self.ready_device
        if device is None:
            self.notice.emit("warning", "Connect a device first.")
            return
        if self._busy_depth:
            return
        self._begin_busy("Reading packages from the device\u2026")
        serial = device.serial

        def work() -> None:
            try:
                inventory = self.adb.inventory(serial)
            except AdbError as error:
                self._profileFailed.emit(str(error))
                self._busyRelease.emit()
                return

            selected = [
                package for package in sorted(inventory.known)
                if include_system
                or str(inventory.paths.get(package, "")).startswith("/data/app/")
            ]
            category_id = slugify(category_name)
            packages = []
            state_counts: Counter[State] = Counter()
            for package_name in selected:
                path = str(inventory.paths.get(package_name, ""))
                system = not path.startswith("/data/app/")
                snapshot_state = inventory.state(package_name)
                state_counts[snapshot_state] += 1
                if snapshot_state is State.DISABLED:
                    action = Action.DISABLE
                    note = "Snapshot: disabled on the device."
                elif snapshot_state is State.UNINSTALLED:
                    action = Action.UNINSTALL
                    note = "Snapshot: already removed for user 0."
                else:
                    action = Action.DISABLE if system else Action.UNINSTALL
                    note = ""
                packages.append(Package(
                    package=package_name,
                    title=package_name.rsplit(".", 1)[-1].replace("_", " ").title(),
                    description=f"Imported from {device.name}.",
                    level=level,
                    action=action,
                    category=category_id,
                    note=note,
                    state=snapshot_state,
                ))

            state_summary = ", ".join(
                f"{state_counts[state]} {label}"
                for state, label in (
                    (State.ACTIVE, "active"),
                    (State.DISABLED, "disabled"),
                    (State.UNINSTALLED, "removed for user 0"),
                )
                if state_counts[state]
            )
            profile = Profile(
                id=slugify(name),
                name=name,
                description=(
                    f"Snapshot of {device.name} ({device.serial}), created "
                    f"{now_iso()[:10]}. {len(packages)} packages"
                    + (f": {state_summary}." if state_summary else ".")
                ),
                categories=[Category(
                    category_id, category_name,
                    "Packages imported from a connected device, with the state "
                    "they had at capture time.",
                )],
                packages=packages,
            )
            self._snapshotBuilt.emit(profile)

        threading.Thread(target=work, daemon=True, name="profile-snapshot").start()

    def _on_snapshot_built(self, profile: Profile) -> None:
        """Persist a snapshot on the GUI thread, then make it active."""
        try:
            profile.id = self.profiles.unique_id(profile.name)
            saved = self.profiles.save(profile)
        except (ProfileError, OSError) as error:
            self._end_busy()
            self.notice.emit("error", f"Could not save the profile: {error}")
            return
        self._on_profile_created(saved)

    def _on_profile_created(self, profile: Profile) -> None:
        self._end_busy()
        self.profilesChanged.emit()
        self.notice.emit("info", f"Created profile \u201c{profile.name}\u201d")
        self.set_profile(profile.id)

    # ------------------------------------------------------------ suggestion
    def profile_matches(self) -> list[tuple[Profile, MatchResult]]:
        device = self.ready_device
        if device is None:
            return []
        props = device.match_props()
        scored = [
            (profile, profile.match_device(props))
            for profile in self.profiles.profiles
            if not profile.match.empty
        ]
        return sorted(scored, key=lambda item: item[1].score, reverse=True)

    def suggested_profile(self) -> tuple[Profile, MatchResult] | None:
        matches = self.profile_matches()
        if not matches:
            return None
        profile, result = matches[0]
        if not result.is_match:
            return None
        if self.profile and profile.id == self.profile.id:
            return None
        return profile, result

    # ------------------------------------------------------------- selection
    def is_selected(self, package: str) -> bool:
        return self.selection.is_selected(package)

    def action_for(self, package: Package) -> Action:
        return self.selection.action_for(package)

    def set_selected(self, package: str, value: bool) -> None:
        if self.selection.set_selected(package, value):
            self.selectionChanged.emit()
            self._save_timer.start()

    def toggle(self, package: str) -> None:
        if self.selection.toggle(package):
            self.selectionChanged.emit()
            self._save_timer.start()

    def set_action(self, package: Package, action: Action) -> None:
        if self.selection.set_action(package, action):
            self.selectionChanged.emit()
            self._save_timer.start()

    def set_many(self, packages: Iterable[Package], value: bool) -> None:
        if self.selection.set_many(list(packages), value):
            self.selectionChanged.emit()
            self._save_timer.start()

    def select_by_level(self, level: Level, value: bool = True) -> None:
        if not self.profile:
            return
        self.set_many(
            [package for package in self.profile.packages if package.level is level],
            value,
        )

    def clear_selection(self) -> None:
        self.selection.clear()
        self.selectionChanged.emit()
        self._save_timer.start()

    def selected_items(self) -> list[WorkItem]:
        if not self.profile:
            return []
        items = []
        for package in self.profile.packages:
            if package.package in self.selection.selected:
                items.append(WorkItem(package, self.selection.action_for(package)))
        return items

    def selection_counts(self) -> dict[Level, int]:
        counts = {level: 0 for level in Level}
        if not self.profile:
            return counts
        for package in self.profile.packages:
            if package.package in self.selection.selected:
                counts[package.level] += 1
        return counts

    def _flush_selection(self) -> None:
        if not self.profile:
            return
        try:
            self.selection_store.save(self.profile, self.selection)
        except OSError:
            pass

    # ------------------------------------------------------------------ runs
    @property
    def running(self) -> bool:
        return self._running

    def apply_selected(self, dry_run: bool = False) -> None:
        self._start_run(self.selected_items(), revert=False, dry_run=dry_run)

    def revert_selected(self, dry_run: bool = False) -> None:
        self._start_run(self.selected_items(), revert=True, dry_run=dry_run)

    def revert_last_run(self) -> None:
        run = self.journal.last_run("apply", include_dry=False)
        if run is None:
            self.notice.emit("info", "There is no previous debloat run to undo.")
            return
        if not self.profile:
            return
        items = []
        for entry in run.entries:
            if not entry.ok:
                continue
            package = self.profile.get(entry.package)
            if package is None:
                package = Package(package=entry.package, title=entry.package,
                                  category="")
            items.append(WorkItem(package, package.action))
        if not items:
            self.notice.emit("info", "The last run has no successful changes to undo.")
            return
        self._start_run(items, revert=True, dry_run=False)

    def _start_run(self, items: list[WorkItem], *, revert: bool, dry_run: bool) -> None:
        device = self.ready_device
        if device is None:
            self.notice.emit("warning", "No authorised device is connected.")
            return
        if not items:
            self.notice.emit("info", "Nothing is selected.")
            return
        if not self.profile:
            return
        if self._running:
            self.notice.emit("info", "A run is already in progress.")
            return

        self._running = True
        self._stop_event.clear()
        states = dict(self.states)
        profile = self.profile
        self._begin_busy(
            ("Restoring " if revert else "Debloating ") + f"{len(items)} packages\u2026"
        )

        def work() -> None:
            result = self.engine.run(
                profile=profile,
                device=device,
                items=items,
                revert=revert,
                dry_run=dry_run,
                states=states,
                stop_event=self._stop_event,
                on_progress=lambda done, total, package, ok: self.progress.emit(
                    done, total, package.package, ok
                ),
                on_log=self.logLine.emit,
            )
            self._runDone.emit(result)

        threading.Thread(target=work, daemon=True, name="debloat-run").start()

    def stop_run(self) -> None:
        if self._running:
            self._stop_event.set()
            self.notice.emit("info", "Stopping after the current package\u2026")

    def _on_run_done(self, result: RunResult) -> None:
        self._running = False
        self._end_busy()
        self.journalChanged.emit()
        self.runFinished.emit(result)
        verb = "Restored" if result.kind == "revert" else "Debloated"
        if result.stopped:
            self.notice.emit(
                "warning",
                f"Stopped after {result.ok} package(s). The remaining commands "
                "were not sent to the phone.",
            )
        elif result.dry_run:
            self.notice.emit(
                "info",
                f"Dry run finished: {result.ok} command(s) simulated, nothing "
                "was sent to the phone.",
            )
        elif result.failed:
            self.notice.emit(
                "warning",
                f"{verb} {result.ok} of {result.total} packages; "
                f"{result.failed} failed. See Activity for details.",
            )
        else:
            self.notice.emit(
                "info", f"{verb} {result.ok} package(s). Reboot to apply changes."
            )
        # Refresh the inventory so the table shows the new states.
        QTimer.singleShot(400, self.refresh_inventory)

    def reboot(self) -> None:
        device = self.ready_device
        if device is None:
            self.notice.emit("warning", "No authorised device is connected.")
            return

        def work() -> None:
            try:
                self.adb.reboot(device.serial)
            except AdbError as error:
                self._errorMessage.emit(str(error))
                return
            self.notice.emit("info", f"Rebooting {device.name}\u2026")

        threading.Thread(target=work, daemon=True, name="adb-reboot").start()

    # ---------------------------------------------------------------- adb
    @property
    def adb_path(self) -> str:
        return self.adb.path or ""

    def set_adb(self, path: str | Path | None) -> None:
        self.adb.refresh_path(str(path) if path else None)
        if self.adb.path:
            self.settings.setValue("adb_path", self.adb.path)
            self.adbChanged.emit()
            self.refresh_devices()
        else:
            self.settings.remove("adb_path")
            self.adbChanged.emit()
            self.notice.emit("error", "That path does not contain adb.exe.")

    def auto_detect_adb(self) -> None:
        found = find_adb()
        if found:
            self.set_adb(found)
            self.notice.emit("info", f"Found adb: {found}")
        else:
            self.notice.emit(
                "warning",
                "adb was not found. Install Android Platform Tools or browse "
                "for adb.exe manually.",
            )

    def install_adb(self) -> None:
        if self._busy_depth:
            return
        self._begin_busy("Installing Android Platform Tools\u2026")

        def work() -> None:
            ok = install_platform_tools(on_output=self.logLine.emit)
            found = find_adb() if ok else None
            self._adbInstallFinished.emit(found)

        threading.Thread(target=work, daemon=True, name="winget-adb").start()

    def _on_adb_install_finished(self, found: str | None) -> None:
        self._end_busy()
        if found:
            self.adb.refresh_path(found)
            self.settings.setValue("adb_path", found)
            self.adbChanged.emit()
            self.refresh_devices()
            self.notice.emit("info", "Android Platform Tools installed.")
        else:
            self.notice.emit(
                "error",
                "winget could not install Platform Tools. Install them "
                "manually and pick adb.exe in Settings.",
            )

    def install_adb_available(self) -> bool:
        return shutil.which("winget") is not None

    # ---------------------------------------------------------------- misc
    def busy_text(self) -> str:
        return self._busy_text

    def _begin_busy(self, text: str) -> None:
        first = self._busy_depth == 0
        self._busy_depth += 1
        self._busy_text = text
        if first:
            self.busyChanged.emit(True)

    def _end_busy(self) -> None:
        self._busy_depth = max(0, self._busy_depth - 1)
        if self._busy_depth == 0:
            self._busy_text = ""
            self.busyChanged.emit(False)

    def save_geometry(self, geometry) -> None:
        self.settings.setValue("geometry", geometry)

    def restore_geometry(self):
        return self.settings.value("geometry")

    def set_setting(self, key: str, value) -> None:
        self.settings.setValue(key, value)

    def setting(self, key: str, default=None):
        return self.settings.value(key, default)

    def flag(self, key: str, default: bool = False) -> bool:
        value = self.settings.value(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def _auto_refresh_seconds(self) -> int:
        try:
            return int(self.settings.value("auto_refresh", 6) or 0)
        except (TypeError, ValueError):
            return 6

    def set_auto_refresh(self, seconds: int) -> None:
        if seconds <= 0:
            self._auto_timer.stop()
        else:
            self._auto_timer.setInterval(max(1, seconds) * 1000)
            self._auto_timer.start()

    def shutdown(self) -> None:
        self._flush_selection()
        self._auto_timer.stop()

    def recent_runs(self, limit: int = 5) -> list[RunSummary]:
        return self.journal.runs(limit=limit)
