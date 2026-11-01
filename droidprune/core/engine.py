"""Execution engine: turns a selection into ADB commands and records the run."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Sequence

from .. import APP_NAME, APP_VERSION
from .adb import Adb, AdbError, OperationResult
from .journal import Journal, JournalEntry
from .models import Action, DeviceInfo, Package, Profile, State

ProgressCallback = Callable[[int, int, Package, bool], None]
LogCallback = Callable[[str], None]


@dataclass(frozen=True)
class WorkItem:
    package: Package
    action: Action


@dataclass
class RunResult:
    run_id: str
    kind: str
    dry_run: bool
    device: str
    profile_name: str
    total: int = 0
    ok: int = 0
    failed: int = 0
    stopped: bool = False
    entries: list[JournalEntry] = field(default_factory=list)
    log_path: Path | None = None
    duration_s: float = 0.0
    fatal_error: str = ""

    @property
    def success(self) -> bool:
        return self.failed == 0 and not self.stopped and not self.fatal_error


def _action_name(action: Action) -> str:
    return action.value


def _dry_command(serial: str, package: str, action_name: str) -> str:
    if action_name == "uninstall":
        args = ["pm", "uninstall", "--user", "0", package]
    elif action_name == "disable":
        args = ["pm", "disable-user", "--user", "0", package]
    elif action_name == "enable":
        args = ["pm", "enable", "--user", "0", package]
    else:
        args = ["cmd", "package", "install-existing", "--user", "0", package]
    return f"adb -s {serial} shell " + " ".join(args)


class Engine:
    """Runs apply/revert batches sequentially, reporting progress as it goes."""

    def __init__(self, adb: Adb, journal: Journal, log_dir: Path) -> None:
        self.adb = adb
        self.journal = journal
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def run(
        self,
        *,
        profile: Profile,
        device: DeviceInfo,
        items: Sequence[WorkItem],
        revert: bool,
        dry_run: bool,
        states: dict[str, State] | None = None,
        stop_event: threading.Event | None = None,
        on_progress: ProgressCallback | None = None,
        on_log: LogCallback | None = None,
    ) -> RunResult:
        states = states or {}
        run_id = uuid.uuid4().hex[:12]
        kind = "revert" if revert else "apply"
        started = datetime.now()
        start_clock = time.perf_counter()
        result = RunResult(
            run_id=run_id,
            kind=kind,
            dry_run=dry_run,
            device=f"{device.name} ({device.serial})",
            profile_name=profile.name,
            total=len(items),
        )

        log_path = self._log_path(kind, started)
        lines: list[str] = [
            f"{APP_NAME} {APP_VERSION}",
            f"Started  : {started.strftime('%Y-%m-%d %H:%M:%S')}",
            f"Profile  : {profile.name}",
            f"Device   : {device.name}  [{device.serial}]",
            f"Mode     : {'revert' if revert else 'debloat'}"
            f"{'  (dry run)' if dry_run else ''}",
            f"Packages : {len(items)}",
            "-" * 78,
        ]

        def log(message: str) -> None:
            lines.append(message)
            if on_log:
                try:
                    on_log(message)
                except Exception:
                    pass

        try:
            for index, item in enumerate(items, start=1):
                if stop_event is not None and stop_event.is_set():
                    result.stopped = True
                    log("Stopped by the user.")
                    break

                package = item.package
                if revert:
                    state = states.get(package.package, State.UNKNOWN)
                    action_name = (
                        "install-existing" if state is State.UNINSTALLED else "enable"
                    )
                else:
                    action_name = _action_name(item.action)

                command = _dry_command(device.serial, package.package, action_name)
                if dry_run:
                    outcome = OperationResult(
                        ok=True,
                        output="Dry run - command not executed.",
                        command=command,
                        action=action_name,
                        duration_ms=0,
                    )
                else:
                    try:
                        if revert:
                            outcome = self.adb.revert(
                                device.serial, package.package,
                                states.get(package.package, State.UNKNOWN),
                            )
                        else:
                            outcome = self.adb.apply(
                                device.serial, package.package, item.action
                            )
                    except AdbError as error:
                        outcome = OperationResult(
                            ok=False, output=str(error), command=command,
                            action=action_name, duration_ms=0,
                        )
                        result.fatal_error = str(error)

                entry = JournalEntry(
                    run_id=run_id,
                    timestamp=datetime.now().replace(microsecond=0).isoformat(),
                    profile_id=profile.id,
                    profile_name=profile.name,
                    device=result.device,
                    kind=kind,
                    package=package.package,
                    action=outcome.action or action_name,
                    ok=outcome.ok,
                    output=outcome.output[:1200],
                    dry_run=dry_run,
                    duration_ms=outcome.duration_ms,
                )
                result.entries.append(entry)
                try:
                    self.journal.append([entry])
                except OSError:
                    pass
                if outcome.ok:
                    result.ok += 1
                    log(f"OK   | {action_name:<16} | {package.package}")
                else:
                    result.failed += 1
                    first_line = (outcome.output or "").strip().splitlines()
                    detail = first_line[0][:200] if first_line else "no output"
                    log(f"FAIL | {action_name:<16} | {package.package}  -> {detail}")
                    log(f"       {outcome.command}")

                if on_progress:
                    try:
                        on_progress(index, len(items), package, outcome.ok)
                    except Exception:
                        pass

                if result.fatal_error:
                    log(f"ADB error, aborting the run: {result.fatal_error}")
                    break
        finally:
            duration = time.perf_counter() - start_clock
            result.duration_s = duration
            lines.extend([
                "-" * 78,
                f"Finished : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                f"  ({duration:.1f} s)",
                f"Result   : {result.ok} ok, {result.failed} failed"
                f"{', stopped' if result.stopped else ''}",
            ])
            try:
                log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                result.log_path = log_path
            except OSError:
                result.log_path = None

        return result

    def _log_path(self, kind: str, started: datetime) -> Path:
        stamp = started.strftime("%Y%m%d_%H%M%S")
        candidate = self.log_dir / f"debloat_{stamp}_{kind}.txt"
        counter = 2
        while candidate.exists():
            candidate = self.log_dir / f"debloat_{stamp}_{kind}_{counter}.txt"
            counter += 1
        return candidate
