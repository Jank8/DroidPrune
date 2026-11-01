"""A deterministic stand-in for :class:`droidprune.core.adb.Adb`.

Used by the test-suite and by the screenshot preview: it simulates a connected
OnePlus 15 with a realistic mix of active, disabled, removed and absent
packages, and records every command it receives.
"""

from __future__ import annotations

from dataclasses import replace

from droidprune.core.adb import OperationResult, PackageInventory
from droidprune.core.models import Action, Device, DeviceInfo, Profile, State

SERIAL = "R5CT123ABCD"


class FakeAdb:
    def __init__(self, profile: Profile, *, serial: str = SERIAL) -> None:
        self.profile = profile
        self.serial = serial
        self.path = r"C:\Android\platform-tools\adb.exe"
        self.calls: list[tuple[str, str, str]] = []
        self.rebooting = False
        self._inventory = self._build_inventory(profile)

    # -- discovery ------------------------------------------------------
    @property
    def available(self) -> bool:
        return True

    def refresh_path(self, preferred=None) -> bool:
        return True

    def version(self) -> str:
        return "Android Debug Bridge version 1.0.41"

    def devices(self) -> list[Device]:
        return [Device(
            serial=self.serial,
            state="device",
            model="OnePlus 15",
            product="CPH2745",
            transport_id="1",
        )]

    def device_info(self, serial: str) -> DeviceInfo:
        return DeviceInfo(
            serial=serial,
            state="device",
            model="OnePlus 15",
            brand="OnePlus",
            android="16",
            sdk="36",
            build="BP2A.250605.015",
            os_version="OxygenOS 16.0.1",
        )

    # -- packages -------------------------------------------------------
    def inventory(self, serial: str) -> PackageInventory:
        return self._inventory

    def _build_inventory(self, profile: Profile) -> PackageInventory:
        installed: set[str] = set()
        disabled: set[str] = set()
        known: set[str] = set()
        paths: dict[str, str] = {}

        for index, package in enumerate(profile.packages):
            bucket = index % 10
            leaf = package.package.rsplit(".", 1)[-1]
            if bucket < 7:
                installed.add(package.package)
                known.add(package.package)
            elif bucket == 7:
                installed.add(package.package)
                known.add(package.package)
                disabled.add(package.package)
            elif bucket == 8:
                known.add(package.package)
            else:
                continue

            if package.category == "3rd-party":
                paths[package.package] = (
                    f"/data/app/~~hash==/{leaf}-token/base.apk"
                )
            else:
                paths[package.package] = (
                    f"/system_ext/priv-app/{leaf}/{leaf}.apk"
                )
        return PackageInventory(
            installed=frozenset(installed),
            disabled=frozenset(disabled),
            known=frozenset(known),
            paths=paths,
        )

    def state_of(self, package: str) -> State:
        return self._inventory.state(package)

    # -- mutations ------------------------------------------------------
    def apply(self, serial: str, package: str, action: Action) -> OperationResult:
        self.calls.append(("apply", package, action.value))
        installed = set(self._inventory.installed)
        disabled = set(self._inventory.disabled)
        known = set(self._inventory.known)
        if action is Action.UNINSTALL:
            installed.discard(package)
            disabled.discard(package)
            known.add(package)
            output = "Success"
        else:
            disabled.add(package)
            installed.add(package)
            known.add(package)
            output = f"Package {package} new state: disabled-user"
        self._inventory = PackageInventory(
            installed=frozenset(installed),
            disabled=frozenset(disabled),
            known=frozenset(known),
            paths=self._inventory.paths,
        )
        return OperationResult(
            ok=True,
            output=output,
            command=f"adb -s {serial} shell pm {action.value} --user 0 {package}",
            action=action.value,
            duration_ms=42,
        )

    def revert(self, serial: str, package: str, state: State) -> OperationResult:
        installed = set(self._inventory.installed)
        disabled = set(self._inventory.disabled)
        known = set(self._inventory.known)
        if state is State.UNINSTALLED:
            action = "install-existing"
            installed.add(package)
            known.add(package)
            output = f"Package {package} installed for user: 0"
        else:
            action = "enable"
            disabled.discard(package)
            installed.add(package)
            known.add(package)
            output = f"Package {package} new state: enabled"
        self.calls.append(("revert", package, action))
        self._inventory = PackageInventory(
            installed=frozenset(installed),
            disabled=frozenset(disabled),
            known=frozenset(known),
            paths=self._inventory.paths,
        )
        return OperationResult(
            ok=True,
            output=output,
            command=f"adb -s {serial} shell pm {action} --user 0 {package}",
            action=action,
            duration_ms=31,
        )

    def reboot(self, serial: str) -> None:
        self.rebooting = True
