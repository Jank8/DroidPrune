"""Profiles page: manage the device catalogues stored as JSON files."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QFileDialog, QGridLayout, QHBoxLayout, QLabel,
                               QVBoxLayout, QWidget)

from qfluentwidgets import (BodyLabel, CaptionLabel, FluentIcon,
                            PrimaryPushButton, PushButton, SmoothScrollArea,
                            StrongBodyLabel)

from ...core.controller import Controller
from ...core.models import Level, Profile
from ...paths import PROFILES_DIR, open_in_explorer
from .. import dialogs, theme
from ..widgets import (Card, EmptyState, HLine, LevelBar, PageHeader, Pill, font)


class ProfilesPage(QWidget):
    def __init__(self, controller: Controller, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("profilesPage")
        self.controller = controller

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 16, 24, 16)
        outer.setSpacing(10)

        header_row = QHBoxLayout()
        self.header = PageHeader(
            "Device profiles",
            "Each profile is a JSON catalogue of packages for one phone family. "
            "Keep several phones side by side and switch whenever you like.",
        )
        header_row.addWidget(self.header, 1)

        self.open_button = PushButton("Open folder")
        self.open_button.setIcon(FluentIcon.FOLDER.icon())
        self.open_button.clicked.connect(
            lambda: open_in_explorer(PROFILES_DIR)
        )
        header_row.addWidget(self.open_button, 0, Qt.AlignTop)

        self.import_button = PushButton("Import…")
        self.import_button.setIcon(FluentIcon.FOLDER_ADD.icon())
        self.import_button.clicked.connect(self._import)
        header_row.addWidget(self.import_button, 0, Qt.AlignTop)

        self.snapshot_button = PrimaryPushButton("Create from device")
        self.snapshot_button.setIcon(FluentIcon.PHONE.icon())
        self.snapshot_button.clicked.connect(self._snapshot)
        header_row.addWidget(self.snapshot_button, 0, Qt.AlignTop)
        outer.addLayout(header_row)

        self.scroll = SmoothScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
        )
        self.scroll.viewport().setAutoFillBackground(False)
        self.content = QWidget()
        self.content.setStyleSheet("background: transparent;")
        self.cards = QVBoxLayout(self.content)
        self.cards.setContentsMargins(0, 2, 6, 2)
        self.cards.setSpacing(10)
        self.scroll.setWidget(self.content)
        outer.addWidget(self.scroll, 1)

        controller.profilesChanged.connect(self.rebuild)
        controller.profileChanged.connect(self._sync_active)
        self.rebuild()

    # ------------------------------------------------------------- build
    def rebuild(self) -> None:
        while self.cards.count():
            item = self.cards.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        errors = self.controller.profile_errors
        if errors:
            self.cards.addWidget(self._error_card(errors))

        profiles = self.controller.profiles_list
        if not profiles:
            empty = EmptyState(
                FluentIcon.FOLDER,
                "No profiles yet",
                "Import a profile JSON file, or snapshot the packages installed "
                "on a connected phone and start from there.",
            )
            empty_button = PushButton("Import a profile…")
            empty_button.setIcon(FluentIcon.FOLDER_ADD.icon())
            empty_button.clicked.connect(self._import)
            empty.add_action(empty_button)
            self.cards.addWidget(empty)
        else:
            for profile in profiles:
                self.cards.addWidget(self._profile_card(profile))
            active = self.controller.profile
            if active is not None:
                self.cards.addWidget(self._breakdown_card(active))
        self.cards.addStretch(1)

    def _error_card(self, errors) -> Card:
        card = Card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(2)
        title = StrongBodyLabel("Some profile files could not be loaded")
        title.setTextColor(theme.palette().caution, theme.palette().caution)
        layout.addWidget(title)
        for path, message in errors:
            label = CaptionLabel(f"{path.name}: {message}")
            label.setWordWrap(True)
            label.setTextColor(theme.palette().dim, theme.palette().dim)
            layout.addWidget(label)
        return card

    def _profile_card(self, profile: Profile) -> Card:
        card = Card()
        layout = QHBoxLayout(card)
        layout.setContentsMargins(18, 12, 16, 12)
        layout.setSpacing(12)

        info = QVBoxLayout()
        info.setSpacing(3)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        name = QLabel(profile.name)
        name.setFont(font(13, QFont.Weight.DemiBold))
        name.setStyleSheet(f"color: {theme.hexa(theme.palette().text)};")
        title_row.addWidget(name)
        if self.controller.profile and self.controller.profile.id == profile.id:
            title_row.addWidget(Pill("Active", theme.palette().accent))
        if any(package.state is not None for package in profile.packages):
            title_row.addWidget(Pill("Snapshot", theme.palette().dim))
        title_row.addStretch(1)
        info.addLayout(title_row)

        device_bits = [profile.device.label]
        if profile.device.os:
            device_bits.append(profile.device.os)
        if profile.device.android:
            device_bits.append(f"Android {profile.device.android}")
        meta = CaptionLabel(
            "  ·  ".join(device_bits)
            + f"     {profile.package_count} packages"
            + f"  ·  {profile.category_count} categories"
        )
        meta.setTextColor(theme.palette().dim, theme.palette().dim)
        info.addWidget(meta)

        description = BodyLabel(
            profile.description or profile.source or "No description."
        )
        description.setWordWrap(True)
        description.setTextColor(theme.palette().faint, theme.palette().faint)
        info.addWidget(description)

        counts = profile.counts()
        chips = QHBoxLayout()
        chips.setSpacing(6)
        for level in Level:
            chip = Pill(
                f"{counts.get(level, 0)} {level.label.lower()}",
                theme.level_color(level),
            )
            chips.addWidget(chip)
        chips.addStretch(1)
        info.addLayout(chips)
        layout.addLayout(info, 1)

        buttons = QVBoxLayout()
        buttons.setSpacing(6)
        active = bool(self.controller.profile
                      and self.controller.profile.id == profile.id)
        use = PushButton("Active" if active else "Use profile")
        use.setEnabled(not active)
        if not active:
            use.setIcon(FluentIcon.ACCEPT.icon())
        use.clicked.connect(lambda _=False, p=profile: self._use(p))
        buttons.addWidget(use)

        export = PushButton("Export…")
        export.setIcon(FluentIcon.SAVE_AS.icon())
        export.clicked.connect(lambda _=False, p=profile: self._export(p))
        buttons.addWidget(export)

        row = QHBoxLayout()
        row.setSpacing(6)
        duplicate = PushButton("Duplicate")
        duplicate.clicked.connect(lambda _=False, p=profile: self._duplicate(p))
        row.addWidget(duplicate)
        delete = PushButton("Delete")
        delete.setIcon(FluentIcon.DELETE.icon())
        delete.clicked.connect(lambda _=False, p=profile: self._delete(p))
        row.addWidget(delete)
        buttons.addLayout(row)
        layout.addLayout(buttons)
        return card

    def _breakdown_card(self, profile: Profile) -> Card:
        card = Card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 12, 18, 14)
        layout.setSpacing(6)
        layout.addWidget(StrongBodyLabel(f"What is inside \u201c{profile.name}\u201d"))
        caption = CaptionLabel(
            "Package count and safety mix per category. The bar uses the same "
            "green / amber / red colours as the safety levels."
        )
        caption.setWordWrap(True)
        caption.setTextColor(theme.palette().faint, theme.palette().faint)
        layout.addWidget(caption)
        layout.addWidget(HLine())

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(7)
        grid.setColumnStretch(1, 1)
        for row, category in enumerate(profile.categories):
            packages = profile.in_category(category.id)
            counts = {level.value: 0 for level in Level}
            for package in packages:
                counts[package.level.value] += 1

            name = QLabel(category.name)
            name.setFont(font(9))
            name.setStyleSheet(f"color: {theme.hexa(theme.palette().text)};")
            grid.addWidget(name, row, 0)

            bar = LevelBar(counts)
            bar.setToolTip(
                f"{len(packages)} packages: "
                + ", ".join(f"{counts[level.value]} {level.label.lower()}"
                            for level in Level)
            )
            grid.addWidget(bar, row, 1)

            total = CaptionLabel(f"{len(packages)}")
            total.setTextColor(theme.palette().faint, theme.palette().faint)
            total.setMinimumWidth(28)
            total.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            grid.addWidget(total, row, 2)

        layout.addLayout(grid)
        return card

    # ------------------------------------------------------------ actions
    def _use(self, profile: Profile) -> None:
        self.controller.set_profile(profile.id)

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import a device profile", str(PROFILES_DIR),
            "Profile JSON (*.json);;All files (*)",
        )
        if not path:
            return
        try:
            self.controller.import_profile(path)
        except Exception as error:  # ProfileError and OSError
            dialogs.notify(self, "error", "Could not import the profile", str(error))

    def _export(self, profile: Profile) -> None:
        suggested = str(PROFILES_DIR / f"{profile.id}.json")
        path, _ = QFileDialog.getSaveFileName(
            self, "Export profile", suggested, "Profile JSON (*.json)"
        )
        if not path:
            return
        try:
            self.controller.export_profile(profile, path)
        except OSError as error:
            dialogs.notify(self, "error", "Could not export the profile", str(error))
            return
        dialogs.notify(self, "info", "Profile exported", path)

    def _duplicate(self, profile: Profile) -> None:
        copy = self.controller.duplicate_profile(profile)
        dialogs.notify(self, "info", "Profile duplicated", copy.name)

    def _delete(self, profile: Profile) -> None:
        if not dialogs.confirm_delete_profile(self, profile.name):
            return
        self.controller.delete_profile(profile)

    def _snapshot(self) -> None:
        device = self.controller.ready_device
        if device is None:
            dialogs.notify(
                self, "warning", "Connect a device first",
                "A profile snapshot is built from the packages installed on the "
                "connected phone.",
            )
            return
        dialog = dialogs.SnapshotDialog(
            self, device.name, f"{device.name} snapshot"
        )
        if not dialog.exec():
            return
        self.controller.create_profile_from_device(
            dialog.profile_name(),
            include_system=dialog.include_system_packages(),
            level=dialog.level(),
        )

    def _sync_active(self) -> None:
        self.rebuild()

    def apply_palette(self) -> None:
        self.header.apply_palette()
        self.rebuild()
