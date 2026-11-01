"""Dialogs and small user-facing helpers shared by the pages."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from qfluentwidgets import (BodyLabel, CaptionLabel, CheckBox, ComboBox,
                            InfoBar, InfoBarPosition, LineEdit, MessageBox,
                            MessageBoxBase, SubtitleLabel)

from ..core.controller import Controller
from ..core.models import Level


def notify(parent: QWidget, kind: str, title: str, content: str = "") -> None:
    """Show a top-right InfoBar toast."""
    factory = {
        "info": InfoBar.success,
        "success": InfoBar.success,
        "warning": InfoBar.warning,
        "error": InfoBar.error,
    }.get(kind, InfoBar.info)
    factory(
        title=title,
        content=content,
        orient=Qt.Orientation.Horizontal,
        isClosable=True,
        position=InfoBarPosition.TOP_RIGHT,
        duration=4200,
        parent=parent,
    )


def confirm(parent: QWidget, title: str, content: str,
            yes_text: str = "Continue", cancel_text: str = "Cancel") -> bool:
    box = MessageBox(title, content, parent)
    box.yesButton.setText(yes_text)
    box.cancelButton.setText(cancel_text)
    return bool(box.exec())


def run_selected(parent: QWidget, controller: Controller, *, revert: bool) -> None:
    """Confirm and start an apply or restore run using the current selection."""
    counts = controller.selection_counts()
    total = sum(counts.values())
    if total == 0:
        notify(parent, "info", "Nothing selected",
               "Tick a few packages in the Packages page first.")
        return
    if controller.running:
        notify(parent, "info", "A run is already in progress")
        return
    if controller.ready_device is None:
        notify(parent, "warning", "No device connected",
               "Connect the phone over USB and accept the debugging prompt.")
        return

    device = controller.ready_device
    risky = counts.get(Level.RISKY, 0)
    if revert:
        title = f"Restore {total} package(s)?"
        content = (
            f"Restore the selected packages on {device.name}.\n\n"
            f"Disabled apps will be enabled; removed apps will be reinstalled "
            f"for user 0. The APKs never left the phone, so this is reversible.\n\n"
            "Reboot the device afterwards for the changes to take effect."
        )
    else:
        title = f"Debloat {total} package(s)?"
        lines = [
            f"Apply the selected actions on {device.name}.",
            "",
            f"  Safe        {counts.get(Level.SAFE, 0)}",
            f"  Caution     {counts.get(Level.CAUTION, 0)}",
            f"  Risky       {risky}",
            "",
            "Everything is done for user 0 only: the APKs stay in the system "
            "image and can be restored from the Activity page.",
            "",
            "Reboot the phone afterwards for the changes to take effect.",
        ]
        if risky:
            lines.insert(
                2,
                f"\u26a0  {risky} package(s) are marked RISKY. Read their notes first!",
            )
        content = "\n".join(lines)

    if not controller.flag("confirm_apply", True):
        if revert:
            controller.revert_selected(dry_run=False)
        else:
            controller.apply_selected(dry_run=False)
        return

    if not confirm(parent, title, content,
                   yes_text="Restore" if revert else "Debloat",
                   cancel_text="Cancel"):
        return

    if revert:
        controller.revert_selected(dry_run=False)
    else:
        controller.apply_selected(dry_run=False)


class TextInputDialog(MessageBoxBase):
    """A Fluent dialog with one text field."""

    def __init__(self, parent: QWidget | None, title: str, label: str,
                 default: str = "", placeholder: str = "") -> None:
        super().__init__(parent)
        self.titleLabel = SubtitleLabel(title, self)
        self.viewLayout.addWidget(self.titleLabel)

        self.body = BodyLabel(label, self)
        self.body.setWordWrap(True)
        self.viewLayout.addWidget(self.body)

        self.edit = LineEdit(self)
        self.edit.setText(default)
        self.edit.setPlaceholderText(placeholder)
        self.edit.setClearButtonEnabled(True)
        self.viewLayout.addWidget(self.edit)

        self.yesButton.setText("Create")
        self.cancelButton.setText("Cancel")
        self.widget.setMinimumWidth(460)
        self.edit.setFocus()

    def text(self) -> str:
        return self.edit.text().strip()

    def validate(self) -> bool:
        valid = bool(self.text())
        self.edit.setError(not valid)
        return valid


class SnapshotDialog(MessageBoxBase):
    """Options for creating a profile from the connected device."""

    def __init__(self, parent: QWidget | None, device_name: str,
                 default_name: str) -> None:
        super().__init__(parent)
        self.titleLabel = SubtitleLabel("Create a profile from the device", self)
        self.viewLayout.addWidget(self.titleLabel)

        self.body = BodyLabel(
            f"Reads every package known to user 0 on {device_name}: active, "
            "disabled and already removed. The state is saved with each entry, "
            "and disabled packages are preset to Disable while removed ones "
            "are preset to Uninstall. Third-party apps are included by default; "
            "system packages are optional.",
            self,
        )
        self.body.setWordWrap(True)
        self.viewLayout.addWidget(self.body)

        name_caption = CaptionLabel("Profile name")
        self.viewLayout.addWidget(name_caption)
        self.name_edit = LineEdit(self)
        self.name_edit.setText(default_name)
        self.name_edit.setClearButtonEnabled(True)
        self.viewLayout.addWidget(self.name_edit)

        self.include_system = CheckBox(
            "Also include system packages (advanced, many entries)", self
        )
        self.viewLayout.addWidget(self.include_system)

        level_caption = CaptionLabel("Default safety level for imported packages")
        self.viewLayout.addWidget(level_caption)
        self.level_combo = ComboBox(self)
        for level in Level:
            self.level_combo.addItem(level.label, userData=level.value)
        self.level_combo.setCurrentIndex(1)
        self.viewLayout.addWidget(self.level_combo)

        self.hint = CaptionLabel(
            "The snapshot is a starting point: review the levels and actions "
            "before applying anything. Search for \u201csnapshot\u201d in the "
            "Packages table to find entries that were not active."
        )
        self.hint.setWordWrap(True)
        self.viewLayout.addWidget(self.hint)

        self.yesButton.setText("Create profile")
        self.cancelButton.setText("Cancel")
        self.widget.setMinimumWidth(500)

    def profile_name(self) -> str:
        return self.name_edit.text().strip()

    def include_system_packages(self) -> bool:
        return self.include_system.isChecked()

    def level(self) -> Level:
        value = self.level_combo.currentData() or "caution"
        return Level.parse(value)

    def validate(self) -> bool:
        valid = bool(self.profile_name())
        self.name_edit.setError(not valid)
        return valid


def confirm_delete_profile(parent: QWidget, name: str) -> bool:
    return confirm(
        parent,
        "Delete this profile?",
        f"\u201c{name}\u201d will be removed from the profiles folder together "
        "with its saved selection. The packages on the phone are not touched.",
        yes_text="Delete",
    )


def confirm_clear_selection(parent: QWidget) -> bool:
    return confirm(
        parent,
        "Clear the selection?",
        "All checkboxes and action overrides for this profile will be reset. "
        "Nothing is sent to the device.",
        yes_text="Clear",
    )
