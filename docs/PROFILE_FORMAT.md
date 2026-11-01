# Device profile format

A **profile** is one UTF-8 JSON file in `profiles/`. It describes a phone family:
its packages, the category each belongs to, how risky it is to remove it and what
the debloater should do by default.

Profiles are validated when they are loaded. A malformed file is skipped and listed
on the Profiles page instead of breaking the application; `tools/validate_profiles.py`
runs the same validation from the command line.

---

## Minimal example

```json
{
  "schema": 1,
  "id": "example_phone",
  "name": "Example Phone — ExampleOS 1",
  "description": "Packages shipped on the Example Phone.",
  "device": {
    "brand": "Example",
    "model": "Phone One",
    "os": "ExampleOS 1",
    "android": "15",
    "build": "EX1.230101.001"
  },
  "match": {
    "brand": "(?i)example",
    "model": "(?i)phone\\s*one",
    "android": "^15"
  },
  "source": "Package dump of a factory device.",
  "categories": [
    {
      "id": "google",
      "name": "Google",
      "description": "Google apps that can usually be replaced."
    }
  ],
  "packages": [
    {
      "package": "com.google.android.apps.docs",
      "title": "Google Drive",
      "description": "Google Drive",
      "level": "safe",
      "action": "uninstall",
      "category": "google",
      "note": ""
    }
  ]
}
```

---

## Top-level fields

| Field | Required | Type | Meaning |
|---|---|---|---|
| `schema` | no | integer | Format version. Currently `1`; newer versions are rejected with a clear error. |
| `id` | **yes** | string | Stable identifier: lowercase letters, digits, `.`, `_`, `-`. Used for the selection file (`data/selection/<id>.json`). |
| `name` | **yes** | string | Display name, e.g. `OnePlus 15 — OxygenOS 16`. |
| `description` | no | string | One or two sentences shown on Home and Profiles. |
| `device` | no | object | `brand`, `model`, `os`, `android`, `build` — metadata for display and for humans. |
| `match` | no | object | Regex rules used to suggest this profile for the connected phone. |
| `source` | no | string | Where the package list and notes come from. |
| `categories` | **yes** | array | At least one category object (an empty catalogue may also have zero packages). |
| `packages` | **yes** | array | Package objects; may be empty for a template profile. |

### Category object

| Field | Required | Meaning |
|---|---|---|
| `id` | **yes** | Slug used by packages (`3rd-party`, `google`, `aosp`, …). Unique within the profile. |
| `name` | **yes** | Label shown in the category rail. |
| `description` | no | Short explanation shown in the UI/tooling. |

### Package object

| Field | Required | Meaning |
|---|---|---|
| `package` | **yes** | Android package name, at least two dot-separated segments (`com.vendor.app`). |
| `title` | no | Short human name. Falls back to the last package segment, title-cased. |
| `description` | no | What the package is / what happens when it is removed. Searchable. |
| `level` | no | `safe`, `caution` or `risky` (lowercase). Defaults to `caution`. |
| `action` | no | `disable` or `uninstall`. Defaults to `disable`. |
| `category` | no | Category id. Must exist in `categories` when set. |
| `note` | no | Extra warning or caveat, e.g. “Keep if you use eSIM”. |
| `state` | no | Snapshot metadata: `active`, `disabled` or `uninstalled`. Written by **Create from device**; hand-written profiles usually omit it. |

Unknown keys are ignored, so extra metadata can be kept in the file without
breaking the application. Duplicate package names and duplicate category ids are
rejected.

### Safety levels

| Value | UI colour | Meaning |
|---|---|---|
| `safe` | green | Bloat, duplicates, telemetry, engineering tools; no functional loss expected. |
| `caution` | amber | Removes a specific feature; read the description/note. |
| `risky` | red | Likely tied to AOD, networking, OTA, battery management or other system features. |

### Actions

| Value | ADB command | Revert |
|---|---|---|
| `disable` | `pm disable-user --user 0 <package>` | `pm enable --user 0 <package>` |
| `uninstall` | `pm uninstall --user 0 <package>` | `cmd package install-existing --user 0 <package>` |

Both are scoped to user 0: the APK remains in the system image, so restore works
without root. The user can override the action per package in the table; the JSON
value is only the default.

### Snapshot metadata (`state`)

A profile created with **Create from device** captures the current state of the
phone instead of only its installed apps:

- `active` — installed and enabled;
- `disabled` — present and disabled for user 0;
- `uninstalled` — removed for user 0, APK still in the system image.

The state is informational: **the action decides what the debloater runs.** The
snapshot presets the action to match the observed state (`disabled` → `disable`,
`uninstalled` → `uninstall`), so applying the profile to a fresh phone reproduces
the captured debloat. Entries that were not active also get a `note` such as
“Snapshot: disabled on the device”, which is visible in the table and searchable —
search for `snapshot` to find them.

`state` is optional and only accepts those three values; `absent` and `unknown`
make no sense in a saved profile and are rejected by validation.

---

## Matching rules

`match` lets the app suggest a profile when a phone is connected. Each present key
is a Python regular expression matched case-insensitively against:

| Key | Source property |
|---|---|
| `brand` | `ro.product.brand` |
| `model` | marketing name (`ro.vendor.oplus.market.name`, `ro.product.marketname`, `ro.product.model`, …) |
| `android` | `ro.build.version.release` |
| `os` | OxygenOS/ColorOS/One UI/… version property when present |

The score is the fraction of rules that match. A profile is suggested when at
least **60 %** of its rules match and it is not already active. Rules are only a
convenience: selecting a profile manually always wins.

Example for the OnePlus 15 profile:

```json
"match": {
  "brand": "(?i)oneplus",
  "model": "(?i)(oneplus\\s*15|CPH27\\d{2})",
  "android": "^16"
}
```

Leaving `match` out disables automatic suggestions for that profile.

---

## Creating a profile

1. **From a device** — Profiles → **Create from device**. The app reads every
   package known to user 0 (active, disabled, removed), stores the observed state
   and presets the matching action. Third-party apps are included by default
   (system apps optional). Review levels and actions before using it.
2. **From an existing profile** — Profiles → **Duplicate**, then edit the JSON and
   restart/reload the application.
3. **From another debloater** — map its package list to this schema; the bundled
   OOS16 profile was ported from the original PowerShell debloater that predates
   this application.
4. **Hand-written** — copy the example above, keep ids unique, then validate:

   ```powershell
   python tools/validate_profiles.py
   ```

Failures are reported with the file name, the offending field and a short reason.
The app shows the same messages on the Profiles page and keeps working with the
remaining valid profiles.

---

## Tips

- Use `adb shell pm list packages` to confirm a package exists on the target
  firmware; packages missing from the ROM show as `Not on device`.
- Vendor skins move packages between releases. Prefer `disable` when unsure — it is
  easier to explain and revert than a reinstall.
- Categories are presentation only; they do not affect commands.
- Keep `title` short: the table draws it in one line above the package name.
- Levels and notes are guidance gathered from UAD, XDA and community reports, not
  a guarantee. Always be ready to restore a package.
