"""Domain model: safety levels, packages, categories and device profiles.

The GUI never manipulates raw JSON; everything goes through these dataclasses,
which validate their input and keep the profile format versioned.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

PACKAGE_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$")
PROFILE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
SCHEMA_VERSION = 1


class ProfileError(ValueError):
    """A profile file is malformed, incomplete or fails validation."""


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


class Level(Enum):
    """How risky it is to get rid of a package."""

    SAFE = "safe"
    CAUTION = "caution"
    RISKY = "risky"

    @property
    def label(self) -> str:
        return {"safe": "Safe", "caution": "Caution", "risky": "Risky"}[self.value]

    @property
    def hint(self) -> str:
        return {
            "safe": "Bloat, duplicates, telemetry and engineering tools. "
                    "No functional loss expected.",
            "caution": "Removes a specific feature. Read the note before selecting.",
            "risky": "Known links to system features, updates, networking or "
                     "battery management. Only for advanced users.",
        }[self.value]

    @property
    def rank(self) -> int:
        return _LEVEL_ORDER.index(self)

    @classmethod
    def parse(cls, value: Any) -> "Level":
        if isinstance(value, Level):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError as error:
            raise ProfileError(
                f"unknown safety level {value!r} (expected safe, caution or risky)"
            ) from error


_LEVEL_ORDER = [Level.SAFE, Level.CAUTION, Level.RISKY]


class Action(Enum):
    """What debloating does to a package."""

    DISABLE = "disable"
    UNINSTALL = "uninstall"

    @property
    def label(self) -> str:
        return {"disable": "Disable", "uninstall": "Uninstall"}[self.value]

    @property
    def description(self) -> str:
        return {
            "disable": "Freeze the app for user 0. Reversible with Enable.",
            "uninstall": "Remove the app for user 0. The APK stays in the "
                         "system image and can be restored.",
        }[self.value]

    @classmethod
    def parse(cls, value: Any) -> "Action":
        if isinstance(value, Action):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError as error:
            raise ProfileError(
                f"unknown action {value!r} (expected disable or uninstall)"
            ) from error


class State(Enum):
    """Live state of a package on the connected device."""

    ACTIVE = "active"
    DISABLED = "disabled"
    UNINSTALLED = "uninstalled"
    ABSENT = "absent"
    UNKNOWN = "unknown"

    @property
    def label(self) -> str:
        return {
            "active": "Active",
            "disabled": "Disabled",
            "uninstalled": "Removed",
            "absent": "Not on device",
            "unknown": "Unknown",
        }[self.value]

    @property
    def on_device(self) -> bool:
        return self in (State.ACTIVE, State.DISABLED, State.UNINSTALLED)

    @property
    def debloated(self) -> bool:
        return self in (State.DISABLED, State.UNINSTALLED)


@dataclass(frozen=True, slots=True)
class Category:
    id: str
    name: str
    description: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            raise ProfileError("category id cannot be empty")
        if not self.name:
            raise ProfileError(f"category {self.id!r} has no name")

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "name": self.name, "description": self.description}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Category":
        if not isinstance(data, Mapping):
            raise ProfileError("category entry must be an object")
        return cls(
            id=str(data.get("id", "")).strip(),
            name=str(data.get("name", "")).strip(),
            description=str(data.get("description", "")).strip(),
        )


@dataclass(frozen=True, slots=True)
class Package:
    package: str
    title: str = ""
    description: str = ""
    level: Level = Level.CAUTION
    action: Action = Action.DISABLE
    category: str = ""
    note: str = ""
    #: State observed when the profile was captured from a device. Optional:
    #: hand-written profiles usually do not have it.
    state: State | None = None

    def __post_init__(self) -> None:
        package = str(self.package).strip()
        if not PACKAGE_NAME_RE.match(package):
            raise ProfileError(f"invalid package name {package!r}")
        object.__setattr__(self, "package", package)
        object.__setattr__(self, "level", Level.parse(self.level))
        object.__setattr__(self, "action", Action.parse(self.action))
        title = (self.title or "").strip()
        if not title:
            title = package.rsplit(".", 1)[-1].replace("_", " ").title()
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "description", (self.description or "").strip())
        object.__setattr__(self, "note", (self.note or "").strip())
        object.__setattr__(self, "state", self._parse_state(self.state))

    @staticmethod
    def _parse_state(value: Any) -> State | None:
        if value is None:
            return None
        if isinstance(value, State):
            state = value
        else:
            text = str(value).strip().lower()
            if not text:
                return None
            try:
                state = State(text)
            except ValueError as error:
                raise ProfileError(
                    f"unknown snapshot state {value!r} (expected active, "
                    "disabled or uninstalled)"
                ) from error
        if state not in (State.ACTIVE, State.DISABLED, State.UNINSTALLED):
            raise ProfileError(
                f"snapshot state {state.value!r} cannot be stored in a profile"
            )
        return state

    @property
    def search_blob(self) -> str:
        parts = [self.title, self.package, self.description, self.note]
        if self.state is not None:
            parts.append(self.state.label)
            if self.state.debloated:
                parts.append("snapshot")
        return " ".join(part for part in parts if part).lower()

    def to_dict(self) -> dict[str, str]:
        data = {
            "package": self.package,
            "title": self.title,
            "description": self.description,
            "level": self.level.value,
            "action": self.action.value,
            "category": self.category,
        }
        if self.note:
            data["note"] = self.note
        if self.state is not None:
            data["state"] = self.state.value
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Package":
        if not isinstance(data, Mapping):
            raise ProfileError("package entry must be an object")
        if not data.get("package"):
            raise ProfileError("package entry is missing the 'package' field")
        return cls(
            package=str(data["package"]),
            title=str(data.get("title", "")),
            description=str(data.get("description", "")),
            level=Level.parse(data.get("level", "caution")),
            action=Action.parse(data.get("action", "disable")),
            category=str(data.get("category", "")),
            note=str(data.get("note", "")),
            state=data.get("state"),
        )


@dataclass(frozen=True, slots=True)
class DeviceMeta:
    brand: str = ""
    model: str = ""
    os: str = ""
    android: str = ""
    build: str = ""

    @property
    def label(self) -> str:
        brand = self.brand.strip()
        model = self.model.strip()
        if model and brand and brand.lower() not in model.lower():
            return f"{brand} {model}"
        return model or brand or "Unknown device"

    def to_dict(self) -> dict[str, str]:
        return {
            "brand": self.brand,
            "model": self.model,
            "os": self.os,
            "android": self.android,
            "build": self.build,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "DeviceMeta":
        data = data or {}
        return cls(
            brand=str(data.get("brand", "")).strip(),
            model=str(data.get("model", "")).strip(),
            os=str(data.get("os", "")).strip(),
            android=str(data.get("android", "")).strip(),
            build=str(data.get("build", "")).strip(),
        )


@dataclass(frozen=True, slots=True)
class MatchResult:
    score: float
    matched: int
    total: int
    details: tuple[str, ...] = ()

    @property
    def is_match(self) -> bool:
        return self.total > 0 and self.score >= 0.6


@dataclass(frozen=True, slots=True)
class MatchRules:
    """Regex rules used to suggest a profile for the connected device."""

    brand: str = ""
    model: str = ""
    android: str = ""
    os: str = ""

    @property
    def empty(self) -> bool:
        return not any((self.brand, self.model, self.android, self.os))

    def evaluate(self, props: Mapping[str, str]) -> MatchResult:
        checks: list[tuple[str, bool]] = []
        details: list[str] = []
        for name in ("brand", "model", "android", "os"):
            pattern = getattr(self, name)
            if not pattern:
                continue
            value = props.get(name, "") or ""
            try:
                matched = bool(re.search(pattern, value, re.IGNORECASE))
            except re.error:
                matched = False
            checks.append((name, matched))
            details.append(f"{name} {'matches' if matched else 'differs'}")
        if not checks:
            return MatchResult(0.0, 0, 0, ())
        matched = sum(1 for _, ok in checks if ok)
        return MatchResult(matched / len(checks), matched, len(checks), tuple(details))

    def to_dict(self) -> dict[str, str]:
        return {
            key: value for key, value in {
                "brand": self.brand,
                "model": self.model,
                "android": self.android,
                "os": self.os,
            }.items() if value
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "MatchRules":
        data = data or {}
        return cls(
            brand=str(data.get("brand", "")),
            model=str(data.get("model", "")),
            android=str(data.get("android", "")),
            os=str(data.get("os", "")),
        )


@dataclass
class Profile:
    """A device-specific package catalogue."""

    id: str
    name: str
    description: str = ""
    device: DeviceMeta = field(default_factory=DeviceMeta)
    match: MatchRules = field(default_factory=MatchRules)
    categories: list[Category] = field(default_factory=list)
    packages: list[Package] = field(default_factory=list)
    source: str = ""
    schema: int = SCHEMA_VERSION
    path: Path | None = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        self.id = str(self.id).strip()
        self.name = str(self.name).strip()
        if not self.id:
            raise ProfileError("profile id cannot be empty")
        if not PROFILE_ID_RE.match(self.id):
            raise ProfileError(
                f"profile id {self.id!r} may only use lowercase letters, digits, "
                "dots, dashes and underscores"
            )
        if not self.name:
            raise ProfileError("profile name cannot be empty")

        self.categories = [
            item if isinstance(item, Category) else Category.from_dict(item)
            for item in self.categories
        ]
        self.packages = [
            item if isinstance(item, Package) else Package.from_dict(item)
            for item in self.packages
        ]

        seen_ids: set[str] = set()
        for category in self.categories:
            if category.id in seen_ids:
                raise ProfileError(f"duplicate category id {category.id!r}")
            seen_ids.add(category.id)

        seen_packages: set[str] = set()
        for package in self.packages:
            if package.package in seen_packages:
                raise ProfileError(f"duplicate package {package.package!r}")
            seen_packages.add(package.package)
            if package.category and package.category not in seen_ids:
                raise ProfileError(
                    f"package {package.package!r} references unknown category "
                    f"{package.category!r}"
                )

        self._by_package = {package.package: package for package in self.packages}
        self._category_by_id = {category.id: category for category in self.categories}

    # -- lookup ---------------------------------------------------------
    @property
    def package_count(self) -> int:
        return len(self.packages)

    @property
    def category_count(self) -> int:
        return len(self.categories)

    def get(self, package: str) -> Package | None:
        return self._by_package.get(package)

    def category(self, category_id: str) -> Category | None:
        return self._category_by_id.get(category_id)

    def category_name(self, category_id: str) -> str:
        category = self._category_by_id.get(category_id)
        return category.name if category else category_id or "Uncategorised"

    def in_category(self, category_id: str) -> list[Package]:
        return [p for p in self.packages if p.category == category_id]

    def counts(self) -> Counter[Level]:
        return Counter(package.level for package in self.packages)

    def category_counts(self) -> Counter[str]:
        return Counter(package.category for package in self.packages)

    def match_device(self, props: Mapping[str, str]) -> MatchResult:
        return self.match.evaluate(props)

    # -- serialisation --------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "device": self.device.to_dict(),
            "match": self.match.to_dict(),
            "source": self.source,
            "categories": [category.to_dict() for category in self.categories],
            "packages": [package.to_dict() for package in self.packages],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], path: Path | None = None) -> "Profile":
        if not isinstance(data, Mapping):
            raise ProfileError("profile root must be a JSON object")
        raw_schema = data.get("schema", SCHEMA_VERSION)
        try:
            schema = int(raw_schema)
        except (TypeError, ValueError) as error:
            raise ProfileError(f"schema must be an integer, got {raw_schema!r}") from error
        if schema < 1:
            raise ProfileError(f"invalid profile schema {schema}")
        if schema > SCHEMA_VERSION:
            raise ProfileError(
                f"profile schema {schema} is newer than supported schema "
                f"{SCHEMA_VERSION}"
            )
        device_data = data.get("device")
        if device_data is not None and not isinstance(device_data, Mapping):
            raise ProfileError("'device' must be an object")
        match_data = data.get("match")
        if match_data is not None and not isinstance(match_data, Mapping):
            raise ProfileError("'match' must be an object")
        categories = data.get("categories") or []
        packages = data.get("packages") or []
        if not isinstance(categories, list):
            raise ProfileError("'categories' must be a list")
        if not isinstance(packages, list):
            raise ProfileError("'packages' must be a list")
        return cls(
            id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            description=str(data.get("description", "")),
            device=DeviceMeta.from_dict(device_data),
            match=MatchRules.from_dict(match_data),
            categories=[Category.from_dict(item) for item in categories],
            packages=[Package.from_dict(item) for item in packages],
            source=str(data.get("source", "")),
            schema=schema,
            path=path,
        )

    @classmethod
    def load(cls, path: Path) -> "Profile":
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except FileNotFoundError as error:
            raise ProfileError(f"profile file not found: {path}") from error
        except UnicodeDecodeError as error:
            raise ProfileError(f"{path.name}: the file is not valid UTF-8") from error
        except json.JSONDecodeError as error:
            raise ProfileError(
                f"{path.name}: invalid JSON at line {error.lineno}: {error.msg}"
            ) from error
        if not isinstance(data, Mapping):
            raise ProfileError(f"{path.name}: profile root must be an object")
        try:
            return cls.from_dict(data, path=path)
        except ProfileError as error:
            raise ProfileError(f"{path.name}: {error}") from error

    def clone(self, *, id: str, name: str) -> "Profile":
        data = self.to_dict()
        data["id"] = id
        data["name"] = name
        return Profile.from_dict(data)


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """Properties of a connected phone, read from ``getprop``."""

    serial: str
    state: str = "device"
    model: str = ""
    brand: str = ""
    android: str = ""
    sdk: str = ""
    build: str = ""
    os_version: str = ""

    @property
    def ready(self) -> bool:
        return self.state == "device"

    @property
    def name(self) -> str:
        return self.model or self.serial

    @property
    def subtitle(self) -> str:
        parts = []
        if self.brand and self.brand.lower() not in self.name.lower():
            parts.append(self.brand)
        if self.android:
            parts.append(f"Android {self.android}")
        if self.os_version and self.os_version != self.android:
            parts.append(self.os_version)
        return "  ·  ".join(parts)

    def match_props(self) -> dict[str, str]:
        return {
            "brand": self.brand,
            "model": self.model,
            "android": self.android,
            "os": self.os_version,
        }


@dataclass(frozen=True, slots=True)
class Device:
    """An entry from ``adb devices -l`` (transport level, no getprop)."""

    serial: str
    state: str
    model: str = ""
    product: str = ""
    transport_id: str = ""

    @property
    def ready(self) -> bool:
        return self.state == "device"

    @property
    def label(self) -> str:
        model = self.model.replace("_", " ").strip()
        return f"{model} ({self.serial})" if model else self.serial
