"""The package table: model, filter proxy, delegate and view."""

from __future__ import annotations

from PySide6.QtCore import (QAbstractTableModel, QModelIndex, QRectF, QSize, Qt,
                            QSortFilterProxyModel, Signal)
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QPainter, QPainterPath,
                           QPen)
from PySide6.QtWidgets import (QAbstractItemView, QHeaderView,
                               QStyledItemDelegate)

from qfluentwidgets import TableView

from ..core.models import Action, Level, Package, State
from . import theme

ROLE_PACKAGE = Qt.ItemDataRole.UserRole + 1
ROLE_OBJECT = Qt.ItemDataRole.UserRole + 2
ROLE_LEVEL = Qt.ItemDataRole.UserRole + 3
ROLE_ACTION = Qt.ItemDataRole.UserRole + 4
ROLE_STATE = Qt.ItemDataRole.UserRole + 5
ROLE_SELECTED = Qt.ItemDataRole.UserRole + 6

COLUMNS = ("", "Package", "Safety", "Action", "On device")


class PackageTableModel(QAbstractTableModel):
    def __init__(self, controller, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._packages: list[Package] = []
        controller.profileChanged.connect(self._reload)
        controller.selectionChanged.connect(self._selection_changed)
        controller.inventoryChanged.connect(self._states_changed)
        self._reload()

    def _reload(self) -> None:
        self.beginResetModel()
        profile = self.controller.profile
        self._packages = list(profile.packages) if profile else []
        self.endResetModel()

    def _selection_changed(self) -> None:
        if self._packages:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self._packages) - 1, len(COLUMNS) - 1),
            )

    def _states_changed(self) -> None:
        self._selection_changed()

    # -- Qt model -------------------------------------------------------
    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self._packages)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if orientation == Qt.Orientation.Horizontal and \
                role == Qt.ItemDataRole.DisplayRole:
            return COLUMNS[section]
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return (
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsUserCheckable
        )

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._packages)):
            return None
        package = self._packages[index.row()]
        column = index.column()
        selected = self.controller.is_selected(package.package)
        state = self.controller.state_for(package.package)
        action = self.controller.action_for(package)

        if role == Qt.ItemDataRole.DisplayRole:
            if column == 0:
                return ""
            if column == 1:
                return package.title
            if column == 2:
                return package.level.label
            if column == 3:
                return action.label
            if column == 4:
                return state.label
            return ""
        if role == Qt.ItemDataRole.CheckStateRole and column == 0:
            return Qt.CheckState.Checked if selected else Qt.CheckState.Unchecked
        if role == ROLE_PACKAGE:
            return package.package
        if role == ROLE_OBJECT:
            return package
        if role == ROLE_LEVEL:
            return package.level
        if role == ROLE_ACTION:
            return action
        if role == ROLE_STATE:
            return state
        if role == ROLE_SELECTED:
            return selected
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._tooltip(package, state, action)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if column in (2, 3, 4):
                return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return None

    @staticmethod
    def _tooltip(package: Package, state: State, action: Action) -> str:
        state_hint = {
            State.ACTIVE: "Installed and enabled for user 0.",
            State.DISABLED: "Disabled for user 0; the APK is still in the system image.",
            State.UNINSTALLED: "Uninstalled for user 0; the APK is still in the system image.",
            State.ABSENT: "This package does not exist on the connected device.",
            State.UNKNOWN: "Connect a device to read the live state.",
        }[state]
        lines = [package.title, package.package, ""]
        if package.state is not None:
            lines.append(f"Snapshot state: {package.state.label}")
            lines.append("")
        if package.description:
            lines.append(package.description)
        if package.note:
            lines.append(f"Note: {package.note}")
        lines.append("")
        lines.append(f"Safety: {package.level.label} - {package.level.hint}")
        lines.append(f"Action: {action.label} - {action.description}")
        lines.append(f"On device: {state.label} - {state_hint}")
        if action is not package.action:
            lines.append(f"Default action for this profile: {package.action.label}")
        return "\n".join(lines)


_STATE_ORDER = {
    State.ACTIVE: 0,
    State.DISABLED: 1,
    State.UNINSTALLED: 2,
    State.ABSENT: 3,
    State.UNKNOWN: 4,
}


