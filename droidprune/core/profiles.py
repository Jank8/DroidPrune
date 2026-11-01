"""Loading, saving and managing device profiles on disk."""

from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path

from .models import Category, DeviceMeta, MatchRules, Profile, ProfileError


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text or "profile"


class ProfileStore:
    """A folder of ``*.json`` profiles plus the operations the UI needs."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._profiles: list[Profile] = []
        self._errors: list[tuple[Path, str]] = []

    # -- reading --------------------------------------------------------
    def reload(self) -> list[Profile]:
        profiles: list[Profile] = []
        errors: list[tuple[Path, str]] = []
        for path in sorted(self.directory.glob("*.json")):
            try:
                profiles.append(Profile.load(path))
            except ProfileError as error:
                errors.append((path, str(error)))
            except OSError as error:
                errors.append((path, f"{path.name}: {error}"))
        self._profiles = sorted(profiles, key=lambda item: item.name.lower())
        self._errors = errors
        return list(self._profiles)

    @property
    def profiles(self) -> list[Profile]:
        return list(self._profiles)

    @property
    def errors(self) -> list[tuple[Path, str]]:
        return list(self._errors)

    def get(self, profile_id: str) -> Profile | None:
        return next((p for p in self._profiles if p.id == profile_id), None)

    def path_for(self, profile_id: str) -> Path:
        return self.directory / f"{profile_id}.json"

    def unique_id(self, base: str) -> str:
        candidate = slugify(base)
        existing = {profile.id for profile in self._profiles}
        if candidate not in existing and not self.path_for(candidate).exists():
            return candidate
        counter = 2
        while f"{candidate}-{counter}" in existing or \
                self.path_for(f"{candidate}-{counter}").exists():
            counter += 1
        return f"{candidate}-{counter}"

    # -- writing --------------------------------------------------------
    def save(self, profile: Profile) -> Profile:
        """Validate and persist a profile atomically, then refresh the cache."""
        if not profile.packages and not profile.categories:
            raise ProfileError("a profile needs at least one package")

        payload = profile.to_json()
        target = self.path_for(profile.id)
        temp = target.with_suffix(".json.tmp")
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            temp.write_text(payload, encoding="utf-8")
            os.replace(temp, target)
        finally:
            if temp.exists():
                try:
                    temp.unlink()
                except OSError:
                    pass

        profile.path = target
        self._replace_in_cache(profile)
        return profile

    def _replace_in_cache(self, profile: Profile) -> None:
        for index, existing in enumerate(self._profiles):
            if existing.id == profile.id:
                self._profiles[index] = profile
                return
        self._profiles.append(profile)
        self._profiles.sort(key=lambda item: item.name.lower())

    def create(self, profile: Profile) -> Profile:
        if self.path_for(profile.id).exists() or self.get(profile.id):
            profile.id = self.unique_id(profile.id)
        return self.save(profile)

    def delete(self, profile: Profile) -> bool:
        target = self.path_for(profile.id)
        if target.parent != self.directory:
            raise ProfileError("refusing to delete a file outside the profile folder")
        if target.exists():
            target.unlink()
        self._profiles = [item for item in self._profiles if item.id != profile.id]
        return True

    def duplicate(self, profile: Profile) -> Profile:
        new_id = self.unique_id(f"{profile.id}-copy")
        copy = profile.clone(id=new_id, name=f"{profile.name} (copy)")
        copy.path = None
        return self.save(copy)

    def import_file(self, source: Path) -> Profile:
        profile = Profile.load(Path(source))
        profile.path = None
        profile.id = self.unique_id(profile.id)
        return self.save(profile)

    def export_file(self, profile: Profile, destination: Path) -> Path:
        destination = Path(destination)
        destination.write_text(profile.to_json(), encoding="utf-8")
        return destination

    def create_blank(self, name: str) -> Profile:
        name = name.strip() or "New profile"
        profile = Profile(
            id=self.unique_id(name),
            name=name,
            description="Empty profile - add packages to it.",
            device=DeviceMeta(),
            match=MatchRules(),
            categories=[Category("general", "General", "Manually curated packages.")],
            packages=[],
        )
        return self.save(profile)
