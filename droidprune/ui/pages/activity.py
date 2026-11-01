"""Activity page: run history, detailed output and one-click undo."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPainter
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QHeaderView,
                               QHBoxLayout, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from qfluentwidgets import (FluentIcon, PrimaryPushButton, PushButton,
                            StrongBodyLabel, TableWidget, TextEdit)

from ...core.controller import Controller
from ...core.journal import RunSummary
from .. import dialogs, theme
from ..widgets import Card, PageHeader


class RunsTable(TableWidget):
    """Activity table that shows a hint when there is no history yet."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.empty_text = (
            "No runs yet. Apply a selection and the results will appear here."
        )

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if self.rowCount() == 0:
            painter = QPainter(self.viewport())
            painter.setFont(QFont("Segoe UI", 9))
            painter.setPen(theme.palette().faint)
            painter.drawText(
                self.viewport().rect(),
                int(Qt.AlignmentFlag.AlignCenter),
                self.empty_text,
            )
            painter.end()


class ActivityPage(QWidget):
    def __init__(self, controller: Controller, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("activityPage")
        self.controller = controller
        self._runs: list[RunSummary] = []
        self._current: RunSummary | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 16, 24, 16)
        outer.setSpacing(10)

        header_row = QHBoxLayout()
        self.header = PageHeader(
            "Activity",
            "Every command is logged with its result. Undo the last debloat run "
            "without re-selecting anything.",
        )
        header_row.addWidget(self.header, 1)
        self.refresh_button = PushButton("Refresh")
        self.refresh_button.setIcon(FluentIcon.SYNC.icon())
        self.refresh_button.clicked.connect(self.refresh)
        header_row.addWidget(self.refresh_button, 0, Qt.AlignTop)
        outer.addLayout(header_row)

        table_card = Card()
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(1, 1, 1, 1)
        self.table = RunsTable()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ["When", "Type", "Profile", "Device", "Result"]
        )
        self.table.verticalHeader().hide()
        self.table.setBorderVisible(True)
        self.table.setBorderRadius(8)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.table.setShowGrid(False)
        header = self.table.horizontalHeader()
        header.setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 150)
        self.table.setColumnWidth(1, 90)
        self.table.setColumnWidth(4, 120)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        table_layout.addWidget(self.table)
        outer.addWidget(table_card, 2)

        detail_card = Card()
        detail_layout = QVBoxLayout(detail_card)
        detail_layout.setContentsMargins(16, 10, 16, 12)
        detail_layout.setSpacing(6)
        detail_top = QHBoxLayout()
        detail_top.addWidget(StrongBodyLabel("Run details"))
        detail_top.addStretch(1)
        self.export_button = PushButton("Export log…")
        self.export_button.setIcon(FluentIcon.SAVE_AS.icon())
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self._export)
        detail_top.addWidget(self.export_button)
        self.undo_button = PrimaryPushButton("Undo last debloat")
        self.undo_button.setIcon(FluentIcon.RETURN.icon())
        self.undo_button.clicked.connect(self._undo)
        detail_top.addWidget(self.undo_button)
        detail_layout.addLayout(detail_top)

        self.detail = TextEdit()
        self.detail.setReadOnly(True)
        self.detail.setFont(QFont("Consolas", 8.5))
        self.detail.setPlaceholderText("Run details will appear here.")
        self.detail.setStyleSheet(
            "TextEdit { background: transparent; border: none; }"
        )
        detail_layout.addWidget(self.detail, 1)
        outer.addWidget(detail_card, 5)

        controller.journalChanged.connect(self.refresh)
        controller.runFinished.connect(lambda _result: self.refresh())
        self.refresh()

    # ------------------------------------------------------------ data
    def refresh(self) -> None:
        selected_id = self._current.run_id if self._current else ""
        self._runs = self.controller.journal.runs(limit=60)
        self.table.blockSignals(True)
        self.table.setRowCount(len(self._runs))
        for row, run in enumerate(self._runs):
            values = [
                run.started.strftime("%Y-%m-%d  %H:%M"),
                run.kind_label + (" (dry)" if run.dry_run else ""),
                run.profile_name,
                run.device,
                f"{run.ok_count}/{run.total} ok"
                + (f"  ·  {run.fail_count} failed" if run.fail_count else ""),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                if column == 4:
                    color = theme.palette().risky if run.fail_count else theme.palette().safe
                    item.setForeground(color)
                self.table.setItem(row, column, item)
        self.table.blockSignals(False)

        target = 0
        for row, run in enumerate(self._runs):
            if run.run_id == selected_id:
                target = row
                break
        if self._runs:
            self.table.selectRow(target)
        else:
            self._current = None
            self.detail.setPlainText("")
            self.export_button.setEnabled(False)

        self.undo_button.setEnabled(
            any(run.kind == "apply" and not run.dry_run for run in self._runs)
        )

        palette = theme.palette()
        self.detail.setStyleSheet(
            "TextEdit { background: transparent; border: none; "
            f"color: {theme.hexa(palette.dim)}; }}"
        )

    def _selection_changed(self) -> None:
        row = self.table.currentRow()
        if not (0 <= row < len(self._runs)):
            self._current = None
            self.detail.setPlainText("")
            self.export_button.setEnabled(False)
            return
        self._current = self._runs[row]
        self.detail.setPlainText(
            self.controller.journal.export_text(self._current)
        )
        self.export_button.setEnabled(True)

    # --------------------------------------------------------- actions
    def _export(self) -> None:
        if self._current is None:
            return
        suggested = f"debloat_{self._current.started.strftime('%Y%m%d_%H%M')}.txt"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save run log", suggested, "Text file (*.txt)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(self.controller.journal.export_text(self._current))
        except OSError as error:
            dialogs.notify(self, "error", "Could not save the log", str(error))
            return
        dialogs.notify(self, "info", "Log saved", path)

    def _undo(self) -> None:
        run = self.controller.journal.last_run("apply", include_dry=False)
        if run is None:
            dialogs.notify(self, "info", "Nothing to undo",
                           "There is no previous debloat run.")
            return
        if self.controller.ready_device is None:
            dialogs.notify(self, "warning", "No device connected")
            return
        if not dialogs.confirm(
            self,
            f"Undo the last debloat run?",
            f"Restore the {run.ok_count} package(s) changed on "
            f"{run.started.strftime('%d %b %H:%M')}. Packages that are currently "
            "disabled will be enabled and removed ones reinstalled for user 0.",
            yes_text="Undo",
        ):
            return
        self.controller.revert_last_run()

    def apply_palette(self) -> None:
        self.header.apply_palette()
        self.refresh()