class PackageFilterProxy(QSortFilterProxyModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setDynamicSortFilter(True)
        self._query = ""
        self._level: Level | None = None
        self._category = ""
        self._only_on_device = False

    def set_query(self, text: str) -> None:
        text = text.strip().lower()
        if text != self._query:
            self._query = text
            self._invalidate()

    def set_level(self, level: Level | None) -> None:
        if level is not self._level:
            self._level = level
            self._invalidate()

    def set_category(self, category: str) -> None:
        if category != self._category:
            self._category = category
            self._invalidate()

    def set_only_on_device(self, value: bool) -> None:
        if value != self._only_on_device:
            self._only_on_device = value
            self._invalidate()

    def _invalidate(self) -> None:
        if hasattr(self, "beginFilterChange") and hasattr(self, "endFilterChange"):
            self.beginFilterChange()
            self.endFilterChange(QSortFilterProxyModel.Direction.Rows)
        elif hasattr(self, "invalidateRowsFilter"):  # Qt 6.10/6.11
            self.invalidateRowsFilter()
        else:  # older Qt
            self.invalidateFilter()

    def filterAcceptsRow(self, row, parent) -> bool:  # noqa: N802
        model = self.sourceModel()
        index = model.index(row, 0, parent)
        package: Package | None = model.data(index, ROLE_OBJECT)
        if package is None:
            return False
        if self._query and self._query not in package.search_blob:
            return False
        if self._level is not None and package.level is not self._level:
            return False
        if self._category and package.category != self._category:
            return False
        if self._only_on_device:
            state: State = model.data(index, ROLE_STATE)
            if not state.on_device:
                return False
        return True

    def lessThan(self, left, right) -> bool:  # noqa: N802
        model = self.sourceModel()
        column = left.column()
        if column == 0:
            return bool(model.data(left, ROLE_SELECTED)) < bool(
                model.data(right, ROLE_SELECTED)
            )
        if column == 2:
            return model.data(left, ROLE_LEVEL).rank < \
                model.data(right, ROLE_LEVEL).rank
        if column == 3:
            return model.data(left, ROLE_ACTION).value < \
                model.data(right, ROLE_ACTION).value
        if column == 4:
            return _STATE_ORDER[model.data(left, ROLE_STATE)] < \
                _STATE_ORDER[model.data(right, ROLE_STATE)]
        return str(model.data(left, Qt.ItemDataRole.DisplayRole)).lower() < str(
            model.data(right, Qt.ItemDataRole.DisplayRole)
        ).lower()


def _with_alpha(color: QColor, alpha: int) -> QColor:
    value = QColor(color)
    value.setAlpha(alpha)
    return value


class PackageDelegate(QStyledItemDelegate):
    ROW_HEIGHT = 56

    def __init__(self, view: "PackageTable") -> None:
        super().__init__(view)
        self.view = view
        self._title_font = QFont("Segoe UI", 10)
        self._title_font.setWeight(QFont.Weight.DemiBold)
        self._mono_font = QFont("Consolas", 8)
        self._small_font = QFont("Segoe UI", 8)
        self._pill_font = QFont("Segoe UI", 8)
        self._pill_font.setWeight(QFont.Weight.DemiBold)

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        return QSize(200, self.ROW_HEIGHT)

    # -- hooks used by qfluentwidgets' TableView -------------------------
    def setHoverRow(self, row: int) -> None:  # noqa: N802
        self.view.hover_row = row

    def setPressedRow(self, row: int) -> None:  # noqa: N802
        pass

    def setSelectedRows(self, indexes) -> None:  # noqa: N802
        pass

    def setCheckedColor(self, light, dark) -> None:  # noqa: N802
        pass

    def paint(self, painter: QPainter, option, index) -> None:
        palette = theme.palette()
        rect = option.rect
        selected = bool(index.data(ROLE_SELECTED))
        hovered = index.row() == self.view.hover_row
        current = index.row() == self.view.currentIndex().row()

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setClipRect(rect)

        if selected:
            painter.fillRect(rect, palette.row_selected)
        elif hovered:
            painter.fillRect(rect, palette.row_hover)

        painter.setPen(QPen(palette.border, 1))
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())

        if current and index.column() == 0:
            painter.fillRect(
                rect.left(), rect.top() + 8, 2, rect.height() - 16, palette.accent
            )

        column = index.column()
        if column == 0:
            self._paint_checkbox(painter, rect, selected, palette)
        elif column == 1:
            self._paint_package(painter, rect, index, palette)
        elif column == 2:
            level = index.data(ROLE_LEVEL)
            self._paint_pill(painter, rect, level.label, theme.level_color(level), 66)
        elif column == 3:
            action = index.data(ROLE_ACTION)
            self._paint_action(painter, rect, action, hovered, palette)
        elif column == 4:
            state = index.data(ROLE_STATE)
            self._paint_state(painter, rect, state, palette)

        painter.restore()

    # -- pieces ---------------------------------------------------------
    def _paint_checkbox(self, painter, rect, selected, palette) -> None:
        size = 20.0
        center = rect.center()
        box = QRectF(
            center.x() - size / 2, center.y() - size / 2, size, size
        )
        if selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(palette.accent)
            painter.drawRoundedRect(box, 6, 6)
            pen = QPen(QColor("#ffffff"))
            pen.setWidthF(2.0)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            path = QPainterPath()
            path.moveTo(box.left() + 5.2, box.top() + 10.4)
            path.lineTo(box.left() + 8.8, box.top() + 14.0)
            path.lineTo(box.left() + 15.0, box.top() + 6.2)
            painter.drawPath(path)
        else:
            pen = QPen(_with_alpha(palette.faint, 170))
            pen.setWidthF(1.4)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(box, 6, 6)

    def _paint_package(self, painter, rect, index, palette) -> None:
        package: Package = index.data(ROLE_OBJECT)
        state: State = index.data(ROLE_STATE)
        left = rect.left() + 10
        width = rect.width() - 16
        dimmed = state is State.ABSENT

        painter.setFont(self._title_font)
        painter.setPen(palette.faint if dimmed else palette.text)
        metrics = QFontMetrics(self._title_font)
        title = metrics.elidedText(package.title, Qt.TextElideMode.ElideRight, width)
        painter.drawText(
            QRectF(left, rect.top() + 7, width, 20),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            title,
        )

        painter.setFont(self._mono_font)
        mono_metrics = QFontMetrics(self._mono_font)
        painter.setPen(palette.faint)
        package_text = mono_metrics.elidedText(
            package.package, Qt.TextElideMode.ElideRight, width
        )
        painter.drawText(
            QRectF(left, rect.top() + 28, width, 17),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            package_text,
        )

        used = mono_metrics.horizontalAdvance(package_text)
        description = package.note or package.description
        if description.strip().casefold() == package.title.strip().casefold():
            description = ""
        if description and used + 26 < width:
            painter.setFont(self._small_font)
            painter.setPen(palette.dim if not dimmed else palette.absent)
            painter.drawText(
                QRectF(left + used + 10, rect.top() + 28, 8, 17),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                "·",
            )
            remaining = width - used - 24
            small_metrics = QFontMetrics(self._small_font)
            text = small_metrics.elidedText(
                description, Qt.TextElideMode.ElideRight, remaining
            )
            painter.drawText(
                QRectF(left + used + 22, rect.top() + 28, remaining, 17),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                text,
            )

    def _paint_pill(self, painter, rect, text, color, width, height=22.0,
                    filled=True, border_color=None) -> None:
        box = QRectF(
            rect.center().x() - width / 2,
            rect.center().y() - height / 2,
            width,
            height,
        )
        painter.setBrush(_with_alpha(color, 34) if filled else Qt.BrushStyle.NoBrush)
        pen = QPen(border_color or _with_alpha(color, 0))
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.drawRoundedRect(box, height / 2, height / 2)
        painter.setFont(self._pill_font)
        painter.setPen(color)
        painter.drawText(
            box,
            int(Qt.AlignmentFlag.AlignCenter),
            text,
        )

    def _paint_action(self, painter, rect, action: Action, hovered, palette) -> None:
        color = theme.action_color(action)
        box_width = 86.0
        border = _with_alpha(color, 110) if hovered else _with_alpha(color, 0)
        self._paint_pill(
            painter, rect, action.label, color, box_width, 24.0,
            filled=True, border_color=border,
        )

    def _paint_state(self, painter, rect, state: State, palette) -> None:
        color = theme.state_color(state)
        center_y = rect.center().y()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color if state is not State.UNKNOWN else palette.faint)
        painter.drawEllipse(QRectF(rect.left() + 16, center_y - 3.5, 7, 7))

        painter.setFont(self._small_font)
        painter.setPen(color if state is not State.UNKNOWN else palette.faint)
        painter.drawText(
            QRectF(rect.left() + 30, rect.top(), rect.width() - 34, rect.height()),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            state.label,
        )


