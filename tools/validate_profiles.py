"""Validate every profile in ``profiles/`` and print a short summary.

Usage::

    python tools/validate_profiles.py
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from droidprune.core.profiles import ProfileStore  # noqa: E402
from droidprune.paths import PROFILES_DIR  # noqa: E402


def main() -> int:
    store = ProfileStore(PROFILES_DIR)
    profiles = store.reload()

    if not profiles:
        print(f"no profiles found in {PROFILES_DIR}")
        return 1

    for profile in profiles:
        levels = Counter(package.level.value for package in profile.packages)
        categories = profile.category_counts()
        print(f"{profile.path.name if profile.path else profile.id}")
        print(f"  name       : {profile.name}")
        print(f"  device     : {profile.device.label}"
              + (f" / {profile.device.os}" if profile.device.os else ""))
        print(f"  packages   : {profile.package_count}")
        print(f"  levels     : " + ", ".join(
            f"{key} {levels.get(key, 0)}" for key in ("safe", "caution", "risky")
        ))
        print(f"  categories : " + ", ".join(
            f"{profile.category_name(cid)} {count}"
            for cid, count in sorted(categories.items())
        ))
        print()

    if store.errors:
        print("invalid profile files:", file=sys.stderr)
        for path, message in store.errors:
            print(f"  - {path.name}: {message}", file=sys.stderr)
        return 1

    print(f"OK - {len(profiles)} profile(s) valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
