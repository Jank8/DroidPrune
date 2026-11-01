"""Per-profile package selection (checkboxes and action overrides)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .models import Action, Package, Profile, now_iso

SCHEMA_VERSION = 1


@dataclass
class Selection:
    """Mutable selection state for one profile."""

    profile_id: str
    selected: set[str] = field(default_factory=set)
    actions: dict[str, Action] = field(default_factory=dict)

    def is_selected(self, package: str) -> bool:
        return package in self.selected

    def set_selected(self, package: str, value: bool) -> bool:
        changed = (package in self.selected) != bool(value)
        if value:
            self.selected.add(package)
        else:
            self.selected.discard(package)
        return changed

    def toggle(self, package: str) -> bool:
        return self.set_selected(package, package not in self.selected)

    def set_many(self, packages: Iterable[Package], value: bool) -> bool:
        changed = False
        for package in packages:
            changed |= self.set_selected(package.package, value)
        return changed

    def action_for(self, package: Package, fallback: Action | None = None) -> Action:
        return self.actions.get(package.package, fallback or package.action)

    def has_override(self, package: Package) -> bool:
        override = self.actions.get(package.package)
        return override is not None and override is not package.action

    def set_action(self, package: Package, action: Action) -> bool:
        """Store an override, dropping it when it equals the profile default."""
        if self.action_for(package) is action:
            return False
        if action is package.action:
            self.actions.pop(package.package, None)
        else:
            self.actions[package.package] = action
        return True

    def clear(self) -> None:
        self.selected.clear()
        self.actions.clear()

    def selected_packages(self, profile: Profile) -> list[Package]:
        return [package for package in profile.packages
                if package.package in self.selected]

    @classmethod
    def from_dict(cls, data: dict, profile_id: str) -> "Selection":
        selection = cls(profile_id=profile_id)
        for entry in data.get("packages", []) or []:
            if not isinstance(entry, dict):
                continue
            package = str(entry.get("package", "")).strip()
            if not package:
                continue
            if entry.get("selected"):
                selection.selected.add(package)
            action = entry.get("action")
            default = entry.get("defaultAction")
            if action and action != default:
                try:
                    selection.actions[package] = Action.parse(action)
                except ValueError:
                    continue
        return selection


class SelectionStore:
    """One JSON file per profile in ``data/selection``."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def path_for(self, profile_id: str) -> Path:
        return self.directory / f"{profile_id}.json"

    def load(self, profile: Profile) -> Selection:
        path = self.path_for(profile.id)
        if not path.exists():
            return Selection(profile.id)
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return Selection(profile.id)

        selection = Selection.from_dict(
            data if isinstance(data, dict) else {}, profile.id
        )
        known = {package.package for package in profile.packages}
        selection.selected &= known
        selection.actions = {
            package: action
            for package, action in selection.actions.items()
            if package in known
        }
        return selection

    def save(self, profile: Profile, selection: Selection) -> None:
        entries = []
        for package in profile.packages:
            selected = package.package in selection.selected
            action = selection.action_for(package)
            if not selected and action is package.action:
                continue
            entries.append({
                "package": package.package,
                "selected": selected,
                "action": action.value,
                "defaultAction": package.action.value,
            })

        payload = {
            "schema": SCHEMA_VERSION,
            "profile": profile.id,
            "savedAt": now_iso(),
            "packages": entries,
        }
        target = self.path_for(profile.id)
        temp = target.with_suffix(".json.tmp")
        try:
            temp.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            temp.replace(target)
        finally:
            if temp.exists():
                try:
                    temp.unlink()
                except OSError:
                    pass

    def delete(self, profile_id: str) -> None:
        path = self.path_for(profile_id)
        if path.exists():
            path.unlink()
