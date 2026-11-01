"""Append-only run history (JSON Lines).

Every package command is recorded together with its outcome, which powers the
Activity page and the "undo the last run" action even after a restart.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .models import now_iso


@dataclass(frozen=True)
class JournalEntry:
    run_id: str
    timestamp: str
    profile_id: str
    profile_name: str
    device: str
    kind: str          # "apply" or "revert"
    package: str
    action: str        # disable / uninstall / enable / install-existing
    ok: bool
    output: str = ""
    dry_run: bool = False
    duration_ms: int = 0

    def to_dict(self) -> dict:
        return {
            "run": self.run_id,
            "ts": self.timestamp,
            "profile": self.profile_id,
            "profileName": self.profile_name,
            "device": self.device,
            "kind": self.kind,
            "package": self.package,
            "action": self.action,
            "ok": self.ok,
            "output": self.output,
            "dryRun": self.dry_run,
            "durationMs": self.duration_ms,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "JournalEntry | None":
        try:
            return cls(
                run_id=str(data["run"]),
                timestamp=str(data["ts"]),
                profile_id=str(data.get("profile", "")),
                profile_name=str(data.get("profileName", "")),
                device=str(data.get("device", "")),
                kind=str(data.get("kind", "apply")),
                package=str(data["package"]),
                action=str(data.get("action", "")),
                ok=bool(data.get("ok", False)),
                output=str(data.get("output", "")),
                dry_run=bool(data.get("dryRun", False)),
                duration_ms=int(data.get("durationMs", 0) or 0),
            )
        except (KeyError, TypeError, ValueError):
            return None

    @property
    def when(self) -> datetime:
        try:
            return datetime.fromisoformat(self.timestamp)
        except ValueError:
            return datetime.min


@dataclass
class RunSummary:
    run_id: str
    entries: list[JournalEntry] = field(default_factory=list)

    @property
    def started(self) -> datetime:
        return min((entry.when for entry in self.entries), default=datetime.min)

    @property
    def finished(self) -> datetime:
        return max((entry.when for entry in self.entries), default=datetime.min)

    @property
    def kind(self) -> str:
        return self.entries[0].kind if self.entries else "apply"

    @property
    def profile_name(self) -> str:
        return self.entries[0].profile_name if self.entries else ""

    @property
    def device(self) -> str:
        return self.entries[0].device if self.entries else ""

    @property
    def dry_run(self) -> bool:
        return any(entry.dry_run for entry in self.entries)

    @property
    def total(self) -> int:
        return len(self.entries)

    @property
    def ok_count(self) -> int:
        return sum(1 for entry in self.entries if entry.ok)

    @property
    def fail_count(self) -> int:
        return sum(1 for entry in self.entries if not entry.ok)

    @property
    def timestamp_label(self) -> str:
        return self.started.strftime("%Y-%m-%d  %H:%M")

    @property
    def kind_label(self) -> str:
        return "Debloat" if self.kind == "apply" else "Restore"


class Journal:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def append(self, entries: Iterable[JournalEntry]) -> None:
        entries = list(entries)
        if not entries:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            for entry in entries:
                handle.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
                handle.flush()

    def entries(self, limit: int | None = None) -> list[JournalEntry]:
        if not self.path.exists():
            return []
        result: list[JournalEntry] = []
        try:
            with self.path.open("r", encoding="utf-8-sig") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    entry = JournalEntry.from_dict(data)
                    if entry:
                        result.append(entry)
        except OSError:
            return []
        if limit:
            result = result[-limit:]
        return result

    def runs(self, limit: int = 50) -> list[RunSummary]:
        grouped: dict[str, RunSummary] = {}
        order: list[str] = []
        for entry in self.entries():
            if entry.run_id not in grouped:
                grouped[entry.run_id] = RunSummary(entry.run_id)
                order.append(entry.run_id)
            grouped[entry.run_id].entries.append(entry)
        # The file is append-only, so reversed insertion order is the newest
        # run first even when several runs share the same whole second.
        ordered = [grouped[run_id] for run_id in reversed(order)]
        if limit:
            ordered = ordered[:limit]
        return ordered

    def last_run(self, kind: str | None = None, *, include_dry: bool = False) -> RunSummary | None:
        for run in self.runs(limit=0):
            if run.dry_run and not include_dry:
                continue
            if kind and run.kind != kind:
                continue
            return run
        return None

    def clear(self) -> None:
        if self.path.exists():
            os.replace(self.path, self.path.with_suffix(".jsonl.bak"))

    def export_text(self, run: RunSummary) -> str:
        lines = [
            f"DroidPrune - {run.kind_label} log",
            f"Run     : {run.run_id}",
            f"Started : {run.started.strftime('%Y-%m-%d %H:%M:%S')}",
            f"Profile : {run.profile_name}",
            f"Device  : {run.device}",
            f"Dry run : {'yes' if run.dry_run else 'no'}",
            f"Result  : {run.ok_count} ok, {run.fail_count} failed",
            "-" * 78,
        ]
        for entry in run.entries:
            status = "OK  " if entry.ok else "FAIL"
            lines.append(f"{status} | {entry.action:<16} | {entry.package}")
            if not entry.ok or entry.dry_run:
                output = entry.output.replace("\n", " ").strip()
                if output:
                    lines.append(f"       -> {output[:300]}")
        return "\n".join(lines) + "\n"