class PackageTable(TableView):
    packageClicked = Signal(str)
    actionClicked = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.hover_row = -1
        self.empty_text = "No packages to show"
        self.setItemDelegate(PackageDelegate(self))
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.verticalHeader().hide()
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setMouseTracking(True)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setBorderVisible(True)
        self.setBorderRadius(8)
        try:
            self.verticalHeader().setDefaultSectionSize(PackageDelegate.ROW_HEIGHT)
            self.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        except Exception:
            pass
        header = self.horizontalHeader()
        header.setHighlightSections(False)
        header.setSectionsClickable(True)
        header.setFixedHeight(38)
        header.setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.clicked.connect(self._on_clicked)

    def setup_columns(self) -> None:
        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.setColumnWidth(0, 54)
        self.setColumnWidth(2, 96)
        self.setColumnWidth(3, 112)
        self.setColumnWidth(4, 128)

    def _on_clicked(self, index: QModelIndex) -> None:
        package = index.data(ROLE_PACKAGE)
        if not package:
            return
        if index.column() == 3:
            self.actionClicked.emit(package)
        else:
            self.packageClicked.emit(package)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            index = self.currentIndex()
            if index.isValid():
                package = index.data(ROLE_PACKAGE)
                if package:
                    self.packageClicked.emit(package)
                return
        super().keyPressEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        model = self.model()
        if model is not None and model.rowCount() == 0:
            palette = theme.palette()
            painter = QPainter(self.viewport())
            painter.setFont(QFont("Segoe UI", 9))
            painter.setPen(palette.faint)
            painter.drawText(
                self.viewport().rect(),
                int(Qt.AlignmentFlag.AlignCenter),
                self.empty_text,
            )
            painter.end()

    def visible_packages(self) -> list[Package]:
        model = self.model()
        if model is None:
            return []
        packages = []
        for row in range(model.rowCount()):
            package = model.index(row, 0).data(ROLE_OBJECT)
            if package is not None:
                packages.append(package)
        return packages
