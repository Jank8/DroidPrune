"""Home page: device status, active profile, quick actions and recent runs."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from qfluentwidgets import (BodyLabel, CaptionLabel, CheckBox, ComboBox,
                            FluentIcon, PrimaryPushButton, ProgressBar,
                            PushButton, SmoothScrollArea, StrongBodyLabel)

from ...core.controller import Controller
from ...core.models import Level, State
from .. import dialogs, theme
from ..widgets import (Card, Dot, HLine, PageHeader, Pill, StatCard, font)


class HomePage(QWidget):
    navigate = Signal(str)

    def __init__(self, controller: Controller, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("homePage")
        self.controller = controller
        self._busy = False
        self._suggested_id = ""
        self._device_serials: tuple[str, ...] = ()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        scroll = SmoothScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.viewport().setAutoFillBackground(False)
        content = QWidget()
        content.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 16, 24, 20)
        layout.setSpacing(12)
        scroll.setWidget(content)
        outer.addWidget(scroll)

        header_row = QHBoxLayout()
        self.header = PageHeader(
            "DroidPrune",
            "Profile-based Android debloater. Pick a profile, choose what goes and "
            "apply — no root required.",
        )
        header_row.addWidget(self.header, 1)
        self.refresh_button = PushButton("Refresh")
        self.refresh_button.clicked.connect(self.controller.refresh_devices)
        header_row.addWidget(self.refresh_button, 0, Qt.AlignTop)
        layout.addLayout(header_row)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(12)
        cards_row.addWidget(self._build_device_card(), 3)
        cards_row.addWidget(self._build_profile_card(), 2)
        layout.addLayout(cards_row)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(12)
        self.stat_selected = StatCard("Selected", "0", "packages ticked")
        self.stat_present = StatCard("Installed", "0", "packages found")
        self.stat_debloated = StatCard("Already debloated", "0", "disabled or removed")
        self.stat_absent = StatCard("Not in this ROM", "0", "not shipped / already gone")
        for card in (self.stat_selected, self.stat_present,
                     self.stat_debloated, self.stat_absent):
            stats_row.addWidget(card, 1)
        layout.addLayout(stats_row)

        layout.addWidget(self._build_action_card())
        bottom = QHBoxLayout()
        bottom.setSpacing(12)
        bottom.addWidget(self._build_activity_card(), 2)
        bottom.addWidget(self._build_legend_card(), 1)
        layout.addLayout(bottom, 1)

        controller.deviceChanged.connect(self.refresh)
        controller.devicesChanged.connect(self.refresh)
        controller.inventoryChanged.connect(self.refresh)
        controller.profileChanged.connect(self.refresh)
        controller.selectionChanged.connect(self.refresh)
        controller.busyChanged.connect(self._on_busy)
        controller.journalChanged.connect(self._rebuild_activity)
        controller.runFinished.connect(lambda _result: self._rebuild_activity())
        controller.profilesChanged.connect(self._on_profiles_changed)

        self._rebuild_profiles()
        self.refresh()
        self._rebuild_activity()

    # ------------------------------------------------------------- build
    def _build_device_card(self) -> Card:
        card = Card()
        card.setMinimumHeight(170)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(4)

        top = QHBoxLayout()
        top.setSpacing(2)
        self.device_dot = Dot(theme.palette().faint, 9)
        top.addWidget(self.device_dot)
        self.device_status = StrongBodyLabel("Checking for a device…")
        top.addWidget(self.device_status)
        top.addStretch(1)
        self.adb_pill = Pill("ADB", theme.palette().faint)
        top.addWidget(self.adb_pill)
        layout.addLayout(top)

        self.device_name = QLabel("…")
        self.device_name.setFont(font(16, QFont.Weight.DemiBold))
        layout.addWidget(self.device_name)

        self.device_meta = QLabel("")
        self.device_meta.setFont(font(9))
        self.device_meta.setWordWrap(True)
        layout.addWidget(self.device_meta)

        self.device_combo = ComboBox()
        self.device_combo.setFixedWidth(260)
        self.device_combo.hide()
        self.device_combo.currentIndexChanged.connect(self._device_changed)
        layout.addWidget(self.device_combo)

        chips = QHBoxLayout()
        chips.setSpacing(6)
        self.device_chip_root = Pill("No root", theme.palette().dim)
        self.device_chip_user = Pill("User 0 only", theme.palette().dim)
        self.device_chip_reversible = Pill("Reversible", theme.palette().dim)
        chips.addWidget(self.device_chip_root)
        chips.addWidget(self.device_chip_user)
        chips.addWidget(self.device_chip_reversible)
        chips.addStretch(1)
        layout.addLayout(chips)

        layout.addStretch(1)

        self.adb_info = CaptionLabel("")
        self.adb_info.setWordWrap(False)
        layout.addWidget(self.adb_info)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.device_hint = CaptionLabel("")
        self.device_hint.setWordWrap(True)
        buttons.addWidget(self.device_hint, 1)
        self.secondary_button = PushButton("Reboot")
        self.secondary_button.setIcon(FluentIcon.POWER_BUTTON.icon())
        self.secondary_button.clicked.connect(self._secondary_action)
        buttons.addWidget(self.secondary_button)
        self.primary_device_button = PushButton("Refresh")
        self.primary_device_button.setIcon(FluentIcon.SYNC.icon())
        self.primary_device_button.clicked.connect(self._primary_action)
        buttons.addWidget(self.primary_device_button)
        layout.addLayout(buttons)
        return card

    def _build_profile_card(self) -> Card:
        card = Card()
        card.setMinimumHeight(170)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(6)

        top = QHBoxLayout()
        caption = CaptionLabel("Device profile")
        manage = PushButton("Manage")
        manage.clicked.connect(lambda: self.navigate.emit("profiles"))
        top.addWidget(caption)
        top.addStretch(1)
        top.addWidget(manage)
        layout.addLayout(top)

        self.profile_combo = ComboBox()
        self.profile_combo.setMinimumWidth(220)
        self.profile_combo.currentIndexChanged.connect(self._profile_changed)
        layout.addWidget(self.profile_combo)

        self.profile_stats = QLabel("")
        self.profile_stats.setFont(font(9))
        layout.addWidget(self.profile_stats)

        pills = QHBoxLayout()
        pills.setSpacing(6)
        self.pill_safe = Pill("0 safe", theme.palette().safe)
        self.pill_caution = Pill("0 caution", theme.palette().caution)
        self.pill_risky = Pill("0 risky", theme.palette().risky)
        pills.addWidget(self.pill_safe)
        pills.addWidget(self.pill_caution)
        pills.addWidget(self.pill_risky)
        pills.addStretch(1)
        layout.addLayout(pills)

        self.profile_description = QLabel("")
        self.profile_description.setFont(font(8.5))
        self.profile_description.setWordWrap(True)
        layout.addWidget(self.profile_description, 1)

        suggestion = QHBoxLayout()
        suggestion.setSpacing(8)
        self.suggestion_label = CaptionLabel("")
        self.suggestion_label.setWordWrap(True)
        suggestion.addWidget(self.suggestion_label, 1)
        self.suggestion_button = PushButton("Use profile")
        self.suggestion_button.clicked.connect(self._use_suggestion)
        suggestion.addWidget(self.suggestion_button)
        self.suggestion_row = QWidget()
        self.suggestion_row.setLayout(suggestion)
        self.suggestion_row.hide()
        layout.addWidget(self.suggestion_row)
        return card

    def _build_action_card(self) -> Card:
        card = Card()
        layout = QHBoxLayout(card)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(12)

        text = QVBoxLayout()
        text.setSpacing(1)
        self.action_title = StrongBodyLabel("Nothing selected yet")
        text.addWidget(self.action_title)
        self.action_subtitle = CaptionLabel(
            "Browse the Packages page and tick what you want to remove."
        )
        text.addWidget(self.action_subtitle)
        self.progress = ProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setFixedHeight(4)
        self.progress.hide()
        text.addWidget(self.progress)
        layout.addLayout(text, 1)

        self.dry_run = CheckBox("Dry run")
        self.dry_run.setToolTip(
            "Show what would be executed without changing the device."
        )
        self.dry_run.setChecked(self.controller.flag("dry_run", False))
        self.dry_run.stateChanged.connect(self._dry_run_changed)
        layout.addWidget(self.dry_run)

        self.stop_button = PushButton("Stop")
        self.stop_button.setIcon(FluentIcon.CANCEL.icon())
        self.stop_button.clicked.connect(self.controller.stop_run)
        self.stop_button.hide()
        layout.addWidget(self.stop_button)

        self.revert_button = PushButton("Restore")
        self.revert_button.setIcon(FluentIcon.SYNC.icon())
        self.revert_button.clicked.connect(self._restore)
        layout.addWidget(self.revert_button)

        self.apply_button = PrimaryPushButton("Debloat")
        self.apply_button.setIcon(FluentIcon.BROOM.icon())
        self.apply_button.clicked.connect(self._apply)
        layout.addWidget(self.apply_button)
        return card

    def _build_activity_card(self) -> Card:
        card = Card()
        card.setMinimumHeight(250)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(6)

        top = QHBoxLayout()
        title = StrongBodyLabel("Recent activity")
        top.addWidget(title)
        top.addStretch(1)
        view_all = PushButton("View all")
        view_all.clicked.connect(lambda: self.navigate.emit("activity"))
        top.addWidget(view_all)
        layout.addLayout(top)

        self.activity_box = QVBoxLayout()
        self.activity_box.setSpacing(4)
        layout.addLayout(self.activity_box)
        layout.addStretch(1)
        return card

    def _build_legend_card(self) -> Card:
        card = Card()
        card.setMinimumHeight(250)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(8)
        layout.addWidget(StrongBodyLabel("Safety levels"))

        self.legend_dots = []
        self.legend_names = []
        self.legend_hints = []
        for level in Level:
            row = QHBoxLayout()
            row.setSpacing(8)
            dot = Dot(theme.level_color(level), 8)
            row.addWidget(dot, 0, Qt.AlignTop)
            text = QVBoxLayout()
            text.setSpacing(0)
            name = QLabel(level.label)
            name.setFont(font(9.5, QFont.Weight.DemiBold))
            hint = QLabel(level.hint)
            hint.setFont(font(8))
            hint.setWordWrap(True)
            text.addWidget(name)
            text.addWidget(hint)
            row.addLayout(text, 1)
            layout.addLayout(row)
            self.legend_dots.append(dot)
            self.legend_names.append(name)
            self.legend_hints.append(hint)
        layout.addWidget(HLine())
        workflow = QLabel(
            "Pick a profile, tick the packages, press Debloat and reboot. "
            "Every change can be undone from Activity."
        )
        workflow.setFont(font(8))
        workflow.setWordWrap(True)
        self.workflow_label = workflow
        layout.addWidget(workflow)
        layout.addStretch(1)
        return card

    # ------------------------------------------------------------ actions
    def _primary_action(self) -> None:
        if not self.controller.adb.available:
            if self.controller.install_adb_available():
                self.controller.install_adb()
            else:
                self.navigate.emit("settings")
            return
        self.controller.refresh_devices()

    def _secondary_action(self) -> None:
        device = self.controller.ready_device
        if device is None:
            self.navigate.emit("settings")
            return
        if dialogs.confirm(
            self,
            f"Reboot {device.name}?",
            "The phone will reboot now. Reconnect it after the boot if you want "
            "to continue debloating.",
            yes_text="Reboot",
        ):
            self.controller.reboot()

    def _apply(self) -> None:
        if self.dry_run.isChecked():
            if not self.controller.selected_items():
                dialogs.notify(self, "info", "Nothing selected",
                               "Tick a few packages in the Packages page first.")
                return
            self.controller.apply_selected(dry_run=True)
            return
        dialogs.run_selected(self, self.controller, revert=False)

    def _restore(self) -> None:
        if self.dry_run.isChecked():
            if not self.controller.selected_items():
                dialogs.notify(self, "info", "Nothing selected")
                return
            self.controller.revert_selected(dry_run=True)
            return
        dialogs.run_selected(self, self.controller, revert=True)

    def _profile_changed(self, index: int) -> None:
        profile_id = self.profile_combo.currentData()
        if profile_id:
            self.controller.set_profile(str(profile_id))

    def _device_changed(self, _index: int) -> None:
        serial = self.device_combo.currentData()
        if serial:
            self.controller.select_device(str(serial))

    def _sync_device_combo(self, devices) -> None:
        ready = [device for device in devices if device.ready]
        serials = tuple(device.serial for device in ready)
        if serials != self._device_serials:
            self._device_serials = serials
            self.device_combo.blockSignals(True)
            self.device_combo.clear()
            for item in ready:
                self.device_combo.addItem(item.label, userData=item.serial)
            self.device_combo.blockSignals(False)
        current = self.controller.ready_device
        if current is not None:
            index = self.device_combo.findData(current.serial)
            if index >= 0 and index != self.device_combo.currentIndex():
                self.device_combo.blockSignals(True)
                self.device_combo.setCurrentIndex(index)
                self.device_combo.blockSignals(False)
        self.device_combo.setVisible(len(ready) > 1)

    def _use_suggestion(self) -> None:
        if self._suggested_id:
            self.controller.set_profile(self._suggested_id)

    def _on_busy(self, busy: bool) -> None:
        self._busy = busy
        if busy:
            self.progress.show()
            self.progress.setRange(0, 0)
            self.action_subtitle.setText(self.controller.busy_text())
        else:
            self.progress.hide()
            self.progress.setRange(0, 1)
            self.progress.setValue(0)
        self.refresh()

    def _dry_run_changed(self, _state: int) -> None:
        self.controller.set_setting("dry_run", self.dry_run.isChecked())

    def showEvent(self, event) -> None:  # noqa: N802
        self.dry_run.blockSignals(True)
        self.dry_run.setChecked(self.controller.flag("dry_run", False))
        self.dry_run.blockSignals(False)
        self.refresh()
        super().showEvent(event)

    def apply_palette(self) -> None:
        self.header.apply_palette()
        palette = theme.palette()
        for chip in (self.device_chip_root, self.device_chip_user,
                     self.device_chip_reversible):
            chip.set_color(palette.dim, bg_alpha=22)
        for level, dot, name, hint in zip(
            Level, self.legend_dots, self.legend_names, self.legend_hints
        ):
            dot.set_color(theme.level_color(level))
            name.setStyleSheet(f"color: {theme.hexa(palette.text)};")
            hint.setStyleSheet(f"color: {theme.hexa(palette.faint)};")
        self.workflow_label.setStyleSheet(f"color: {theme.hexa(palette.faint)};")
        self.refresh()
        self._rebuild_activity()

    def _on_profiles_changed(self) -> None:
        self._rebuild_profiles()
        self.refresh()

    def _rebuild_profiles(self) -> None:
        current = self.controller.profile.id if self.controller.profile else ""
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for profile in self.controller.profiles_list:
            self.profile_combo.addItem(profile.name, userData=profile.id)
        if current:
            index = self.profile_combo.findData(current)
            if index >= 0:
                self.profile_combo.setCurrentIndex(index)
        self.profile_combo.blockSignals(False)

    # ------------------------------------------------------------ refresh
    def refresh(self) -> None:
        palette = theme.palette()
        device = self.controller.ready_device
        devices = self.controller.devices
        adb_ready = self.controller.adb.available
        self._sync_device_combo(devices)

        self.adb_pill.setText("ADB ready" if adb_ready else "ADB missing")
        self.adb_pill.set_color(palette.safe if adb_ready else palette.risky)

        if device is not None:
            self.device_dot.set_color(palette.safe)
            self.device_status.setText("Connected")
            self.device_name.setText(device.name)
            meta = [part for part in (device.brand, f"Android {device.android}"
                                      if device.android else "",
                                      device.os_version) if part]
            meta.append(f"S/N {device.serial}")
            self.device_meta.setText("  ·  ".join(meta))
            self.device_hint.setText(
                "Changes apply to the whole device (user 0)."
            )
            self.secondary_button.setText("Reboot")
            self.secondary_button.setIcon(FluentIcon.POWER_BUTTON.icon())
            self.secondary_button.setEnabled(not self._busy)
            self.primary_device_button.setText("Refresh")
            self.primary_device_button.setIcon(FluentIcon.SYNC.icon())
        elif devices:
            pending = devices[0]
            authorized = pending.state == "unauthorized"
            self.device_dot.set_color(palette.caution)
            self.device_status.setText(
                "Waiting for authorisation" if authorized else "Device not ready"
            )
            self.device_name.setText(pending.label)
            self.device_meta.setText(
                "Accept the USB debugging prompt on the phone, then refresh."
                if authorized
                else f"ADB reports the device as \u201c{pending.state}\u201d."
            )
            self.device_hint.setText("")
            self.secondary_button.setText("Settings")
            self.secondary_button.setIcon(FluentIcon.SETTING.icon())
            self.secondary_button.setEnabled(True)
            self.primary_device_button.setText("Refresh")
            self.primary_device_button.setIcon(FluentIcon.SYNC.icon())
        elif not adb_ready:
            self.device_dot.set_color(palette.risky)
            self.device_status.setText("ADB not found")
            self.device_name.setText("Android Platform Tools are required")
            self.device_meta.setText(
                "Install them with winget, or point the app at adb.exe in "
                "Settings."
            )
            self.device_hint.setText("")
            self.secondary_button.setText("Settings")
            self.secondary_button.setIcon(FluentIcon.SETTING.icon())
            self.secondary_button.setEnabled(True)
            self.primary_device_button.setText(
                "Install ADB" if self.controller.install_adb_available() else "Find ADB"
            )
            self.primary_device_button.setIcon(FluentIcon.DOWNLOAD.icon())
        else:
            self.device_dot.set_color(palette.faint)
            self.device_status.setText("No device connected")
            self.device_name.setText("Plug in your phone")
            self.device_meta.setText(
                "Enable USB debugging in Developer options, then accept the RSA "
                "prompt on the device."
            )
            self.device_hint.setText("")
            self.secondary_button.setText("Settings")
            self.secondary_button.setIcon(FluentIcon.SETTING.icon())
            self.secondary_button.setEnabled(True)
            self.primary_device_button.setText("Refresh")
            self.primary_device_button.setIcon(FluentIcon.SYNC.icon())

        for label, color in (
            (self.device_name, palette.text),
            (self.device_meta, palette.dim),
            (self.device_hint, palette.faint),
            (self.adb_info, palette.faint),
            (self.profile_stats, palette.dim),
            (self.profile_description, palette.dim),
            (self.suggestion_label, palette.accent),
        ):
            label.setStyleSheet(f"color: {theme.hexa(color)};")
        for chip in (self.device_chip_root, self.device_chip_user,
                     self.device_chip_reversible):
            chip.set_color(palette.dim, bg_alpha=22)
        self.workflow_label.setStyleSheet(f"color: {theme.hexa(palette.faint)};")

        adb_path = self.controller.adb_path
        if adb_path:
            folder = Path(adb_path).parent.name or "adb"
            self.adb_info.setText(f"ADB  ·  {folder}")
            self.adb_info.setToolTip(adb_path)
        else:
            self.adb_info.setText("ADB  ·  not configured")
            self.adb_info.setToolTip("")

        profile = self.controller.profile
        packages = profile.packages if profile else []
        counts = profile.counts() if profile else {}
        risky = counts.get(Level.RISKY, 0)

        self.profile_stats.setText(
            f"{len(packages)} packages  ·  "
            f"{profile.category_count if profile else 0} categories"
        )
        self.pill_safe.setText(f"{counts.get(Level.SAFE, 0)} safe")
        self.pill_safe.set_color(palette.safe)
        self.pill_caution.setText(f"{counts.get(Level.CAUTION, 0)} caution")
        self.pill_caution.set_color(palette.caution)
        self.pill_risky.setText(f"{risky} risky")
        self.pill_risky.set_color(palette.risky)
        self.profile_description.setText(profile.description if profile else "")

        suggestion = self.controller.suggested_profile()
        if suggestion:
            suggested, match = suggestion
            self._suggested_id = suggested.id
            self.suggestion_label.setText(
                f"Looks like this phone matches \u201c{suggested.name}\u201d "
                f"({match.matched}/{match.total} rules)."
            )
            self.suggestion_row.show()
        else:
            self._suggested_id = ""
            self.suggestion_row.hide()

        states = self.controller.states
        installed = sum(
            1 for package in packages
            if states.get(package.package, State.UNKNOWN)
            in (State.ACTIVE, State.DISABLED)
        )
        debloated = sum(1 for package in packages
                        if states.get(package.package, State.UNKNOWN).debloated)
        absent = sum(1 for package in packages
                     if states.get(package.package, State.UNKNOWN)
                     is State.ABSENT)
        has_inventory = self.controller.inventory is not None
        self.stat_present.set_value(
            str(installed) if has_inventory else "—",
            f"of {len(packages)} in the profile",
            muted=not has_inventory,
        )
        self.stat_debloated.set_value(
            str(debloated) if has_inventory else "—",
            "disabled or removed",
            muted=not has_inventory,
        )
        self.stat_absent.set_value(
            str(absent) if has_inventory else "—",
            "different firmware?",
            muted=not has_inventory,
        )

        selection = self.controller.selection_counts()
        selected = sum(selection.values())
        self.stat_selected.set_value(str(selected), "packages ticked")
        self.action_title.setText(
            "Nothing selected yet" if selected == 0
            else f"Ready to debloat {selected} package(s)"
        )
        breakdown = (
            f"{selection.get(Level.SAFE, 0)} safe  ·  "
            f"{selection.get(Level.CAUTION, 0)} caution  ·  "
            f"{selection.get(Level.RISKY, 0)} risky"
        )
        self.action_subtitle.setText(
            breakdown if selected else
            "Browse the Packages page and tick what you want to remove."
        )

        can_run = bool(device) and selected > 0 and not self._busy
        self.apply_button.setText(
            f"Debloat {selected}" if selected else "Debloat"
        )
        self.apply_button.setEnabled(can_run)
        self.revert_button.setEnabled(can_run)
        running = self.controller.running
        self.stop_button.setVisible(running)
        self.stop_button.setEnabled(running)

    # ----------------------------------------------------------- activity
    def _rebuild_activity(self) -> None:
        while self.activity_box.count():
            item = self.activity_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        palette = theme.palette()
        runs = self.controller.recent_runs(limit=4)
        if not runs:
            empty = BodyLabel(
                "No runs yet. Applied changes show up here with their results."
            )
            empty.setTextColor(palette.faint, palette.faint)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setContentsMargins(0, 40, 0, 0)
            self.activity_box.addWidget(empty)
            return

        for run in runs:
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 2, 0, 2)
            layout.setSpacing(8)
            ok = run.fail_count == 0
            dot = Dot(palette.safe if ok else palette.caution, 7)
            layout.addWidget(dot)

            label = BodyLabel(
                f"{run.kind_label}  \u00b7  {run.ok_count}/{run.total} ok"
                + (f"  \u00b7  {run.fail_count} failed" if run.fail_count else "")
                + ("   (dry run)" if run.dry_run else "")
            )
            label.setTextColor(palette.text, palette.text)
            layout.addWidget(label, 1)

            when = CaptionLabel(run.started.strftime("%d %b  %H:%M"))
            when.setTextColor(palette.faint, palette.faint)
            layout.addWidget(when)
            self.activity_box.addWidget(row)
