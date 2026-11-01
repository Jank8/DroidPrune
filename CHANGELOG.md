# Changelog

## 1.0.0 beta — 2026-11-01

First public release.

- Profile-based debloater: JSON catalogues, import/export/duplicate, automatic
  profile suggestion and device snapshots.
- Bundled OnePlus 15 / OxygenOS 16 profile with 232 packages across six categories.
- Device snapshots capture active, disabled and uninstalled packages, store the
  observed state and preset the matching action.
- Fluent PySide6 UI: package table with live state, search, category and safety
  filters, per-package Disable/Uninstall override.
- Apply, restore, dry run, stop after the current package, run journal, per-run
  logs and one-click undo of the last debloat run.
- Multi-device selector, ADB auto-discovery and winget installation.
- Mica backdrop, Windows accent, live dark/light theme and a code-drawn icon.
- Portable data layout; no telemetry.
- 33 unit/Qt tests, a fake ADB harness and a screenshot/stress preview harness.
