"""Thin, well-behaved wrapper around the Android Debug Bridge.

Only the small subset of ADB the debloater needs is implemented.  Every call
is explicit about its device serial so a laptop with several connected phones
never applies a command to the wrong one.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Sequence

from ..paths import BASE_DIR
from .models import Action, Device, DeviceInfo, State

CREATE_NO_WINDOW = 0x08000000
_GETPROP_RE = re.compile(r"^\[(?P<key>[^\]]+)\]:\s*\[(?P<value>.*)\]\s*$")
_FAILURE_HINTS = re.compile(
    r"(?i)\b(error|exception|failure|failed|unknown package|not installed|"
    r"securityexception|illegalargumentexception)\b"
)
_OS_PROP_KEYS = (
    "ro.build.version.oplusrom",
    "ro.oplus.os.version",
    "ro.oplus.version",
    "ro.build.version.opporom",
    "ro.build.version.realme",
    "ro.miui.ui.version.name",
    "ro.build.version.emui",
    "ro.build.version.oneui",
    "ro.system.build.version.incremental",
)
_MODEL_PROP_KEYS = (
    "ro.vendor.oplus.market.name",
    "ro.product.marketname",
    "ro.product.vendor.model",
    "ro.product.model",
    "ro.product.name",
)


class AdbError(RuntimeError):
    """ADB is missing, timed out or returned an unexpected error."""


def _hidden_process_kwargs() -> dict:
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {"startupinfo": startupinfo, "creationflags": CREATE_NO_WINDOW}


@dataclass(frozen=True)
class OperationResult:
    """Outcome of a single ``pm`` command."""

    ok: bool
    output: str
    command: str
    action: str = ""
    duration_ms: int = 0


@dataclass(frozen=True)
class PackageInventory:
    """Package sets read from a device in one go."""

    installed: frozenset[str] = frozenset()
    disabled: frozenset[str] = frozenset()
    known: frozenset[str] = frozenset()
    paths: Mapping[str, str] = field(default_factory=dict)

    def state(self, package: str) -> State:
        if package in self.disabled:
            return State.DISABLED
        if package in self.installed:
            return State.ACTIVE
        if package in self.known:
            return State.UNINSTALLED
        return State.ABSENT

    def states_for(self, packages: Sequence[str]) -> dict[str, State]:
        return {package: self.state(package) for package in packages}

    @property
    def total(self) -> int:
        return len(self.installed)


def candidate_adb_paths(preferred: str | Path | None = None) -> list[Path]:
    """Find adb in the usual Windows locations, most specific first."""
    candidates: list[Path] = []
    if preferred:
        candidates.append(Path(preferred))

    candidates.extend([
        BASE_DIR / "platform-tools" / "adb.exe",
        BASE_DIR / "adb.exe",
    ])

    on_path = shutil.which("adb")
    if on_path:
        candidates.append(Path(on_path))

    for env_name in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        value = os.environ.get(env_name)
        if value:
            candidates.append(Path(value) / "platform-tools" / "adb.exe")

    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "Android" / "Sdk" / "platform-tools" / "adb.exe")
        winget_root = Path(local) / "Microsoft" / "WinGet" / "Packages"
        if winget_root.exists():
            candidates.extend(sorted(
                winget_root.glob("Google.PlatformTools*/platform-tools/adb.exe")
            ))

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate).lower()
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def find_adb(preferred: str | Path | None = None) -> str | None:
    for candidate in candidate_adb_paths(preferred):
        if candidate.is_file():
            return str(candidate)
    return None


def winget_available() -> bool:
    return shutil.which("winget") is not None


def install_platform_tools(
    on_output: Callable[[str], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> bool:
    """Install Google Platform Tools through winget; returns success."""
    winget = shutil.which("winget")
    if not winget:
        return False
    command = [
        winget, "install", "-e", "--id", "Google.PlatformTools",
        "--accept-source-agreements", "--accept-package-agreements",
        "--disable-interactivity",
    ]
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            **_hidden_process_kwargs(),
        )
    except OSError as error:
        if on_output:
            on_output(f"Could not start winget: {error}")
        return False

    assert process.stdout is not None
    for line in process.stdout:
        if should_stop and should_stop():
            process.kill()
            return False
        text = line.rstrip()
        if text and on_output:
            on_output(text)
    return process.wait() == 0


class Adb:
    """A configured ADB client."""

    def __init__(self, path: str | Path | None = None, timeout: float = 30.0) -> None:
        self._requested_path = str(path) if path else None
        self.timeout = timeout
        self.path = find_adb(self._requested_path)

    # -- discovery ------------------------------------------------------
    @property
    def available(self) -> bool:
        return bool(self.path and Path(self.path).is_file())

    def refresh_path(self, preferred: str | Path | None = None) -> bool:
        self._requested_path = str(preferred) if preferred else self._requested_path
        self.path = find_adb(self._requested_path)
        return self.available

    def version(self) -> str:
        result = self._run(["version"], timeout=10)
        first = result.stdout.strip().splitlines()
        return first[0].strip() if first else ""

    # -- low level ------------------------------------------------------
    def _run(
        self,
        args: Sequence[str],
        *,
        serial: str | None = None,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if not self.available:
            raise AdbError(
                "adb was not found. Install Android Platform Tools or point the "
                "application at adb.exe in Settings."
            )
        command = [self.path or "adb"]
        if serial:
            command += ["-s", serial]
        command += list(args)
        try:
            return subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout or self.timeout,
                **_hidden_process_kwargs(),
            )
        except subprocess.TimeoutExpired as error:
            raise AdbError(
                f"adb timed out after {int(timeout or self.timeout)} s while "
                f"running: {' '.join(args)}"
            ) from error
        except FileNotFoundError as error:
            raise AdbError(f"adb executable not found: {self.path}") from error
        except OSError as error:
            raise AdbError(f"could not start adb: {error}") from error

    def _shell(
        self,
        serial: str,
        args: Sequence[str],
        *,
        timeout: float | None = None,
    ) -> str:
        result = self._run(["shell", *args], serial=serial, timeout=timeout)
        output = result.stdout.replace("\r\n", "\n").replace("\r", "\n")
        error = result.stderr.replace("\r\n", "\n").strip()
        if error and not output.strip():
            output = error
        return output.strip()

    # -- devices --------------------------------------------------------
    def devices(self) -> list[Device]:
        result = self._run(["devices", "-l"], timeout=15)
        devices: list[Device] = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("List of devices") or line.startswith("*"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            serial, state = parts[0], parts[1]
            properties = {}
            for token in parts[2:]:
                if ":" in token:
                    key, value = token.split(":", 1)
                    properties[key] = value
            devices.append(Device(
                serial=serial,
                state=state,
                model=properties.get("model", "").replace("_", " "),
                product=properties.get("product", ""),
                transport_id=properties.get("transport_id", ""),
            ))
        return devices

    def device_info(self, serial: str) -> DeviceInfo:
        raw = self._shell(serial, ["getprop"], timeout=45)
        props: dict[str, str] = {}
        for line in raw.splitlines():
            match = _GETPROP_RE.match(line.strip())
            if match:
                props[match.group("key")] = match.group("value").strip()

        model = next(
            (props[key] for key in _MODEL_PROP_KEYS if props.get(key)), serial
        )
        os_version = next(
            (props[key] for key in _OS_PROP_KEYS if props.get(key)), ""
        )
        return DeviceInfo(
            serial=serial,
            state="device",
            model=model,
            brand=props.get("ro.product.brand", ""),
            android=props.get("ro.build.version.release", ""),
            sdk=props.get("ro.build.version.sdk", ""),
            build=props.get("ro.build.display.id", ""),
            os_version=os_version,
        )

    # -- packages -------------------------------------------------------
    def _pm_package_map(self, serial: str, flags: Sequence[str]) -> dict[str, str]:
        output = self._shell(
            serial,
            ["pm", "list", "packages", "--user", "0", "-f", *flags],
            timeout=60,
        )
        packages: dict[str, str] = {}
        for line in output.splitlines():
            line = line.strip()
            if not line.startswith("package:"):
                continue
            body = line[len("package:"):]
            if "=" in body:
                path, package = body.rsplit("=", 1)
            else:
                path, package = "", body
            package = package.strip()
            if package:
                packages[package] = path.strip()
        return packages

    def inventory(self, serial: str) -> PackageInventory:
        known = self._pm_package_map(serial, ("-u",))
        installed = self._pm_package_map(serial, ())
        disabled = self._pm_package_map(serial, ("-d",))

        paths: dict[str, str] = {}
        for mapping in (known, installed):
            for package, path in mapping.items():
                if path and package not in paths:
                    paths[package] = path
        return PackageInventory(
            installed=frozenset(installed),
            disabled=frozenset(disabled),
            known=frozenset(known),
            paths=paths,
        )

    # -- mutations ------------------------------------------------------
    def apply(self, serial: str, package: str, action: Action) -> OperationResult:
        if action is Action.UNINSTALL:
            args = ["pm", "uninstall", "--user", "0", package]
            action_name = "uninstall"
        else:
            args = ["pm", "disable-user", "--user", "0", package]
            action_name = "disable"
        return self._mutate(serial, args, action_name, package)

    def revert(self, serial: str, package: str, state: State) -> OperationResult:
        if state is State.UNINSTALLED:
            args = ["cmd", "package", "install-existing", "--user", "0", package]
            action_name = "install-existing"
        else:
            args = ["pm", "enable", "--user", "0", package]
            action_name = "enable"
        return self._mutate(serial, args, action_name, package)

    def _mutate(
        self, serial: str, args: Sequence[str], action_name: str, package: str
    ) -> OperationResult:
        started = time.perf_counter()
        output = self._shell(serial, args, timeout=90)
        duration = int((time.perf_counter() - started) * 1000)
        command = "adb -s " + serial + " shell " + " ".join(args)
        return OperationResult(
            ok=self._success(action_name, output),
            output=output or "(no output)",
            command=command,
            action=action_name,
            duration_ms=duration,
        )

    @staticmethod
    def _success(action: str, output: str) -> bool:
        text = output.strip()
        lowered = text.lower()
        if not text:
            return False
        if _FAILURE_HINTS.search(lowered) and "success" not in lowered:
            return False
        if action == "uninstall":
            return "success" in lowered
        if action in ("disable", "enable"):
            if "new state:" in lowered:
                wanted = "disabled" if action == "disable" else "enabled"
                state = lowered.split("new state:", 1)[1].strip()
                return state.startswith(wanted)
            return "success" in lowered
        if action == "install-existing":
            return "installed" in lowered
        return "success" in lowered

    def reboot(self, serial: str) -> None:
        self._run(["reboot"], serial=serial, timeout=15)
