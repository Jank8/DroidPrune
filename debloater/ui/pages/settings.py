"""Settings page: ADB, appearance, behaviour and data maintenance."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QVBoxLayout,
                               QWidget)

from qfluentwidgets import (BodyLabel, CaptionLabel, ComboBox, FluentIcon,
                            PushButton, SmoothScrollArea, StrongBodyLabel,
                            SwitchButton)

from ... import APP_NAME, APP_VERSION
from ...core.controller import Controller
from ...paths import DATA_DIR, LOG_DIR, PROFILES_DIR, open_in_explorer
from .. import dialogs, theme
from ..widgets import Card, HLine, PageHeader, Pill, font


class SettingsPage(QWidget):
    themeChanged = Signal(str)

    def __init__(self, controller: Controller, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("settingsPage")
        self.controller = controller
        self._dim_labels: list[CaptionLabel] = []
        self._faint_labels: list[CaptionLabel] = []
        self._body_labels: list[BodyLabel] = []
        self._lines: list[HLine] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 16, 24, 16)
        outer.setSpacing(10)

        self.header = PageHeader(
            "Settings",
            "Connection, appearance and where the application keeps its data.",
        )
        outer.addWidget(self.header)

        scroll = SmoothScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.viewport().setAutoFillBackground(False)
        content = QWidget()
        content.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 2, 6, 2)
        layout.setSpacing(10)

        layout.addWidget(self._build_adb_card())
        layout.addWidget(self._build_appearance_card())
        layout.addWidget(self._build_data_card())
        layout.addWidget(self._build_about_card())
        layout.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        controller.adbChanged.connect(self._refresh_adb)
        controller.devicesChanged.connect(self._refresh_adb)
        controller.selectionChanged.connect(self._refresh_adb)
        controller.profileChanged.connect(self._refresh_adb)
        self._refresh_adb()

    # ------------------------------------------------------------- cards
    def _section(self, title: str, subtitle: str) -> tuple[Card, QVBoxLayout]:
        card = Card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(6)
        heading = StrongBodyLabel(title)
        layout.addWidget(heading)
        if subtitle:
            caption = CaptionLabel(subtitle)
            caption.setWordWrap(True)
            caption.setTextColor(theme.palette().dim, theme.palette().dim)
            self._dim_labels.append(caption)
            layout.addWidget(caption)
        line = HLine()
        self._lines.append(line)
        layout.addWidget(line)
        return card, layout

    def _row(self, title: str, hint: str, control: QWidget) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(12)
        text = QVBoxLayout()
        text.setSpacing(0)
        label = BodyLabel(title)
        text.addWidget(label)
        if hint:
            caption = CaptionLabel(hint)
            caption.setWordWrap(True)
            caption.setTextColor(theme.palette().faint, theme.palette().faint)
            self._faint_labels.append(caption)
            text.addWidget(caption)
        layout.addLayout(text, 1)
        layout.addWidget(control, 0, Qt.AlignRight | Qt.AlignVCenter)
        return row

    def _build_adb_card(self) -> Card:
        card, layout = self._section(
            "Android Debug Bridge",
            "adb.exe is the only external dependency. Install Google Platform "
            "Tools with winget or point the app at an existing copy.",
        )
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self.adb_status = Pill("Checking…", theme.palette().faint)
        status_row.addWidget(self.adb_status)
        self.adb_path_label = QLabel("")
        self.adb_path_label.setFont(font(8.5))
        self.adb_path_label.setWordWrap(True)
        self.adb_path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        status_row.addWidget(self.adb_path_label, 1)
        layout.addLayout(status_row)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch(1)
        self.install_button = PushButton("Install via winget")
        self.install_button.setIcon(FluentIcon.DOWNLOAD.icon())
        self.install_button.clicked.connect(self.controller.install_adb)
        buttons.addWidget(self.install_button)
        detect = PushButton("Auto-detect")
        detect.setIcon(FluentIcon.SEARCH.icon())
        detect.clicked.connect(self.controller.auto_detect_adb)
        buttons.addWidget(detect)
        browse = PushButton("Browse…")
        browse.setIcon(FluentIcon.FOLDER.icon())
        browse.clicked.connect(self._browse_adb)
        buttons.addWidget(browse)
        layout.addLayout(buttons)
        return card

    def _build_appearance_card(self) -> Card:
        card, layout = self._section(
            "Appearance and behaviour",
            "The interface follows Windows by default: Mica backdrop, system "
            "accent colour and live dark/light switching.",
        )

        self.theme_combo = ComboBox()
        self.theme_combo.addItem("Follow Windows", userData="system")
        self.theme_combo.addItem("Dark", userData="dark")
        self.theme_combo.addItem("Light", userData="light")
        self.theme_combo.setFixedWidth(180)
        mode = str(self.controller.setting("theme", "system") or "system")
        index = self.theme_combo.findData(mode)
        self.theme_combo.setCurrentIndex(max(0, index))
        self.theme_combo.currentIndexChanged.connect(self._theme_changed)
        layout.addWidget(self._row(
            "Theme", "Switching is instant; the table repaints with the new palette.",
            self.theme_combo,
        ))

        self.refresh_combo = ComboBox()
        for label, seconds in (("Off", 0), ("Every 3 seconds", 3),
                               ("Every 6 seconds", 6), ("Every 10 seconds", 10)):
            self.refresh_combo.addItem(label, userData=seconds)
        self.refresh_combo.setFixedWidth(180)
        current = int(self.controller.setting("auto_refresh", 6) or 0)
        index = self.refresh_combo.findData(current)
        self.refresh_combo.setCurrentIndex(index if index >= 0 else 2)
        self.refresh_combo.currentIndexChanged.connect(self._refresh_interval)
        layout.addWidget(self._row(
            "Device watchdog",
            "How often the app checks whether a phone was plugged in or removed.",
            self.refresh_combo,
        ))

        self.confirm_switch = SwitchButton()
        self.confirm_switch.setChecked(self.controller.flag("confirm_apply", True))
        self.confirm_switch.checkedChanged.connect(
            lambda value: self.controller.set_setting("confirm_apply", value)
        )
        layout.addWidget(self._row(
            "Confirm before applying",
            "Show a summary of the batch before any command reaches the phone.",
            self.confirm_switch,
        ))

        self.dry_switch = SwitchButton()
        self.dry_switch.setChecked(self.controller.flag("dry_run", False))
        self.dry_switch.checkedChanged.connect(
            lambda value: self.controller.set_setting("dry_run", value)
        )
        layout.addWidget(self._row(
            "Start with dry run",
            "Pre-tick the Dry run checkbox on the Home and Packages pages.",
            self.dry_switch,
        ))
        return card

    def _build_data_card(self) -> Card:
        card, layout = self._section(
            "Data and maintenance",
            "Everything is portable and lives next to the launcher. Copy the "
            "whole folder to a USB stick and the profiles come along.",
        )

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        profiles = PushButton("Profile folder")
        profiles.setIcon(FluentIcon.FOLDER.icon())
        profiles.clicked.connect(lambda: open_in_explorer(PROFILES_DIR))
        buttons.addWidget(profiles)

        logs = PushButton("Run logs")
        logs.setIcon(FluentIcon.DOCUMENT.icon())
        logs.clicked.connect(lambda: open_in_explorer(LOG_DIR))
        buttons.addWidget(logs)

        data = PushButton("Data folder")
        data.setIcon(FluentIcon.ZIP_FOLDER.icon())
        data.clicked.connect(lambda: open_in_explorer(DATA_DIR))
        buttons.addWidget(data)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.selection_label = CaptionLabel("")
        self.selection_label.setWordWrap(True)
        layout.addWidget(self.selection_label)

        row = QHBoxLayout()
        row.addStretch(1)
        clear = PushButton("Clear saved selection")
        clear.clicked.connect(self._clear_selection)
        row.addWidget(clear)
        layout.addLayout(row)
        return card

    def _build_about_card(self) -> Card:
        card, layout = self._section(
            "About", "A portable PySide6 front-end for ADB package management.",
        )
        title = QLabel(f"{APP_NAME} {APP_VERSION}")
        title.setFont(font(12, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {theme.palette().accent_hex};")
        layout.addWidget(title)

        body = BodyLabel(
            "No root, no custom ROM: every action only affects user 0 and the "
            "APKs stay in the system image. Restore any package from the Activity "
            "page or with one tap in the Packages table."
        )
        body.setWordWrap(True)
        body.setTextColor(theme.palette().dim, theme.palette().dim)
        self._body_labels.append(body)
        layout.addWidget(body)

        credits = CaptionLabel(
            "Package research: Universal Android Debloater (UAD), XDA Forums, "
            "DroidWin and community reports.  ·  "
            "UI built with PySide6 and PySide6-Fluent-Widgets."
        )
        credits.setWordWrap(True)
        credits.setTextColor(theme.palette().faint, theme.palette().faint)
        self._faint_labels.append(credits)
        layout.addWidget(credits)
        return card

    # ------------------------------------------------------------ actions
    def _browse_adb(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select adb.exe", "", "adb.exe (adb.exe);;All files (*)"
        )
        if path:
            self.controller.set_adb(path)

    def _theme_changed(self, _index: int) -> None:
        mode = str(self.theme_combo.currentData() or "system")
        self.controller.set_setting("theme", mode)
        self.themeChanged.emit(mode)

    def _refresh_interval(self, _index: int) -> None:
        seconds = int(self.refresh_combo.currentData() or 0)
        self.controller.set_auto_refresh(seconds)
        self.controller.set_setting("auto_refresh", seconds)

    def _clear_selection(self) -> None:
        if not dialogs.confirm_clear_selection(self):
            return
        self.controller.clear_selection()

    def _refresh_adb(self) -> None:
        palette = theme.palette()
        ready = self.controller.adb.available
        self.adb_status.setText("Ready" if ready else "Missing")
        self.adb_status.set_color(palette.safe if ready else palette.risky)
        path = self.controller.adb_path
        self.adb_path_label.setText(path or "adb.exe was not found.")
        self.adb_path_label.setStyleSheet(
            f"color: {theme.hexa(palette.dim if ready else palette.risky)};"
        )
        self.install_button.setVisible(self.controller.install_adb_available())

        profile = self.controller.profile
        if profile is not None:
            self.selection_label.setText(
                f"Selection is stored per profile in data/selection/"
                f"{profile.id}.json. Currently saved: "
                f"{len(self.controller.selection.selected)} package(s)."
            )
        else:
            self.selection_label.setText("")

    def apply_palette(self) -> None:
        palette = theme.palette()
        self.header.apply_palette()
        for label in self._dim_labels:
            label.setTextColor(palette.dim, palette.dim)
        for label in self._faint_labels:
            label.setTextColor(palette.faint, palette.faint)
        for label in self._body_labels:
            label.setTextColor(palette.dim, palette.dim)
        for line in self._lines:
            line.apply_palette()
        self._refresh_adb()
