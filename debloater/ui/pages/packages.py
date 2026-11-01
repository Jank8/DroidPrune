"""Packages page: category rail, filterable table and apply bar."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QVBoxLayout,
                               QWidget)

from qfluentwidgets import (CheckBox, ComboBox, FluentIcon,
                            PrimaryPushButton, ProgressBar, PushButton,
                            SearchLineEdit, StrongBodyLabel)

from ...core.controller import Controller
from ...core.models import Action, Level
from .. import dialogs, theme
from ..table import PackageFilterProxy, PackageTable, PackageTableModel
from ..widgets import Card, CategoryRow, PageHeader, Pill, font


class PackagesPage(QWidget):
    def __init__(self, controller: Controller, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("packagesPage")
        self.controller = controller
        self._busy = False
        self._sort_column = -1
        self._sort_ascending = True

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 16, 24, 16)
        outer.setSpacing(10)

        header_row = QHBoxLayout()
        self.header = PageHeader("Packages", "")
        header_row.addWidget(self.header, 1)
        self.refresh_button = PushButton("Refresh")
        self.refresh_button.setIcon(FluentIcon.SYNC.icon())
        self.refresh_button.setToolTip("Re-read the package list from the device")
        self.refresh_button.clicked.connect(self._refresh)
        header_row.addWidget(self.refresh_button, 0, Qt.AlignTop)
        outer.addLayout(header_row)

        outer.addLayout(self._build_toolbar())

        body = QHBoxLayout()
        body.setSpacing(12)
        body.addWidget(self._build_categories(), 0)
        body.addWidget(self._build_table(), 1)
        outer.addLayout(body, 1)

        outer.addWidget(self._build_footer())

        self._shortcuts = [
            QShortcut(QKeySequence.StandardKey.Find, self, self.search.setFocus),
        ]

        controller.profileChanged.connect(self._on_profile_changed)
        controller.profilesChanged.connect(self._on_profile_changed)
        controller.inventoryChanged.connect(self._on_inventory_changed)
        controller.selectionChanged.connect(self._update_footer)
        controller.busyChanged.connect(self._on_busy)
        controller.progress.connect(self._on_progress)
        controller.runFinished.connect(lambda _result: self._on_run_finished())
        controller.deviceChanged.connect(self._update_footer)

        self._rebuild_categories()
        self._on_profile_changed()
        self._update_footer()

    # ------------------------------------------------------------- build
    def _build_toolbar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        self.search = SearchLineEdit()
        self.search.setPlaceholderText("Search packages, vendors, notes…")
        self.search.setMinimumWidth(300)
        self.search.textChanged.connect(self._on_search)
        row.addWidget(self.search)

        self.level_combo = ComboBox()
        self.level_combo.addItem("All safety levels", userData="")
        for level in Level:
            self.level_combo.addItem(level.label, userData=level.value)
        self.level_combo.setFixedWidth(150)
        self.level_combo.currentIndexChanged.connect(self._on_level)
        row.addWidget(self.level_combo)

        self.device_only = CheckBox("On device only")
        self.device_only.setToolTip(
            "Hide packages that are not present on the connected phone."
        )
        self.device_only.stateChanged.connect(
            lambda _state: self.proxy.set_only_on_device(self.device_only.isChecked())
        )
        row.addWidget(self.device_only)

        row.addStretch(1)

        self.select_visible_button = PushButton("Select visible")
        self.select_visible_button.setToolTip("Tick every package matching the filters")
        self.select_visible_button.clicked.connect(self._select_visible)
        row.addWidget(self.select_visible_button)

        self.select_safe_button = PushButton("Select safe")
        self.select_safe_button.setToolTip("Tick every SAFE package in the profile")
        self.select_safe_button.clicked.connect(self._select_safe)
        row.addWidget(self.select_safe_button)

        self.clear_button = PushButton("Clear")
        self.clear_button.clicked.connect(self._clear_selection)
        row.addWidget(self.clear_button)
        return row

    def _build_categories(self) -> Card:
        card = Card()
        card.setFixedWidth(246)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(6, 10, 6, 10)
        layout.setSpacing(6)

        caption = QLabel("Categories")
        caption.setFont(font(10, QFont.Weight.DemiBold))
        caption.setContentsMargins(10, 0, 10, 0)
        layout.addWidget(caption)

        self.category_list = QListWidget()
        self.category_list.setFrameShape(QFrame.Shape.NoFrame)
        self.category_list.setStyleSheet("QListWidget { background: transparent; }")
        self.category_list.setSpacing(2)
        self.category_list.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.category_list.currentRowChanged.connect(self._category_changed)
        layout.addWidget(self.category_list, 1)
        return card

    def _build_table(self) -> Card:
        card = Card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(1, 1, 1, 1)

        self.model = PackageTableModel(self.controller, self)
        self.proxy = PackageFilterProxy(self)
        self.proxy.setSourceModel(self.model)

        self.table = PackageTable()
        self.table.setModel(self.proxy)
        self.table.setup_columns()
        self.table.setSortingEnabled(False)
        self.table.packageClicked.connect(self.controller.toggle)
        self.table.actionClicked.connect(self._toggle_action)
        self.table.horizontalHeader().sectionClicked.connect(self._on_header_clicked)
        self.table.empty_text = "No packages match these filters"
        layout.addWidget(self.table)
        return card

    def _build_footer(self) -> Card:
        card = Card()
        layout = QHBoxLayout(card)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(8)

        self.selection_label = StrongBodyLabel("0 selected")
        layout.addWidget(self.selection_label)
        self.pill_safe = Pill("0 safe", theme.palette().safe)
        self.pill_caution = Pill("0 caution", theme.palette().caution)
        self.pill_risky = Pill("0 risky", theme.palette().risky)
        layout.addWidget(self.pill_safe)
        layout.addWidget(self.pill_caution)
        layout.addWidget(self.pill_risky)

        self.progress = ProgressBar()
        self.progress.setFixedWidth(190)
        self.progress.setFixedHeight(4)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.progress_label = QLabel("")
        self.progress_label.setFont(font(8))
        self.progress_label.hide()
        layout.addWidget(self.progress_label)

        layout.addStretch(1)

        self.dry_run = CheckBox("Dry run")
        self.dry_run.setToolTip("Only print the commands; do not touch the phone")
        self.dry_run.setChecked(self.controller.flag("dry_run", False))
        self.dry_run.stateChanged.connect(self._dry_run_changed)
        layout.addWidget(self.dry_run)

        self.stop_button = PushButton("Stop")
        self.stop_button.setIcon(FluentIcon.CANCEL.icon())
        self.stop_button.setToolTip("Finish the current package and stop the run")
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

    # ----------------------------------------------------------- filters
    def _on_search(self, text: str) -> None:
        self.proxy.set_query(text)

    def _on_level(self, _index: int) -> None:
        value = self.level_combo.currentData()
        self.proxy.set_level(Level.parse(value) if value else None)

    def _category_changed(self, _row: int) -> None:
        item = self.category_list.currentItem()
        category = item.data(Qt.ItemDataRole.UserRole) if item else ""
        self.proxy.set_category(category or "")

    def _on_header_clicked(self, column: int) -> None:
        if column == 0:
            return
        if self._sort_column == column:
            self._sort_ascending = not self._sort_ascending
        else:
            self._sort_column = column
            self._sort_ascending = True
        order = (
            Qt.SortOrder.AscendingOrder
            if self._sort_ascending
            else Qt.SortOrder.DescendingOrder
        )
        self.table.horizontalHeader().setSortIndicator(column, order)
        self.table.horizontalHeader().setSortIndicatorShown(True)
        self.proxy.sort(column, order)

    # ---------------------------------------------------------- selection
    def _toggle_action(self, package_name: str) -> None:
        profile = self.controller.profile
        if profile is None:
            return
        package = profile.get(package_name)
        if package is None:
            return
        current = self.controller.action_for(package)
        new_action = Action.DISABLE if current is Action.UNINSTALL else Action.UNINSTALL
        self.controller.set_action(package, new_action)

    def _select_visible(self) -> None:
        packages = self.table.visible_packages()
        self.controller.set_many(packages, True)

    def _select_safe(self) -> None:
        self.controller.select_by_level(Level.SAFE, True)

    def _clear_selection(self) -> None:
        if self.controller.selected_items() and not dialogs.confirm_clear_selection(self):
            return
        self.controller.clear_selection()

    def _apply(self) -> None:
        if self.dry_run.isChecked():
            if not self.controller.selected_items():
                dialogs.notify(self, "info", "Nothing selected")
                return
            self.controller.apply_selected(dry_run=True)
            return
        dialogs.run_selected(self, self.controller, revert=False)

    def _dry_run_changed(self, _state: int) -> None:
        self.controller.set_setting("dry_run", self.dry_run.isChecked())

    def showEvent(self, event) -> None:  # noqa: N802
        self.dry_run.blockSignals(True)
        self.dry_run.setChecked(self.controller.flag("dry_run", False))
        self.dry_run.blockSignals(False)
        self._update_footer()
        super().showEvent(event)

    def _restore(self) -> None:
        if self.dry_run.isChecked():
            if not self.controller.selected_items():
                dialogs.notify(self, "info", "Nothing selected")
                return
            self.controller.revert_selected(dry_run=True)
            return
        dialogs.run_selected(self, self.controller, revert=True)

    def _refresh(self) -> None:
        if self.controller.adb.available:
            self.controller.refresh_devices()
            self.controller.refresh_inventory()
        else:
            self.controller.auto_detect_adb()

    # ------------------------------------------------------------ state
    def _on_profile_changed(self) -> None:
        profile = self.controller.profile
        if profile is None:
            self.header.set_subtitle("No profile selected")
        else:
            self.header.set_subtitle(
                f"{profile.name}  ·  {profile.package_count} packages  ·  "
                f"{profile.category_count} categories"
            )
        self._rebuild_categories()
        self._update_footer()

    def _on_inventory_changed(self) -> None:
        has_inventory = self.controller.inventory is not None
        self.device_only.setEnabled(has_inventory)
        if not has_inventory:
            self.device_only.setChecked(False)
        self._update_footer()

    def _on_busy(self, busy: bool) -> None:
        self._busy = busy
        if not busy:
            self.progress.hide()
            self.progress_label.hide()
        self._update_footer()

    def _on_progress(self, done: int, total: int, package: str, ok: bool) -> None:
        self.progress.show()
        self.progress_label.show()
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(done)
        marker = "✓" if ok else "✗"
        self.progress_label.setText(f"{marker} {done}/{total}  {package}")
        self.progress_label.setStyleSheet(
            f"color: {theme.hexa(theme.palette().dim)};"
        )

    def _on_run_finished(self) -> None:
        self.progress.hide()
        self.progress_label.hide()
        self._update_footer()

    def _update_footer(self) -> None:
        counts = self.controller.selection_counts()
        total = sum(counts.values())
        self.selection_label.setText(f"{total} selected")
        self.pill_safe.setText(f"{counts.get(Level.SAFE, 0)} safe")
        self.pill_safe.set_color(theme.palette().safe)
        self.pill_caution.setText(f"{counts.get(Level.CAUTION, 0)} caution")
        self.pill_caution.set_color(theme.palette().caution)
        self.pill_risky.setText(f"{counts.get(Level.RISKY, 0)} risky")
        self.pill_risky.set_color(theme.palette().risky)

        device_ready = self.controller.ready_device is not None
        enabled = total > 0 and device_ready and not self._busy
        self.apply_button.setEnabled(enabled)
        self.revert_button.setEnabled(enabled)
        self.apply_button.setText(f"Debloat {total}" if total else "Debloat")
        self.refresh_button.setEnabled(not self._busy)
        running = self.controller.running
        self.stop_button.setVisible(running)
        self.stop_button.setEnabled(running)

    # ---------------------------------------------------------- categories
    def _rebuild_categories(self) -> None:
        previous = ""
        item = self.category_list.currentItem()
        if item is not None:
            previous = item.data(Qt.ItemDataRole.UserRole) or ""

        self.category_list.blockSignals(True)
        self.category_list.clear()
        profile = self.controller.profile
        if profile is not None:
            total = profile.package_count
            self._add_category("All packages", total, "")
            counts = profile.category_counts()
            for category in profile.categories:
                self._add_category(
                    category.name, counts.get(category.id, 0), category.id
                )
            if previous:
                for row in range(self.category_list.count()):
                    candidate = self.category_list.item(row)
                    if (candidate.data(Qt.ItemDataRole.UserRole) or "") == previous:
                        self.category_list.setCurrentRow(row)
                        break
            else:
                self.category_list.setCurrentRow(0)
        self.category_list.blockSignals(False)
        item = self.category_list.currentItem()
        self.proxy.set_category(
            (item.data(Qt.ItemDataRole.UserRole) or "") if item else ""
        )

    def _add_category(self, name: str, count: int, category_id: str) -> None:
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, category_id)
        item.setSizeHint(QSize(0, 40))
        self.category_list.addItem(item)
        self.category_list.setItemWidget(item, CategoryRow(name, count))

    # --------------------------------------------------------------- misc
    def apply_palette(self) -> None:
        self.header.apply_palette()
        self._rebuild_categories()
        self._update_footer()
        self.table.viewport().update()
        self.table.update()
